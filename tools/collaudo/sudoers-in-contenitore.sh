#!/usr/bin/env bash
# Prova la candidata in un contenitore Debian 12 usa-e-getta: installa sudo, mette le regole
# (validate con visudo), e lancia la tabella come operatore. Non tocca la macchina su cui gira.
set -euo pipefail
QUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
docker run --rm -v "$QUI:/c:ro" debian:12 bash -c '
  set -e
  apt-get update -qq >/dev/null && apt-get install -y -qq sudo systemd >/dev/null 2>&1
  useradd -m -u 1001 operatore
  bash /c/sudoers-operatore.sh operatore /home/operatore/vps1777 > /tmp/regole
  visudo -cf /tmp/regole >/dev/null && install -m 0440 /tmp/regole /etc/sudoers.d/90-operatore
  sudo -V | head -1
  su operatore -c "bash /c/sudoers-tabella.sh /home/operatore/vps1777"
'
