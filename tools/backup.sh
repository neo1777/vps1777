#!/usr/bin/env bash
# tools/backup.sh — Backup age-encrypted dei volumi + secrets + config, su DUE livelli.
#
# ── I DUE LIVELLI (29/08/2026, decisione dell'owner: «basta n, n-1 per paranoia…
#    dobbiamo farci stare quel che serve») ─────────────────────────────────────
#   Misurato il 29/08 sulla VPS: un backup pesava 9,7 GB, e 9,7 GB erano il solo
#   volume `archive-data` — i DB dell'archivio, RIGENERABILI dai bundle/export che
#   l'owner conserva fuori dalla VPS (re-ingest ~2h, fatto la notte prima). Tutto
#   il resto — gateway-data (utenti, client OAuth, audit), nlm-auth, secrets,
#   config — pesava 250 KB ed è INSOSTITUIBILE. Si pagavano 9,7 GB a notte per
#   proteggere 250 KB, a regime ~70 GB su un disco da 118.
#   ⇒ CORE     — ogni notte: tutto TRANNE i volumi dell'archivio, + l'export delle
#                `description` dei DB (l'unica parte dell'archivio che il
#                re-ingest NON rigenera). Ritenzione: 7 giorni + 4 settimanali +
#                ultime 3 versioni, com'era. Costa KB.
#      ARCHIVIO — ogni ARCHIVIO_OGNI_GIORNI (7): i volumi dell'archivio, compressi
#                prima di cifrare, in `backups/archivio/`. Ritenzione: le ultime
#                KEEP_ARCHIVIO (2) copie — n e n-1. Fra un giro e l'altro la rete
#                è doppia: le fonti fuori dalla VPS + lo snapshot pre-update.
#
# Output: backups/vps1777-YYYY-MM-DD-HHMMSS.tar.age                 (core)
#         backups/archivio/vps1777-archivio-YYYY-MM-DD-HHMMSS.tar.age (archivio)
#
# ⚠️ IL NOME DICE `.tar.age` ANCHE SE DENTRO C'È zstd (o gzip): il suffisso è un
#    CONTRATTO — lo leggono la ritenzione qui sotto, `copertura_backup` nella CLI,
#    `restore.sh`, i test — e cambiarlo avrebbe spostato quel contratto in otto
#    posti per un'informazione che sta già nel sidecar `.meta` (`compressione:`) e
#    nei primi 4 byte del decifrato. `restore.sh` riconosce il formato dai byte,
#    non dal nome. A mano: `age -d -i chiave f.tar.age | zstd -dc | tar -x`.
#
# Cosa include il CORE:
#   - i volumi Docker del progetto TRANNE $VOLUMI_ARCHIVIO (gateway-data,
#     gateway-uploads, nlm-auth, nlm-artifacts, caddy-* se attivi…)
#   - `descrizioni/<db>.txt` — la `description` di ogni DB dell'archivio
#   - Cartella `secrets/` (file in chiaro, age cifra l'archivio intero)
#   - `.env`, `compose.yaml`, `compose.*.yaml`, `ingress/`
# Cosa include l'ARCHIVIO: i soli volumi $VOLUMI_ARCHIVIO (default: archive-data).
#
# Requisiti host: docker, age, tar; zstd (o gzip) per la compressione — se manca
# lo dice e cifra senza comprimere, MAI in silenzio: il livello va nel log e nel
# sidecar.
#
# Usa la chiave age da `tools/age-recipients.txt` (una riga = un recipient).
# Se non esiste, SI FERMA e ti dice come generare la coppia SUL TUO PC (H5).
# 🔴 NIENTE auto-keygen qui: generare la chiave sulla VPS metterebbe la PRIVATA
#    sullo stesso disco dei backup, e la cifratura non proteggerebbe più da furto
#    o perdita del disco — cioè dalla cosa per cui la si sta usando.
#    Il codice che lo impedisce è alle righe 93-102, con le istruzioni.
#
# ⚠️ Fino al 01/08 queste due righe dicevano il contrario — «Se non esiste, fa
#    age-keygen e crea uno solo» — che era vero PRIMA del fix di H5 e non è mai
#    stato aggiornato. Un header che promette proprio il gesto che il corpo del
#    file vieta per sicurezza: chi legge solo l'intestazione conclude che lo
#    script se la cava da solo, e sulla VPS è esattamente ciò che non deve fare.
#
# Uso:
#   bash tools/backup.sh                   core + archivio SE DOVUTO, poi ritenzione
#   bash tools/backup.sh --archivio        core + archivio COMUNQUE (es. pre-cutover)
#   bash tools/backup.sh --senza-archivio  solo core (es. `vps1777 update`, che ha
#                                          già lo snapshot pre-update dell'archivio)
#   bash tools/backup.sh --prune-only      SOLO ritenzione, nessun backup nuovo
#
# `--prune-only` non è un'opzione di comodo: la ritenzione decide quali backup
# sopravvivono, ed è l'unico pezzo di questo script che si può provare senza
# cifrare 2,5 GB. Senza di lei una modifica alla ritenzione andrebbe in
# produzione senza controprova — su backup.

set -euo pipefail

# ───── argomenti ─────
PRUNE_ONLY=0
ARCHIVIO=auto          # auto = se dovuto · si = comunque · no = mai
case "${1:-}" in
  --prune-only)      PRUNE_ONLY=1 ;;
  --archivio)        ARCHIVIO=si ;;
  --senza-archivio)  ARCHIVIO=no ;;
  "")                ;;
  *)  printf 'uso: %s [--prune-only | --archivio | --senza-archivio]\n' "$0" >&2; exit 2 ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

BACKUP_DIR="${BACKUP_DIR:-$REPO_ROOT/backups}"
mkdir -p "$BACKUP_DIR"
# ⚠️ La cartella dell'archivio NON si crea qui: nasce col primo backup archivio.
#    Un `--prune-only` su una cartella di prova non deve lasciarci dentro una
#    sottocartella (il banco della ritenzione confronta i SOPRAVVISSUTI: una dir
#    nuova sarebbe un sopravvissuto in più su tutti i quindici casi).
ARCHIVIO_DIR="$BACKUP_DIR/archivio"
# Nomi LOGICI (senza prefisso progetto), separati da spazio. È l'insieme dei
# volumi RIGENERABILI da fonti fuori dalla VPS: la ragione dello split sta in testa.
VOLUMI_ARCHIVIO="${VOLUMI_ARCHIVIO:-archive-data}"
ARCHIVIO_OGNI_GIORNI="${ARCHIVIO_OGNI_GIORNI:-7}"
KEEP_ARCHIVIO="${KEEP_ARCHIVIO:-2}"

RECIPIENTS_FILE="$SCRIPT_DIR/age-recipients.txt"
TIMESTAMP="$(date -u +%Y-%m-%d-%H%M%S)"
OUT="$BACKUP_DIR/vps1777-${TIMESTAMP}.tar.age"
OUT_ARCHIVIO="$ARCHIVIO_DIR/vps1777-archivio-${TIMESTAMP}.tar.age"
TMP="$(mktemp -d)"
# INCOMPLETO tiene il nome del backup mentre lo stiamo scrivendo, e si svuota
# quando è finito. Senza, un'interruzione a metà — disco pieno, OOM, un kill —
# lascia sul disco un `.tar.age` TRONCATO col nome giusto: la ritenzione lo
# conta come il backup di quel giorno, il conteggio torna, e la finestra di
# ripristino ha dentro un file che non si apre. Un backup rotto che occupa il
# posto di uno buono è peggio di un backup mancante, perché non si vede.
INCOMPLETO=""
trap 'rm -rf "$TMP"; if [ -n "$INCOMPLETO" ]; then rm -f "$INCOMPLETO"; fi' EXIT

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

# ╔═ SOLO SE STIAMO CREANDO UN BACKUP ════════════════════════════════════════╗
# Le sezioni «prerequisiti», «recipients» e 1-4 restano NON indentate dentro
# questo if: è voluto. Rientrarle avrebbe fatto un diff di sessanta righe su uno
# script di backup per una modifica che non le tocca — e un diff illeggibile su
# questo file è un rischio, non uno stile.
#
# I prerequisiti stanno DENTRO e non fuori: la ritenzione non cifra e non
# dumpa, quindi non ha bisogno né di `age` né di docker né di tar. Lasciarli
# fuori avrebbe reso `--prune-only` ineseguibile proprio dove serve provarlo —
# su una macchina qualunque, senza il corredo della VPS.
if [ "$PRUNE_ONLY" -eq 0 ]; then

# ───── prerequisiti ─────
# docker serve SOLO nel contesto host (dump via `docker run`). Nel container
# backup i volumi sono montati direttamente (BACKUP_VOLUMES_DIR) e docker NON
# serve — così il container non monta più docker.sock (finding 2.8/H13).
command -v age    >/dev/null || die "age non installato (apt install age)"
command -v tar    >/dev/null || die "tar non trovato"
if [ -z "${BACKUP_VOLUMES_DIR:-}" ]; then
  command -v docker >/dev/null || die "docker non trovato (né BACKUP_VOLUMES_DIR impostato)"
fi

# ───── compressione: DICHIARATA, mai muta ─────
# SQLite con FTS si comprime 2-3×: il livello archivio è l'unico che pesa, ed è
# proprio quello che finora viaggiava nudo (9,7 GB di .tar.age = 9,7 GB di
# volume, misurato il 29/08). zstd se c'è (multi-thread, veloce), altrimenti
# gzip; se manca anche gzip si cifra senza comprimere — e ognuna delle tre vie
# finisce nel log, nel MANIFEST e nel sidecar `.meta`, così chi ripristina sa
# cosa ha in mano PRIMA di decifrare.
if command -v zstd >/dev/null 2>&1; then
  COMPRESSIONE="zstd"
  comprimi() { zstd -q -T0 -3; }
elif command -v gzip >/dev/null 2>&1; then
  COMPRESSIONE="gzip"
  comprimi() { gzip -1; }
else
  COMPRESSIONE="nessuna"
  comprimi() { cat; }
  warn "né zstd né gzip: cifro SENZA comprimere (l'archivio peserà quanto il volume)"
fi

# ───── il livello ARCHIVIO: è dovuto? ─────
# Si decide dal NOME dell'ultimo backup archivio (la data è nel nome), non dal
# suo mtime: un rsync o un `touch` cambiano l'mtime, non la notte in cui è nato.
_e_volume_archivio() {  # <nome logico> → 0 se appartiene al livello archivio
  case " $VOLUMI_ARCHIVIO " in *" $1 "*) return 0 ;; esac
  return 1
}
archivio_dovuto() {
  local ultimo ymd eta
  # shellcheck disable=SC2012  # nomi generati da questo script: niente caratteri strani
  ultimo="$( (ls -1 "$ARCHIVIO_DIR"/vps1777-archivio-*.tar.age 2>/dev/null || true) | sort | tail -1)"
  [ -n "$ultimo" ] || return 0                      # mai fatto: dovuto
  ymd="$(basename "$ultimo" | sed -E 's/^vps1777-archivio-([0-9]{4}-[0-9]{2}-[0-9]{2}).*/\1/')"
  date -d "$ymd" +%F >/dev/null 2>&1 || return 0    # nome illeggibile: meglio uno in più
  eta=$(( ( $(date -u +%s) - $(date -u -d "$ymd" +%s) ) / 86400 ))
  [ "$eta" -ge "$ARCHIVIO_OGNI_GIORNI" ]
}
FA_ARCHIVIO=0
case "$ARCHIVIO" in
  si)   FA_ARCHIVIO=1 ;;
  no)   FA_ARCHIVIO=0 ;;
  auto) if archivio_dovuto; then FA_ARCHIVIO=1; fi ;;
esac
if [ "$FA_ARCHIVIO" -eq 1 ]; then
  log "livelli: CORE + ARCHIVIO (${VOLUMI_ARCHIVIO}) · compressione: $COMPRESSIONE"
else
  log "livelli: solo CORE (archivio: non dovuto, ne serve uno ogni $ARCHIVIO_OGNI_GIORNI giorni) · compressione: $COMPRESSIONE"
fi
TMP_ARCHIVIO="$TMP/archivio"
mkdir -p "$TMP_ARCHIVIO/volumes"

# ───── recipients ─────
# NIENTE auto-keygen sulla VPS: generare la chiave qui metterebbe la PRIVATA
# sullo stesso disco dei backup → la cifratura non proteggerebbe da furto/perdita
# del disco. Il backup cifra con la sola chiave PUBBLICA (recipient); la privata
# vive sul TUO PC e serve solo per il restore.
if [ ! -s "$RECIPIENTS_FILE" ]; then
  die "Nessun recipient age in $RECIPIENTS_FILE.

Genera la coppia sul TUO PC (NON sulla VPS), la privata resta lì:
    age-keygen -o ~/.config/age/keys.txt
poi copia SOLO la riga 'public key' nel file recipient della VPS:
    grep 'public key' ~/.config/age/keys.txt   # → age1...  in $RECIPIENTS_FILE

Restore: porti la chiave privata dal PC e decifri (vedi docs/BACKUP-RESTORE.md)."
fi

# ───── 1. dump volumi ─────
mkdir -p "$TMP/volumes"
if [ -n "${BACKUP_VOLUMES_DIR:-}" ] && [ -d "$BACKUP_VOLUMES_DIR" ]; then
  # Contesto CONTAINER: i volumi sono montati (ro) sotto $BACKUP_VOLUMES_DIR →
  # tar diretto, NIENTE docker.sock (H13). Un sottodir = un volume.
  log "Dump volumi (mount diretti, no docker.sock)..."
  for src in "$BACKUP_VOLUMES_DIR"/*/; do
    [ -d "$src" ] || continue
    name=$(basename "$src")
    if _e_volume_archivio "$name"; then
      if [ "$FA_ARCHIVIO" -eq 1 ]; then
        log "  → $name (livello ARCHIVIO)"
        tar -C "$src" -cf "$TMP_ARCHIVIO/volumes/vps1777_${name}.tar" . 2>/dev/null || warn "    dump $name fallito (vuoto?)"
      else
        log "  ⚪ $name: livello archivio, non dovuto stanotte"
      fi
      continue
    fi
    log "  → $name"
    tar -C "$src" -cf "$TMP/volumes/vps1777_${name}.tar" . 2>/dev/null || warn "    dump $name fallito (vuoto?)"
  done
else
  # Contesto HOST: docker disponibile → dump via `docker run` (volume ro).
  #
  # 🔴 10/08 — QUI C'ERA UNA LISTA DI VOLUMI ENUMERATA A MANO, e ne perdeva DUE del
  #   compose PRINCIPALE. Misurato mentre si preparava la prova del restore chiesta da
  #   Neo, prima di una formattazione della VPS:
  #     dichiarati nei compose 8 · salvati 6
  #     🔴 gateway-uploads (compose.yaml, montato da `gateway`)  ← i file degli utenti
  #     🔴 nlm-artifacts   (compose.yaml, montato da `nb1777-mcp`)
  #     ⚪ tailscale-state  era nella regex e in NESSUN compose: un nome morto in una
  #        lista viva — la prova che l'insieme non era più governato da nessuno.
  #   Col `|| true` in coda, un volume mancante non era un errore: il ciclo girava su una
  #   lista più corta e stampava «Volumi dumpati». ⭐ Un backup che non trova una cosa non
  #   fallisce: la OMETTE — e al restore la perdita si legge come «fatto», dicendo il vero.
  #
  # 🔑 La regola è già in questo repo, in `restore.sh` (r.~104, per il `down`):
  #   «Docker sa già cosa appartiene al progetto: glielo si chiede, invece di dirglielo.»
  #   Qui si faceva il contrario sullo stesso oggetto. Adesso la lista si CHIEDE: segue
  #   gli overlay ATTIVI (se caddy è su, i suoi volumi ci sono; se non lo è, non servono)
  #   e non può divergere dai compose.
  # ⚠️ FAIL-CLOSED, di proposito: se non si riesce a chiedere, il backup NON PARTE. Un
  #   backup che non sa cosa deve salvare non è un backup ridotto, è un backup falso —
  #   e la sua bugia si scopre solo il giorno del ripristino.
  log "Dump volumi Docker..."
  VOLS_LOGICI=$(docker compose config --volumes 2>/dev/null || true)
  [ -n "$VOLS_LOGICI" ] || die "non riesco a chiedere i volumi a \`docker compose config --volumes\` (variabili .env mancanti?). Un backup che non sa cosa salvare non parte."
  PROJ="${COMPOSE_PROJECT_NAME:-$(basename "$PWD")}"
  VOLUMES=""
  for logico in $VOLS_LOGICI; do
    reale="${PROJ}_${logico}"
    if docker volume inspect "$reale" >/dev/null 2>&1; then
      VOLUMES="$VOLUMES $reale"
    else
      # Dichiarato e non ancora creato: NON è un errore (il servizio può non essere mai
      # partito), ma va DETTO — il silenzio qui è indistinguibile da «l'ho salvato».
      warn "  ⚪ $reale dichiarato nei compose ma non esiste ancora: niente da salvare"
    fi
  done
  # 🔴 10/08, SECONDO GIRO — LA CURA QUI SOPRA AVEVA LASCIATO IL DIFETTO CHE DESCRIVE,
  #   spostato di un anello (trovato da 71d540e6 revisionando la PR #146, e PROVATO
  #   eseguendo: col prefisso sbagliato il ciclo salva ZERO volumi, stampa «✓ Volumi
  #   dumpati» ed esce 0). Il fail-closed copriva «non so QUALI volumi» e non «non ne ho
  #   trovato NESSUNO»: `docker compose config` dà i nomi LOGICI, il prefisso del progetto
  #   lo mette questo script — e se sbaglia il prefisso, ogni volume risulta «non esiste
  #   ancora», che è un avviso, non un errore.
  # ⭐ La lezione, ed è la stessa forma per la terza volta oggi: **una cura può riprodurre
  #   la classe che cura, un anello più in là.** Lì era la lista enumerata, qui è il nome
  #   costruito: in entrambi i casi l'insieme finale non veniva confrontato con nulla.
  # ⇒ ZERO volumi da salvare è un ESITO, e va deciso: o il progetto non è mai partito
  #   (e allora non c'è backup da fare, va detto forte), o il prefisso non combacia (e il
  #   backup sarebbe vuoto e silenzioso). In nessuno dei due casi si prosegue.
  if [ -z "$(echo "$VOLUMES" | tr -d ' ')" ]; then
    die "nessun volume trovato per il progetto «$PROJ»: i compose ne dichiarano $(echo "$VOLS_LOGICI" | wc -w) ($(echo "$VOLS_LOGICI" | tr '\n' ' ')) e nessuno esiste col prefisso «${PROJ}_». O lo stack non è mai partito, o COMPOSE_PROJECT_NAME non è quello con cui sono stati creati i volumi (\`docker volume ls\` per vederli). Un backup vuoto che esce 0 è peggio di un backup che non parte."
  fi
  for vol in $VOLUMES; do
    dst="$TMP/volumes"
    if _e_volume_archivio "${vol#"${PROJ}"_}"; then
      if [ "$FA_ARCHIVIO" -eq 0 ]; then
        log "  ⚪ $vol: livello archivio, non dovuto adesso"
        continue
      fi
      dst="$TMP_ARCHIVIO/volumes"
      log "  → $vol (livello ARCHIVIO)"
    else
      log "  → $vol"
    fi
    docker run --rm \
      -v "$vol:/src:ro" \
      -v "$dst:/dst" \
      --entrypoint sh \
      busybox:latest \
      -c "cd /src && tar cf /dst/${vol}.tar ." 2>/dev/null || warn "    dump $vol fallito (volume vuoto?)"
  done
fi
ok "Volumi dumpati"

# ───── 1-bis. le `description` dei DB: la sola parte dell'archivio che NON si rigenera ─────
# Il re-ingest ricostruisce i DB dalle fonti, ma le schede scritte a mano con
# `set_description` (tabella `meta` di ogni DB) no: senza questo export, un
# restore-da-fonti le perderebbe. Si esportano nel CORE, ogni notte, in chiaro
# dentro il cifrato. Contesto container: il volume è montato sotto
# $BACKUP_VOLUMES_DIR e sqlite3 è nel container (pinnato in
# backup-container-setup.sh). Contesto host: il volume non è leggibile senza
# root e sqlite3 di norma manca ⇒ si DICE, e restano quelle dentro l'ultimo
# backup archivio (al più ARCHIVIO_OGNI_GIORNI giorni indietro).
mkdir -p "$TMP/descrizioni"
n_descr=0
for logico in $VOLUMI_ARCHIVIO; do
  dbdir="${BACKUP_VOLUMES_DIR:-}/$logico/db"
  if [ -z "${BACKUP_VOLUMES_DIR:-}" ] || [ ! -d "$dbdir" ]; then continue; fi
  command -v sqlite3 >/dev/null 2>&1 || continue
  for db in "$dbdir"/*.db; do
    [ -f "$db" ] || continue
    if sqlite3 -readonly "$db" "SELECT value FROM meta WHERE key='description'" \
         > "$TMP/descrizioni/$(basename "$db" .db).txt" 2>/dev/null; then
      n_descr=$((n_descr + 1))
    else
      warn "  description non leggibile: $(basename "$db")"
    fi
  done
done
if [ "$n_descr" -gt 0 ]; then
  ok "description di $n_descr DB esportate (descrizioni/<db>.txt nel core)"
else
  warn "description dei DB NON esportate (volume non leggibile in questo contesto o sqlite3 assente): restano quelle dentro l'ultimo backup archivio"
fi

# ───── 2. config + secrets ─────
log "Archivio config + secrets..."
mkdir -p "$TMP/config"
cp -a .env "$TMP/config/" 2>/dev/null || warn ".env mancante"
cp -a compose*.yaml "$TMP/config/" 2>/dev/null || true
cp -a ingress "$TMP/config/" 2>/dev/null || true
mkdir -p "$TMP/secrets"
cp -a secrets/*.txt "$TMP/secrets/" 2>/dev/null || warn "Nessun secret"
ok "Config + secrets archiviati"

# ───── 3. metadata ─────
# Identità versione: sulla VPS non c'è git (deploy via tar/bundle), quindi
# la verità è il tag deployato (VPS1777_TAG) + il VERSION del bundle.
manifest() {  # <tier> <cosa contiene> → stdout
  echo "vps1777 backup"
  echo "tier: $1"
  echo "contiene: $2"
  echo "compressione: $COMPRESSIONE"
  echo "timestamp: $TIMESTAMP"
  echo "version: $(grep '^VPS1777_TAG=' .env 2>/dev/null | cut -d= -f2 | head -1 || true)"
  echo "bundle: $(tr -d '[:space:]' < VERSION 2>/dev/null || echo '?')"
  echo "git: $(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo 'no-git')"
  echo "host: $(hostname)"
  echo "docker: $(command -v docker >/dev/null && docker --version || echo 'n/d (contesto container)')"
}
manifest core "volumi (tranne $VOLUMI_ARCHIVIO) + descrizioni dei DB + config + secrets" > "$TMP/MANIFEST.txt"
if [ "$FA_ARCHIVIO" -eq 1 ]; then
  manifest archivio "volumi: $VOLUMI_ARCHIVIO" > "$TMP_ARCHIVIO/MANIFEST.txt"
fi

# ───── 4. spazio, poi tar + age ─────
# La stima è il backup più recente che c'è: questo archivio contiene gli stessi
# volumi di ieri, quindi ieri è la miglior previsione di oggi. Al primo giro non
# c'è nulla da cui stimare e non si inventa una soglia — si dice che non si è
# controllato. Il 20% di margine copre la crescita normale dei dati fra due
# notti, non un raddoppio.
# Perché serve: senza, un disco quasi pieno non ferma il backup — lo fa fallire
# a metà scrittura, che è la strada per il file troncato di cui sopra.
# Per LIVELLO: la stima del core viene dall'ultimo core, quella dell'archivio
# dall'ultimo archivio — sommate se stanotte si scrivono entrambi.
# shellcheck disable=SC2012
ULTIMO=$(ls -1t "$BACKUP_DIR"/vps1777-*.tar.age 2>/dev/null | head -1 || true)
SERVE_KB=0
STIMA_DA=""
if [ -n "$ULTIMO" ]; then
  SERVE_KB=$(( $(du -k "$ULTIMO" | cut -f1) * 12 / 10 ))
  STIMA_DA="core $(du -h "$ULTIMO" | cut -f1)"
fi
if [ "$FA_ARCHIVIO" -eq 1 ]; then
  # shellcheck disable=SC2012
  ULTIMO_A=$(ls -1t "$ARCHIVIO_DIR"/vps1777-archivio-*.tar.age 2>/dev/null | head -1 || true)
  if [ -n "$ULTIMO_A" ]; then
    SERVE_KB=$(( SERVE_KB + $(du -k "$ULTIMO_A" | cut -f1) * 12 / 10 ))
    STIMA_DA="${STIMA_DA:+$STIMA_DA + }archivio $(du -h "$ULTIMO_A" | cut -f1)"
  else
    warn "primo backup dell'archivio: nessun precedente da cui stimare il suo spazio"
  fi
fi
if [ "$SERVE_KB" -gt 0 ]; then
  LIBERI_KB=$(df -P "$BACKUP_DIR" | awk 'NR==2 {print $4}')
  if [ "$LIBERI_KB" -lt "$SERVE_KB" ]; then
    die "spazio insufficiente in $BACKUP_DIR: $((LIBERI_KB / 1024)) MB liberi,
ne servono almeno $((SERVE_KB / 1024)) (l'ultimo pesa: $STIMA_DA, + 20% di margine).
Nessun backup scritto: meglio nessuno che uno troncato."
  fi
else
  warn "nessun backup precedente da cui stimare lo spazio necessario: non controllato"
fi

log "Cifro con age (compressione: $COMPRESSIONE)..."
RECIPIENT_ARGS=()
while IFS= read -r r; do
  [ -n "$r" ] && [[ "$r" != \#* ]] && RECIPIENT_ARGS+=("-r" "$r")
done < "$RECIPIENTS_FILE"
[ ${#RECIPIENT_ARGS[@]} -eq 0 ] && die "Nessun recipient valido in $RECIPIENTS_FILE"

# SCRITTURA ATOMICA — il residuo dichiarato di H58, curato qui perché la ragione
# per cui l'avevo rimandato è scaduta: volevo che la modifica della RITENZIONE
# andasse in produzione DA SOLA e misurabile, e ci è andata (0.40.10, misurata).
#
# Il trap copre l'interruzione ordinata; NON copre un `kill -9` né un crash del
# kernel, perché lì il trap non gira. Scrivendo su un nome provvisorio e
# rinominando alla fine, quella classe si chiude per costruzione: la rinomina è
# atomica, quindi il nome definitivo o non esiste o è un file completo. Non c'è
# istante in cui esista un `.tar.age` a metà — che era il modo in cui la
# ritenzione poteva contare come «la copia di quel giorno» un file che non si apre.
#
# `.parziale` NON combacia con `vps1777-*.tar.age`: né il glob della ritenzione,
# né la regex della copertura (ancorata a `.tar.age$`) lo vedono. Verificato coi
# casi ⑩ e ⑪ del test invece che dedotto dalla forma del pattern.
# Il livello archivio è una SOTTOCARTELLA del tar (`archivio/`) fino a qui, e
# viene cifrato A PARTE: `--exclude=./archivio` tiene il core pulito. I due
# livelli si scrivono in sequenza, ognuno col suo `.parziale` — se l'archivio
# muore a metà, il core è già intero e la notte non è scoperta del tutto.
scrivi_cifrato() {  # <dir sorgente> <file di uscita> [opzioni tar…]
  local src="$1" out="$2"; shift 2
  local parziale="$out.parziale"
  mkdir -p "$(dirname "$out")"
  INCOMPLETO="$parziale"
  tar -C "$src" "$@" -cf - . | comprimi | age "${RECIPIENT_ARGS[@]}" -o "$parziale"
  chmod 600 "$parziale"
  # I byte sul disco prima della rinomina: senza, la rinomina sarebbe atomica
  # rispetto ai PROCESSI ma non rispetto a un'interruzione dell'alimentazione, e
  # resterebbe un nome definitivo su un file mai sceso dalla cache. `sync` con un
  # argomento fa fdatasync su quel file solo; se la versione non lo accetta, si
  # prosegue — un backup scritto vale più di una garanzia in più non ottenuta.
  sync "$parziale" 2>/dev/null || true
  mv -f "$parziale" "$out"
  INCOMPLETO=""
}
scrivi_cifrato "$TMP" "$OUT" --exclude=./archivio
if [ "$FA_ARCHIVIO" -eq 1 ]; then
  scrivi_cifrato "$TMP_ARCHIVIO" "$OUT_ARCHIVIO"
fi

# ───── 4-bis. il sidecar: la VERSIONE, in chiaro, accanto all'archivio ─────
# 🔴 PERCHÉ (voce f9818614, metà «b»; scelta di @Neo il 16/08: «b mi sembra ok»).
#   La ritenzione qui è tarata sul TEMPO (7 giorni + 4 weekly) e il volume dipende
#   dal RITMO DI RILASCIO, che non è parametro di nessuno. Gli snapshot pre-update
#   hanno preso l'asse VERSIONI (#169) perché il loro nome LA PORTA:
#   `backups/pre-update/{versione}-{ts}`. Qui il nome è solo `vps1777-{ts}.tar.age`,
#   e la versione esiste — in MANIFEST.txt, riga 208 — ma **dentro il tar cifrato**:
#   leggerla in fase di potatura vorrebbe dire decifrare ~2,58 GB per file a ogni
#   giro. Non è una cura, è un costo.
# ⇒ Il sidecar la mette **fuori**, in chiaro, senza toccare il formato cifrato né
#   il percorso di ripristino (`restore.sh` usa il glob `vps1777-*.tar.age` e
#   accetta un path: un file `.meta` accanto non lo vede nemmeno).
# 🛡️ COSA CI VA E COSA NO: solo la versione e il timestamp. **Niente che non sia
#   già pubblico**: il tag di una release è su GitHub. Il MANIFEST completo resta
#   dentro il cifrato — host, git sha e versione docker NON escono di lì.
# ⚠️ E il sidecar NON è una garanzia di esistenza del backup: è un file accanto, e
#   un accanto si può perdere da solo. Chi legge la retention deve trattare
#   «manca il .meta» come «versione ignota» e ricadere sulla regola a tempo —
#   mai come «backup da potare». Vedi la guardia nella sezione 5.
VERSIONE_TAG="$(grep '^VPS1777_TAG=' .env 2>/dev/null | cut -d= -f2 | head -1 || true)"
sidecar() {  # <file di uscita> <tier>
  {
    echo "version: ${VERSIONE_TAG:-sconosciuta}"
    echo "timestamp: $TIMESTAMP"
    echo "tier: $2"
    echo "compressione: $COMPRESSIONE"   # com'è dentro: restore.sh lo legge dai byte, chi fa a mano da qui
  } > "$1.meta"
  chmod 644 "$1.meta"
}
sidecar "$OUT" core

SIZE=$(du -h "$OUT" | cut -f1)
ok "Backup CORE completato: $OUT ($SIZE) · versione ${VERSIONE_TAG:-sconosciuta} in $(basename "$OUT").meta"
if [ "$FA_ARCHIVIO" -eq 1 ]; then
  sidecar "$OUT_ARCHIVIO" archivio
  ok "Backup ARCHIVIO completato: $OUT_ARCHIVIO ($(du -h "$OUT_ARCHIVIO" | cut -f1)) · compressione $COMPRESSIONE"
fi

else
  log "--prune-only: nessun backup nuovo, applico solo la ritenzione"
fi
# ╚═══════════════════════════════════════════════════════════════════════════╝

# ───── 5. rotation (mantieni schema 7 GIORNI + 4 weekly) ─────
log "Pruning vecchi backup (7 giorni distinti + 4 weekly)..."
cd "$BACKUP_DIR"

# I resti delle scritture uccise prima del trap (`kill -9`, crash, spegnimento).
# A questo punto la rinomina è già avvenuta, quindi qualunque `.parziale` qui è
# spazzatura di un giro precedente — 2,5 GB l'uno su una macchina in cui i backup
# sono già il 69% del disco occupato. Si dicono invece di sparire in silenzio: un
# `.parziale` rimasto è la traccia di un backup MORTO, cioè di una notte scoperta.
for resto in vps1777-*.tar.age.parziale; do
  [ -e "$resto" ] || continue
  warn "resto di una scrittura interrotta, lo rimuovo: $resto ($(du -h "$resto" | cut -f1))"
  warn "  ⇒ quel backup NON è mai stato completato: quella notte non è coperta."
  rm -f "$resto"
done

# I quattro `ls` di questa sezione e di restore.sh danno SC2012 («usa find»).
# Dichiarati invece che riscritti: i nomi li genera QUESTO script
# (vps1777-${TIMESTAMP}.tar.age, TIMESTAMP da `date`) — niente spazi, niente a capo,
# niente caratteri strani. `find` sarebbe più generale e cambierebbe la logica di
# RITENZIONE DEI BACKUP per un rilievo di stile: il rischio sbagliato da correre.
# La riga qui sotto tiene la soglia della CI al minimo senza tollerare nulla in
# silenzio — un'eccezione scritta è diversa da un avviso ignorato.
# shellcheck disable=SC2012
mapfile -t all < <(ls -1 vps1777-*.tar.age 2>/dev/null | sort -r)

# Daily: UNO per GIORNO — il più recente di quel giorno — per gli ultimi 7
# giorni DISTINTI.
#
# PRIMA: `ls | sort -r | head -7`, cioè gli ultimi 7 FILE. La riga prometteva
# «7 daily» e consegnava sette file: due unità di misura diverse con lo stesso
# nome. Finché i backup arrivano uno per notte le due coincidono, ed è per
# questo che è passata inosservata per mesi.
#
# 🔴 MISURATO IN PRODUZIONE il 27/07/2026: sette file, TRE giorni (25-26-27).
# Quattro update nella stessa mattina — 01:54, 06:41, 07:10, 07:50 — hanno
# fatto quattro backup pre-update che si sono presi quattro dei sette posti,
# e i notturni dal 20 al 24 sono stati potati. La finestra di ripristino è
# passata da 7 giorni a 3 senza che nulla lo segnalasse.
#
# ⚠️ E il livello weekly non poteva salvarli: tiene UN backup per settimana
# ISO, e dal 20 al 26 luglio è tutta la settimana 2026-30 (verificato con
# `date +%G-%V`). I due livelli hanno la stessa larghezza — sette giorni —
# quindi il secondo non copre mai i buchi del primo.
#
# ⭐ LA FORMA, che è la cosa da ricordare: la ritenzione conta EVENTI, la
# promessa è in GIORNI, e il produttore di eventi extra è l'update — cioè
# l'evento a rischio. Il giorno in cui aggiorni quattro volte perché qualcosa
# si è rotto è il giorno in cui la finestra di ripristino si accorcia.
#
# 💾 Il costo su disco NON cambia: restano sette posti, ognuno da ~2,58 GB.
# Cambia solo che ora sono sette giorni invece di sette file. Su una macchina
# in cui i backup sono già il 69% del disco occupato, «tenerne di più» non era
# una strada: quella giusta era smettere di sprecarli sullo stesso giorno.
declare -A giorni
daily=()
for f in "${all[@]}"; do
  ymd=$(echo "$f" | sed -E 's/^vps1777-([0-9]{4}-[0-9]{2}-[0-9]{2}).*/\1/')
  # stessa guardia del weekly qui sotto, e per la stessa ragione: un nome non
  # parsabile non deve occupare un posto. `sed` non fallisce su un nome che non
  # combacia — restituisce la stringa intera — quindi la validazione la fa
  # `date`, che su quella stringa non parsa.
  if ! date -d "$ymd" +%F >/dev/null 2>&1; then
    # non occupa un posto — ma nemmeno sparisce in silenzio. Sotto, la
    # cancellazione lo prende comunque perché non è in `keep`: un file che
    # questo script non sa leggere e cancella senza dirlo è il modo in cui si
    # perde un backup senza accorgersene.
    warn "nome non interpretabile, escluso dalla ritenzione: $f"
    continue
  fi
  # `all` è ordinato decrescente ⇒ la prima occorrenza di un giorno è la sua
  # più recente. Per il giorno in corso è il backup fatto appena prima
  # dell'ultimo update: esattamente quello che serve a un rollback.
  if [ -z "${giorni[$ymd]:-}" ] && [ ${#daily[@]} -lt 7 ]; then
    giorni[$ymd]=$f
    daily+=("$f")
  fi
done

# Weekly: tieni 1 per settimana negli ultimi 4 (in più dei 7 daily se distanti)
declare -A weeks
weekly_keep=()
for f in "${all[@]}"; do
  # Estrai YYYY-MM-DD dal nome
  ymd=$(echo "$f" | sed -E 's/^vps1777-([0-9]{4}-[0-9]{2}-[0-9]{2}).*/\1/')
  # PRIMA: `week=$(date … || continue)` — il `continue` girava DENTRO la
  # sostituzione di comando, cioè in una subshell, e non saltava un bel niente
  # (SC2106). Un nome di file non parsabile non veniva scartato: `week` restava
  # vuoto, `weeks[""]` veniva occupato, e quel file si prendeva UNO DEI QUATTRO
  # POSTI weekly buttando fuori un backup vero. In uno script di ritenzione dei
  # backup. Lo diceva shellcheck dal primo giorno: la CI lo eseguiva con
  # `|| true` e ne buttava via il verdetto.
  if ! week=$(date -d "$ymd" +%G-%V 2>/dev/null); then
    continue
  fi
  if [ -z "${weeks[$week]:-}" ] && [ ${#weekly_keep[@]} -lt 4 ]; then
    weeks[$week]=$f
    weekly_keep+=("$f")
  fi
done

# Set degli da tenere
declare -A keep
for f in "${daily[@]}"; do keep[$f]=1; done
for f in "${weekly_keep[@]}"; do keep[$f]=1; done

# ───── 5-bis. …e l'ultimo backup di ciascuna delle ultime N VERSIONI ─────
# 🔴 La metà «b» della voce f9818614 (l'altra è snapshot_prune, #169). I due livelli
#   qui sopra misurano il TEMPO: 7 giorni + 4 settimane. Ma quante VERSIONI indietro
#   si può tornare non lo dice nessuno dei due, e *un margine dichiarato in tempo
#   viene consumato da un ritmo che nessuno misura* — è la tesi della voce, misurata
#   in produzione il 27/07 (8 release in 10 ore).
# 🛡️ STESSO VINCOLO DELLA #169, e qui pesa di più perché questi file sono l'unica
#   copia cifrata: **questo blocco può solo AGGIUNGERE a `keep`, mai togliere.**
#   Se sbaglia a leggere una versione, quel backup ricade sulla regola a tempo di
#   prima — il comportamento precedente, non uno peggiore. Il costo di un errore
#   qui è spazio su disco, non un backup perduto.
# ⚠️ Un `.meta` mancante è «versione IGNOTA», non «da potare»: i backup scritti
#   prima di questa modifica non ce l'hanno, ed è il caso normale per settimane.
KEEP_VERSIONI="${KEEP_VERSIONI:-3}"
declare -A ultimo_per_versione
# ⚠️ `n_versioni` NON è ridondante con `${#ultimo_per_versione[@]}`: sotto `set -u`
#   un array associativo DICHIARATO MA VUOTO è «variabile non assegnata», non un
#   array di zero elementi — verificato isolato su bash 5.2.21. Senza questo
#   contatore lo script esce 1 su OGNI giro in cui nessun backup ha il sidecar,
#   che è il caso normale finché i vecchi non ruotano. Preso dal banco esistente
#   (`test-backup-retention.sh`): 11 su 11 rossi, e il controllo su origin/main
#   era 11 su 11 verdi — il delta diceva che ero io, non il banco.
n_versioni=0
for f in "${all[@]}"; do
  [ -r "$f.meta" ] || continue                       # niente sidecar → versione ignota
  v=$(sed -n 's/^version: *//p' "$f.meta" | head -1 | tr -d '[:space:]')
  v="${v#v}"                                          # il tag è «v0.41.2», la versione «0.41.2»
  case "$v" in ''|sconosciuta) continue;; esac
  # `all` è già ordinato per nome DECRESCENTE (sort -r) e il nome inizia col
  # timestamp: il PRIMO che incontro per una versione è il suo più recente.
  if [ -z "${ultimo_per_versione[$v]:-}" ]; then
    ultimo_per_versione[$v]="$f"
    n_versioni=$((n_versioni + 1))
  fi
done
if [ "$n_versioni" -gt 0 ]; then
  # per ORDINE DI VERSIONE, non alfabetico: «0.10.0» < «0.9.0» come stringhe, e
  # l'ordinamento lessicografico proteggerebbe la versione sbagliata. Stessa
  # trappola dichiarata in vps1777.py:snapshot_versioni_da_tenere.
  mapfile -t ultime < <(printf '%s\n' "${!ultimo_per_versione[@]}" | sort -t. -k1,1n -k2,2n -k3,3n | tail -n "$KEEP_VERSIONI")
  for v in "${ultime[@]}"; do
    f="${ultimo_per_versione[$v]}"
    [ -n "${keep[$f]:-}" ] || log "  ↳ tengo $f: ultimo della versione $v (regola per VERSIONI)"
    keep[$f]=1
  done
fi

# Cancella il resto
removed=0
for f in "${all[@]}"; do
  if [ -z "${keep[$f]:-}" ]; then
    rm -f "$f"
    # il sidecar segue l'archivio: un `.meta` senza il suo `.tar.age` è un
    # puntatore a una cosa che non c'è — la stessa classe del `.parziale` qui sopra.
    rm -f "$f.meta"
    removed=$((removed + 1))
  fi
done

# I `.meta` rimasti orfani per altre vie (backup cancellato a mano, disco pieno a
# metà giro): si dicono e si tolgono. Un orfano non fa danno, ma fa CONTARE una
# versione che non è più ripristinabile — e la regola qui sopra la userebbe.
for m in *.tar.age.meta; do
  [ -e "$m" ] || continue
  [ -e "${m%.meta}" ] && continue
  warn "sidecar orfano (l'archivio non c'è più), lo rimuovo: $m"
  rm -f "$m"
done

if [ "$removed" -gt 0 ]; then
  ok "Rimossi $removed vecchi backup"
else
  ok "Nessun backup da rimuovere"
fi

# ───── 5-ter. la ritenzione dell'ARCHIVIO: le ultime KEEP_ARCHIVIO copie, n e n-1 ─────
# Nessun asse a tempo qui, di proposito: l'archivio è RIGENERABILE dalle fonti e
# la paranoia giusta (decisione dell'owner, 29/08) è «una copia in più di quella
# che serve», non «una copia per ogni giorno». Cartella separata ⇒ i due livelli
# non si contano a vicenda: i glob del core (`vps1777-*.tar.age`) non entrano in
# `archivio/`, e questo blocco non esce da lì.
n_archivio=0
eta_archivio=""
if [ -d "$ARCHIVIO_DIR" ]; then
  for resto in "$ARCHIVIO_DIR"/vps1777-archivio-*.tar.age.parziale; do
    [ -e "$resto" ] || continue
    warn "archivio: resto di una scrittura interrotta, lo rimuovo: $(basename "$resto") ($(du -h "$resto" | cut -f1))"
    rm -f "$resto"
  done
  # shellcheck disable=SC2012  # stessa ragione dei quattro `ls` qui sopra
  mapfile -t tutti_a < <( (ls -1 "$ARCHIVIO_DIR"/vps1777-archivio-*.tar.age 2>/dev/null || true) | sort -r)
  i=0
  rimossi_a=0
  for f in "${tutti_a[@]}"; do
    i=$((i + 1))
    if [ "$i" -le "$KEEP_ARCHIVIO" ]; then
      n_archivio=$((n_archivio + 1))
      continue
    fi
    rm -f "$f" "$f.meta"
    rimossi_a=$((rimossi_a + 1))
  done
  for m in "$ARCHIVIO_DIR"/vps1777-archivio-*.tar.age.meta; do
    [ -e "$m" ] || continue
    [ -e "${m%.meta}" ] && continue
    warn "archivio: sidecar orfano, lo rimuovo: $(basename "$m")"
    rm -f "$m"
  done
  [ "$rimossi_a" -gt 0 ] && ok "archivio: rimosse $rimossi_a copie oltre le ultime $KEEP_ARCHIVIO"
  if [ "${#tutti_a[@]}" -gt 0 ]; then
    ymd_a="$(basename "${tutti_a[0]}" | sed -E 's/^vps1777-archivio-([0-9]{4}-[0-9]{2}-[0-9]{2}).*/\1/')"
    if date -d "$ymd_a" +%F >/dev/null 2>&1; then
      eta_archivio=$(( ( $(date -u +%s) - $(date -u -d "$ymd_a" +%s) ) / 86400 ))
    fi
  fi
fi

# vedi il blocco in testa alla rotazione
# `|| true` NON è tolleranza: senza, su cartella vuota `ls` esce 2, `pipefail`
# lo propaga e `set -e` uccide lo script DOPO che ha già fatto tutto — con un
# codice d'errore che dice «backup fallito» su un backup riuscito. Difetto
# preesistente ma irraggiungibile: nel flusso normale un file c'è sempre,
# perché lo abbiamo appena creato. L'ha scoperto il caso ⑥ del test, quello
# della cartella vuota — cioè uno dei casi messi lì «perché non la riguardano».
# shellcheck disable=SC2012
KEPT=$( (ls -1 vps1777-*.tar.age 2>/dev/null || true) | wc -l)

# ───── 6. il rendiconto, nell'unità della promessa ─────
# PRIMA c'era solo «Backup totali mantenuti: N» — un CONTEGGIO, mentre la
# promessa è in GIORNI. È esattamente il difetto che questa release cura,
# sopravvissuto nella riga che RENDICONTA la cura: il 27/07 sette file
# coprivano tre giorni, e il rendiconto diceva «7» — vero, e muto.
# ⭐ Se questa riga fosse esistita, la finestra ristretta si sarebbe vista da
# sola, nel log del cron, senza che nessuno la cercasse. Un presidio che
# rendiconta in un'unità diversa dalla propria promessa non mente: tace nel
# momento esatto in cui avrebbe dovuto parlare.
# Rilievo di abdd732a, misurando l'arrivo della 0.40.10 in produzione.
# La copertura si misura su ciò che è RIMASTO SUL DISCO, non sull'insieme che
# volevamo tenere: misurare l'intento invece del risultato è la stessa classe
# di errore, un piano più su.
# shellcheck disable=SC2012
mapfile -t restanti < <( (ls -1 vps1777-*.tar.age 2>/dev/null || true) | sort )
declare -A visti
copertura=0
primo=""
ultimo=""
for f in "${restanti[@]}"; do
  ymd=$(echo "$f" | sed -E 's/^vps1777-([0-9]{4}-[0-9]{2}-[0-9]{2}).*/\1/')
  if ! date -d "$ymd" +%F >/dev/null 2>&1; then
    continue
  fi
  if [ -z "${visti[$ymd]:-}" ]; then
    visti[$ymd]=1
    copertura=$((copertura + 1))
    if [ -z "$primo" ]; then
      primo=$ymd
    fi
    ultimo=$ymd
  fi
done

if [ "$copertura" -eq 0 ]; then
  warn "copertura: NESSUN giorno — non c'è un solo backup con una data leggibile"
elif [ "$copertura" -lt 7 ]; then
  warn "copertura: $copertura giorni distinti ($primo → $ultimo) sui 7 promessi.
  Su un'installazione nuova è normale: la finestra si riempie una notte per volta.
  Se NON è nuova, qualcosa ha potato più del dovuto — il sospettato tipico è un
  giorno con più aggiornamenti, perché ognuno fa la sua copia."
else
  ok "copertura: $copertura giorni distinti ($primo → $ultimo)"
fi
ok "Backup totali mantenuti: $KEPT file"
# Il rendiconto dell'archivio, nella SUA unità: copie e giorni dall'ultima.
# Un archivio più vecchio del doppio del passo è una promessa mancata — il cron
# non gira, o gira e fallisce a metà: si dice qui, dove il log del cron lo mostra.
if [ "$n_archivio" -eq 0 ]; then
  warn "archivio: NESSUNA copia in $ARCHIVIO_DIR (ne è dovuta una ogni $ARCHIVIO_OGNI_GIORNI giorni)"
elif [ -n "$eta_archivio" ] && [ "$eta_archivio" -gt $(( ARCHIVIO_OGNI_GIORNI * 2 )) ]; then
  warn "archivio: $n_archivio copie, ma l'ultima ha $eta_archivio giorni — ne era dovuta una ogni $ARCHIVIO_OGNI_GIORNI"
else
  ok "archivio: $n_archivio copie (ultime $KEEP_ARCHIVIO tenute), ultima di ${eta_archivio:-?} giorni fa"
fi
