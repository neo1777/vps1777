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

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

BACKUP_DIR="${BACKUP_DIR:-$REPO_ROOT/backups}"
mkdir -p "$BACKUP_DIR"

RECIPIENTS_FILE="$SCRIPT_DIR/age-recipients.txt"
TIMESTAMP="$(date -u +%Y-%m-%d-%H%M%S)"
OUT="$BACKUP_DIR/vps1777-${TIMESTAMP}.tar.age"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

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

# ───── prerequisiti ─────
command -v docker >/dev/null || die "docker non trovato"
command -v age    >/dev/null || die "age non installato (apt install age)"
command -v tar    >/dev/null || die "tar non trovato"

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
log "Dump volumi Docker..."
mkdir -p "$TMP/volumes"
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
  echo "docker: $(docker --version)"
} > "$TMP/MANIFEST.txt"

# ───── 4. tar + age ─────
log "Cifro con age..."
RECIPIENT_ARGS=()
while IFS= read -r r; do
  [ -n "$r" ] && [[ "$r" != \#* ]] && RECIPIENT_ARGS+=("-r" "$r")
done < "$RECIPIENTS_FILE"
[ ${#RECIPIENT_ARGS[@]} -eq 0 ] && die "Nessun recipient valido in $RECIPIENTS_FILE"

tar -C "$TMP" -cf - . | age "${RECIPIENT_ARGS[@]}" -o "$OUT"
chmod 600 "$OUT"
SIZE=$(du -h "$OUT" | cut -f1)
ok "Backup completato: $OUT ($SIZE)"

# ───── 5. rotation (mantieni schema 7 daily + 4 weekly) ─────
log "Pruning vecchi backup (7 daily + 4 weekly)..."
cd "$BACKUP_DIR"

# Daily: tieni gli ultimi 7
mapfile -t daily < <(ls -1 vps1777-*.tar.age 2>/dev/null | sort -r | head -7)
mapfile -t all < <(ls -1 vps1777-*.tar.age 2>/dev/null | sort -r)

# Weekly: tieni 1 per settimana negli ultimi 4 (in più dei 7 daily se distanti)
declare -A weeks
weekly_keep=()
for f in "${all[@]}"; do
  # Estrai YYYY-MM-DD dal nome
  ymd=$(echo "$f" | sed -E 's/^vps1777-([0-9]{4}-[0-9]{2}-[0-9]{2}).*/\1/')
  week=$(date -d "$ymd" +%G-%V 2>/dev/null || continue)
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

KEPT=$(ls vps1777-*.tar.age 2>/dev/null | wc -l)
ok "Backup totali mantenuti: $KEPT"
