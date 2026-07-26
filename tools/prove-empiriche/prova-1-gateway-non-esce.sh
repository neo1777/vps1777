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
cd "$(dirname "${BASH_SOURCE[0]}")/../.." || exit 2

command -v docker >/dev/null || { echo "⚠️  docker assente — prova non eseguibile"; exit 2; }
docker compose ps --status running -q gateway >/dev/null 2>&1 || {
  echo "⚠️  il servizio 'gateway' non è in esecuzione — prova non eseguibile"; exit 2; }

echo "── prova-1 · il gateway raggiunge Internet?   $(date '+%F %T')"
# Tre bersagli diversi: un IP nudo (salta il DNS), un dominio (usa il DNS), una porta alta.
# Tre perché un solo negativo può essere un DNS rotto, non un egress chiuso — e
# «non risolve» ≠ «non esce»: sono due difese diverse e vanno distinte.
esce=0
for t in "https://1.1.1.1" "https://example.com" "https://api.telegram.org"; do
  # -m 6: se la rete è bloccata il timeout scade; se è aperta risponde in <2s.
  code=$(docker compose exec -T gateway sh -c \
        "command -v curl >/dev/null && curl -s -o /dev/null -m 6 -w '%{http_code}' '$t' || echo NOCURL" 2>/dev/null | tr -d '\r')
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
" 2>/dev/null | tr -d '\r')
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
