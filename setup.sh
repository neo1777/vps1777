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

# Versione da installare (modello pull: immagini ghcr, MAI build sulla VPS 4GB).
# Override: VPS1777_INSTALL_VERSION=X.Y.Z. Escape hatch dev: DEV_BUILD=1.
DEV_BUILD="${DEV_BUILD:-0}"
INSTALL_VERSION=""
if [ "$DEV_BUILD" != "1" ]; then
  INSTALL_VERSION="${VPS1777_INSTALL_VERSION:-$(curl -fsS -m 10 https://api.github.com/repos/neo1777/vps1777/releases/latest 2>/dev/null \
    | python3 -c 'import sys,json;print(json.load(sys.stdin).get("tag_name","").lstrip("v"))' 2>/dev/null || true)}"
  if [ -n "$INSTALL_VERSION" ]; then
    ok "Installerò la release v$INSTALL_VERSION (pull da ghcr, nessuna build)"
  else
    warn "Nessuna release pubblicata trovata → fallback: build locale (dev)"
    DEV_BUILD=1
  fi
fi

# ───── 2. .env ─────
if [ -f .env ]; then
  warn ".env esiste già. Per rigenerare, cancellalo prima."
else
  log "Configuro .env..."
  ask ADMIN_EMAIL "Email admin OAuth (il TUO Gmail)" ""
  [ -z "$ADMIN_EMAIL" ] && die "Email admin obbligatoria"
  ask TG_OWNER_ID "TELEGRAM_OWNER_ID (numerico, da @userinfobot)" ""
  [ -z "$TG_OWNER_ID" ] && warn "OWNER_ID vuoto — bot Telegram E Mini App NEGATI a tutti (fail-closed) finché non lo imposti. Nessuno può entrare, nemmeno tu: configuralo appena hai l'ID."

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

# VPS1777_TAG/IMAGE_BASE: versione deployata + registry (scritti sempre, anche
# se .env preesiste, per allineare il tag da pullare).
set_kv() { grep -q "^$1=" .env && sed -i "s|^$1=.*|$1=$2|" .env || echo "$1=$2" >> .env; }
set_kv VPS1777_TAG "${INSTALL_VERSION:-dev}"
set_kv VPS1777_IMAGE_BASE "${VPS1777_IMAGE_BASE:-ghcr.io/neo1777}"
# dir runtime create ORA (non da Docker come root): il gateway/CLI ci scrivono
mkdir -p onboarding var backups releases && chmod 700 var

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

# ───── 4. Immagini + start ─────
INGRESS_PROFILE="$(grep ^INGRESS_PROFILE= .env | cut -d= -f2)"
COMPOSE_FILES=("-f" "compose.yaml" "-f" "compose.${INGRESS_PROFILE}.yaml")
# In dev l'overlay di build ri-aggiunge i build context (compose.yaml è pull-only)
[ "$DEV_BUILD" = "1" ] && COMPOSE_FILES=("-f" "compose.yaml" "-f" "compose.build.yaml" "-f" "compose.${INGRESS_PROFILE}.yaml")

log ""
if [ "$DEV_BUILD" = "1" ]; then
  log "Pronto a buildare in locale (dev) e avviare:"
  log "  docker compose ${COMPOSE_FILES[*]} --profile $INGRESS_PROFILE up -d --build"
else
  log "Pronto a pullare le immagini v$INSTALL_VERSION da ghcr e avviare (nessuna build):"
  log "  docker compose ${COMPOSE_FILES[*]} --profile $INGRESS_PROFILE pull && ... up -d"
fi
log ""
if confirm "Procedo ora?"; then
  if [ "$DEV_BUILD" = "1" ]; then
    docker compose "${COMPOSE_FILES[@]}" --profile "$INGRESS_PROFILE" up -d --build
  else
    docker compose "${COMPOSE_FILES[@]}" --profile "$INGRESS_PROFILE" pull
    docker compose "${COMPOSE_FILES[@]}" --profile "$INGRESS_PROFILE" up -d
  fi
  echo
  ok "Stack avviato. Stato:"
  docker compose "${COMPOSE_FILES[@]}" ps
  echo
  # ── canale di aggiornamento: CLI + unit systemd (richiede sudo) ──
  if command -v sudo >/dev/null && [ -f tools/vps1777.py ]; then
    log "Installo il canale di aggiornamento (CLI vps1777 + timer)…"
    if sudo install -m755 tools/vps1777.py /usr/local/bin/vps1777 2>/dev/null; then
      for u in systemd/vps1777-*; do
        case "$u" in *.service|*.timer|*.path) sudo install -m644 "$u" /etc/systemd/system/ 2>/dev/null || true;; esac
      done
      sudo systemctl daemon-reload 2>/dev/null || true
      sudo systemctl enable --now vps1777-check-update.timer vps1777-update.path 2>/dev/null \
        && ok "Canale update attivo: \`vps1777 update\` + pulsante admin + check giornaliero" \
        || warn "Unit systemd non abilitate (systemd assente?) — la CLI è comunque installata"
    else
      warn "Installazione CLI saltata (sudo negato) — installala dopo con: sudo install -m755 tools/vps1777.py /usr/local/bin/vps1777"
    fi
  fi
  echo
  log "Prossimi step:"
  log "  - Apri il pannello admin: <PUBLIC_BASE>/admin/login"
  log "  - Carica il profilo NotebookLM: <PUBLIC_BASE>/admin/nlm"
  log "  - Aggiungi connector a claude.ai con URL: <PUBLIC_BASE>/<SECRET>/<service>/mcp"
  log "  - Aggiornamenti: \`vps1777 update\` o tab Update del pannello (vedi docs/UPDATE.md)"
else
  log "OK, avvialo a mano quando vuoi:"
  if [ "$DEV_BUILD" = "1" ]; then
    log "  docker compose ${COMPOSE_FILES[*]} --profile $INGRESS_PROFILE up -d --build"
  else
    log "  docker compose ${COMPOSE_FILES[*]} --profile $INGRESS_PROFILE pull && docker compose ${COMPOSE_FILES[*]} --profile $INGRESS_PROFILE up -d"
  fi
fi
