#!/usr/bin/env sh
# tools/backup-container-setup.sh — eseguito DENTRO il container backup all'avvio.
#
# Setup:
#   1. installa age + bash + docker-cli (alpine apk)
#   2. crea cron job: ogni notte 03:00 UTC → bash /vps1777/tools/backup.sh
#   3. esegue cron in foreground

set -e

# NON installiamo docker-cli: i volumi dati sono montati direttamente (ro) e
# backup.sh li tara da $BACKUP_VOLUMES_DIR → niente docker.sock (H13).
#
# Pin delle versioni (H13). Il container installa i pacchetti a RUNTIME
# (`apk add --no-cache`): l'immagine base è digest-pinnata in compose, ma ciò NON
# congela ciò che apk scarica dal mirror live — solo un pin esplicito lo fa.
# Verificato su Alpine 3.20 (main+community), identico su x86_64 e aarch64:
#     age  1.2.1-r0   (community)
#     bash 5.2.26-r0  (main)
# Installiamo SOLO ciò che backup.sh usa davvero — age, bash, e busybox `tar`
# (già nell'immagine). Rimossi py3-pip/py3-bcrypt/tini: erano dipendenze del
# gateway finite qui per copia-incolla (con docker-cli, tolto in #37), MAI usate
# dal backup — ogni pacchetto in più è superficie della catena di fornitura.
#
# CAVEAT dichiarato: i mirror stabili di Alpine tengono UNA sola `-rN` per
# pacchetto; a un rebuild upstream (1.2.1-r0 → -r1) questo `apk add` fallisce con
# un messaggio chiaro, non con un pacchetto silenziosamente diverso — a quel punto
# si bumpa il pin di proposito. Il fix più robusto (fuori dal mio scope: tocca il
# Dockerfile/compose) è cuocere questi pacchetti in un'immagine custom a build-time
# invece di apk-a-runtime. Vedi la nota nel report.
echo "[backup] installing age + bash (pinned)..."
apk add --no-cache age=1.2.1-r0 bash=5.2.26-r0 >/dev/null

echo "[backup] writing crontab..."
cat > /etc/crontabs/root <<EOF
# vps1777 daily backup at 03:00 UTC
0 3 * * * cd /vps1777 && bash tools/backup.sh >> /var/log/backup.log 2>&1
EOF

touch /var/log/backup.log
echo "[backup] cron schedule:"
crontab -l

echo "[backup] starting crond in foreground..."
exec crond -f -d 8
