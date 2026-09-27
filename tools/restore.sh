#!/usr/bin/env bash
# tools/restore.sh — Ripristina un backup age-encrypted o uno snapshot locale.
#
# Uso:
#   ./tools/restore.sh backups/vps1777-YYYY-MM-DD-HHMMSS.tar.age
#   ./tools/restore.sh --yes --volumes-only vol1,vol2 backups/pre-update/<dir>
#
# Input:
#   - archivio .tar.age  → decifrato con la chiave age: AGE_KEY se la dai, altrimenti
#                          ~/.config/vps1777/age-key.txt (dove la creano deploy.sh e
#                          l'installer grafico), poi ~/.config/age/keys.txt.
#   --chiave             → stampa la chiave che userebbe ed esce (non tocca niente)
#                          Vale per ENTRAMBI i livelli di backup.sh: il CORE
#                          (`backups/vps1777-<ts>.tar.age`: volumi piccoli, config,
#                          secrets, descrizioni dei DB) e l'ARCHIVIO
#                          (`backups/archivio/vps1777-archivio-<ts>.tar.age`: i
#                          volumi dell'archivio). Un disaster recovery completo
#                          è DUE restore, uno per livello — vedi BACKUP-RESTORE.md.
#                          Il decifrato può essere compresso (zstd/gzip) anche se
#                          il nome dice `.tar.age`: il formato si legge dai primi
#                          byte, non dal nome (vedi `estrai_cifrato`).
#   - DIRECTORY          → snapshot locale non cifrato (<vol>.tar dentro);
#                          usato dall'auto-rollback di `vps1777 update`,
#                          che NON può dipendere dalla age-key (spesso solo
#                          sul PC dell'utente).
# Flag:
#   --yes                → nessuna conferma interattiva (default: chiede)
#   --volumes-only LIST  → ripristina SOLO i volumi elencati (CSV, nomi corti
#                          o con prefisso vps1777_); salta config e secrets
#
# Procedura:
#   1. ferma stack: docker compose down --remove-orphans  (senza, l'ingress resta su)
#   2. decifra/legge l'input
#   3. ripristina volumi Docker (+ secrets/config se non --volumes-only)
#   4. lascia all'utente (o alla CLI) lanciare `docker compose up -d`

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# 🔴 27/09 (audit della doc): qui c'era solo ~/.config/age/keys.txt, mentre deploy.sh e
#   l'installer grafico creano la chiave in ~/.config/vps1777/age-key.txt. Con i default
#   il ripristino si fermava con «chiave age non trovata»: il giorno in cui serve.
_CHIAVI_CANDIDATE=("${XDG_CONFIG_HOME:-$HOME/.config}/vps1777/age-key.txt"
                   "$HOME/.config/age/keys.txt")
if [ -z "${AGE_KEY:-}" ]; then
  for _k in "${_CHIAVI_CANDIDATE[@]}"; do
    if [ -f "$_k" ]; then AGE_KEY="$_k"; break; fi
  done
fi
AGE_KEY="${AGE_KEY:-${_CHIAVI_CANDIDATE[0]}}"

ARCHIVE=""
ASSUME_YES=0
SOLO_COMANDO=0
VOLUMES_ONLY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --yes) ASSUME_YES=1 ;;
    --comando-riavvio) SOLO_COMANDO=1 ;;
    --chiave)
      if [ -f "$AGE_KEY" ]; then printf '%s\n' "$AGE_KEY"; exit 0; fi
      printf '[✗] chiave age non trovata. Cercata in: %s. Passa AGE_KEY=<file>.\n' \
        "${_CHIAVI_CANDIDATE[*]}" >&2
      exit 1 ;;
    --volumes-only) shift; VOLUMES_ONLY="${1:-}" ;;
    --volumes-only=*) VOLUMES_ONLY="${1#*=}" ;;
    -*) printf '[✗] flag sconosciuta: %s\n' "$1" >&2; exit 1 ;;
    *) ARCHIVE="$1" ;;
  esac
  shift
done

# ───── UI ─────
if [ -t 1 ]; then
  C_OK=$'\e[32m'; C_W=$'\e[33m'; C_E=$'\e[31m'; C_I=$'\e[34m'; C_R=$'\e[0m'
else
  C_OK=''; C_W=''; C_E=''; C_I=''; C_R=''
fi
log()  { printf '%s[*]%s %s\n' "$C_I"  "$C_R" "$*"; }
ok()   { printf '%s[✓]%s %s\n' "$C_OK" "$C_R" "$*"; }
warn() { printf '%s[!]%s %s\n' "$C_W"  "$C_R" "$*"; }
die()  { printf '%s[✗]%s %s\n' "$C_E"  "$C_R" "$*" >&2; exit 1; }


# ───── il comando per riavviare lo stack ─────
# 🔴 27/09 (audit della doc): stampava solo compose.yaml + l'ingress. Il restore fa
#   `down --remove-orphans`, che toglie anche il container del backup notturno, e con
#   quel comando il backup restava spento fino al prossimo update — in silenzio, subito
#   dopo aver dimostrato che i backup servono. Ora entrano anche le feature dichiarate
#   in VPS1777_FEATURES, con la stessa mappa di vps1777.py (OPS_COMPOSE_FEATURES).
# 🔴 `|| true` NON è cosmetico (b82df434, 16/08 — trovato ESEGUENDO il ciclo, mai
#   fatto prima): con `set -o pipefail` un `.env` assente fa uscire `grep` con 2, e
#   questa funzione è l'ULTIMO comando dello script prima del trap di cleanup ⇒
#   `restore.sh` usciva **2 a restore RIUSCITO**. `tools/vps1777.py` lo chiama con
#   `check=True`: l'auto-rollback falliva esattamente quando era l'ultima rete.
comando_riavvio() {
  local ingress feat f file prof flag=""
  ingress="$(grep ^INGRESS_PROFILE= .env 2>/dev/null | cut -d= -f2 | tr -d '"' || true)"
  feat="$(grep ^VPS1777_FEATURES= .env 2>/dev/null | cut -d= -f2 | tr -d '"' || true)"
  [ -n "$feat" ] || feat="backup,autoupdate"          # DEFAULT_FEATURES di vps1777.py
  for f in ${feat//,/ }; do
    case "$f" in
      backup)     file=ops.backup;     prof=ops.backup ;;
      portainer)  file=ops.portainer;  prof=ops.portainer ;;
      watchtower) file=ops.watchtower; prof=ops.autoupdate ;;
      *) continue ;;
    esac
    flag="$flag -f compose.$file.yaml --profile $prof"
  done
  if [ -n "$ingress" ]; then
    log "  docker compose -f compose.yaml -f compose.${ingress}.yaml --profile $ingress$flag up -d"
  else
    # Gli `-f` dell'ingress non sono facoltativi: senza, l'overlay non entra nel progetto
    # (gateway senza `ports:`, rete `funnel` assente) e lo stack riparte irraggiungibile.
    # Qui il profilo non si sa (.env illeggibile): si mostra il default, ma completo.
    log "  docker compose -f compose.yaml -f compose.ingress.tailscale.yaml \\"
    log "    --profile ingress.tailscale$flag up -d   # o caddy / cloudflared"
  fi
}
if [ "$SOLO_COMANDO" = "1" ]; then comando_riavvio; exit 0; fi

# ───── arg ─────
if [ -z "$ARCHIVE" ]; then
  echo "Uso: $0 [--yes] [--volumes-only v1,v2] <backup.tar.age | snapshot-dir>"
  echo
  echo "Backup CORE disponibili in backups/:"
  # nomi generati da backup.sh: nessun carattere strano
  # shellcheck disable=SC2012
  ls -1 backups/vps1777-*.tar.age 2>/dev/null | sed 's/^/  /' || echo "  (nessuno)"
  echo "Backup ARCHIVIO disponibili in backups/archivio/:"
  # shellcheck disable=SC2012
  ls -1 backups/archivio/vps1777-archivio-*.tar.age 2>/dev/null | sed 's/^/  /' || echo "  (nessuno)"
  exit 1
fi
[ -e "$ARCHIVE" ] || die "input non trovato: $ARCHIVE"

# ───── prerequisiti ─────
command -v docker >/dev/null || die "docker non trovato"
command -v tar    >/dev/null || die "tar non trovato"
if [ -f "$ARCHIVE" ]; then
  command -v age >/dev/null || die "age non installato"
  [ -f "$AGE_KEY" ] || die "chiave age non trovata: $AGE_KEY (cercata in: ${_CHIAVI_CANDIDATE[*]}; passa AGE_KEY=<file>)"
fi

# ───── conferma ─────
if [ "$ASSUME_YES" != "1" ]; then
  echo
  if [ -n "$VOLUMES_ONLY" ]; then
    warn "ATTENZIONE: questo cancella e ripristina i volumi: $VOLUMES_ONLY"
  else
    warn "ATTENZIONE: questo cancella i volumi correnti e sovrascrive .env + secrets."
  fi
  warn "Input: $ARCHIVE"
  echo
  read -r -p "Procedo? [s/N]: " ack
  case "$ack" in s|S|si|SI|y|Y|yes|YES) ;; *) die "Annullato" ;; esac
fi

# ───── 1. stop stack ─────
# 🔴 `--remove-orphans` NON è una rifinitura: senza, questo `down` lasciava ACCESO
#    l'ingress. Misurato il 09/08 (docker 29.4.1, A/B in sandbox): un `down` senza gli
#    `-f` costruisce il modello dai soli file che vede, e ciò che sta nell'overlay non
#    è nel modello ⇒ non viene fermato. Le label di progetto NON bastano (ipotesi
#    verificata e caduta): il container dell'overlay restava su e la rete usciva con
#    «Resource is still in use».
#      up  -f compose.yaml -f compose.ingress.X.yaml  →  base + ingress
#      down (senza -f)                                →  ferma base, ingress RESTA
#      down --remove-orphans                          →  ferma tutto, rete rimossa
#    Qui pesa perché è il passo 1 di un RESTORE: l'ingress servirebbe traffico sopra
#    volumi che stanno venendo ripristinati sotto di lui.
# 🔑 Si usa `--remove-orphans` e non gli `-f` di proposito: a questo punto il profilo
#    non è ancora stato letto (succede a r.180), e una cura che deve INDOVINARE quale
#    overlay era attivo sarebbe l'ennesimo insieme enumerato a mano. Docker sa già
#    cosa appartiene al progetto: glielo si chiede, invece di dirglielo.
log "Stop stack..."
docker compose down --remove-orphans 2>/dev/null || true

# ───── 2. decifra / leggi input ─────
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
if [ -d "$ARCHIVE" ]; then
  # Snapshot locale: directory con <vol>.tar — nessuna cifratura.
  log "Snapshot locale: $ARCHIVE"
  mkdir -p "$TMP/volumes"
  cp -a "$ARCHIVE"/*.tar "$TMP/volumes/" 2>/dev/null || die "nessun .tar nello snapshot"
  ok "Snapshot caricato"
else
  # ── il formato si legge dai BYTE, non dal nome ──
  # Dal 0.43.13 backup.sh comprime prima di cifrare (zstd, o gzip) e il nome resta
  # `.tar.age` per contratto (vedi la sua testa). Qui si sbircia il magic number
  # del decifrato con una prima decifratura tagliata a 4 byte — costa una seconda
  # passata di age sul file, che è veloce, e non scrive 10 GB in chiaro su disco
  # solo per guardarne quattro. Poi la pipeline giusta, in streaming.
  #   28 b5 2f fd → zstd · 1f 8b → gzip · altro → tar nudo (i backup pre-0.43.13)
  log "Decifro archivio..."
  magic="$( (age -d -i "$AGE_KEY" "$ARCHIVE" 2>/dev/null || true) | head -c 4 | od -An -tx1 | tr -d ' \n')"
  case "$magic" in
    28b52ffd)
      command -v zstd >/dev/null || die "il backup è compresso con zstd e qui zstd manca (apt install zstd)"
      log "  formato: tar + zstd"
      age -d -i "$AGE_KEY" "$ARCHIVE" | zstd -dc | tar -C "$TMP" -xf - ;;
    1f8b*)
      command -v gzip >/dev/null || die "il backup è compresso con gzip e qui gzip manca"
      log "  formato: tar + gzip"
      age -d -i "$AGE_KEY" "$ARCHIVE" | gzip -dc | tar -C "$TMP" -xf - ;;
    "")
      die "decifratura fallita: chiave sbagliata, file troncato o non è un backup age ($ARCHIVE)" ;;
    *)
      log "  formato: tar (non compresso)"
      age -d -i "$AGE_KEY" "$ARCHIVE" | tar -C "$TMP" -xf - ;;
  esac
  ok "Decifrato"
fi

# Mostra manifest
if [ -f "$TMP/MANIFEST.txt" ]; then
  log "Manifest del backup:"
  sed 's/^/    /' "$TMP/MANIFEST.txt"
fi

# ───── 3. restore config + secrets (saltato con --volumes-only) ─────
if [ -z "$VOLUMES_ONLY" ]; then
  log "Ripristino config..."
  # ⚠️ Prima diceva `ok "Config ripristinata"` INCONDIZIONATO dopo tre `cp` con
  #   `2>/dev/null || true`: ogni fallimento era silenziato E forzato a successo,
  #   e bastava che `$TMP/config` esistesse — anche VUOTA — perché il restore
  #   annunciasse di aver ripristinato. Su un restore, quel messaggio è l'unica
  #   cosa che una persona guarda prima di ripartire.
  #   Il modo giusto era già dieci righe sotto, nel blocco `secrets`, che concatena
  #   con `&&` e quindi non può mentire. Qui non basta copiarlo: gli elementi sono
  #   tre e opzionali, quindi si CONTA ciò che è arrivato davvero e lo si dice.
  if [ -d "$TMP/config" ]; then
    _n=0 _falliti=""
    for _src in "$TMP/config/.env" "$TMP/config/"compose*.yaml "$TMP/config/ingress"; do
      [ -e "$_src" ] || continue          # non c'era nel backup: non è un fallimento
      if cp -a "$_src" . 2>/dev/null; then
        _n=$((_n + 1))
      else
        _falliti="$_falliti $(basename "$_src")"
      fi
    done
    if [ -n "$_falliti" ]; then
      warn "Config ripristinata solo in parte ($_n ok) — NON copiati:$_falliti"
    elif [ "$_n" -gt 0 ]; then
      ok "Config ripristinata ($_n elementi)"
    else
      warn "Config NON ripristinata: la cartella config/ del backup è vuota"
    fi
    unset _n _falliti _src
  else
    warn "Config NON ripristinata: il backup non contiene una cartella config/"
  fi

  log "Ripristino secrets..."
  mkdir -p secrets
  if [ -d "$TMP/secrets" ]; then
    cp -a "$TMP/secrets/"*.txt secrets/ 2>/dev/null && \
      chmod 600 secrets/*.txt && \
      ok "Secrets ripristinati"
  fi
fi

# ───── 4. restore volumi ─────
# Con --volumes-only ripristina solo i volumi elencati (nomi corti o completi).
_want_volume() {
  [ -z "$VOLUMES_ONLY" ] && return 0
  local name="$1" short
  short="${name#vps1777_}"
  case ",$VOLUMES_ONLY," in
    *",$name,"*|*",$short,"*) return 0 ;;
    *) return 1 ;;
  esac
}

log "Ripristino volumi Docker..."
if [ -d "$TMP/volumes" ]; then
  for tar_file in "$TMP/volumes"/*.tar; do
    [ -f "$tar_file" ] || continue
    vol_name="$(basename "$tar_file" .tar)"
    # Snapshot locali possono usare nomi corti: normalizza al nome compose.
    case "$vol_name" in vps1777_*) ;; *) vol_name="vps1777_${vol_name}" ;; esac
    _want_volume "$vol_name" || { log "  → $vol_name (saltato)"; continue; }
    log "  → $vol_name"
    # Crea volume se non esiste
    docker volume create "$vol_name" >/dev/null
    docker run --rm \
      -v "$vol_name:/dst" \
      -v "$tar_file:/src.tar:ro" \
      --entrypoint sh \
      busybox:1.37.0@sha256:bdf57e528e45e4433820e045b29b4597825a1c9e38353532d90a01445013f82e \
      -c "rm -rf /dst/* /dst/..?* /dst/.[!.]* 2>/dev/null; tar -C /dst -xf /src.tar"
  done
  ok "Volumi ripristinati"
fi

# ───── 5. done ─────
echo
ok "Restore completato."
log "Per riavviare lo stack:"
comando_riavvio
