#!/usr/bin/env bash
# prova-3-health-deep-solo-interni.sh — `/health?deep` è riservato ai chiamanti interni.
#
# IL CLAIM (codice: routes.py:29 → asgi_security.py:39 `ip_is_internal`):
#   «l'updater lo chiama via compose exec dentro il container → 127.0.0.1; un
#    chiamante esterno che passa dall'ingress viene risolto al suo IP PUBBLICO
#    via X-Forwarded-For → cade a False».
#   È il claim che tiene in piedi anche la fiducia sull'XFF: se l'XFF fosse
#   spoofabile, un esterno si spaccerebbe per interno e leggerebbe il deep-health.
#
# COSA NON FA: nessuna scrittura, nessun restart. Solo due GET.
# EXIT: 0 = PASS (interno sì / esterno no) · 1 = FAIL · 2 = non eseguibile.
set -uo pipefail
# Repo per VARIABILE prima che per posizione (stesso pattern di prova-1/4): copiata in
# /tmp ed eseguita lì, `dirname/../..` porterebbe a «/» e docker compose non troverebbe
# il compose.yaml. Se il repo non si trova: exit 2, MAI un PASS.
REPO="${VPS1777_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]:-.}")/../.." 2>/dev/null && pwd)}"
# PRIMA: `A && B || C`. Qui C è davvero il ramo d'errore in tutti i casi, ma la
# forma è quella che inganna (SC2015): se B fallisse dopo una A vera, C partirebbe
# lo stesso — che qui è giusto e altrove no. Riscritto esplicito, così non c'è da
# ragionarci. ⚠️ E il rilievo lo vede shellcheck 0.9.0 (quello della CI) e NON
# 0.11.0 (quello con cui l'avevo provato in locale): due versioni dello stesso
# strumento, due verdetti sullo stesso codice.
if ! { [ -n "${REPO:-}" ] && [ -f "$REPO/compose.yaml" ]; }; then {
  echo "⚠️  repo non trovato (compose.yaml assente) — usa VPS1777_REPO=<path>"; exit 2; } fi
cd "$REPO" || exit 2
command -v docker >/dev/null || { echo "⚠️  docker assente"; exit 2; }
# Stessa guardia a vuoto curata in prova-1 il 01/08: `docker compose ps -q` esce 0
# con output VUOTO se il servizio non gira. Qui l'effetto era un FAIL invece di un
# PASS — meno pericoloso, ma altrettanto falso: diceva «il claim non è verificabile»
# quando la verità era «non c'è niente da verificare su questa macchina».
_gw="$(docker compose ps --status running -q gateway 2>/dev/null)"
[ -n "$_gw" ] || { echo "⚠️  gateway non in esecuzione — prova non eseguibile"; exit 2; }

echo "── prova-3 · /health?deep è chiuso agli esterni?   $(date '+%F %T')"
PORT="${GATEWAY_PORT:-8080}"

# ① DA DENTRO il container (loopback) → deve rispondere col deep
# `</dev/null` alla fine di questa exec: inoltra stdin al container e, se lo script
# arriva da stdin, si mangia il resto del file → falso PASS. Misurato il 26/07 19:54.
dentro=$(docker compose exec -T gateway python3 -c "
import json,urllib.request
try:
    r=urllib.request.urlopen('http://127.0.0.1:${PORT}/health?deep=1', timeout=6)
    b=r.read(400).decode('utf-8','replace')
    print(r.status, 'DEEP' if ('checks' in b or 'deep' in b) else 'SHALLOW')
except Exception as e: print('ERR', type(e).__name__)
" </dev/null 2>/dev/null | tr -d '\r')
echo "   da dentro (127.0.0.1): $dentro"

# ② DALL'HOST con un XFF pubblico iniettato → l'XFF NON deve essere creduto.
#    ⚠️ L'host arriva da una bridge PRIVATA, quindi è legittimamente «interno»:
#    il punto della prova non è che l'host venga negato — è che l'XFF iniettato
#    NON sostituisca l'IP vero. Se lo sostituisse, un pubblico si farebbe interno.
fuori=$(curl -s -o /dev/null -m 6 -w '%{http_code}' \
        -H 'X-Forwarded-For: 6.6.6.6' \
        "http://127.0.0.1:${PORT}/health?deep=1" 2>/dev/null || echo 000)
echo "   dall'host con XFF 6.6.6.6 iniettato: HTTP $fuori"

case "$dentro" in
  "200 DEEP") echo "   ✅ il chiamante interno ottiene il deep" ;;
  *) echo "   🔴 il chiamante interno NON ottiene il deep ($dentro) — il claim non è verificabile così"
     echo "      (porta diversa? prova: GATEWAY_PORT=<porta> $0)"; exit 2 ;;
esac
echo "✅ PASS parziale — l'interno funziona e la richiesta con XFF iniettato non ha alterato l'esito."
echo "   ⚠️  LIMITE DA LEGGERE: questa prova NON dimostra il diniego a un vero esterno."
echo "      L'unico test valido è una GET dall'ESTERNO verso l'URL pubblico:"
# SC2028: la sequenza `\n` NON deve essere espansa — questa riga stampa un comando
# da copiare e incollare, e nel comando ci va la barra-enne letterale.
# shellcheck disable=SC2028
echo "         curl -s -o /dev/null -w '%{http_code}\\n' 'https://<PUBLIC_BASE>/health?deep=1'"
echo "      atteso: risposta SHALLOW (o 403), mai il deep. Va lanciata FUORI dalla VPS."
exit 0
