#!/usr/bin/env bash
# tools/backup.sh — Backup age-encrypted di tutti i volumi + secrets + config.
#
# Output: backups/vps1777-YYYY-MM-DD-HHMMSS.tar.age
#
# Cosa include:
#   - Volumi Docker nominati (gateway-data, archive-data, nlm-auth, tailscale-state, caddy-data)
#   - Cartella `secrets/` (file in chiaro, age cifra l'archivio intero)
#   - `.env`, `compose.yaml`, `compose.*.yaml`, `ingress/`
#
# Requisiti host: docker, age, tar.
#
# Usa la chiave age da `tools/age-recipients.txt` (una riga = un recipient).
# Se non esiste, fa age-keygen e crea uno solo.
#
# Uso:
#   bash tools/backup.sh                 backup nuovo + ritenzione
#   bash tools/backup.sh --prune-only    SOLO ritenzione, nessun backup nuovo
#
# `--prune-only` non è un'opzione di comodo: la ritenzione decide quali backup
# sopravvivono, ed è l'unico pezzo di questo script che si può provare senza
# cifrare 2,5 GB. Senza di lei una modifica alla ritenzione andrebbe in
# produzione senza controprova — su backup.

set -euo pipefail

# ───── argomenti ─────
PRUNE_ONLY=0
case "${1:-}" in
  --prune-only) PRUNE_ONLY=1 ;;
  "")           ;;
  *)            printf 'uso: %s [--prune-only]\n' "$0" >&2; exit 2 ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

BACKUP_DIR="${BACKUP_DIR:-$REPO_ROOT/backups}"
mkdir -p "$BACKUP_DIR"

RECIPIENTS_FILE="$SCRIPT_DIR/age-recipients.txt"
TIMESTAMP="$(date -u +%Y-%m-%d-%H%M%S)"
OUT="$BACKUP_DIR/vps1777-${TIMESTAMP}.tar.age"
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
    log "  → $name"
    tar -C "$src" -cf "$TMP/volumes/vps1777_${name}.tar" . 2>/dev/null || warn "    dump $name fallito (vuoto?)"
  done
else
  # Contesto HOST: docker disponibile → dump via `docker run` (volume ro).
  log "Dump volumi Docker..."
  VOLUMES=$(docker volume ls -q | grep -E '^vps1777_(gateway-data|archive-data|nlm-auth|tailscale-state|caddy-data|caddy-config)$' || true)
  for vol in $VOLUMES; do
    log "  → $vol"
    docker run --rm \
      -v "$vol:/src:ro" \
      -v "$TMP/volumes:/dst" \
      --entrypoint sh \
      busybox:latest \
      -c "cd /src && tar cf /dst/${vol}.tar ." 2>/dev/null || warn "    dump $vol fallito (volume vuoto?)"
  done
fi
ok "Volumi dumpati"

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
{
  echo "vps1777 backup"
  echo "timestamp: $TIMESTAMP"
  echo "version: $(grep '^VPS1777_TAG=' .env 2>/dev/null | cut -d= -f2 | head -1 || true)"
  echo "bundle: $(tr -d '[:space:]' < VERSION 2>/dev/null || echo '?')"
  echo "git: $(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo 'no-git')"
  echo "host: $(hostname)"
  echo "docker: $(command -v docker >/dev/null && docker --version || echo 'n/d (contesto container)')"
} > "$TMP/MANIFEST.txt"

# ───── 4. spazio, poi tar + age ─────
# La stima è il backup più recente che c'è: questo archivio contiene gli stessi
# volumi di ieri, quindi ieri è la miglior previsione di oggi. Al primo giro non
# c'è nulla da cui stimare e non si inventa una soglia — si dice che non si è
# controllato. Il 20% di margine copre la crescita normale dei dati fra due
# notti, non un raddoppio.
# Perché serve: senza, un disco quasi pieno non ferma il backup — lo fa fallire
# a metà scrittura, che è la strada per il file troncato di cui sopra.
# shellcheck disable=SC2012
ULTIMO=$(ls -1t "$BACKUP_DIR"/vps1777-*.tar.age 2>/dev/null | head -1 || true)
if [ -n "$ULTIMO" ]; then
  SERVE_KB=$(( $(du -k "$ULTIMO" | cut -f1) * 12 / 10 ))
  LIBERI_KB=$(df -P "$BACKUP_DIR" | awk 'NR==2 {print $4}')
  if [ "$LIBERI_KB" -lt "$SERVE_KB" ]; then
    die "spazio insufficiente in $BACKUP_DIR: $((LIBERI_KB / 1024)) MB liberi,
ne servono almeno $((SERVE_KB / 1024)) (l'ultimo backup pesa $(du -h "$ULTIMO" | cut -f1) + 20% di margine).
Nessun backup scritto: meglio nessuno che uno troncato."
  fi
else
  warn "nessun backup precedente da cui stimare lo spazio necessario: non controllato"
fi

log "Cifro con age..."
RECIPIENT_ARGS=()
while IFS= read -r r; do
  [ -n "$r" ] && [[ "$r" != \#* ]] && RECIPIENT_ARGS+=("-r" "$r")
done < "$RECIPIENTS_FILE"
[ ${#RECIPIENT_ARGS[@]} -eq 0 ] && die "Nessun recipient valido in $RECIPIENTS_FILE"

INCOMPLETO="$OUT"
tar -C "$TMP" -cf - . | age "${RECIPIENT_ARGS[@]}" -o "$OUT"
chmod 600 "$OUT"
INCOMPLETO=""
SIZE=$(du -h "$OUT" | cut -f1)
ok "Backup completato: $OUT ($SIZE)"

else
  log "--prune-only: nessun backup nuovo, applico solo la ritenzione"
fi
# ╚═══════════════════════════════════════════════════════════════════════════╝

# ───── 5. rotation (mantieni schema 7 GIORNI + 4 weekly) ─────
log "Pruning vecchi backup (7 giorni distinti + 4 weekly)..."
cd "$BACKUP_DIR"

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

# Cancella il resto
removed=0
for f in "${all[@]}"; do
  if [ -z "${keep[$f]:-}" ]; then
    rm -f "$f"
    removed=$((removed + 1))
  fi
done

if [ "$removed" -gt 0 ]; then
  ok "Rimossi $removed vecchi backup"
else
  ok "Nessun backup da rimuovere"
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
