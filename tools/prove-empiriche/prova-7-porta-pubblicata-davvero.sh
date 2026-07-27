#!/usr/bin/env bash
# prova-7-porta-pubblicata-davvero.sh — il gateway è raggiungibile DA FUORI di sé?
#
# COSA VERIFICA (empirico, sul vivo — e nessun presidio esistente lo vede):
#   Lo healthcheck del gateway interroga `http://127.0.0.1:8080/health` DA DENTRO
#   il container. Lì la porta risponde SEMPRE, anche quando dall'esterno non è
#   pubblicata affatto: `healthy` non dice «raggiungibile», dice «il processo
#   parla con sé stesso». Questa prova fa la sola domanda che conta per chi usa
#   il servizio: **dall'host, la porta esiste e risponde?**
#
# PERCHÉ ESISTE (27/07/2026, incidente reale, 1h40m di irraggiungibilità):
#   il fix di H50 ha lasciato il gateway solo su una rete `internal: true`. Da una
#   rete `internal` UNA PORTA NON SI PUÒ PUBBLICARE: docker accetta la direttiva
#   `ports:` e non la applica, IN SILENZIO. Per tutta la durata del guasto:
#     · il container era `healthy`                        → nessun allarme
#     · `docker compose config` mostrava il port mapping  → nessun allarme
#     · l'health-gate dell'auto-update era passato        → NESSUN ROLLBACK
#   Tre verdi su un servizio giù. Il guasto l'ha visto un umano, aprendo l'URL.
#   ⇒ La classe non è «una rete sbagliata»: è **un presidio che sonda dal lato in
#     cui il guasto non si vede**. Questa prova sta dall'altro lato.
#
# COSA NON FA: non modifica niente, non riavvia niente, non scrive file.
#   Non attraversa il Funnel/proxy: si ferma alla porta sull'host. Un Funnel giù
#   con la porta viva è un altro guasto, e questa prova non lo copre — dichiarato
#   qui perché un PASS non prometta più di quel che ha misurato.
# EXIT: 0 = PASS (pubblicata e risponde) · 1 = FAIL · 2 = non eseguibile/non applicabile.
set -uo pipefail

command -v docker >/dev/null || { echo "⚠️  docker assente — prova non eseguibile"; exit 2; }

echo "── prova-7 · la porta del gateway è pubblicata e risponde?   $(date '+%F %T')"

# Il container si trova per LABEL, non per file compose: questa prova deve poter
# girare senza sapere con quali `-f` lo stack è stato lanciato — ed è proprio la
# divergenza fra «i file che credo» e «ciò che gira» che stiamo misurando.
# Il servizio è parametrico per un motivo solo: poter puntare la prova a un
# container DELIBERATAMENTE ROTTO e vederla diventare rossa. Un presidio che non
# è mai stato visto fallire non è un presidio — è una speranza con un exit code.
SERVIZIO="${VPS1777_SERVIZIO:-gateway}"
PORTA="${VPS1777_PORTA:-8080}"
CID=$(docker ps -q --filter "label=com.docker.compose.service=$SERVIZIO" | head -1)
[ -n "$CID" ] || { echo "⚠️  nessun container '$SERVIZIO' in esecuzione — prova non eseguibile"; exit 2; }

SALUTE=$(docker inspect "$CID" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}(senza healthcheck){{end}}' 2>/dev/null)
echo "   ·  container $(docker inspect "$CID" --format '{{.Name}}' | tr -d '/') → healthcheck dice: $SALUTE"

# ── ① la porta è pubblicata? ──────────────────────────────────────────────
MAP=$(docker port "$CID" "$PORTA/tcp" 2>/dev/null | head -1 | tr -d '\r')
if [ -z "$MAP" ]; then
  # Un proxy in container (caddy/cloudflared) pubblica LUI la porta: in quel
  # profilo il gateway non deve pubblicare nulla e la prova non si applica.
  # «Non applicabile» non è «passata»: exit 2, mai 0.
  PROXY=$(docker ps --format '{{.Names}}' | grep -Ei 'caddy|cloudflared' | head -1)
  if [ -n "$PROXY" ]; then
    echo "   ⚠️  il gateway non pubblica porte, ma c'è un proxy in container ($PROXY):"
    echo "       profilo diverso da Tailscale — questa prova non si applica. NON è un PASS."
    exit 2
  fi
  echo "   🔴 nessuna porta pubblicata per $PORTA/tcp, e nessun proxy in container che la pubblichi."
  echo "🔴 FAIL — il gateway NON è raggiungibile dall'host."
  echo "   Causa tipica: il gateway sta solo su reti \`internal: true\` — da lì una porta"
  echo "   non si può pubblicare, e docker non lo segnala. Guarda le sue reti:"
  echo "       docker inspect $CID --format '{{range \$k,\$v := .NetworkSettings.Networks}}{{\$k}} {{end}}'"
  [ "$SALUTE" = "healthy" ] && echo "   ⚠️  E NOTA: il container è \`healthy\` lo stesso. È il difetto, non un dettaglio."
  exit 1
fi
echo "   ✅ pubblicata: $PORTA/tcp → $MAP"

# ── ② risponde davvero? ───────────────────────────────────────────────────
# Pubblicata ≠ servita: docker-proxy può tenere il listener aperto mentre dietro
# non c'è nessuno. La misura è la risposta, non la dichiarazione.
HOSTPORT="$MAP"
case "$HOSTPORT" in
  0.0.0.0:*|"[::]:"*) HOSTPORT="127.0.0.1:${MAP##*:}" ;;   # 0.0.0.0 non si interroga: si usa il loopback
esac
URL="http://${HOSTPORT}/health"

CODE=""
if command -v curl >/dev/null; then
  CODE=$(curl -s -o /dev/null -m 10 -w '%{http_code}' "$URL" 2>/dev/null)
elif command -v python3 >/dev/null; then
  CODE=$(python3 -c "
import urllib.request,sys
try:
    print(urllib.request.urlopen('$URL', timeout=10).status)
except Exception:
    print('000')
" 2>/dev/null)
else
  echo "   ⚠️  né curl né python3 sull'host — non posso interrogare la porta"
  echo "   ⚠️  la porta È pubblicata, ma «risponde» resta NON MISURATO: non concludo."
  exit 2
fi

case "$CODE" in
  200)
    echo "   ✅ $URL → HTTP 200"
    echo "✅ PASS — la porta è pubblicata e il gateway risponde dall'host."
    echo "   ⚠️  Limite: misura la porta sull'host, non il percorso pubblico (Funnel/proxy/TLS)."
    exit 0 ;;
  000|"")
    echo "   🔴 $URL → nessuna risposta"
    echo "🔴 FAIL — la porta è pubblicata ma dietro non risponde nessuno."
    [ "$SALUTE" = "healthy" ] && echo "   ⚠️  E il container è \`healthy\`: il presidio interno non può vederlo."
    exit 1 ;;
  *)
    echo "   🔴 $URL → HTTP $CODE (atteso 200)"
    echo "🔴 FAIL — il gateway risponde ma non è in salute sull'endpoint /health."
    exit 1 ;;
esac
