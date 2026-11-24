#!/usr/bin/env bash
# Avvia in locale, con dati finti, ciò che serve alle schermate: installatore grafico, gateway, upstream finto.
set -u
V="$(cd "$(dirname "$0")" && pwd)"; R="$(cd "$V/../.." && pwd)"; L="${1:?uso: avvia.sh <cartella-di-lavoro>}"; mkdir -p "$L/dati/onb" "$L/dati/db" "$L/scatti"
python3 "$V/finto_upstream.py" > "$L/upstream.log" 2>&1 &
cd "$R/services/gateway" || exit 1
PWD_PROVA='Schermata-di-Prova-1777'
HASH="$(uv run --locked python -c "import bcrypt,sys;print(bcrypt.hashpw(sys.argv[1].encode(),bcrypt.gensalt(4)).decode())" "$PWD_PROVA")"
printf '%s' '{"current": "0.98.12", "latest": "0.98.13", "checked_at": "2026-11-24T06:00:02Z", "published_at": "2026-11-24T14:05:21Z", "changelog": "Il canale di aggiornamento firmato e con scadenza: se il canale scade, l'"'"'aggiornamento automatico si ferma e avvisa.", "error": null}' > "$L/dati/onb/update_status.json"
VETRINA_GATEWAY=1 GATEWAY_HOST=127.0.0.1 GATEWAY_PORT=18080 GATEWAY_PUBLIC_BASE=https://la-mia-vps.example.invalid \
 GATEWAY_SECRET=segreto-di-prova-per-le-schermate-0001 OAUTH_SIGNING_SECRET=firma-di-prova-per-le-schermate-000000000000000000001 \
 OAUTH_PWD_HASH="$HASH" OAUTH_ALLOWED_EMAILS=tu@example.invalid OAUTH_REQUIRED=true \
 TELEGRAM_WEBAPP_SECRET=$(printf 'a%.0s' $(seq 64)) TELEGRAM_OWNER_ID=424242 \
 AUDIT_LOG_PATH="$L/dati/audit.jsonl" ONBOARDING_DIR="$L/dati/onb" ARCHIVE_DB_DIR="$L/dati/db" \
 NLM_INTERNAL_BASE=http://127.0.0.1:18003 GATEWAY_UPSTREAMS=nb1777=127.0.0.1:18003,archive=127.0.0.1:18003 \
 VPS1777_VERSION=0.98.12 VPS1777_TAG=0.98.12 \
 uv run --locked python -m app > "$L/gateway.log" 2>&1 &
cd "$R" && VPS1777_INSTALLER_PORT=18777 python3 installer/installer.py > "$L/installer.log" 2>&1 &
sleep 6
for u in http://127.0.0.1:18080/health http://127.0.0.1:18080/admin/login http://127.0.0.1:18777/; do printf '%s → %s\n' "$u" "$(curl -s -o /dev/null -w '%{http_code}' -m 5 "$u")"; done
tail -3 "$L/gateway.log" | cut -c1-200
