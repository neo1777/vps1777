#!/usr/bin/env bash
# tools/restore.sh — Ripristina un backup age-encrypted o uno snapshot locale.
#
# Uso:
#   ./tools/restore.sh backups/vps1777-YYYY-MM-DD-HHMMSS.tar.age
#   ./tools/restore.sh --yes --volumes-only vol1,vol2 backups/pre-update/<dir>
#
# Input:
#   - archivio .tar.age  → decifrato con la chiave age (~/.config/age/keys.txt)
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
#   1. ferma stack: docker compose down
#   2. decifra/legge l'input
#   3. ripristina volumi Docker (+ secrets/config se non --volumes-only)
#   4. lascia all'utente (o alla CLI) lanciare `docker compose up -d`

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

AGE_KEY="${AGE_KEY:-$HOME/.config/age/keys.txt}"

ARCHIVE=""
ASSUME_YES=0
VOLUMES_ONLY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --yes) ASSUME_YES=1 ;;
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

# ───── arg ─────
if [ -z "$ARCHIVE" ]; then
  echo "Uso: $0 [--yes] [--volumes-only v1,v2] <backup.tar.age | snapshot-dir>"
  echo
  echo "Backup disponibili in backups/:"
  ls -1 backups/vps1777-*.tar.age 2>/dev/null | sed 's/^/  /' || echo "  (nessuno)"
  exit 1
fi
[ -e "$ARCHIVE" ] || die "input non trovato: $ARCHIVE"

# ───── prerequisiti ─────
command -v docker >/dev/null || die "docker non trovato"
command -v tar    >/dev/null || die "tar non trovato"
if [ -f "$ARCHIVE" ]; then
  command -v age >/dev/null || die "age non installato"
  [ -f "$AGE_KEY" ] || die "chiave age non trovata: $AGE_KEY"
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
log "Stop stack..."
docker compose down 2>/dev/null || true

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
  log "Decifro archivio..."
  age -d -i "$AGE_KEY" "$ARCHIVE" | tar -C "$TMP" -xf -
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
