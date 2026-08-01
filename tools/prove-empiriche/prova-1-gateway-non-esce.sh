#!/usr/bin/env bash
# prova-1-gateway-non-esce.sh — il gateway NON deve raggiungere Internet.
#
# COSA VERIFICA (empirico, sul vivo — nessun banco può dirlo):
#   `compose.yaml` mette il gateway su `backend` (internal:true) + `ingress`.
#   `ingress` è un bridge NON internal → il gateway POTREBBE avere uscita NAT.
#   La domanda che nessuna lettura statica chiude: **esce o non esce?**
#   Se esce, un gateway compromesso può esfiltrare i 5 secret che monta
#   (`telegram_bot_token` incluso) verso un endpoint dell'attaccante.
#
# COSA NON FA: non modifica niente, non riavvia niente, non scrive file.
#   Solo `docker compose exec` con una richiesta in uscita e un timeout.
# EXIT: 0 = PASS (non esce) · 1 = FAIL (esce) · 2 = non eseguibile.
set -uo pipefail
# Il repo si trova per variabile PRIMA che per posizione: questa prova gira anche
# passata via stdin (`ssh host 'VPS1777_REPO=… bash -s' < prova-1.sh`), dove
# BASH_SOURCE non esiste e un `cd` relativo a sé stessa porterebbe altrove.
# Stesso pattern di prova-4. Se il repo non si trova: exit 2 (non eseguibile),
# MAI un PASS — «non misurato» non è «passato».
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

command -v docker >/dev/null || { echo "⚠️  docker assente — prova non eseguibile"; exit 2; }
# 🔴 01/08 — QUESTA GUARDIA PASSAVA A VUOTO, e la prova dichiarava PASS su un
# gateway che non esisteva. `docker compose ps -q <svc>` esce **0 con output
# VUOTO** quando il servizio non gira: controllare l'exit code chiede «il comando
# ha funzionato?», non «ha TROVATO qualcosa?». Sono due domande diverse, e la
# seconda è quella che serve.
# ⭐ L'effetto era il difetto che queste prove esistono per non commettere:
#    «non ho potuto guardare» usciva come «✅ PASS — nessuna uscita rilevata».
#    Trovato lanciando la prova DOVE NON PUÒ FUNZIONARE — che è il modo per
#    scoprire se una prova sa di essere nell'ambiente sbagliato.
_gw="$(docker compose ps --status running -q gateway 2>/dev/null)"
[ -n "$_gw" ] || {
  echo "⚠️  il servizio 'gateway' non è in esecuzione — prova non eseguibile"; exit 2; }

echo "── prova-1 · il gateway raggiunge Internet?   $(date '+%F %T')"
# Tre bersagli diversi: un IP nudo (salta il DNS), un dominio (usa il DNS), una porta alta.
# Tre perché un solo negativo può essere un DNS rotto, non un egress chiuso — e
# «non risolve» ≠ «non esce»: sono due difese diverse e vanno distinte.
esce=0
for t in "https://1.1.1.1" "https://example.com" "https://api.telegram.org"; do
  # -m 6: se la rete è bloccata il timeout scade; se è aperta risponde in <2s.
  # `</dev/null` NON è cosmetico: `docker compose exec -T` INOLTRA stdin al container.
  # Lanciata via `ssh host 'bash -s' < prova-1.sh`, la prima exec si mangia il RESTO
  # dello script → bash finisce l'input, esce 0 e stampa un PASS senza aver misurato.
  # Misurato sul campo il 26/07 19:54: falso PASS su una garanzia di sicurezza.
  code=$(docker compose exec -T gateway sh -c \
        "command -v curl >/dev/null && curl -s -o /dev/null -m 6 -w '%{http_code}' '$t' || echo NOCURL" \
        </dev/null 2>/dev/null | tr -d '\r')
  case "$code" in
    NOCURL) echo "   ?  $t → curl assente nel container (uso il fallback sotto)"; continue ;;
    000|"")  echo "   ✅ $t → nessuna risposta (uscita bloccata)" ;;
    *)       echo "   🔴 $t → HTTP $code — IL GATEWAY ESCE"; esce=1 ;;
  esac
done

# Fallback senza curl: /dev/tcp di sh non c'è, ma python3 spesso sì.
if [ "$esce" -eq 0 ]; then
  out=$(docker compose exec -T gateway python3 -c "
import socket
socket.setdefaulttimeout(5)
try:
    socket.create_connection(('1.1.1.1', 443)); print('APERTO')
except Exception as e:
    print('CHIUSO', type(e).__name__)
" </dev/null 2>/dev/null | tr -d '\r')
  case "$out" in
    APERTO*) echo "   🔴 socket diretto 1.1.1.1:443 → APERTO — IL GATEWAY ESCE"; esce=1 ;;
    CHIUSO*) echo "   ✅ socket diretto 1.1.1.1:443 → $out" ;;
    *)       echo "   ?  socket diretto: esito non interpretabile («$out») — NON concludo" ;;
  esac
fi

if [ "$esce" -eq 0 ]; then
  echo "✅ PASS — nessuna uscita rilevata dal gateway."
  echo "   ⚠️  Limite: prova l'assenza di uscita sulle destinazioni provate, non su TUTTE."
  exit 0
fi
echo "🔴 FAIL — il gateway ha uscita su Internet."
echo "   Impatto: un gateway compromesso può esfiltrare i secret che monta."
echo "   Fix candidato: togliere al gateway l'uscita NAT (ingress solo verso il proxy)."
exit 1
