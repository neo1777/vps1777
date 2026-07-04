# nb1777-bot

Bot Telegram owner-only — gestione NotebookLM da chat.

## Variabili d'ambiente

| Var | Default | Descrizione |
|---|---|---|
| `TELEGRAM_BOT_TOKEN_FILE` | `/run/secrets/telegram_bot_token` | path al file con TOKEN BotFather |
| `TELEGRAM_OWNER_ID` | (none) | il TUO Telegram numeric ID |
| `GATEWAY_PUBLIC_BASE` | (none) | URL del gateway (per mostrare link /admin/nlm) |
| `NB1777_MCP_URL` | `http://nb1777-mcp:8003/mcp` | MCP server per chiamate tool |
| `NLM_HOME` | `/var/lib/nlm` | volume condiviso (legge AUTH_PENDING.flag) |
| `VPS1777_VERSION` | `0.0.0-dev` | versione dell'immagine (iniettata dalla CI) |

## Comandi MVP

- `/start` — saluto + check AUTH (se pending, messaggio guida)
- `/aiuto` — lista comandi
- `/lista` — elenca notebook
- `/chiedi <id> <domanda>` — domanda RAG

(Il set completo dei ~60 comandi arriverà in una release successiva.)

## Healthcheck & standby

Il bot è long-poll puro (nessuna porta): la prova di vita è un file heartbeat
(`/tmp/nb1777-bot.heartbeat`, toccato ogni 30s) che il healthcheck compose
verifica (mtime < 90s). Serve anche al health-gate di `vps1777 update`.

Senza token (`secrets/telegram_bot_token.txt` vuoto) il bot **non va in
crash-loop**: entra in *standby* tenendo vivo l'heartbeat (container healthy),
così un update non fallisce sulle installazioni senza Telegram. Configura il
token e `docker compose restart nb1777-bot` per attivarlo.
