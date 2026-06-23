#!/usr/bin/env bash
# launch.sh — installer web locale di vps1777 (Linux / Mac / WSL).
# Doppio-click o: bash installer/launch.sh
#
# Avvia un mini-server su http://127.0.0.1:8777 e apre il browser.
# Deploy via SSH in Python puro (paramiko) — niente bash/sshpass remoti.
# Requisiti: python3. (paramiko installato qui sotto se manca.)

set -e
cd "$(dirname "$0")"

command -v python3 >/dev/null || { echo "python3 non trovato. Installalo e riprova."; exit 1; }

# paramiko: installa in --user se manca
if ! python3 -c "import paramiko" 2>/dev/null; then
  echo "  Installo paramiko (dipendenza SSH)…"
  python3 -m pip install --user --quiet paramiko \
    || python3 -m pip install --user --break-system-packages --quiet paramiko \
    || { echo "Impossibile installare paramiko. Prova: pip install paramiko"; exit 1; }
fi

echo
echo "  vps1777 installer"
echo "  Se il browser non si apre da solo, vai su:  http://127.0.0.1:8777"
echo

exec python3 installer.py
