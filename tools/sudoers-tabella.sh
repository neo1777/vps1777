#!/usr/bin/env bash
# sudoers-tabella.sh — prova le regole sudo dell'operatore SENZA eseguire niente: `sudo -n -l -- comando`
# dice se il comando sarebbe permesso (esce 0) o negato (esce 1). Va lanciato COME L'OPERATORE.
#
# Uso:  bash sudoers-tabella.sh <cartella-del-prodotto>
# Esce: 0 tutta la tabella torna · 1 almeno una riga non torna · 2 non ho potuto provare
set -uo pipefail
R="${1:-}"; [ -n "$R" ] || { echo "manca la cartella del prodotto"; exit 2; }
command -v sudo >/dev/null || { echo "⚪ sudo non c'è"; exit 2; }
# `sudo -n -l comando` dice «permesso» anche per ciò che è permesso SOLO con una password. Se chi
# lancia è nel gruppo sudo, tutto risulta permesso e la tabella non misura niente (successo davvero
# il 23/11/2026: 31 su 31 nel contenitore di prova, 13 su 31 sulla macchina vera).
if id -nG | tr ' ' '\n' | grep -qx -e sudo -e wheel; then
  echo "⚪ NON MISURATO — $(id -un) è nel gruppo sudo: ogni comando risulterebbe permesso (con la password)."; exit 2
fi
[ "$(id -u)" -ne 0 ] || { echo "⚪ NON MISURATO — va lanciata come l'operatore, non da root"; exit 2; }
IO="$(id -u):$(id -g)"
ESITO=0; N=0
prova() { # $1 = sì|no, poi il comando
  local atteso="$1"; shift; N=$((N+1))
  if sudo -n -l -- "$@" >/dev/null 2>&1; then avuto="sì"; else avuto="no"; fi
  if [ "$avuto" = "$atteso" ]; then printf '  ✅ %-3s %s\n' "$avuto" "$*"; else printf '  🔴 %-3s (atteso %s) %s\n' "$avuto" "$atteso" "$*"; ESITO=1; fi
}
echo "── i 12 usi veri della CLI: devono passare"
prova sì install -m 755 "$R/.cosign-dl" /usr/local/bin/cosign
prova sì install -m 755 "$R/releases/v0.98.6/bundle/tools/vps1777.py" /usr/local/bin/vps1777
prova sì install -m 755 "$R/tools/vps1777.py" /usr/local/bin/vps1777
prova sì install -m 644 "$R/var/.vps1777-update.service.rendered" /etc/systemd/system/vps1777-update.service
prova sì install -m 644 "$R/var/.vps1777-avvisa-fallimento@.service.rendered" /etc/systemd/system/vps1777-avvisa-fallimento@.service
prova sì systemctl daemon-reload
prova sì systemctl enable --now vps1777-check-update.timer vps1777-update.path vps1777-secrets-check.timer vps1777-ingest.path
prova sì systemctl enable --now vps1777-check-update.timer vps1777-update.path vps1777-secrets-check.timer vps1777-ingest.path vps1777-auto-update.timer
prova sì systemctl disable --now vps1777-auto-update.timer
prova sì systemctl enable --now vps1777-ingest.path
prova sì systemctl enable --now vps1777-indice-notturno.timer
prova sì chown -hR "$IO" "$R/releases/v0.98.6"
prova sì chown -hR "$IO" "$R/onboarding" "$R/var" "$R/backups" "$R/releases"
echo "── abusi: devono essere negati"
prova no systemctl stop ssh
prova no systemctl start vps1777-update.service
prova no systemctl enable --now ssh.socket
prova no systemctl enable --now vps1777-update.path ssh.socket
prova no systemctl daemon-reload --root=/tmp/x
prova no install -m 644 /tmp/x /etc/sudoers.d/99-x
prova no install -m 4755 "$R/tools/vps1777.py" /usr/local/bin/vps1777
prova no install -m 755 /tmp/vps1777.py /usr/local/bin/vps1777
prova no install -m 755 "$R/tools/../../../tmp/x/tools/vps1777.py" /usr/local/bin/vps1777
prova no install -m 644 "$R/var/.vps1777-x.service.rendered" /etc/systemd/system/ssh.service
prova no install -m 644 "$R/var/.vps1777-x.service.rendered" /etc/systemd/system/vps1777-x.service /etc/cron.d/
prova no chown -R "$IO" "$R/var"
prova no chown -hR "$IO" /etc
prova no chown -hR "$IO" "$R/var/../../../etc"
prova no chown -hR "$IO" "$R/var" /etc/shadow
prova no chown -hR "$IO" "$R"
prova no chown -hR 0:0 "$R/var"
prova no cat /etc/shadow
prova no bash
echo "── $N righe provate"
exit "$ESITO"
