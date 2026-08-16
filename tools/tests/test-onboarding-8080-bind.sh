#!/usr/bin/env bash
# La porta del pannello di setup sta sul LOOPBACK per default, e chi legge lo schermo
# deve sapere come aprirlo — altrimenti la cura si legge come «il deploy è fallito».
#
# Due cose provate, e sono di natura diversa:
#   ① il DATO      `compose config` risolve `host_ip: 127.0.0.1`?  ⇒ non è più 0.0.0.0
#   ② l'ISTRUZIONE il blocco di deploy.sh dice la cosa giusta nei TRE rami?
#      (tailscale · loopback · ONBOARDING_BIND=0.0.0.0)
#
# ⭐ Il ② non è un di più. Cambiare il binding senza cambiare la riga che dice
#   «apri http://IP:8080» manda l'utente contro un rifiuto di connessione, e la
#   lettura naturale è «è rotto». *Una cura che non aggiorna le sue istruzioni si
#   presenta come un guasto.*
#
# Il blocco si ESTRAE da deploy.sh al momento del test: una copia proverebbe se stessa.
# Uso:  bash tools/tests/test-onboarding-8080-bind.sh
set -uo pipefail

RADICE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FALLITI=0
ESEGUITI=0

ok()   { printf 'ok   %s\n' "$1"; }
fail() { printf 'FAIL %s\n     %s\n' "$1" "$2"; FALLITI=$((FALLITI + 1)); }

# ── ① il dato: cosa risolve compose ──────────────────────────────────────────
prova_compose() {
  local nome="$1" atteso="$2"; shift 2
  ESEGUITI=$((ESEGUITI + 1))
  if ! command -v docker >/dev/null 2>&1; then
    printf '⚪ %s — docker assente: NON eseguito (e questo non è un pass)\n' "$nome"
    return
  fi
  local out
  out="$(env "$@" CADDY_DOMAIN=esempio.invalid CADDY_EMAIL=a@esempio.invalid \
        ADMIN_EMAIL=a@esempio.invalid TELEGRAM_OWNER_ID=0 \
        docker compose --project-directory "$RADICE" -f "$RADICE/compose.yaml" \
          -f "$RADICE/compose.ingress.caddy.yaml" \
          -f "$RADICE/compose.onboarding.yaml" config 2>/dev/null)"
  if [ -z "$out" ]; then
    printf '⚪ %s — compose config non ha prodotto output: NON eseguito\n' "$nome"
    return
  fi
  local piatto; piatto="$(printf '%s' "$out" | tr '\n' '~')"
  if printf '%s' "$piatto" | grep -qE "$atteso"; then ok "$nome"
  else fail "$nome" "atteso /$atteso/ nella config risolta"; fi
}

prova_compose "default → host_ip 127.0.0.1" 'host_ip: 127\.0\.0\.1~ *target: 8080'
prova_compose "ONBOARDING_BIND=0.0.0.0 → torna aperta" 'host_ip: 0\.0\.0\.0~ *target: 8080' \
  ONBOARDING_BIND=0.0.0.0

# ── ② l'istruzione: i tre rami di deploy.sh ──────────────────────────────────
# Il blocco sta fra il commento che lo apre e il `fi` in colonna 0 che lo chiude.
# In deploy.sh ci sono DUE `if [ "$INGRESS" = "tailscale" ]`: il blocco giusto è
# quello che ASSEGNA ISTR_PANNELLO, e si prende per QUELLO. Cercarlo per la riga di
# apertura ne trovava un altro — e il test falliva su codice sano, che è il modo
# peggiore di sbagliare: si legge come un difetto dell'oggetto.
estrai_istruzioni() {
  python3 - "$RADICE/deploy.sh" <<'EOPY'
import re, sys
righe = open(sys.argv[1], encoding="utf-8").read().splitlines()
i = next(n for n, r in enumerate(righe) if "ISTR_PANNELLO=" in r)
apre = max(n for n in range(i) if righe[n].startswith('if [ "$INGRESS"'))
chiude = next(n for n in range(i, len(righe)) if righe[n] == "fi")
print("\n".join(righe[apre:chiude + 1]))
EOPY
}

prova_istruzione() {
  local nome="$1" atteso="$2" nonatteso="$3"; shift 3
  ESEGUITI=$((ESEGUITI + 1))
  local blocco; blocco="$(estrai_istruzioni)"
  # il blocco giusto è quello che ASSEGNA ISTR_PANNELLO: se il marcatore cambia,
  # meglio un rosso rumoroso che un verde su un blocco vuoto.
  if ! printf '%s' "$blocco" | grep -q "ISTR_PANNELLO="; then
    fail "$nome" "blocco non estratto da deploy.sh: il marcatore è cambiato?"
    return
  fi
  local box out; box="$(mktemp -d)"
  # Heredoc QUOTATO: qui dentro non espande niente, ed e' quello che serve —
  # `$ISTR_PANNELLO` e `\n` devono arrivare LETTERALI nel file generato, che e' dove
  # verranno interpretati. Con `echo '...'` shellcheck ha ragione due volte (SC2028 sul
  # `\n`, SC2016 sul `$`), e sono `info`: la CI lancia shellcheck senza soglia, quindi
  # un `info` e' rosso quanto un `error`. E' la seconda volta oggi che lo sbaglio.
  {
    cat <<'INTESTA'
set -u
C_B=""; C_R=""; C_OK=""
VPS_IP="203.0.113.9"; VPS_USER="tizio"; PUBLIC_BASE=""
INTESTA
    printf '%s\n' "$blocco"
    cat <<'CODA'
printf "%s\n" "$ISTR_PANNELLO"
CODA
  } > "$box/p.sh"
  out="$(env "$@" bash "$box/p.sh" 2>&1)"
  rm -rf "$box"
  local piatto; piatto="$(printf '%s' "$out" | tr '\n' '~')"
  if ! printf '%s' "$piatto" | grep -qE "$atteso"; then
    fail "$nome" "manca /$atteso/ — ottenuto: ${out:0:200}"; return
  fi
  if [ -n "$nonatteso" ] && printf '%s' "$piatto" | grep -qE "$nonatteso"; then
    fail "$nome" "NON doveva contenere /$nonatteso/ — ottenuto: ${out:0:200}"; return
  fi
  ok "$nome"
}

# loopback (il default): deve dire il TUNNEL e NON deve dire «apri http://IP:8080»
prova_istruzione "default → istruzione col tunnel SSH" \
  'ssh -L 8080:127\.0\.0\.1:8080 tizio@203\.0\.113\.9' \
  'http://203\.0\.113\.9:8080' INGRESS=caddy

# 0.0.0.0: deve dare l'URL diretto E l'avviso del tradeoff
prova_istruzione "ONBOARDING_BIND=0.0.0.0 → URL diretto + avviso" \
  'http://203\.0\.113\.9:8080/admin/setup.*in chiaro' \
  '' INGRESS=caddy ONBOARDING_BIND=0.0.0.0

# tailscale: il percorso non cambia — è la controprova di polarità
prova_istruzione "tailscale → Funnel, non tunnel SSH" \
  'Funnel' 'ssh -L' INGRESS=tailscale

echo "──────────────────────────────────────────"
if [ "$FALLITI" -eq 0 ]; then echo "✅ $ESEGUITI casi, tutti passati"; exit 0; fi
echo "🔴 $FALLITI falliti su $ESEGUITI"; exit 1
