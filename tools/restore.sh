#!/usr/bin/env bash
# tools/restore.sh — Ripristina un backup age-encrypted.
#
# Uso: ./tools/restore.sh backups/vps1777-YYYY-MM-DD-HHMMSS.tar.age
#
# Procedura:
#   1. ferma stack: docker compose down
#   2. decifra l'archivio con la chiave age (~/.config/age/keys.txt)
#   3. ripristina volumi Docker, secrets, config
#   4. lascia all'utente lanciare `docker compose up -d` per ripartire

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

ARCHIVE="${1:-}"
AGE_KEY="${AGE_KEY:-$HOME/.config/age/keys.txt}"

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

# ───── arg ─────
if [ -z "$ARCHIVE" ]; then
  echo "Uso: $0 <path/to/backup.tar.age>"
  echo
  echo "Backup disponibili in backups/:"
  ls -1 backups/vps1777-*.tar.age 2>/dev/null | sed 's/^/  /' || echo "  (nessuno)"
  exit 1
fi
[ -f "$ARCHIVE" ] || die "archivio non trovato: $ARCHIVE"
[ -f "$AGE_KEY" ] || die "chiave age non trovata: $AGE_KEY"

# ───── prerequisiti ─────
command -v docker >/dev/null || die "docker non trovato"
command -v age    >/dev/null || die "age non installato"
command -v tar    >/dev/null || die "tar non trovato"

# ───── conferma ─────
echo
warn "ATTENZIONE: questo cancella i volumi correnti e sovrascrive .env + secrets."
warn "Archivio: $ARCHIVE"
echo
read -r -p "Procedo? [s/N]: " ack
case "$ack" in s|S|si|SI|y|Y|yes|YES) ;; *) die "Annullato" ;; esac

# ───── 1. stop stack ─────
log "Stop stack..."
docker compose down 2>/dev/null || true

# ───── 2. decifra ─────
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
log "Decifro archivio..."
age -d -i "$AGE_KEY" "$ARCHIVE" | tar -C "$TMP" -xf -
ok "Decifrato"

# Mostra manifest
if [ -f "$TMP/MANIFEST.txt" ]; then
  log "Manifest del backup:"
  sed 's/^/    /' "$TMP/MANIFEST.txt"
fi

# ───── 3. restore config + secrets ─────
log "Ripristino config..."
if [ -d "$TMP/config" ]; then
  cp -a "$TMP/config/.env" . 2>/dev/null || true
  cp -a "$TMP/config/"compose*.yaml . 2>/dev/null || true
  cp -a "$TMP/config/ingress" . 2>/dev/null || true
  ok "Config ripristinata"
fi

log "Ripristino secrets..."
mkdir -p secrets
if [ -d "$TMP/secrets" ]; then
  cp -a "$TMP/secrets/"*.txt secrets/ 2>/dev/null && \
    chmod 600 secrets/*.txt && \
    ok "Secrets ripristinati"
fi

# ───── 4. restore volumi ─────
log "Ripristino volumi Docker..."
if [ -d "$TMP/volumes" ]; then
  for tar_file in "$TMP/volumes"/*.tar; do
    [ -f "$tar_file" ] || continue
    vol_name="$(basename "$tar_file" .tar)"
    log "  → $vol_name"
    # Crea volume se non esiste
    docker volume create "$vol_name" >/dev/null
    docker run --rm \
      -v "$vol_name:/dst" \
      -v "$tar_file:/src.tar:ro" \
      --entrypoint sh \
      busybox:latest \
      -c "rm -rf /dst/* /dst/..?* /dst/.[!.]* 2>/dev/null; tar -C /dst -xf /src.tar"
  done
  ok "Volumi ripristinati"
fi

# ───── 5. done ─────
echo
ok "Restore completato."
log "Per riavviare lo stack:"
INGRESS_PROFILE="$(grep ^INGRESS_PROFILE= .env 2>/dev/null | cut -d= -f2)"
if [ -n "$INGRESS_PROFILE" ]; then
  log "  docker compose -f compose.yaml -f compose.${INGRESS_PROFILE}.yaml --profile $INGRESS_PROFILE up -d"
else
  log "  docker compose --profile ingress.tailscale up -d   # o caddy / cloudflared"
fi
