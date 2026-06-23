#!/usr/bin/env bash
# setup.sh — wizard interattivo per il primo install di vps1777.
#
# Cosa fa:
#   1. Controlla Docker + Compose v2 + python3
#   2. Crea .env da .env.example (chiedendoti email admin, OWNER_ID, ingress scelto)
#   3. Genera secrets/* (gateway_secret, oauth_signing, admin_password bcrypt, ts_authkey)
#   4. Avvia `docker compose --profile ingress.<scelto> up -d`
#
# Idempotente: rilanciabile, salta lo step se già fatto.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ───── UI helpers ─────
if [ -t 1 ]; then
  C_R=$'\e[0m'; C_B=$'\e[1m'; C_OK=$'\e[32m'; C_W=$'\e[33m'; C_E=$'\e[31m'; C_I=$'\e[34m'
else
  C_R=''; C_B=''; C_OK=''; C_W=''; C_E=''; C_I=''
fi
log()  { printf '%s[*]%s %s\n' "$C_I"  "$C_R" "$*"; }
ok()   { printf '%s[✓]%s %s\n' "$C_OK" "$C_R" "$*"; }
warn() { printf '%s[!]%s %s\n' "$C_W"  "$C_R" "$*"; }
die()  { printf '%s[✗]%s %s\n' "$C_E"  "$C_R" "$*" >&2; exit 1; }
ask()  {
  local var="$1" question="$2" default="${3:-}" response
  if [ -n "$default" ]; then
    printf '%s%s%s [%s]: ' "$C_B" "$question" "$C_R" "$default" >&2
  else
    printf '%s%s%s: ' "$C_B" "$question" "$C_R" >&2
  fi
  IFS= read -r response || true
  [ -z "$response" ] && response="$default"
  printf -v "$var" '%s' "$response"
}
confirm() {
  local prompt="$1" response
  printf '%s%s%s [s/N]: ' "$C_B" "$prompt" "$C_R" >&2
  IFS= read -r response || true
  case "$response" in s|S|si|SI|y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

cat <<'BANNER'

  ┌─────────────────────────────────────────────────────────────┐
  │                                                             │
  │   vps1777 — setup wizard                                    │
  │                                                             │
  └─────────────────────────────────────────────────────────────┘

BANNER

# ───── 1. preflight ─────
log "Verifico Docker + Compose..."
command -v docker >/dev/null || die "Docker non installato. Vedi https://docs.docker.com/engine/install/"
docker compose version >/dev/null 2>&1 || die "docker compose v2 non disponibile. Aggiorna Docker."
command -v python3 >/dev/null || die "python3 non installato"
ok "Docker $(docker --version | awk '{print $3}' | tr -d ',') + Compose v2 OK"

# ───── 2. .env ─────
if [ -f .env ]; then
  warn ".env esiste già. Per rigenerare, cancellalo prima."
else
  log "Configuro .env..."
  ask ADMIN_EMAIL "Email admin OAuth (il TUO Gmail)" ""
  [ -z "$ADMIN_EMAIL" ] && die "Email admin obbligatoria"
  ask TG_OWNER_ID "TELEGRAM_OWNER_ID (numerico, da @userinfobot)" ""
  [ -z "$TG_OWNER_ID" ] && warn "OWNER_ID vuoto — il bot Telegram non risponderà. Imposterai dopo."

  echo
  log "Scegli ingress:"
  log "  1) Tailscale Funnel (consigliato — HTTPS auto, magicDNS)"
  log "  2) Caddy + Let's Encrypt (richiede tuo dominio)"
  log "  3) Cloudflare Tunnel (richiede account CF + token)"
  ask INGRESS_NUM "Quale ingress? [1/2/3]" "1"
  case "$INGRESS_NUM" in
    1) INGRESS=tailscale; PUBLIC_BASE="" ;;
    2) INGRESS=caddy
       ask CADDY_DOMAIN "Dominio (es. vps.miosito.com)" ""
       ask CADDY_EMAIL "Email per Let's Encrypt" "$ADMIN_EMAIL"
       PUBLIC_BASE="https://$CADDY_DOMAIN"
       ;;
    3) INGRESS=cloudflared; PUBLIC_BASE=""; CADDY_DOMAIN=""; CADDY_EMAIL="" ;;
    *) die "Scelta non valida" ;;
  esac

  cp .env.example .env
  sed -i "s|^ADMIN_EMAIL=.*|ADMIN_EMAIL=$ADMIN_EMAIL|" .env
  sed -i "s|^TELEGRAM_OWNER_ID=.*|TELEGRAM_OWNER_ID=$TG_OWNER_ID|" .env
  sed -i "s|^PUBLIC_BASE=.*|PUBLIC_BASE=$PUBLIC_BASE|" .env
  [ -n "${CADDY_DOMAIN:-}" ] && sed -i "s|^CADDY_DOMAIN=.*|CADDY_DOMAIN=$CADDY_DOMAIN|" .env
  [ -n "${CADDY_EMAIL:-}" ] && sed -i "s|^CADDY_EMAIL=.*|CADDY_EMAIL=$CADDY_EMAIL|" .env
  echo "INGRESS_PROFILE=ingress.$INGRESS" >> .env
  ok ".env creato"
fi

# ───── 3. secrets ─────
log "Genero secrets in secrets/..."
mkdir -p secrets

gen_random() { python3 -c "import secrets; print(secrets.token_urlsafe($1))"; }

if [ ! -s secrets/gateway_secret.txt ]; then
  gen_random 24 > secrets/gateway_secret.txt
  chmod 600 secrets/gateway_secret.txt
  ok "gateway_secret.txt generato"
else
  ok "gateway_secret.txt già presente"
fi

if [ ! -s secrets/oauth_signing_secret.txt ]; then
  gen_random 48 > secrets/oauth_signing_secret.txt
  chmod 600 secrets/oauth_signing_secret.txt
  ok "oauth_signing_secret.txt generato"
else
  ok "oauth_signing_secret.txt già presente"
fi

if [ ! -s secrets/admin_password_bcrypt.txt ]; then
  log ""
  if confirm "Vuoi che generi io una password admin random (24 char)?"; then
    ADMIN_PWD="$(python3 -c 'import secrets,string; print("".join(secrets.choice(string.ascii_letters+string.digits) for _ in range(24)))')"
    log "Password admin generata: $C_B$ADMIN_PWD$C_R"
    log "  → SALVALA SUBITO in un password manager. Non te la riproporrò."
  else
    printf '%sPassword admin (min 12 char):%s ' "$C_B" "$C_R"
    read -rs ADMIN_PWD
    echo
    [ -z "$ADMIN_PWD" ] || [ ${#ADMIN_PWD} -lt 12 ] && die "Password troppo corta"
  fi
  log "Calcolo bcrypt..."
  # Usa python3 di sistema con bcrypt (installato al volo se manca)
  if ! python3 -c 'import bcrypt' 2>/dev/null; then
    python3 -m pip install --user --quiet bcrypt || die "Impossibile installare bcrypt"
  fi
  ADMIN_PWD_RAW="$ADMIN_PWD" python3 -c '
import os, bcrypt
pwd = os.environ["ADMIN_PWD_RAW"].encode()
print(bcrypt.hashpw(pwd, bcrypt.gensalt(rounds=12)).decode())
' > secrets/admin_password_bcrypt.txt
  chmod 600 secrets/admin_password_bcrypt.txt
  ok "admin_password_bcrypt.txt generato"
else
  ok "admin_password_bcrypt.txt già presente (per rigenerarla, cancellala)"
fi

if [ ! -s secrets/telegram_bot_token.txt ]; then
  ask TG_TOKEN "TELEGRAM_BOT_TOKEN (da @BotFather, vuoto per configurare dopo)" ""
  if [ -n "$TG_TOKEN" ]; then
    printf '%s' "$TG_TOKEN" > secrets/telegram_bot_token.txt
    chmod 600 secrets/telegram_bot_token.txt
    ok "telegram_bot_token.txt salvato"
  else
    : > secrets/telegram_bot_token.txt
    chmod 600 secrets/telegram_bot_token.txt
    warn "Token Telegram vuoto — il bot non partirà. Salvalo dopo in secrets/telegram_bot_token.txt"
  fi
fi

# ───── 4. Pull immagini ingress + start ─────
INGRESS_PROFILE="$(grep ^INGRESS_PROFILE= .env | cut -d= -f2)"
COMPOSE_FILES=("-f" "compose.yaml" "-f" "compose.${INGRESS_PROFILE}.yaml")

log ""
log "Pronto a lanciare:"
log "  docker compose ${COMPOSE_FILES[*]} --profile $INGRESS_PROFILE up -d --build"
log ""
if confirm "Procedo ora?"; then
  docker compose "${COMPOSE_FILES[@]}" --profile "$INGRESS_PROFILE" up -d --build
  echo
  ok "Stack avviato. Stato:"
  docker compose "${COMPOSE_FILES[@]}" ps
  echo
  log "URL gateway (attendi 30s che salga il healthcheck):"
  docker compose "${COMPOSE_FILES[@]}" logs gateway --tail 20 | grep -i "url\|listen" || true
  echo
  log "Prossimi step:"
  log "  - Apri il pannello admin: <PUBLIC_BASE>/admin/login"
  log "  - Carica auth.json NotebookLM: <PUBLIC_BASE>/admin/nlm"
  log "  - Aggiungi connector a claude.ai con URL: <PUBLIC_BASE>/<SECRET>/<service>/mcp"
else
  log "OK, avvialo a mano quando vuoi:"
  log "  docker compose ${COMPOSE_FILES[*]} --profile $INGRESS_PROFILE up -d --build"
fi
