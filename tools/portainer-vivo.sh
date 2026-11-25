#!/usr/bin/env bash
# portainer-vivo.sh — Portainer risponde? Il controllo dall'HOST che sostituisce l'healthcheck (25/11/2026).
#
# Perché esiste. `compose.ops.portainer.yaml` tiene Portainer sempre acceso (restart: unless-stopped)
# ma non può dichiarare un healthcheck: l'immagine a monte contiene solo il binario `portainer`,
# senza shell né client HTTP (verificato elencandone il contenuto), quindi dentro il contenitore
# non c'è niente con cui interrogarlo. Un healthcheck finto sarebbe peggio di nessuno. Lo si
# interroga da fuori, sulla porta che il compose pubblica solo sul loopback, e lo lancia ogni
# giorno `vps1777 check` quando la feature `portainer` è dichiarata.
#
# Che cosa guarda: GET /api/system/status, l'endpoint pubblico di stato di Portainer. Il
# certificato è autofirmato (Portainer se lo genera), quindi non si verifica: si parla col
# loopback della stessa macchina, e qui si chiede solo «rispondi?».
#
# Uso:   bash tools/portainer-vivo.sh
# Esce:  0 risponde · 1 non risponde o risponde male · 2 non ho potuto guardare (manca curl)
set -uo pipefail
URL="${PORTAINER_URL:-https://127.0.0.1:9443/api/system/status}"
command -v curl >/dev/null 2>&1 || { echo "⚪ portainer: manca curl, non ho potuto guardare"; exit 2; }
codice="$(curl --insecure --silent --output /dev/null --max-time "${PORTAINER_TIMEOUT_S:-5}" \
  --write-out '%{http_code}' "$URL" 2>/dev/null)" || codice="${codice:-000}"
if [ "$codice" = "200" ]; then
  echo "✅ portainer: risponde ($URL)"
  exit 0
fi
echo "🔴 portainer: non risponde come dovrebbe ($URL → HTTP $codice)"
exit 1
