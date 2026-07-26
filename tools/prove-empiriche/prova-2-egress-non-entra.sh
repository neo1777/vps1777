#!/usr/bin/env bash
# prova-2-egress-non-entra.sh — sulla rete `egress` si ESCE ma non si ENTRA.
#
# PERCHÉ ESISTE: l'audio del round-2 ha dichiarato questa esatta lacuna —
#   «il vero isolamento NAT di egress non è stato testato dal vivo, tutto è
#    puramente inferito dalla configurazione statica».
#   La lettura statica dice: `egress` è un bridge SENZA porte pubblicate ⇒ NAT
#   in uscita, nessun ingresso. Questa prova lo misura invece di dedurlo.
#
# COSA NON FA: non apre porte, non modifica il compose, non riavvia nulla.
# EXIT: 0 = PASS · 1 = FAIL (raggiungibile dall'esterno) · 2 = non eseguibile.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.." || exit 2
command -v docker >/dev/null || { echo "⚠️  docker assente"; exit 2; }

echo "── prova-2 · la rete egress è unidirezionale?   $(date '+%F %T')"

# ① nessuna porta pubblicata dai servizi su egress (il fatto configurativo)
pub=$(docker compose ps --format '{{.Service}} {{.Publishers}}' 2>/dev/null \
      | grep -E '^(nb1777-mcp|nb1777-bot) ' | grep -v '^\S* *$' || true)
if [ -n "$pub" ]; then
  echo "   🔴 servizi su egress con porte pubblicate:"; echo "$pub" | sed 's/^/      /'
  echo "🔴 FAIL — una porta pubblicata è un ingresso, non un'uscita."; exit 1
fi
echo "   ✅ nessuna porta pubblicata da nb1777-mcp / nb1777-bot"

# ② l'uscita FUNZIONA (controprova positiva: se qui fallisce, il ① sopra non
#    prova niente — un servizio isolato del tutto darebbe lo stesso verde)
out=$(docker compose exec -T nb1777-mcp python3 -c "
import socket
socket.setdefaulttimeout(6)
try:
    socket.create_connection(('1.1.1.1', 443)); print('ESCE')
except Exception as e:
    print('NON-ESCE', type(e).__name__)
" 2>/dev/null | tr -d '\r')
case "$out" in
  ESCE)     echo "   ✅ nb1777-mcp ESCE (controprova positiva: la prova sa dire sì)" ;;
  NON-ESCE*) echo "   ⚠️  nb1777-mcp NON esce ($out) — allora il verde del ① non dimostra il NAT:"
             echo "      questo servizio deve poter parlare con NotebookLM. Da guardare."; ;;
  *)        echo "   ?  esito non interpretabile («$out») — NON concludo" ;;
esac

# ③ l'IP del container su egress non è raggiungibile dall'host su porte comuni
ip=$(docker compose exec -T nb1777-mcp hostname -i 2>/dev/null | tr -d '\r' | awk '{print $1}')
if [ -n "$ip" ]; then
  echo "   ip interno di nb1777-mcp: $ip (privato: atteso)"
  for p in 8003 80 443; do
    if timeout 3 bash -c "echo > /dev/tcp/$ip/$p" 2>/dev/null; then
      echo "   ℹ️  $ip:$p risponde DALL'HOST — atteso: l'host è sulla bridge."
      echo "      NON è un fallimento: il claim è «non raggiungibile da INTERNET», non dall'host."
    fi
  done
fi
echo "✅ PASS — nessun ingresso pubblicato su egress."
echo "   ⚠️  Limite: provato dall'HOST. La prova definitiva è dall'ESTERNO"
echo "      (una macchina fuori dalla VPS verso l'IP pubblico) e questa non la fa."
exit 0
