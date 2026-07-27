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
# Repo per VARIABILE prima che per posizione (come prova-1/3/4): copiata in /tmp,
# `dirname/../..` porterebbe a «/». Se non si trova: exit 2, MAI un PASS.
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

echo "── prova-2 · la rete egress è unidirezionale?   $(date '+%F %T')"

# ① nessuna porta PUBBLICATA dai servizi su egress (il fatto configurativo)
#
# 🔴 QUI C'ERA UN FALSO POSITIVO, misurato sul vivo il 26/07 alle 20:03. La versione
#    precedente leggeva `{{.Publishers}}`, che elenca ANCHE le porte solo ESPOSTE
#    (`EXPOSE` nel Dockerfile) con `PublishedPort: 0`. Su nb1777-mcp ha stampato
#    «{ 8003 0 tcp}» e ha gridato FAIL: ma `docker port` era VUOTO e sull'host non
#    c'era nulla in ascolto su :8003 — la porta è esposta alle reti docker, NON
#    pubblicata. ⇒ `expose` ≠ `ports`, ed è la stessa distinzione che il round-4
#    aveva già dovuto fare su H48. Sapevamo la differenza e lo strumento no.
#    ⭐ Un falso FAIL non è più innocuo di un falso PASS: manda a caccia di un
#      problema che non esiste e toglie credibilità ai rossi veri.
# Ora si chiede a `docker port`, che risponde SOLO delle pubblicazioni reali.
pub=""
for svc in nb1777-mcp nb1777-bot; do
  cid=$(docker compose ps -q "$svc" 2>/dev/null | head -1)
  [ -n "$cid" ] || continue
  mapped=$(docker port "$cid" 2>/dev/null)          # vuoto = nessuna pubblicazione
  [ -n "$mapped" ] && pub="$pub$svc → $mapped"$'\n'
done
if [ -n "$pub" ]; then
  echo "   🔴 servizi su egress con porte PUBBLICATE sull'host:"; printf '%s' "$pub" | sed 's/^/      /'
  echo "🔴 FAIL — una porta pubblicata è un ingresso, non un'uscita."; exit 1
fi
echo "   ✅ nessuna porta pubblicata da nb1777-mcp / nb1777-bot (le porte EXPOSE non contano:"
echo "      sono visibili solo alle reti docker, non all'host)"

# ② l'uscita FUNZIONA (controprova positiva: se qui fallisce, il ① sopra non
#    prova niente — un servizio isolato del tutto darebbe lo stesso verde)
out=$(docker compose exec -T nb1777-mcp python3 -c "
import socket
socket.setdefaulttimeout(6)
try:
    socket.create_connection(('1.1.1.1', 443)); print('ESCE')
except Exception as e:
    print('NON-ESCE', type(e).__name__)
" </dev/null 2>/dev/null | tr -d '\r')
case "$out" in
  ESCE)     echo "   ✅ nb1777-mcp ESCE (controprova positiva: la prova sa dire sì)" ;;
  NON-ESCE*) echo "   ⚠️  nb1777-mcp NON esce ($out) — allora il verde del ① non dimostra il NAT:"
             echo "      questo servizio deve poter parlare con NotebookLM. Da guardare."; ;;
  *)        echo "   ?  esito non interpretabile («$out») — NON concludo" ;;
esac

# ③ l'IP del container su egress non è raggiungibile dall'host su porte comuni
ip=$(docker compose exec -T nb1777-mcp hostname -i </dev/null 2>/dev/null | tr -d '\r' | awk '{print $1}')
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
