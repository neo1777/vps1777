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
# NONINTERACTIVE=1 → niente prompt: ask/ask_secret usano il valore già presente
# nella variabile (es. esportata dall'installer web locale); confirm legge da
# variabili *_YES. Permette di pilotare deploy.sh da un frontend.
ask() {
  local var="$1" q="$2" def="${3:-}" resp
  # Se la variabile è già valorizzata (env), salta il prompt.
  if [ -n "${!var:-}" ]; then return; fi
  if [ "${NONINTERACTIVE:-0}" = "1" ]; then printf -v "$var" '%s' "$def"; return; fi
  if [ -n "$def" ]; then printf '%s%s%s [%s]: ' "$C_B" "$q" "$C_R" "$def" >&2
  else printf '%s%s%s: ' "$C_B" "$q" "$C_R" >&2; fi
  IFS= read -r resp || true
  [ -z "$resp" ] && resp="$def"
  printf -v "$var" '%s' "$resp"
}
ask_secret() {
  local var="$1" q="$2" resp
  if [ -n "${!var:-}" ]; then return; fi
  if [ "${NONINTERACTIVE:-0}" = "1" ]; then printf -v "$var" '%s' ""; return; fi
  printf '%s%s%s: ' "$C_B" "$q" "$C_R" >&2
  IFS= read -rs resp || true
  echo >&2
  printf -v "$var" '%s' "$resp"
}
confirm() {
  local q="$1" resp
  if [ "${NONINTERACTIVE:-0}" = "1" ]; then
    # In modalità non-interattiva: default "sì" (l'installer ha già deciso).
    return 0
  fi
  printf '%s%s%s [s/N]: ' "$C_B" "$q" "$C_R" >&2
  IFS= read -r resp || true
  case "$resp" in s|S|si|SI|y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

# ─────────────────────────────────────────── policy password (H16)
# UNA policy sola per i tre ingressi (deploy.sh, setup.sh, tools/rotate-secret.sh):
# min 16 caratteri, almeno 3 classi, niente pattern comuni. Prima ognuno aveva la
# sua (12 qui, 12 in setup.sh, 16+3classi solo in rotate-secret.sh): la porta più
# debole decideva per tutte. Copia sincronizzata di tools/rotate-secret.sh —
# se cambi qui, cambia LÀ (e in setup.sh).
pw_weak_reason() {
  local pw="$1" classes=0
  if [ "${#pw}" -lt 16 ]; then echo "troppo corta (min 16 caratteri)"; return 1; fi
  printf '%s' "$pw" | LC_ALL=C grep -q '[a-z]'        && classes=$((classes+1))
  printf '%s' "$pw" | LC_ALL=C grep -q '[A-Z]'        && classes=$((classes+1))
  printf '%s' "$pw" | LC_ALL=C grep -q '[0-9]'        && classes=$((classes+1))
  printf '%s' "$pw" | LC_ALL=C grep -q '[^a-zA-Z0-9]' && classes=$((classes+1))
  if [ "$classes" -lt 3 ]; then
    echo "poca varietà: servono almeno 3 tra minuscole, MAIUSCOLE, cifre e simboli"; return 1
  fi
  if printf '%s' "$pw" | LC_ALL=C grep -qiE 'password|12345|qwerty|abcdef|letmein|welcome|admin|vps1777|000000|111111'; then
    echo "contiene un pattern comune/prevedibile"; return 1
  fi
  return 0
}

# Password admin generata QUI, sul PC (H16), non più sulla VPS: così il chiaro non
# torna mai indietro sullo stdout SSH. Viaggia solo in avanti, dentro lo STDIN del
# `bash -s` remoto (canale cifrato, mai argv), dove diventa un bcrypt.
# python3 se c'è (è già un requisito di fatto: lo usiamo per la release), /dev/urandom
# altrimenti. In entrambi i casi il risultato passa dal gate pw_weak_reason.
gen_pwd_local() {
  local p="" i=0
  while [ "$i" -lt 20 ]; do
    i=$((i+1))
    if command -v python3 >/dev/null 2>&1; then
      p="$(python3 -c "import secrets,string;print(''.join(secrets.choice(string.ascii_letters+string.digits) for _ in range(24)))" 2>/dev/null || true)"
    else
      # `|| true`: head chiude la pipe e tr muore di SIGPIPE → con pipefail
      # l'assegnazione fallirebbe sotto `set -e`.
      p="$( { LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 24; } 2>/dev/null || true )"
    fi
    if [ -n "$p" ] && pw_weak_reason "$p" >/dev/null; then printf '%s' "$p"; return 0; fi
  done
  die "generazione password fallita (né python3 né /dev/urandom utilizzabili)"
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

# ─────────────────────────────────────────── H15: la authkey è usa-e-getta
# La auth-key Tailscale è MONOUSO: dopo un `tailscale up` riuscito il nodo ha la
# sua identità nel tailnet e la key non serve più a nulla — resta solo a terra,
# in chiaro, in un .env che nessuno ruota. Qui la azzeriamo (il nodo NON si
# slogga: lo stato del login vive in /var/lib/tailscale, non in .env), mettiamo
# .env a 600 e rimuoviamo l'orfano secrets/ts_authkey.txt.
# Chiamare SOLO dopo un up confermato: se il login fallisce la key resta in .env
# e `./deploy.sh --apply` può ritentare.
ts_wipe_authkey() {
  local script
  script='cd ~/vps1777 || exit 1
if grep -q "^TS_AUTHKEY=" .env 2>/dev/null; then
  rest=$(grep -v "^TS_AUTHKEY=" .env || true)
  { [ -n "$rest" ] && printf "%s\n" "$rest"; printf "%s\n" "TS_AUTHKEY="; } > .env
fi
chmod 600 .env 2>/dev/null || true
rm -f secrets/ts_authkey.txt'
  if printf '%s\n' "$script" | SSH "sudo -u $OPERATOR_USER bash -s" >/dev/null 2>&1; then
    ok "TS_AUTHKEY azzerata in .env (key monouso, ormai consumata) · .env 600"
  else
    warn "wipe di TS_AUTHKEY non riuscito — controlla ~/vps1777/.env a mano"
  fi
}

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

  # 1. Scrivi i secret + .env come operator.
  # I segreti NON vanno mai nell'argv di un comando remoto (dove `ps` li
  # mostrerebbe a ogni utente locale): lo script viaggia nello STDIN di
  # `bash -s` (canale SSH cifrato), e set_kv scrive con printf-redirect
  # (builtin) — il valore non finisce nell'argv di sed/echo.
  log "Scrivo secret + .env..."
  APPLY_SCRIPT=$(cat <<'RS'
cd ~/vps1777 || exit 1
set_kv() {   # scrittura .env senza passare il valore all'argv di comandi esterni
  k=$1; v=$2
  rest=$(grep -v "^${k}=" .env 2>/dev/null || true)
  { [ -n "$rest" ] && printf '%s\n' "$rest"; printf '%s=%s\n' "$k" "$v"; } > .env
}
RS
)
  # Righe dinamiche: i segreti sono interpolati nel TESTO dello script, che
  # però transita via STDIN, non via argv. tailscale key e bot token sono
  # [A-Za-z0-9:_-] → l'apice singolo è sicuro.
  # NB (H15): NIENTE `secrets/ts_authkey.txt` — era un file orfano, nessun compose
  # lo consumava (Tailscale gira sull'host, non più come sidecar). La key sta in
  # .env solo il tempo di servire, e viene azzerata dopo il `tailscale up`.
  [ -n "$TS_KEY" ]   && APPLY_SCRIPT="$APPLY_SCRIPT
set_kv TS_AUTHKEY '$TS_KEY'"
  [ -n "$TG_TOKEN" ] && APPLY_SCRIPT="$APPLY_SCRIPT
printf %s '$TG_TOKEN' > secrets/telegram_bot_token.txt; chmod 600 secrets/telegram_bot_token.txt"
  [ -n "$TG_OWNER" ] && APPLY_SCRIPT="$APPLY_SCRIPT
set_kv TELEGRAM_OWNER_ID '$TG_OWNER'"
  [ -n "$PUB" ]      && APPLY_SCRIPT="$APPLY_SCRIPT
set_kv PUBLIC_BASE '$PUB'"
  # .env contiene segreti (TS_AUTHKEY, e i valori che ci scrive il pannello):
  # 600, non 644 (H15). E ripulisce l'orfano se un deploy precedente l'ha creato.
  APPLY_SCRIPT="$APPLY_SCRIPT
chmod 600 .env 2>/dev/null || true
chmod 700 secrets backups onboarding 2>/dev/null || true
rm -f secrets/ts_authkey.txt"
  printf '%s\n' "$APPLY_SCRIPT" | SSH "sudo -u $OPERATOR_USER bash -s" || die "Scrittura secret/.env fallita"
  ok "Secret + .env aggiornati (.env 600, dir sensibili 700)"

  # 2. Tailscale SULL'HOST: install + up + serve + funnel (no sidecar container).
  if [ -n "$TS_KEY" ]; then
    log "Attivo Tailscale sull'host + Funnel..."
    SSH "curl -fsSL https://tailscale.com/install.sh | sh" >/dev/null 2>&1 || warn "install tailscale fallito"
    SSH "systemctl enable --now tailscaled" >/dev/null 2>&1 || true
    # authkey via STDIN → file temporaneo → --authkey=file: (mai in argv/ps)
    printf %s "$TS_KEY" | SSH "umask 077; f=\$(mktemp); cat > \"\$f\"; tailscale up --authkey=file:\"\$f\" --hostname=${TS_HOSTNAME:-vps1777} --accept-dns=false --reset; r=\$?; rm -f \"\$f\"; exit \$r" >/dev/null 2>&1 || warn "tailscale up fallito"
    sleep 5
    TS_URL="$(SSH "tailscale status --json 2>/dev/null | python3 -c \"import sys,json;d=json.load(sys.stdin);n=d.get('Self',{}).get('DNSName','').rstrip('.');print('https://'+n if n else '')\" 2>/dev/null" || echo "")"
    if echo "$TS_URL" | grep -q '\.ts\.net$'; then
      SSH "tailscale serve reset" >/dev/null 2>&1 || true
      SSH "tailscale funnel --bg --https=443 http://127.0.0.1:8080" >/dev/null 2>&1 || true
      SSH "tailscale cert ${TS_URL#https://}" >/dev/null 2>&1 || true
      ok "Funnel HTTPS attivo: $TS_URL"
      [ -z "$PUB" ] && PUB="$TS_URL"
      ts_wipe_authkey   # up riuscito: la key monouso non serve più (H15)
    else
      warn "URL Tailscale non pronto — controlla key/prerequisiti (MagicDNS+HTTPS+nodeAttr funnel)."
    fi
  fi

  # 3. Se ho un PUBLIC_BASE (fornito o da Tailscale), aggiorno .env
  if [ -n "$PUB" ]; then
    SSH "sudo -u $OPERATOR_USER bash -lc 'cd ~/vps1777 && (grep -q ^PUBLIC_BASE= .env && sed -i \"s|^PUBLIC_BASE=.*|PUBLIC_BASE=$PUB|\" .env || echo PUBLIC_BASE=$PUB >> .env)'"
    ok "PUBLIC_BASE=$PUB"
  fi

  # 4. Restart servizi. Per tailscale il gateway resta su 127.0.0.1:8080
  #    (GATEWAY_BIND), quindi la porta pubblica :8080 si chiude da sé.
  log "Riavvio i servizi..."
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
# Preserva eventuali valori già esportati (installer web), non azzerare.
CADDY_DOMAIN="${CADDY_DOMAIN:-}"; CADDY_EMAIL="${CADDY_EMAIL:-}"
TS_AUTHKEY="${TS_AUTHKEY:-}"; CF_TOKEN="${CF_TOKEN:-}"; PUBLIC_BASE="${PUBLIC_BASE:-}"
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

# GEN_PWD può essere pre-impostato dall'installer (auto). Altrimenti chiedi.
GEN_PWD="${GEN_PWD:-}"
if [ -z "$GEN_PWD" ]; then
  if confirm "Genero io una password admin sicura (24 char)?"; then
    GEN_PWD="auto"
  else
    while :; do
      ask_secret ADMIN_PWD_MANUAL "Password admin (min 16, ≥3 classi: minusc/MAIUSC/cifre/simboli)"
      if reason="$(pw_weak_reason "$ADMIN_PWD_MANUAL")"; then break; fi
      warn "Password debole: $reason."
      # In NONINTERACTIVE non possiamo richiedere: la debole è un errore fatale.
      [ "${NONINTERACTIVE:-0}" = "1" ] && die "Password admin fornita troppo debole: $reason"
      ADMIN_PWD_MANUAL=""   # svuota così ask_secret richiede
    done
  fi
fi

# H16 — la password admin NASCE SUL PC (qui), non più sulla VPS: così il chiaro
# non torna mai indietro sullo stdout SSH (era il leak di H16). Viaggia solo in
# AVANTI, dentro lo STDIN cifrato del `bash -s` remoto (mai argv), codificato
# base64 per non rompersi su caratteri speciali/`$`. Sulla VPS diventa un bcrypt.
# Se questo PC ha python3+bcrypt, l'hash lo calcoliamo QUI e attraversa SSH solo
# l'hash (H16 "viaggia solo come hash"); altrimenti — nessuna dipendenza nuova
# forzata sul PC — mandiamo il chiaro AVANTI e la VPS lo hasha (python3-bcrypt
# è installato allo step 3). In entrambi i casi il chiaro non RITORNA.
if [ "$GEN_PWD" = "auto" ]; then
  ADMIN_PWD_PLAIN="$(gen_pwd_local)"
else
  ADMIN_PWD_PLAIN="$ADMIN_PWD_MANUAL"
fi
ADMIN_PWD_BCRYPT=""
if command -v python3 >/dev/null 2>&1 && python3 -c 'import bcrypt' 2>/dev/null; then
  ADMIN_PWD_BCRYPT="$(printf '%s' "$ADMIN_PWD_PLAIN" \
    | python3 -c 'import bcrypt,sys;print(bcrypt.hashpw(sys.stdin.buffer.read(),bcrypt.gensalt(12)).decode())' 2>/dev/null || true)"
fi
# base64 (portatile Linux/Mac) per un transito sicuro nell'heredoc interpolato.
ADMIN_PWD_PLAIN_B64="$(printf '%s' "$ADMIN_PWD_PLAIN" | base64 | tr -d '\n')"
ADMIN_PWD_BCRYPT_B64="$(printf '%s' "$ADMIN_PWD_BCRYPT" | base64 | tr -d '\n')"

# Utente operatore sulla VPS. NON usare "operator" — su Debian è un nome
# di sistema (gruppo GID 37) e adduser fallisce.
OPERATOR_USER="${OPERATOR_USER:-vps1777}"
REMOTE_DIR="/home/$OPERATOR_USER/vps1777"

# Versione del plugin compose v2 da installare se manca (Debian docker.io
# non lo include). Binario ufficiale da GitHub releases.
COMPOSE_VERSION="v2.32.4"

# ── Versione vps1777 da installare (modello pull: immagini ghcr, MAI build
#    sulla VPS 4GB). Override per test rc: VPS1777_INSTALL_VERSION=X.Y.Z-rc.1
#    Escape hatch sviluppo: DEV_BUILD=1 (build locale con compose.build.yaml).
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
  # uid 1000 = stesso uid dei container → nessun mismatch di ownership sui
  # bind-mount (onboarding/) e sui file del canale update. Fallback se occupato.
  if getent passwd 1000 >/dev/null; then
    useradd -m -s /bin/bash "$OPERATOR_USER"
  else
    useradd -m -u 1000 -s /bin/bash "$OPERATOR_USER"
  fi
fi
usermod -aG docker "$OPERATOR_USER"
getent group sudo >/dev/null && usermod -aG sudo "$OPERATOR_USER" || true
# H12 — sudoers WHITELIST invece di NOPASSWD:ALL. Via sudo l'operator può
# eseguire SOLO i binari che la CLI vps1777 e gli script di install/update usano:
#   install    → CLI in /usr/local/bin, unit in /etc/systemd/system, cosign
#   systemctl  → daemon-reload, enable --now dei timer/path
#   chown      → ownership delle dir runtime (bootstrap, reclaim)
# Censiti alla fonte: ogni sudo([...]) in tools/vps1777.py usa uno di questi tre.
# ATTENZIONE: l'operator resta ROOT-EQUIVALENTE via gruppo docker (può montare /
# in un container) — vedi SECURITY.md. Questa è riduzione della superficie sudo
# (niente più `sudo bash`, `sudo cat /etc/shadow`, install pacchetti a caso),
# non de-privilegio completo.
SUDO_CMDS=""
for _b in install systemctl chown; do
  for _d in /usr/bin /bin /usr/sbin /sbin; do
    [ -x "$_d/$_b" ] && SUDO_CMDS="$SUDO_CMDS${SUDO_CMDS:+, }$_d/$_b"
  done
done
SUDOERS_FILE="/etc/sudoers.d/90-$OPERATOR_USER"
if [ -n "$SUDO_CMDS" ]; then
  _tmp_sudo="$(mktemp)"
  printf '%s ALL=(root) NOPASSWD: %s\n' "$OPERATOR_USER" "$SUDO_CMDS" > "$_tmp_sudo"
  # MAI installare un sudoers non validato (un file rotto blocca sudo per tutti).
  if visudo -cf "$_tmp_sudo" >/dev/null 2>&1; then
    install -m 0440 "$_tmp_sudo" "$SUDOERS_FILE"
    echo "SUDOERS_WHITELIST_OK"
  else
    echo "SUDOERS_INVALID"   # non installo nulla: fail-closed
  fi
  rm -f "$_tmp_sudo"
else
  echo "SUDOERS_EMPTY"
fi

echo "DOCKER=$(docker --version 2>/dev/null || echo none)"
docker compose version >/dev/null 2>&1 && echo "COMPOSE=ok" || echo "COMPOSE=MISSING"
PREP

COMPOSE_OK=$(SSH 'docker compose version >/dev/null 2>&1 && echo ok || echo no')
[ "$COMPOSE_OK" = "ok" ] || die "docker compose v2 non disponibile sulla VPS dopo l'install del plugin. Controlla la connettività a github.com."

# H12 — verifica che la whitelist sudoers sia in posizione (senza, il canale
# update dell'operator si romperebbe: la CLI usa `sudo -n`, niente prompt).
SSH "test -f /etc/sudoers.d/90-$OPERATOR_USER" 2>/dev/null \
  || warn "sudoers whitelist NON installata (vedi SUDOERS_INVALID sopra) — install/systemctl/chown via sudo falliranno per l'operator. Controlla /etc/sudoers.d/90-$OPERATOR_USER a mano."
ok "Docker + Compose v2 pronti, utente $OPERATOR_USER creato"

# ═══════════════════════════════════════════ 4. TRASFERISCI REPO
step "4/8 — Trasferisco il repo sulla VPS"

log "tar over SSH → $REMOTE_DIR..."
SSH "rm -rf /tmp/vps1777-xfer && mkdir -p /tmp/vps1777-xfer"
# onboarding/var/releases = runtime della VPS (pending.json, state del canale
# update, bundle staged): mai sovrascritti da un re-deploy.
tar --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
    --exclude='.venv' --exclude='secrets/*.txt' --exclude='backups' \
    --exclude='onboarding' --exclude='var' --exclude='releases' \
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
# runtime dir create ORA come operatore: se le creasse Docker (bind mount)
# sarebbero root-owned e gateway/CLI non potrebbero scriverci.
# H38 — chmod 700 anche su secrets/, backups/, onboarding/ (prima solo var/).
# backups/ 700 protegge per traversal anche backups/pre-update/ (creata poi
# dalla CLI, che imposta 0700 sul singolo snapshot).
mkdir -p secrets onboarding var backups releases
chmod 700 var secrets backups onboarding

gen() { python3 -c "import secrets;print(secrets.token_urlsafe(\$1))"; }

# secrets random
[ -s secrets/gateway_secret.txt ]       || { gen 24 > secrets/gateway_secret.txt; }
[ -s secrets/oauth_signing_secret.txt ] || { gen 48 > secrets/oauth_signing_secret.txt; }
chmod 600 secrets/gateway_secret.txt secrets/oauth_signing_secret.txt

# admin password — generata SUL PC (H16). Arriva qui come hash bcrypt (se il PC
# poteva calcolarlo) o come chiaro base64 da hashare qui. Mai come chiaro di
# ritorno. Il chiaro decodificato va in python via STDIN (builtin printf), non
# in argv.
if [ ! -s secrets/admin_password_bcrypt.txt ]; then
  if [ -n "$ADMIN_PWD_BCRYPT_B64" ]; then
    printf '%s' '$ADMIN_PWD_BCRYPT_B64' | base64 -d > secrets/admin_password_bcrypt.txt
  else
    printf '%s' '$ADMIN_PWD_PLAIN_B64' | base64 -d \
      | python3 -c "import bcrypt,sys; print(bcrypt.hashpw(sys.stdin.buffer.read(), bcrypt.gensalt(12)).decode())" > secrets/admin_password_bcrypt.txt
  fi
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
set_kv() {   # scrive .env senza passare il valore all'argv di comandi esterni (sed/echo)
  k=\$1; v=\$2
  rest=\$(grep -v "^\${k}=" .env 2>/dev/null || true)
  { [ -n "\$rest" ] && printf '%s\n' "\$rest"; printf '%s=%s\n' "\$k" "\$v"; } > .env
}
set_kv ADMIN_EMAIL "$ADMIN_EMAIL"
set_kv TELEGRAM_OWNER_ID "$TG_OWNER_ID"
set_kv PUBLIC_BASE "$PUBLIC_BASE"
set_kv INGRESS_PROFILE "ingress.$INGRESS"
set_kv TS_HOSTNAME "${TS_HOSTNAME:-}"
set_kv TS_AUTHKEY "$TS_AUTHKEY"
set_kv CADDY_DOMAIN "$CADDY_DOMAIN"
set_kv CADDY_EMAIL "$CADDY_EMAIL"
set_kv VPS1777_TAG "${INSTALL_VERSION:-dev}"
set_kv VPS1777_IMAGE_BASE "${VPS1777_IMAGE_BASE:-ghcr.io/neo1777}"
# H15 — .env contiene TS_AUTHKEY (e altri valori): 600, non 644. E rimuovi
# l'eventuale orfano secrets/ts_authkey.txt (nessun compose lo consuma).
chmod 600 .env 2>/dev/null || true
rm -f secrets/ts_authkey.txt
echo "ENV_OK"
RSETUP
)

# Lo script (con i segreti interpolati) viaggia via STDIN di `bash -s`, MAI
# come argv di `bash -lc` (dove `ps` lo mostrerebbe a ogni utente locale).
OUT=$(printf '%s\n' "$REMOTE_SETUP" | SSH "sudo -u $OPERATOR_USER bash -s")
echo "$OUT" | grep -q ENV_OK || { echo "$OUT"; die "Setup .env/secrets fallito"; }
# H16 — la password NON torna più dalla VPS: l'abbiamo generata sul PC, la
# mostriamo da qui. GENERATED_PWD serve al riepilogo/UI installer (righe locali).
GENERATED_PWD=""
[ "$GEN_PWD" = "auto" ] && GENERATED_PWD="$ADMIN_PWD_PLAIN"
ok ".env + secrets generati (.env 600, dir sensibili 700)"
if [ -n "$GENERATED_PWD" ]; then
  warn "PASSWORD ADMIN GENERATA: ${C_B}$GENERATED_PWD${C_R}"
  warn "  → SALVALA SUBITO in un password manager. Non la rivedrai."
fi

# ═══════════════════════════════════════════ 6. IMMAGINI + UP
step "6/8 — Immagini + avvio stack"

# Per tailscale (host-mode) l'esposizione la gestisce GATEWAY_BIND, NON
# compose.onboarding (che pubblicherebbe una 2ª porta in conflitto sulla :8080).
if [ "$INGRESS" = "tailscale" ]; then
  COMPOSE_CMD="docker compose -f compose.yaml -f compose.ingress.tailscale.yaml --profile ingress.tailscale"
else
  COMPOSE_CMD="docker compose -f compose.yaml -f compose.ingress.${INGRESS}.yaml -f compose.onboarding.yaml --profile ingress.${INGRESS}"
fi
if [ "$DEV_BUILD" = "1" ]; then
  # build locale: aggiunge l'overlay compose.build.yaml (solo dev/fallback)
  COMPOSE_CMD_BUILD="${COMPOSE_CMD/--profile/-f compose.build.yaml --profile}"
  SSHT "sudo -u "$OPERATOR_USER" bash -lc 'cd $REMOTE_DIR && $COMPOSE_CMD_BUILD up -d --build'" \
    || die "docker compose up (build locale) fallito"
  ok "Stack avviato (build locale — dev)"
else
  SSHT "sudo -u "$OPERATOR_USER" bash -lc 'cd $REMOTE_DIR && $COMPOSE_CMD pull && $COMPOSE_CMD up -d'" \
    || die "docker compose pull/up fallito"
  ok "Stack avviato (immagini v$INSTALL_VERSION pullate — niente build in produzione)"
fi

# ── Canale di aggiornamento: CLI vps1777 + unit systemd (idempotente)
log "Installo il canale di aggiornamento (CLI + timer + path unit)..."
SSH "install -m755 $REMOTE_DIR/tools/vps1777.py /usr/local/bin/vps1777 \
  && for u in $REMOTE_DIR/systemd/vps1777-*; do case \"\$u\" in *.service|*.timer|*.path) sed -e \"s|@OPERATOR_USER@|$OPERATOR_USER|g\" -e \"s|@REPO@|$REMOTE_DIR|g\" \"\$u\" | install -m644 /dev/stdin /etc/systemd/system/\$(basename \"\$u\");; esac; done \
  && systemctl daemon-reload \
  && systemctl enable --now vps1777-check-update.timer vps1777-update.path vps1777-secrets-check.timer" \
  && ok "Canale update attivo: \`vps1777 update\` + pulsante admin + check giornaliero + check settimanale secret" \
  || warn "Setup canale update fallito — installalo dopo con tools/bootstrap.sh"
SSH "sudo -u $OPERATOR_USER bash -lc 'cd ~/vps1777 && /usr/local/bin/vps1777 check || true'" >/dev/null 2>&1 || true

log "Stato container:"
SSH "sudo -u "$OPERATOR_USER" bash -lc 'cd $REMOTE_DIR && $COMPOSE_CMD ps'" || true

# ── Tailscale SULL'HOST (no container): install + up + serve + funnel verso
#    il gateway su 127.0.0.1:8080. Niente sidecar → niente containerboot/netns.
if [ "$INGRESS" = "tailscale" ] && [ -n "$TS_AUTHKEY" ]; then
  log "Tailscale: installo sull'host + Funnel..."
  SSH "curl -fsSL https://tailscale.com/install.sh | sh" >/dev/null 2>&1 || warn "install tailscale fallito"
  SSH "systemctl enable --now tailscaled" >/dev/null 2>&1 || true
  # authkey via STDIN → file temporaneo → --authkey=file: (mai in argv/ps)
  printf %s "$TS_AUTHKEY" | SSH "umask 077; f=\$(mktemp); cat > \"\$f\"; tailscale up --authkey=file:\"\$f\" --hostname=${TS_HOSTNAME:-vps1777} --accept-dns=false --reset; r=\$?; rm -f \"\$f\"; exit \$r" >/dev/null 2>&1 || warn "tailscale up fallito"
  sleep 5
  TS_URL="$(SSH "tailscale status --json 2>/dev/null | python3 -c \"import sys,json;d=json.load(sys.stdin);n=d.get('Self',{}).get('DNSName','').rstrip('.');print('https://'+n if n else '')\" 2>/dev/null" || echo "")"
  if echo "$TS_URL" | grep -q '\.ts\.net$'; then
    PUBLIC_BASE="$TS_URL"
    SSH "tailscale serve reset" >/dev/null 2>&1 || true
    SSH "tailscale funnel --bg --https=443 http://127.0.0.1:8080" >/dev/null 2>&1 || true
    SSH "tailscale cert ${TS_URL#https://}" >/dev/null 2>&1 || true
    SSH "sudo -u $OPERATOR_USER bash -lc 'cd ~/vps1777 && (grep -q ^PUBLIC_BASE= .env && sed -i \"s|^PUBLIC_BASE=.*|PUBLIC_BASE=$TS_URL|\" .env || echo PUBLIC_BASE=$TS_URL >> .env) && $COMPOSE_CMD up -d gateway'" >/dev/null 2>&1 || true
    ok "Funnel HTTPS attivo: $TS_URL"
    ts_wipe_authkey   # up riuscito: la key monouso non serve più (H15)
  else
    warn "URL Tailscale non ricavato — controlla key/prerequisiti (MagicDNS+HTTPS+nodeAttr funnel)."
  fi
fi

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

# Righe machine-readable per l'installer web (le parsa per la schermata finale).
echo "RESULT_URL=${PUBLIC_BASE:-http://$VPS_IP:8080}"
echo "RESULT_SECRET=$GATEWAY_SECRET"
echo "RESULT_ADMIN_EMAIL=$ADMIN_EMAIL"
[ -n "${GENERATED_PWD:-}" ] && echo "RESULT_ADMIN_PWD=$GENERATED_PWD"
echo "RESULT_SETUP_URL=${PUBLIC_BASE:-http://$VPS_IP:8080}/admin/setup"
echo "RESULT_INGRESS=$INGRESS"

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
