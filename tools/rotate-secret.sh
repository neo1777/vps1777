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

# Gate di robustezza password: 0 = forte; altrimenti stampa il motivo e ritorna 1.
# Policy: min 16 caratteri, almeno 3 classi (minuscole/MAIUSCOLE/cifre/simboli),
# niente pattern comuni/prevedibili. Non permettiamo password deboli, punto.
# H75 (28/09) — la password generata si mostra SOLO a un terminale. Se l'output va altrove
# (un agente, una pipe, un log) finisce nei transcript e da lì nell'archivio: una password
# stampata da setup.sh è ricomparsa così, in chiaro, cercando nell'archivio. Fuori da un
# terminale va in un file 600 e si stampa il percorso. Stessa funzione in setup.sh,
# deploy.sh e tools/rotate-secret.sh: tools/tests/test_password_generata_non_stampata.py
# la tiene identica.
consegna_password() {
  if [ -t 1 ]; then
    warn "PASSWORD ADMIN GENERATA: ${C_B}$1${C_R}"
    warn "  → SALVALA SUBITO in un password manager. Non la rivedrai."
    return 0
  fi
  local dir="${XDG_CONFIG_HOME:-$HOME/.config}/vps1777" f
  f="$dir/admin-password-$(date +%Y%m%d-%H%M%S).txt"
  ( umask 077 && mkdir -p "$dir" && printf '%s\n' "$1" > "$f" )
  warn "PASSWORD ADMIN GENERATA: non la stampo, l'output non va a un terminale (H75)."
  warn "  → è in $f (la legge solo il tuo utente): copiala in un password manager, poi cancella il file."
}

consegna_gateway_secret() {
  # $1 = il segreto, $2 = l'URL pubblico (può mancare). Imposta GW_SEGRETO_MOSTRATO (il
  # valore davanti a un terminale, altrimenti un rimando al file) e GW_SEGRETO_FILE.
  local base="${2:-<URL>}"
  if [ -t 1 ]; then
    # shellcheck disable=SC2034  # le legge deploy.sh; rotate-secret.sh no (funzione identica)
    GW_SEGRETO_MOSTRATO="$1" GW_SEGRETO_FILE=""
    warn "GATEWAY_SECRET: ${C_B}$1${C_R}"
    warn "  → connettori claude.ai: $base/$1/archive/mcp  e  $base/$1/nb1777/mcp"
    return 0
  fi
  local dir="${XDG_CONFIG_HOME:-$HOME/.config}/vps1777" f
  f="$dir/gateway-secret-$(date +%Y%m%d-%H%M%S).txt"
  ( umask 077 && mkdir -p "$dir" && printf 'gateway_secret: %s\nconnettore archive1777: %s/%s/archive/mcp\nconnettore nb1777: %s/%s/nb1777/mcp\n' "$1" "$base" "$1" "$base" "$1" > "$f" )
  # shellcheck disable=SC2034  # come sopra
  GW_SEGRETO_MOSTRATO="<nel file $f>" GW_SEGRETO_FILE="$f"
  warn "GATEWAY_SECRET: non lo stampo, l'output non va a un terminale (H77)."
  warn "  → segreto e URL dei connettori sono in $f (lo legge solo il tuo utente)."
}

pw_weak_reason() {
  local pw="$1" classes=0
  if [ "${#pw}" -lt 16 ]; then echo "troppo corta (min 16 caratteri)"; return 1; fi
  printf '%s' "$pw" | LC_ALL=C grep -q '[a-z]'      && classes=$((classes+1))
  printf '%s' "$pw" | LC_ALL=C grep -q '[A-Z]'      && classes=$((classes+1))
  printf '%s' "$pw" | LC_ALL=C grep -q '[0-9]'      && classes=$((classes+1))
  printf '%s' "$pw" | LC_ALL=C grep -q '[^a-zA-Z0-9]' && classes=$((classes+1))
  if [ "$classes" -lt 3 ]; then
    echo "poca varietà: servono almeno 3 tra minuscole, MAIUSCOLE, cifre e simboli"; return 1
  fi
  if printf '%s' "$pw" | LC_ALL=C grep -qiE 'password|12345|qwerty|abcdef|letmein|welcome|admin|vps1777|000000|111111'; then
    echo "contiene un pattern comune/prevedibile"; return 1
  fi
  return 0
}

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
    log "Rotation gateway_secret (namespace URL + canale interno)"
    log "ATTENZIONE: gli URL connector di claude.ai cambieranno. Dovrai rigenerare i connector."
    read -r -p "Procedo? [s/N]: " ack
    case "$ack" in s|S|si|SI|y|Y|yes|YES) ;; *) die "Annullato" ;; esac
    NEW=$(gen_random 24)
    echo -n "$NEW" > "$FILE"
    chmod 600 "$FILE"
    # H77: mai `ok "Nuovo gateway_secret: …"` — lanciato da un agente finiva nel transcript.
    consegna_gateway_secret "$NEW" "$(sed -n 's/^PUBLIC_BASE=//p' .env 2>/dev/null | tr -d "\"'")"
    # Il gateway_secret NON è solo il namespace dell'URL: dalla v0.30.0 (H6) è
    # anche il segreto del canale interno gateway/bot → nb1777-mcp (il profilo
    # NotebookLM). Riavviare il solo gateway lascerebbe nb1777-mcp e il bot col
    # segreto VECCHIO → 403 sul canale interno (/admin/nlm rotto, il bot che
    # crede l'auth mancante). Vanno riavviati TUTTI i consumatori.
    log "Restart dei consumatori (gateway, nb1777-mcp, nb1777-bot)..."
    docker compose restart gateway nb1777-mcp nb1777-bot
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
    log "Rotation password admin"
    if [ -t 0 ]; then
      while :; do
        printf '%sNuova password (min 16, ≥3 classi; vuoto = la genero forte io):%s ' "$C_B" "$C_R"
        read -rs PWD; echo
        [ -z "$PWD" ] && break
        if reason="$(pw_weak_reason "$PWD")"; then break; fi
        warn "Password debole: $reason. Riprova (o Invio vuoto per generarne una forte)."
      done
    fi
    if [ -z "${PWD:-}" ]; then
      PWD=$(gen_pass 24)
      consegna_password "$PWD"
    elif ! reason="$(pw_weak_reason "$PWD")"; then
      die "Password troppo debole: $reason. Rifiutata (policy: min 16, ≥3 classi, niente pattern comuni)."
    fi
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
    # 🔴 27/09 (audit della doc): il gateway verifica la Mini App con la chiave DERIVATA
    #   dal token (HMAC_SHA256 «WebAppData», H54), non col token. Senza riderivarla qui la
    #   Mini App rifiutava ogni accesso col bot che rispondeva: il guasto si cercava altrove.
    #   Stessa derivazione di `assicura_webapp_secret` in vps1777.py e degli installer.
    TELEGRAM_BOT_TOKEN="$TOK" python3 -c '
import hashlib, hmac, os
print(hmac.new(b"WebAppData", os.environ["TELEGRAM_BOT_TOKEN"].encode(), hashlib.sha256).hexdigest(), end="")
' > secrets/telegram_webapp_secret.txt
    chmod 600 secrets/telegram_webapp_secret.txt
    ok "Chiave della Mini App (telegram_webapp_secret) riderivata dal token nuovo"
    docker compose restart nb1777-bot gateway
    ok "Fatto"
    ;;
  *)
    die "secret '$WHICH' non gestito"
    ;;
esac
