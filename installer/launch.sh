#!/usr/bin/env bash
# launch.sh — avvia l'installer web locale di vps1777 (Linux / Mac / WSL).
# Doppio-click o: bash installer/launch.sh
#
# Avvia un mini-server su http://127.0.0.1:8777 e apre il browser.
# Requisiti: python3, ssh; per auth password anche sshpass.

set -e
cd "$(dirname "$0")"

command -v python3 >/dev/null || { echo "python3 non trovato. Installalo e riprova."; exit 1; }

echo
echo "  vps1777 installer"
echo "  Se il browser non si apre da solo, vai su:  http://127.0.0.1:8777"
echo

exec python3 installer.py
