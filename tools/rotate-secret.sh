#!/usr/bin/env bash
# tools/rotate-secret.sh — Rotation guidata dei secret.
#
# Uso:
#   ./tools/rotate-secret.sh                    # menu interattivo
#   ./tools/rotate-secret.sh gateway_secret
#   ./tools/rotate-secret.sh oauth_signing_secret
#   ./tools/rotate-secret.sh admin_password
#   ./tools/rotate-secret.sh telegram_bot_token

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

WHICH="${1:-}"

# ───── UI ─────
if [ -t 1 ]; then
  C_B=$'\e[1m'; C_OK=$'\e[32m'; C_W=$'\e[33m'; C_E=$'\e[31m'; C_I=$'\e[34m'; C_R=$'\e[0m'
else
  C_B=''; C_OK=''; C_W=''; C_E=''; C_I=''; C_R=''
fi
log()  { printf '%s[*]%s %s\n' "$C_I"  "$C_R" "$*"; }
ok()   { printf '%s[✓]%s %s\n' "$C_OK" "$C_R" "$*"; }
warn() { printf '%s[!]%s %s\n' "$C_W"  "$C_R" "$*"; }
die()  { printf '%s[✗]%s %s\n' "$C_E"  "$C_R" "$*" >&2; exit 1; }

gen_random() { python3 -c "import secrets; print(secrets.token_urlsafe($1))"; }
gen_pass()   { python3 -c "import secrets,string; print(''.join(secrets.choice(string.ascii_letters+string.digits) for _ in range($1)))"; }

if [ -z "$WHICH" ]; then
  echo "Quale secret ruotare?"
  echo "  1) gateway_secret          — namespace URL"
  echo "  2) oauth_signing_secret    — JWT signing key (invalida TUTTI i token)"
  echo "  3) admin_password          — password admin OAuth"
  echo "  4) telegram_bot_token      — TOKEN BotFather"
  printf '%sScelta [1-4]:%s ' "$C_B" "$C_R"
  read -r choice
  case "$choice" in
    1) WHICH=gateway_secret ;;
    2) WHICH=oauth_signing_secret ;;
    3) WHICH=admin_password ;;
    4) WHICH=telegram_bot_token ;;
    *) die "Scelta non valida" ;;
  esac
fi

case "$WHICH" in
  gateway_secret)
    FILE=secrets/gateway_secret.txt
    log "Rotation gateway_secret (namespace URL)"
    log "ATTENZIONE: gli URL connector di claude.ai cambieranno. Dovrai rigenerare i connector."
    read -r -p "Procedo? [s/N]: " ack
    case "$ack" in s|S|si|SI|y|Y|yes|YES) ;; *) die "Annullato" ;; esac
    NEW=$(gen_random 24)
    echo -n "$NEW" > "$FILE"
    chmod 600 "$FILE"
    ok "Nuovo gateway_secret: $NEW"
    log "Restart gateway in corso..."
    docker compose restart gateway
    ok "Fatto. Aggiorna i connector claude.ai con i nuovi URL."
    ;;
  oauth_signing_secret)
    FILE=secrets/oauth_signing_secret.txt
    log "Rotation oauth_signing_secret"
    warn "ATTENZIONE: invalida TUTTI i token attivi (access, refresh, admin cookie, miniapp)."
    warn "I client OAuth (claude.ai) re-faranno login via refresh; tu re-login admin."
    read -r -p "Procedo? [s/N]: " ack
    case "$ack" in s|S|si|SI|y|Y|yes|YES) ;; *) die "Annullato" ;; esac
    NEW=$(gen_random 48)
    echo -n "$NEW" > "$FILE"
    chmod 600 "$FILE"
    ok "Nuovo oauth_signing_secret generato (48 byte url-safe)"
    docker compose restart gateway
    ok "Fatto"
    ;;
  admin_password)
    FILE=secrets/admin_password_bcrypt.txt
    log "Rotation password admin OAuth"
    if [ -t 0 ]; then
      printf '%sNuova password (min 12 char, vuoto = genero io):%s ' "$C_B" "$C_R"
      read -rs PWD
      echo
    fi
    if [ -z "${PWD:-}" ]; then
      PWD=$(gen_pass 24)
      log "Password generata: ${C_B}$PWD${C_R}"
      log "  → SALVALA SUBITO in password manager. Non te la riproporrò."
    fi
    if [ "${#PWD}" -lt 12 ]; then die "Password troppo corta (min 12 char)"; fi
    if ! python3 -c 'import bcrypt' 2>/dev/null; then
      python3 -m pip install --user --quiet bcrypt || die "bcrypt non installabile"
    fi
    ADMIN_PWD_RAW="$PWD" python3 -c '
import os, bcrypt
print(bcrypt.hashpw(os.environ["ADMIN_PWD_RAW"].encode(), bcrypt.gensalt(12)).decode())
' > "$FILE"
    chmod 600 "$FILE"
    ok "Nuovo bcrypt salvato"
    docker compose restart gateway
    ok "Fatto. Login admin con la nuova password."
    ;;
  telegram_bot_token)
    FILE=secrets/telegram_bot_token.txt
    log "Rotation telegram_bot_token"
    log "Revoca il TOKEN vecchio su @BotFather → /mybots → API Token → Revoke."
    log "Poi genera il nuovo e incollalo qui."
    printf '%sNuovo TOKEN:%s ' "$C_B" "$C_R"
    read -r TOK
    [ -z "$TOK" ] && die "TOKEN vuoto"
    echo -n "$TOK" > "$FILE"
    chmod 600 "$FILE"
    ok "TOKEN salvato"
    docker compose restart nb1777-bot gateway
    ok "Fatto"
    ;;
  *)
    die "secret '$WHICH' non gestito"
    ;;
esac
