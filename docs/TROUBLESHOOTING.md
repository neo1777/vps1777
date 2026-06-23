# Troubleshooting — vps1777

Casi reali, diagnosi, fix.

## `docker compose up` fallisce con "permission denied" sui secret

Causa: i file `secrets/*.txt` hanno owner sbagliato.

Fix:
```bash
chmod 600 secrets/*.txt
chown $(id -u):$(id -g) secrets/*.txt
```

## Gateway non risponde su `/health`

Diagnosi:
```bash
docker compose ps gateway
docker compose logs gateway --tail 50
```

Casi comuni:
- `bcrypt` hash malformato in `admin_password_bcrypt.txt` → rigenera con `./tools/rotate-secret.sh admin_password`
- `gateway_secret.txt` vuoto → `./setup.sh` lo rigenera
- Porta 8080 occupata sul host (dev) → `lsof -iTCP:8080` e killa il processo

## Bot Telegram non risponde a `/start`

Diagnosi:
```bash
docker compose logs nb1777-bot --tail 30
```

Casi:
- `TELEGRAM_BOT_TOKEN` vuoto → riempi `secrets/telegram_bot_token.txt` + `docker compose restart nb1777-bot`
- `TELEGRAM_OWNER_ID` sbagliato → controlla `.env`, deve essere il TUO numero (non `0`)
- TOKEN revocato su BotFather → genera uno nuovo, aggiorna `secrets/telegram_bot_token.txt`

## Bot risponde "Auth NotebookLM mancante"

È atteso al primo avvio. Carica `auth.json` da `<PUBLIC_BASE>/admin/nlm`.

## `/admin/nlm` upload — "non è JSON valido"

Causa: hai caricato il file sbagliato.

`auth.json` corretto è quello che `nlm login` crea in `~/.notebooklm-mcp-cli/auth.json`. Deve avere chiave `profiles.default`.

Verifica sul tuo PC:
```bash
python3 -c "import json; d = json.load(open('~/.notebooklm-mcp-cli/auth.json')); print(list(d.keys()))"
# → ['profiles']
```

## Tailscale Funnel: "https://<host>.ts.net" non risponde

Diagnosi:
```bash
docker compose logs tailscale --tail 50
```

- Hostname non risolto: verifica `tailscale status` mostri il device
- Funnel non attivo: `docker exec tailscale tailscale funnel status`

## Archive MCP non trova niente (`search` ritorna vuoto)

Causa: i DB sono vuoti (degraded mode).

Soluzione: popola i dati:
```bash
docker compose exec archive-mcp ls /var/lib/archive/data/
# Devono esistere claude-web/, claude-cli/, claude-cli-dash/ con file di export
```

Vedi [docs/ARCHITECTURE.md](ARCHITECTURE.md) §archive-mcp per i formati attesi.

## Reset completo (perdi dati)

```bash
docker compose down -v       # -v cancella volumi
rm -rf secrets/ .env backups/
./setup.sh                   # ricominci da capo
```
