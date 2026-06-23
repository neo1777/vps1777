#!/usr/bin/env bash
# launch.sh — installer web locale di vps1777 (Linux / Mac / WSL).
# Doppio-click o: bash installer/launch.sh
#
# Avvia un mini-server su http://127.0.0.1:8777 e apre il browser.
# Deploy via SSH in Python puro (paramiko) — niente bash/sshpass remoti.
# Requisiti: python3. paramiko installato qui sotto se manca (pip/ensurepip/apt).

set -e
cd "$(dirname "$0")"

command -v python3 >/dev/null || { echo "python3 non trovato. Installalo e riprova."; exit 1; }

if ! python3 -c "import paramiko" 2>/dev/null; then
  echo "  Installo paramiko (dipendenza SSH)…"
  installed=0

  # 1) pip, se disponibile
  if [ "$installed" = "0" ] && python3 -m pip --version >/dev/null 2>&1; then
    if python3 -m pip install --user --quiet paramiko 2>/dev/null \
       || python3 -m pip install --user --break-system-packages --quiet paramiko 2>/dev/null; then
      installed=1
    fi
  fi

  # 2) ensurepip → pip
  if [ "$installed" = "0" ] && python3 -m ensurepip --user >/dev/null 2>&1; then
    if python3 -m pip install --user --quiet paramiko 2>/dev/null; then installed=1; fi
  fi

  # 3) apt (Debian/Ubuntu/WSL) — pacchetto di sistema, no pip
  if [ "$installed" = "0" ] && command -v apt-get >/dev/null 2>&1; then
    echo "  (serve sudo per installare python3-paramiko via apt)"
    if sudo apt-get update -q && sudo apt-get install -y python3-paramiko; then installed=1; fi
  fi

  # 4) brew (Mac)
  if [ "$installed" = "0" ] && command -v brew >/dev/null 2>&1; then
    brew install python-paramiko 2>/dev/null && installed=1 || true
  fi

  if ! python3 -c "import paramiko" 2>/dev/null; then
    echo
    echo "  Impossibile installare paramiko automaticamente. Prova a mano:"
    echo "    Debian/Ubuntu/WSL:  sudo apt install python3-paramiko"
    echo "    con pip:            pip install paramiko"
    echo "    Mac:                brew install python-paramiko"
    exit 1
  fi
fi

echo
echo "  vps1777 installer"
echo "  Se il browser non si apre da solo, vai su:  http://127.0.0.1:8777"
echo

exec python3 installer.py
