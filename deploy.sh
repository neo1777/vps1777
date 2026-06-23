#!/usr/bin/env bash
# deploy.sh — Deploy one-click di vps1777 su una VPS Linux fresh.
#
# Da lanciare sul TUO PC (Linux/Mac/WSL), NON sulla VPS.
#
# Cosa fa, tutto via SSH:
#   1. Chiede IP, user, password della VPS (o usa SSH key se password vuota)
#   2. Raccoglie la config (email admin, OWNER_ID, ingress, token, ecc.)
#   3. Prepara la VPS: installa Docker + Compose v2, crea utente operatore (vps1777)
#   4. Trasferisce questo repo sulla VPS (tar over SSH)
#   5. Genera .env + secrets sulla VPS (random + bcrypt)
#   6. `docker compose up -d --build`
#   7. RIAVVIA la VPS e verifica che i container ripartano da soli al boot
#   8. Stampa gli URL finali + prossimi step
#
# Requisiti PC locale: bash, ssh, tar. Per auth password: sshpass.
#
# Uso:
#   ./deploy.sh                 # interattivo (chiede tutto)
#   ./deploy.sh 1.2.3.4         # IP pre-compilato

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ─────────────────────────────────────────── UI
if [ -t 1 ]; then
  C_R=$'\e[0m'; C_B=$'\e[1m'; C_D=$'\e[2m'
  C_OK=$'\e[32m'; C_W=$'\e[33m'; C_E=$'\e[31m'; C_I=$'\e[34m'
else
  C_R=''; C_B=''; C_D=''; C_OK=''; C_W=''; C_E=''; C_I=''
fi
log()  { printf '%s[*]%s %s\n' "$C_I"  "$C_R" "$*"; }
ok()   { printf '%s[✓]%s %s\n' "$C_OK" "$C_R" "$*"; }
warn() { printf '%s[!]%s %s\n' "$C_W"  "$C_R" "$*"; }
die()  { printf '%s[✗]%s %s\n' "$C_E"  "$C_R" "$*" >&2; exit 1; }
step() {
  printf '\n%s%s════════════════════════════════════════════════════════════%s\n' "$C_B" "$C_I" "$C_R"
  printf '%s%s %s%s\n' "$C_B" "$C_I" "$*" "$C_R"
  printf '%s%s════════════════════════════════════════════════════════════%s\n\n' "$C_B" "$C_I" "$C_R"
}
ask() {
  local var="$1" q="$2" def="${3:-}" resp
  if [ -n "$def" ]; then printf '%s%s%s [%s]: ' "$C_B" "$q" "$C_R" "$def" >&2
  else printf '%s%s%s: ' "$C_B" "$q" "$C_R" >&2; fi
  IFS= read -r resp || true
  [ -z "$resp" ] && resp="$def"
  printf -v "$var" '%s' "$resp"
}
ask_secret() {
  local var="$1" q="$2" resp
  printf '%s%s%s: ' "$C_B" "$q" "$C_R" >&2
  IFS= read -rs resp || true
  echo >&2
  printf -v "$var" '%s' "$resp"
}
confirm() {
  local q="$1" resp
  printf '%s%s%s [s/N]: ' "$C_B" "$q" "$C_R" >&2
  IFS= read -r resp || true
  case "$resp" in s|S|si|SI|y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

# ─────────────────────────────────────────── banner
cat <<'BANNER'

  ┌─────────────────────────────────────────────────────────────┐
  │                                                             │
  │   vps1777 — deploy one-click                                │
  │   Docker stack: gateway OAuth + MCP + bot, su VPS Linux     │
  │                                                             │
  └─────────────────────────────────────────────────────────────┘

BANNER

# ─────────────────────────────────────────── prerequisiti locali
command -v ssh >/dev/null || die "ssh non trovato"
command -v tar >/dev/null || die "tar non trovato"
for f in compose.yaml services/gateway/Dockerfile; do
  [ -f "$f" ] || die "File repo mancante: $f — lancia dalla dir di vps1777"
done

# Modalità: deploy completo (default) o --apply (applica config dal pannello)
APPLY_MODE=0
if [ "${1:-}" = "--apply" ]; then APPLY_MODE=1; shift; fi

# ═══════════════════════════════════════════ 1. CONNESSIONE VPS
step "1/8 — Connessione VPS"

VPS_IP="${1:-}"
[ -z "$VPS_IP" ] && ask VPS_IP "IP pubblico della VPS" ""
echo "$VPS_IP" | grep -qE '^[0-9]{1,3}(\.[0-9]{1,3}){3}$' || die "IP non valido: $VPS_IP"

ask VPS_USER "Utente SSH della VPS" "root"
ask_secret VPS_PASS "Password SSH (vuoto = usa la tua SSH key)"

# Wrapper SSH/SCP che usa password (sshpass) o key
SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -o ServerAliveInterval=15)
if [ -n "$VPS_PASS" ]; then
  command -v sshpass >/dev/null || die "sshpass non installato (serve per auth password). Installa: apt install sshpass / brew install hudochenkov/sshpass/sshpass"
  SSH()  { sshpass -p "$VPS_PASS" ssh  "${SSH_OPTS[@]}" "$VPS_USER@$VPS_IP" "$@"; }
  SSHT() { sshpass -p "$VPS_PASS" ssh -t "${SSH_OPTS[@]}" "$VPS_USER@$VPS_IP" "$@"; }
  PIPE_IN() { sshpass -p "$VPS_PASS" ssh "${SSH_OPTS[@]}" "$VPS_USER@$VPS_IP" "$@"; }
else
  SSH()  { ssh  "${SSH_OPTS[@]}" "$VPS_USER@$VPS_IP" "$@"; }
  SSHT() { ssh -t "${SSH_OPTS[@]}" "$VPS_USER@$VPS_IP" "$@"; }
  PIPE_IN() { ssh "${SSH_OPTS[@]}" "$VPS_USER@$VPS_IP" "$@"; }
fi

# pulizia known_hosts stale (VPS riformattata = nuova host key)
ssh-keygen -f "$HOME/.ssh/known_hosts" -R "$VPS_IP" >/dev/null 2>&1 || true

log "Test connessione..."
SSH 'echo ok' >/dev/null 2>&1 || die "Connessione fallita. Verifica IP/user/password e che la VPS sia up."
OS_INFO=$(SSH '. /etc/os-release; echo "$PRETTY_NAME ($(uname -m))"' 2>/dev/null || echo "?")
ok "Connesso: $OS_INFO"

[ "$VPS_USER" = "root" ] || warn "User non-root: assicurati abbia sudo NOPASSWD, altrimenti alcuni step falliranno."

# ═══════════════════════════════════════════ MODALITÀ --apply
# Legge onboarding/pending.json (scritto dal pannello /admin/setup) e applica:
# tailscale up, secret bot, PUBLIC_BASE, restart servizi.
if [ "$APPLY_MODE" = "1" ]; then
  OPERATOR_USER="${OPERATOR_USER:-vps1777}"
  REMOTE_DIR="/home/$OPERATOR_USER/vps1777"
  PENDING="$REMOTE_DIR/onboarding/pending.json"
  INGRESS_PROFILE="$(SSH "sudo -u $OPERATOR_USER grep ^INGRESS_PROFILE= $REMOTE_DIR/.env 2>/dev/null | cut -d= -f2" || echo "ingress.tailscale")"
  [ -z "$INGRESS_PROFILE" ] && INGRESS_PROFILE="ingress.tailscale"
  INGRESS="${INGRESS_PROFILE#ingress.}"
  COMPOSE_CMD="docker compose -f compose.yaml -f compose.ingress.${INGRESS}.yaml --profile ${INGRESS_PROFILE}"

  step "APPLY — leggo la config dal pannello /admin/setup"
  log "Leggo $PENDING ..."
  SSH "test -f $PENDING" 2>/dev/null || die "Nessuna config trovata in $PENDING. Apri il pannello /admin/setup, compila e Salva, poi rilancia --apply."

  get() { SSH "python3 -c \"import json;print(json.load(open('$PENDING')).get('$1',''))\" 2>/dev/null"; }
  TS_KEY="$(get tailscale_authkey)"
  TG_TOKEN="$(get telegram_bot_token)"
  TG_OWNER="$(get telegram_owner_id)"
  PUB="$(get public_base)"
  ok "Config letta (ts_key:$([ -n "$TS_KEY" ] && echo sì || echo no), bot:$([ -n "$TG_TOKEN" ] && echo sì || echo no), owner:$([ -n "$TG_OWNER" ] && echo sì || echo no))"

  # 1. Scrivi i secret + .env come operator
  log "Scrivo secret + .env..."
  SSH "sudo -u $OPERATOR_USER bash -lc '
    cd ~/vps1777
    set_kv() { grep -q \"^\$1=\" .env && sed -i \"s|^\$1=.*|\$1=\$2|\" .env || echo \"\$1=\$2\" >> .env; }
    $([ -n "$TS_KEY" ]   && echo "printf %s \"$TS_KEY\"   > secrets/ts_authkey.txt; chmod 600 secrets/ts_authkey.txt")
    $([ -n "$TG_TOKEN" ] && echo "printf %s \"$TG_TOKEN\" > secrets/telegram_bot_token.txt; chmod 600 secrets/telegram_bot_token.txt")
    $([ -n "$TG_OWNER" ] && echo "set_kv TELEGRAM_OWNER_ID \"$TG_OWNER\"")
    $([ -n "$TS_KEY" ]   && echo "set_kv TS_AUTHKEY \"$TS_KEY\"")
    $([ -n "$PUB" ]      && echo "set_kv PUBLIC_BASE \"$PUB\"")
    true
  '" || die "Scrittura secret/.env fallita"
  ok "Secret + .env aggiornati"

  # 2. Tailscale up (se key fornita)
  if [ -n "$TS_KEY" ]; then
    log "Attivo Tailscale (tailscale up)..."
    SSH "sudo docker exec vps1777-tailscale tailscale up --authkey='$TS_KEY' --hostname=vps1777 2>&1 | tail -5" || warn "tailscale up ha restituito un errore — verifica la key"
    sleep 3
    TS_URL="$(SSH "sudo docker exec vps1777-tailscale tailscale status --json 2>/dev/null | python3 -c \"import sys,json;print('https://'+json.load(sys.stdin).get('Self',{}).get('DNSName','').rstrip('.'))\" 2>/dev/null" || echo "")"
    if echo "$TS_URL" | grep -q '\.ts\.net$'; then
      ok "Tailscale attivo: $TS_URL"
      [ -z "$PUB" ] && PUB="$TS_URL"
    else
      warn "URL Tailscale non ricavato automaticamente — controlla 'tailscale status'"
    fi
  fi

  # 3. Se ho un PUBLIC_BASE (fornito o da Tailscale), aggiorno .env
  if [ -n "$PUB" ]; then
    SSH "sudo -u $OPERATOR_USER bash -lc 'cd ~/vps1777 && (grep -q ^PUBLIC_BASE= .env && sed -i \"s|^PUBLIC_BASE=.*|PUBLIC_BASE=$PUB|\" .env || echo PUBLIC_BASE=$PUB >> .env)'"
    ok "PUBLIC_BASE=$PUB"
  fi

  # 4. Restart servizi SENZA compose.onboarding (chiude la porta 8080 in chiaro)
  log "Riavvio i servizi (chiudo la porta 8080 di onboarding)..."
  SSHT "sudo -u $OPERATOR_USER bash -lc 'cd ~/vps1777 && $COMPOSE_CMD up -d'" || die "restart fallito"
  ok "Servizi riavviati"

  # 5. Cancella pending.json (contiene valori sensibili)
  SSH "sudo -u $OPERATOR_USER rm -f $PENDING" && ok "pending.json rimosso"

  echo
  ok "Apply completato."
  [ -n "$PUB" ] && log "URL: ${C_B}$PUB${C_R}  →  /admin/login · /admin/nlm · /<SECRET>/<service>/mcp"
  exit 0
fi

# ═══════════════════════════════════════════ 2. CONFIG
step "2/8 — Configurazione stack"

ask ADMIN_EMAIL "Email admin OAuth (il TUO Gmail)" ""
[ -z "$ADMIN_EMAIL" ] && die "Email admin obbligatoria"
ask TG_OWNER_ID "TELEGRAM_OWNER_ID (numerico, da @userinfobot, vuoto = dopo)" ""

log ""
log "Ingress (come esporre HTTPS pubblico):"
log "  1) Tailscale Funnel (consigliato)"
log "  2) Caddy + Let's Encrypt (richiede tuo dominio)"
log "  3) Cloudflare Tunnel (richiede token CF)"
ask INGRESS_NUM "Scelta [1/2/3]" "1"
CADDY_DOMAIN=""; CADDY_EMAIL=""; TS_AUTHKEY=""; CF_TOKEN=""; PUBLIC_BASE=""
case "$INGRESS_NUM" in
  1) INGRESS=tailscale
     ask TS_HOSTNAME "Hostname Tailscale (es. vps1777)" "vps1777"
     ask_secret TS_AUTHKEY "Tailscale auth-key (tskey-auth-..., vuoto = configuri dopo)"
     ;;
  2) INGRESS=caddy
     ask CADDY_DOMAIN "Dominio (es. vps.tuosito.com)" ""
     [ -z "$CADDY_DOMAIN" ] && die "Dominio obbligatorio per Caddy"
     ask CADDY_EMAIL "Email Let's Encrypt" "$ADMIN_EMAIL"
     PUBLIC_BASE="https://$CADDY_DOMAIN"
     ;;
  3) INGRESS=cloudflared
     ask_secret CF_TOKEN "Cloudflare Tunnel token"
     ;;
  *) die "Scelta non valida" ;;
esac

ask_secret TG_TOKEN "TELEGRAM_BOT_TOKEN (da BotFather, vuoto = dopo)"

GEN_PWD=""
if confirm "Genero io una password admin sicura (24 char)?"; then
  GEN_PWD="auto"
else
  ask_secret ADMIN_PWD_MANUAL "Password admin (min 12 char)"
  [ "${#ADMIN_PWD_MANUAL}" -lt 12 ] && die "Password troppo corta"
fi

# Utente operatore sulla VPS. NON usare "operator" — su Debian è un nome
# di sistema (gruppo GID 37) e adduser fallisce.
OPERATOR_USER="${OPERATOR_USER:-vps1777}"
REMOTE_DIR="/home/$OPERATOR_USER/vps1777"

# Versione del plugin compose v2 da installare se manca (Debian docker.io
# non lo include). Binario ufficiale da GitHub releases.
COMPOSE_VERSION="v2.32.4"

# ═══════════════════════════════════════════ 3. PREPARA VPS
step "3/8 — Preparo la VPS (Docker + Compose v2 + utente $OPERATOR_USER)"

log "Installo Docker + Compose v2 + git + age (può richiedere 1-2 min)..."
SSH "export OPERATOR_USER='$OPERATOR_USER' COMPOSE_VERSION='$COMPOSE_VERSION'; bash -s" <<'PREP'
set -e
export DEBIAN_FRONTEND=noninteractive

# 1. Pacchetti base — installa solo ciò che manca (idempotente, granulare).
#    python3-bcrypt serve allo step 5 per l'hash della password admin
#    (Debian minimale non ha né pip né il modulo bcrypt).
NEED=""
command -v docker >/dev/null 2>&1 || NEED="$NEED docker.io"
command -v git    >/dev/null 2>&1 || NEED="$NEED git"
command -v curl   >/dev/null 2>&1 || NEED="$NEED curl"
command -v age    >/dev/null 2>&1 || NEED="$NEED age"
command -v python3 >/dev/null 2>&1 || NEED="$NEED python3"
python3 -c "import bcrypt" 2>/dev/null || NEED="$NEED python3-bcrypt"
if [ -n "$NEED" ]; then
  apt-get update -q
  # shellcheck disable=SC2086
  apt-get install -y -q $NEED ca-certificates || true
fi
systemctl enable --now docker

# 2. Compose v2 plugin — docker.io di Debian NON lo include.
#    Installo il binario ufficiale come cli-plugin (funziona con docker.io 20.10+).
if ! docker compose version >/dev/null 2>&1; then
  case "$(uname -m)" in
    x86_64)        CARCH=x86_64 ;;
    aarch64|arm64) CARCH=aarch64 ;;
    *)             CARCH=x86_64 ;;
  esac
  mkdir -p /usr/local/lib/docker/cli-plugins
  curl -fsSL "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-${CARCH}" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
fi

# 3. Utente operatore (nome non collidente con utenti di sistema Debian)
if ! id "$OPERATOR_USER" >/dev/null 2>&1; then
  useradd -m -s /bin/bash "$OPERATOR_USER"
fi
usermod -aG docker "$OPERATOR_USER"
getent group sudo >/dev/null && usermod -aG sudo "$OPERATOR_USER" || true
echo "$OPERATOR_USER ALL=(ALL) NOPASSWD: ALL" > "/etc/sudoers.d/90-$OPERATOR_USER"
chmod 0440 "/etc/sudoers.d/90-$OPERATOR_USER"

echo "DOCKER=$(docker --version 2>/dev/null || echo none)"
docker compose version >/dev/null 2>&1 && echo "COMPOSE=ok" || echo "COMPOSE=MISSING"
PREP

COMPOSE_OK=$(SSH 'docker compose version >/dev/null 2>&1 && echo ok || echo no')
[ "$COMPOSE_OK" = "ok" ] || die "docker compose v2 non disponibile sulla VPS dopo l'install del plugin. Controlla la connettività a github.com."
ok "Docker + Compose v2 pronti, utente $OPERATOR_USER creato"

# ═══════════════════════════════════════════ 4. TRASFERISCI REPO
step "4/8 — Trasferisco il repo sulla VPS"

log "tar over SSH → $REMOTE_DIR..."
SSH "rm -rf /tmp/vps1777-xfer && mkdir -p /tmp/vps1777-xfer"
tar --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
    --exclude='.venv' --exclude='secrets/*.txt' --exclude='backups' \
    -cf - . | PIPE_IN "tar -xf - -C /tmp/vps1777-xfer"
SSH "export OPERATOR_USER='$OPERATOR_USER' REMOTE_DIR='$REMOTE_DIR'; bash -s" <<'PREP2'
set -e
install -d -o "$OPERATOR_USER" -g "$OPERATOR_USER" "$REMOTE_DIR"
cp -a /tmp/vps1777-xfer/. "$REMOTE_DIR/"
chown -R "$OPERATOR_USER:$OPERATOR_USER" "$REMOTE_DIR"
rm -rf /tmp/vps1777-xfer
PREP2
ok "Repo in $REMOTE_DIR"

# ═══════════════════════════════════════════ 5. .env + SECRETS
step "5/8 — Genero .env + secrets sulla VPS"

# Costruisco lo script di setup remoto con le variabili interpolate.
# Gira come $OPERATOR_USER dentro REMOTE_DIR.
REMOTE_SETUP=$(cat <<RSETUP
set -e
cd "$REMOTE_DIR"
mkdir -p secrets

gen() { python3 -c "import secrets;print(secrets.token_urlsafe(\$1))"; }
genpwd() { python3 -c "import secrets,string;print(''.join(secrets.choice(string.ascii_letters+string.digits) for _ in range(24)))"; }

# secrets random
[ -s secrets/gateway_secret.txt ]       || { gen 24 > secrets/gateway_secret.txt; }
[ -s secrets/oauth_signing_secret.txt ] || { gen 48 > secrets/oauth_signing_secret.txt; }
chmod 600 secrets/gateway_secret.txt secrets/oauth_signing_secret.txt

# admin password
if [ ! -s secrets/admin_password_bcrypt.txt ]; then
  if [ "$GEN_PWD" = "auto" ]; then
    PWD_RAW="\$(genpwd)"
    echo "GENERATED_ADMIN_PWD=\$PWD_RAW"
  else
    PWD_RAW="$(printf '%s' "${ADMIN_PWD_MANUAL:-}")"
  fi
  python3 -c "import bcrypt,sys; print(bcrypt.hashpw(sys.argv[1].encode(), bcrypt.gensalt(12)).decode())" "\$PWD_RAW" > secrets/admin_password_bcrypt.txt
  chmod 600 secrets/admin_password_bcrypt.txt
fi

# telegram token
printf '%s' "$TG_TOKEN" > secrets/telegram_bot_token.txt
chmod 600 secrets/telegram_bot_token.txt

# cloudflared token (se serve)
if [ -n "$CF_TOKEN" ]; then
  printf '%s' "$CF_TOKEN" > secrets/cloudflared_token.txt
  chmod 600 secrets/cloudflared_token.txt
fi

# .env
cp -n .env.example .env 2>/dev/null || true
set_kv() { grep -q "^\$1=" .env && sed -i "s|^\$1=.*|\$1=\$2|" .env || echo "\$1=\$2" >> .env; }
set_kv ADMIN_EMAIL "$ADMIN_EMAIL"
set_kv TELEGRAM_OWNER_ID "$TG_OWNER_ID"
set_kv PUBLIC_BASE "$PUBLIC_BASE"
set_kv INGRESS_PROFILE "ingress.$INGRESS"
set_kv TS_HOSTNAME "${TS_HOSTNAME:-}"
set_kv TS_AUTHKEY "$TS_AUTHKEY"
set_kv CADDY_DOMAIN "$CADDY_DOMAIN"
set_kv CADDY_EMAIL "$CADDY_EMAIL"
echo "ENV_OK"
RSETUP
)

OUT=$(SSH "sudo -u "$OPERATOR_USER" bash -lc $(printf '%q' "$REMOTE_SETUP")")
echo "$OUT" | grep -q ENV_OK || { echo "$OUT"; die "Setup .env/secrets fallito"; }
# Estrai password generata se c'è
GENERATED_PWD=$(echo "$OUT" | sed -n 's/^GENERATED_ADMIN_PWD=//p')
ok ".env + secrets generati"
if [ -n "$GENERATED_PWD" ]; then
  warn "PASSWORD ADMIN GENERATA: ${C_B}$GENERATED_PWD${C_R}"
  warn "  → SALVALA SUBITO in un password manager. Non la rivedrai."
fi

# ═══════════════════════════════════════════ 6. BUILD + UP
step "6/8 — Build immagini + avvio stack (può richiedere alcuni minuti)"

# Include compose.onboarding.yaml → espone :8080 sull'host per il pannello
# /admin/setup (raggiungibile prima che Tailscale sia attivo). deploy.sh --apply
# poi riavvia SENZA questo override, chiudendo la porta.
COMPOSE_CMD="docker compose -f compose.yaml -f compose.ingress.${INGRESS}.yaml -f compose.onboarding.yaml --profile ingress.${INGRESS}"
SSHT "sudo -u "$OPERATOR_USER" bash -lc 'cd $REMOTE_DIR && $COMPOSE_CMD up -d --build'" \
  || die "docker compose up fallito"
ok "Stack avviato (pannello onboarding su http://$VPS_IP:8080/admin/setup)"

log "Stato container:"
SSH "sudo -u "$OPERATOR_USER" bash -lc 'cd $REMOTE_DIR && $COMPOSE_CMD ps'" || true

# ═══════════════════════════════════════════ 7. REBOOT TEST
step "7/8 — Riavvio VPS per verificare che tutto riparta al boot"

if confirm "Riavvio la VPS ora? (verifica auto-start dei container)"; then
  log "Reboot in corso..."
  SSH 'nohup reboot >/dev/null 2>&1 &' || true
  sleep 5
  log "Attendo che la VPS torni su (max 120s)..."
  back=0
  for i in $(seq 1 24); do
    sleep 5
    if SSH 'echo up' >/dev/null 2>&1; then back=1; break; fi
    printf '.' >&2
  done
  echo >&2
  if [ "$back" = "1" ]; then
    ok "VPS tornata online"
    log "Attendo 20s che Docker risollevi i container..."
    sleep 20
    log "Stato container dopo reboot:"
    SSH "sudo -u "$OPERATOR_USER" bash -lc 'cd $REMOTE_DIR && $COMPOSE_CMD ps'" || true
  else
    warn "VPS non ancora raggiungibile dopo 120s — controlla manualmente."
  fi
else
  log "Reboot saltato. Test auto-start non eseguito."
fi

# ═══════════════════════════════════════════ 8. RIEPILOGO
step "8/8 — Fatto"

GATEWAY_SECRET=$(SSH "sudo -u "$OPERATOR_USER" cat $REMOTE_DIR/secrets/gateway_secret.txt" 2>/dev/null || echo "<SECRET>")

cat <<DONE2

${C_B}${C_OK}╔═══════════════════════════════════════════════════════════════╗
║   ✅ vps1777 deployato — ora finisci dal PANNELLO web          ║
╚═══════════════════════════════════════════════════════════════╝${C_R}

  ${C_B}Ingress:${C_R} $INGRESS    ${C_B}Repo:${C_R} $REMOTE_DIR
  ${C_B}Admin:${C_R} email $ADMIN_EMAIL  (password: vedi sopra/password manager)

  ${C_B}═══ COMPLETA TUTTO DA QUI — niente terminale ═══${C_R}

  1. ${C_B}Apri il pannello${C_R} (porta aperta per il primo setup):
        ${C_OK}http://$VPS_IP:8080/admin/setup${C_R}
     Login con email + password admin.

  2. ${C_B}Nel pannello inserisci${C_R}:
        • Tailscale auth-key  (da login.tailscale.com/admin/settings/keys)
        • Token bot Telegram + Owner ID  (opzionale)
        • Carica auth.json NotebookLM  (bottone dedicato)
     Clicca ${C_B}Salva configurazione${C_R}.

  3. ${C_B}Applica${C_R} — da questo PC, nella cartella del repo:
        ${C_OK}./deploy.sh --apply${C_R}
     Attiva Tailscale, imposta l'URL, riavvia i servizi, chiude la
     porta 8080. Stampa l'URL HTTPS finale.

  4. ${C_B}Connector claude.ai${C_R}: <URL>/$GATEWAY_SECRET/archive/mcp  (e /nb1777/mcp)

  ${C_D}Amministrazione: ssh $VPS_USER@$VPS_IP → sudo -u $OPERATOR_USER -i → cd vps1777${C_R}

DONE2
