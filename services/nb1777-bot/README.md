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

## Comandi MVP

- `/start` — saluto + check AUTH (se pending, messaggio guida)
- `/aiuto` — lista comandi
- `/lista` — elenca notebook
- `/chiedi <id> <domanda>` — domanda RAG

(In F8 aggiungiamo il set completo dei ~60 comandi)
