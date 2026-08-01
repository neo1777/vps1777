#!/usr/bin/env bash
# tools/migra-chiave-miniapp.sh — H54: togli al gateway il token del bot, dagli la chiave.
#
# Uso:
#   ./tools/migra-chiave-miniapp.sh              # prepara la chiave e dice cosa fare
#   ./tools/migra-chiave-miniapp.sh --verifica   # controlla lo stato, non tocca niente
#
# ───────────────────────────────────────────────────────────────────────────────
# PERCHÉ QUESTO SCRIPT ESISTE, e perché NON applica da solo.
#
# `settings.py:159`, verbatim: «Facoltativa di proposito: senza, tutto funziona come
# prima. Migrare è una decisione di chi possiede la macchina, non un effetto
# collaterale di un update.»
#   ⇒ questo script PREPARA la decisione e la rende reversibile. Non la prende.
#
# Il codice per la chiave derivata è entrato con 6d9f9d5 (27/07), ma quel commit non
# ha toccato `compose.yaml`: il servizio `gateway` monta ancora `telegram_bot_token`
# (righe 87 e 97). Per questo H54 è rimasto `partial` — il gateway SA usare la chiave,
# nessuno gliel'ha ancora data.
#
# 🔑 COSA CAMBIA DAVVERO. Il gateway non chiama MAI l'API di Telegram (misurato in
# 6d9f9d5: zero occorrenze di api.telegram.org, sendMessage, getUpdates in
# services/gateway/). Del token gli serve UNA cosa: HMAC_SHA256("WebAppData", token).
# Col token intero, chi buca il gateway parla come il bot ovunque; con la chiave
# derivata può al massimo forgiare una initData per un gateway che è già suo.
# La derivazione è a senso unico: dalla chiave non si torna al token.
#
# ⚠️ QUESTO SCRIPT NON STAMPA MAI IL TOKEN, e non lo copia da nessuna parte. Legge il
#    file del secret, deriva, scrive SOLO la chiave derivata. Se lo interrompi a metà
#    non hai perso niente: il token resta dov'era e il compose non è toccato.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if [ -t 1 ]; then
  C_B=$'\e[1m'; C_OK=$'\e[32m'; C_W=$'\e[33m'; C_E=$'\e[31m'; C_I=$'\e[34m'; C_R=$'\e[0m'
else
  C_B=''; C_OK=''; C_W=''; C_E=''; C_I=''; C_R=''
fi
log()  { printf '%s[*]%s %s\n' "$C_I"  "$C_R" "$*"; }
ok()   { printf '%s[✓]%s %s\n' "$C_OK" "$C_R" "$*"; }
warn() { printf '%s[!]%s %s\n' "$C_W"  "$C_R" "$*"; }
die()  { printf '%s[✗]%s %s\n' "$C_E"  "$C_R" "$*" >&2; exit 1; }

TOKEN_FILE="./secrets/telegram_bot_token.txt"
CHIAVE_FILE="./secrets/telegram_webapp_secret.txt"
OVERLAY="compose.miniapp-secret.yaml"

# ───── stato: dove siamo, misurato e non supposto ─────
stato() {
  printf '%s── H54: chi ha il token del bot ──%s\n' "$C_B" "$C_R"
  if grep -qE '^\s+- telegram_bot_token\s*$' compose.yaml; then
    # a quale servizio appartiene ogni occorrenza: la chiave a due spazi più vicina sopra
    python3 - <<'PY'
import re
serv = None
for i, l in enumerate(open('compose.yaml', encoding='utf-8').read().split('\n'), 1):
    m = re.match(r'^  ([a-z0-9_-]+):\s*$', l)
    if m:
        serv = m.group(1)
    if re.match(r'^\s+- telegram_bot_token\s*$', l):
        marca = '  ← ESPOSTO SU INTERNET' if serv == 'gateway' else ''
        print(f'    compose.yaml:{i}  il servizio «{serv}» monta il token intero{marca}')
PY
  else
    ok "nessun servizio monta telegram_bot_token in compose.yaml"
  fi
  if [ -f "$CHIAVE_FILE" ]; then
    ok "la chiave derivata ESISTE: $CHIAVE_FILE"
  else
    warn "la chiave derivata non c'è ancora ($CHIAVE_FILE)"
  fi
  if [ -f "$OVERLAY" ]; then
    ok "l'overlay ESISTE: $OVERLAY"
  else
    warn "l'overlay non c'è ancora ($OVERLAY)"
  fi
}

if [ "${1:-}" = "--verifica" ]; then
  stato
  exit 0
fi

stato
echo

[ -f "$TOKEN_FILE" ] || die "non trovo $TOKEN_FILE — senza il token non posso derivare la chiave.
      (È l'unico momento in cui serve, e non esce da questa macchina.)"

if [ -f "$CHIAVE_FILE" ]; then
  warn "$CHIAVE_FILE esiste già: non lo sovrascrivo."
  warn "Se il token è stato ruotato, cancellalo a mano e rilancia — così la"
  warn "sovrascrittura è un tuo gesto, non un effetto collaterale del mio."
else
  log "derivo la chiave: HMAC_SHA256(\"WebAppData\", token) → 64 hex"
  umask 077
  python3 - "$TOKEN_FILE" "$CHIAVE_FILE" <<'PY'
import hashlib
import hmac
import sys

token = open(sys.argv[1], encoding="utf-8").read().strip()
if not token:
    sys.exit("il file del token è vuoto")
# la STESSA riga di services/gateway/app/miniapp_core.py:43 — se un giorno diverge,
# la Mini App smette di autenticare e il test qui sotto lo dice prima del deploy.
chiave = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).hexdigest()
open(sys.argv[2], "w", encoding="utf-8").write(chiave + "\n")
print(f"    lunghezza: {len(chiave)} hex   (attese 64)")
PY
  chmod 600 "$CHIAVE_FILE"
  ok "scritta $CHIAVE_FILE (0600) — il token NON è stato copiato né stampato"
fi

# ───── l'overlay: toglie il token al gateway e gli dà la chiave ─────
if [ ! -f "$OVERLAY" ]; then
  log "scrivo l'overlay $OVERLAY"
  cat > "$OVERLAY" <<'YAML'
# compose.miniapp-secret.yaml — H54: al gateway la chiave derivata, non il token.
#
# Uso:
#   docker compose -f compose.yaml -f compose.miniapp-secret.yaml up -d gateway
#
# È un OVERLAY e non una modifica a compose.yaml di proposito: la migrazione resta
# una scelta esplicita di chi gestisce la macchina, e si annulla togliendo un -f.
# `!reset` azzera la lista dei secrets ereditata da compose.yaml prima di riscriverla
# (compose ALTRIMENTI FONDE le liste, e il token resterebbe montato: il difetto
# sopravviverebbe a un file scritto per toglierlo).
services:
  gateway:
    environment:
      TELEGRAM_BOT_TOKEN_FILE: ""
      TELEGRAM_WEBAPP_SECRET_FILE: /run/secrets/telegram_webapp_secret
    # La lista è RISCRITTA PER INTERO: sono i secrets di compose.yaml (righe 93-98)
    # meno `telegram_bot_token`, più la chiave derivata.
    # ⚠️ `!reset` prima serve perché compose FONDE le liste invece di sostituirle:
    #    senza, il token resterebbe montato e questo file — scritto per toglierlo —
    #    non toglierebbe niente, in silenzio.
    secrets: !reset
      - gateway_secret
      - oauth_signing_secret
      - admin_password_bcrypt
      - archive_desc_secret
      - telegram_webapp_secret

secrets:
  telegram_webapp_secret:
    file: ./secrets/telegram_webapp_secret.txt
YAML
  ok "scritto $OVERLAY"
fi

# ───── il controllo che rende l'overlay verificabile invece che sperato ─────
# 🔴 La prima versione di questo script scriveva `secrets: !reset []` — lista VUOTA —
#    e un avviso che diceva «completala a mano». Chi non avesse letto l'avviso avrebbe
#    avviato il gateway senza NESSUN segreto. La prudenza che produce un artefatto
#    rotto non è prudenza: è il difetto, con una nota di scuse accanto.
# ⇒ adesso la lista c'è, ed è CONFRONTATA con compose.yaml invece che creduta.
log "confronto la lista dei secrets dell'overlay con quella di compose.yaml"
python3 - "$OVERLAY" <<'PY'
import re
import sys


def secrets_di(path, servizio):
    testo = open(path, encoding="utf-8").read().split("\n")
    serv, dentro, out = None, False, []
    for riga in testo:
        m = re.match(r"^  ([a-z0-9_-]+):\s*$", riga)
        if m:
            serv, dentro = m.group(1), False
        if re.match(r"^    secrets:", riga):
            dentro = serv == servizio
            continue
        if dentro:
            m2 = re.match(r"^      - ([a-z0-9_]+)\s*$", riga)
            if m2:
                out.append(m2.group(1))
            elif riga.strip() and not riga.startswith("      "):
                dentro = False
    return out


base = set(secrets_di("compose.yaml", "gateway"))
nuovo = set(secrets_di(sys.argv[1], "gateway"))
persi = base - nuovo - {"telegram_bot_token"}
if "telegram_bot_token" in nuovo:
    sys.exit("🔴 l'overlay monta ANCORA telegram_bot_token: non toglie niente")
if persi:
    sys.exit(f"🔴 l'overlay PERDE dei secrets che il gateway usa: {sorted(persi)}\n"
             "   il gateway partirebbe senza, e il modo in cui fallisce non dice quale manca")
if "telegram_webapp_secret" not in nuovo:
    sys.exit("🔴 l'overlay non dà la chiave derivata: il gateway non potrebbe autenticare")
print(f"    base {len(base)} secrets · overlay {len(nuovo)} · "
      f"tolto il token, aggiunta la chiave: nessuno perso")
PY
ok "l'overlay toglie il token E non perde nessun altro segreto — verificato, non sperato"

cat <<MSG

${C_B}── COSA MANCA, ed è tuo ──${C_R}
  1  ${C_B}docker compose -f compose.yaml -f ${OVERLAY} up -d gateway${C_R}
  2  prova che ha funzionato — ${C_B}sono due domande diverse${C_R}:
     · il token non c'è più:
       ${C_B}docker compose exec gateway ls /run/secrets/${C_R}   → nessun telegram_bot_token
     · e la Mini App autentica ancora:
       apri il pannello dal bot. Se si apre, la chiave derivata sta lavorando.
     ⚠️  la prima senza la seconda non è una migrazione: è un servizio rotto in modo
        silenzioso. Un pannello che non si apre più è il modo in cui te ne accorgi
        DOPO, e solo se qualcuno prova ad aprirlo.
  3  se qualcosa non torna: ${C_B}togli il -f ${OVERLAY}${C_R} e sei tornato indietro.
     Il token non è mai stato toccato.

${C_B}── e per il registro ──${C_R}
  H54 si chiude solo con la prova ESEGUITA (\`security/findings.yml\` la pretende):
  incolla l'output dei due comandi del punto 3, con la data. Finché non c'è,
  resta \`partial\` — ed è giusto così: oggi il codice sa, la macchina no.
MSG
