#!/usr/bin/env sh
# tools/backup-container-setup.sh — eseguito DENTRO il container backup all'avvio.
#
# Setup:
#   1. installa age + bash + docker-cli (alpine apk)
#   2. crea cron job: ogni notte 03:00 UTC → bash /vps1777/tools/backup.sh
#   3. esegue cron in foreground

set -e

echo "[backup] installing age + bash + docker-cli + py3-pip + tini..."
apk add --no-cache age bash docker-cli py3-pip py3-bcrypt tini >/dev/null

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
