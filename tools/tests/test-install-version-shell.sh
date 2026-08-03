#!/usr/bin/env bash
# La parte SHELL del fix «non c'è nessuna release» ≠ «non ho potuto chiedere».
#
# Esercita il blocco vero di `setup.sh` e `deploy.sh` — estratto dal file al momento
# del test, non ricopiato qui: una copia proverebbe se stessa. `curl` è finto e messo
# davanti nel PATH; `die/ok/warn` sono stub che stampano un prefisso riconoscibile.
#
# Casi, e cosa distinguono:
#   ① curl esce ≠0            → DEVE fermarsi     (prima: DEV_BUILD=1, build locale)
#   ② GitHub risponde {}      → build locale, ed è l'unico caso in cui è vero
#   ③ GitHub dà una release   → la installa       (controprova di polarità)
#   ④ VPS1777_INSTALL_VERSION → non chiede a nessuno (controprova di polarità)
#
# Uso:  bash tools/tests/test-install-version-shell.sh
set -uo pipefail

RADICE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FALLITI=0
ESEGUITI=0

# Il blocco: da `DEV_BUILD="${DEV_BUILD:-0}"` al primo `fi` in colonna 0. I `fi`
# interni sono indentati, quindi la fine non è ambigua.
estrai_blocco() {
  awk '/^DEV_BUILD="\$\{DEV_BUILD:-0\}"$/,/^fi$/' "$1"
}

# $1 script · $2 nome del caso · $3 comportamento di curl (script sh) · $4 atteso (regex)
# $5.. eventuali VAR=val da esportare
prova() {
  local script="$1" nome="$2" curl_finto="$3" atteso="$4"; shift 4
  ESEGUITI=$((ESEGUITI + 1))
  local box; box="$(mktemp -d)"
  printf '%s\n' "$curl_finto" > "$box/curl"; chmod +x "$box/curl"

  local blocco; blocco="$(estrai_blocco "$RADICE/$script")"
  if [ -z "$blocco" ]; then
    printf 'FAIL %-9s %-34s (blocco non estratto: il marcatore è cambiato?)\n' "$script" "$nome"
    FALLITI=$((FALLITI + 1)); rm -rf "$box"; return
  fi

  {
    echo 'set -euo pipefail'
    echo 'die()  { printf "ESITO=die %s\n" "$*" >&2; exit 1; }'
    echo 'ok()   { printf "ESITO=ok %s\n"   "$*"; }'
    echo 'warn() { printf "ESITO=warn %s\n" "$*"; }'
    printf '%s\n' "$blocco"
    echo 'printf "FINALE INSTALL_VERSION=[%s] DEV_BUILD=[%s]\n" "$INSTALL_VERSION" "$DEV_BUILD"'
  } > "$box/prova.sh"

  local out piatto
  out="$(env "$@" PATH="$box:$PATH" bash "$box/prova.sh" 2>&1)"
  # ⚠️ il grep si fa sull'output APPIATTITO: `grep -E` lavora riga per riga, quindi un
  # `.*` in un pattern NON attraversa il newline. Con l'output su più righe i pattern
  # che legano il messaggio all'esito finale fallivano — e il comportamento era giusto:
  # sarebbe stato un test rosso su codice sano, cioè una guardia che si finisce per
  # disattivare. Il difetto stava nella sonda, non nell'oggetto.
  piatto="$(printf '%s' "$out" | tr '\n' '~')"

  if printf '%s' "$piatto" | grep -qE "$atteso"; then
    printf 'ok   %-9s %s\n' "$script" "$nome"
  else
    printf 'FAIL %-9s %-34s atteso /%s/, ottenuto:\n%s\n' "$script" "$nome" "$atteso" "$out"
    FALLITI=$((FALLITI + 1))
  fi
  rm -rf "$box"
}

CURL_ROTTO='#!/bin/sh
exit 6'                                            # 6 = couldn'"'"'t resolve host
CURL_RATE_LIMIT='#!/bin/sh
exit 22'                                           # 22 = HTTP >= 400 con -f
CURL_NESSUNA='#!/bin/sh
echo "{}"'
CURL_RELEASE='#!/bin/sh
echo "{\"tag_name\": \"v0.41.0\"}"'

for s in setup.sh deploy.sh; do
  # ① la domanda senza risposta NON diventa «nessuna release»
  prova "$s" "rete giù → si ferma"        "$CURL_ROTTO"      'ESITO=die.*curl exit 6'
  prova "$s" "rate-limit → si ferma"      "$CURL_RATE_LIMIT" 'ESITO=die.*curl exit 22'
  # ② l'unico caso che può ancora portare alla build locale
  prova "$s" "nessuna release → dev build" "$CURL_NESSUNA"   'ESITO=warn.*GitHub ha risposto.*DEV_BUILD=\[1\]'
  # ③④ controprove di polarità: il caso buono non si è rotto
  prova "$s" "release trovata → la installa" "$CURL_RELEASE" 'ESITO=ok.*v0\.41\.0.*INSTALL_VERSION=\[0\.41\.0\]'
  prova "$s" "versione imposta → non chiede" "$CURL_ROTTO"   'INSTALL_VERSION=\[9\.9\.9\]' \
        VPS1777_INSTALL_VERSION=9.9.9
  prova "$s" "DEV_BUILD=1 → non chiede"      "$CURL_ROTTO"   'INSTALL_VERSION=\[\] DEV_BUILD=\[1\]' \
        DEV_BUILD=1
done

echo "─────────────────────────────────────────────"
if [ "$FALLITI" -eq 0 ]; then
  echo "✅ $ESEGUITI casi, tutti passati"
  exit 0
fi
echo "🔴 $FALLITI falliti su $ESEGUITI"
exit 1
