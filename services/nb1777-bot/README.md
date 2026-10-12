# nb1777-bot

Bot Telegram owner-only — gestione NotebookLM da chat.

## Variabili d'ambiente

| Var | Default | Descrizione |
|---|---|---|
| `TELEGRAM_BOT_TOKEN_FILE` | `/run/secrets/telegram_bot_token` | path al file con TOKEN BotFather |
| `TELEGRAM_OWNER_ID` | (none) | il TUO Telegram numeric ID |
| `GATEWAY_PUBLIC_BASE` | (none) | URL del gateway (per mostrare link /admin/nlm) |
| `NLM_HOME` | `/var/lib/nlm` | volume condiviso (legge AUTH_PENDING.flag) |
| `VPS1777_VERSION` | `0.0.0-dev` | versione dell'immagine (iniettata dalla CI) |

## Comandi

- `/start` — il bottone del pannello (la Mini App); se l'auth NotebookLM manca, la guida

Dal 12/10/2026 è l'unico: `/aiuto`, `/pannello`, `/lista` e `/chiedi` sono stati tolti, e
le domande ai notebook passano dalla Mini App (il bottone «Pannello» accanto al campo di
testo). Il bot porta anche i promemoria e il bottone «✓ Fatto» del canonico.

## Healthcheck & standby

Il bot è long-poll puro (nessuna porta): la prova di vita è un file heartbeat
(`/tmp/nb1777-bot.heartbeat`, toccato ogni 30s) che il healthcheck compose
verifica (mtime < 90s). Serve anche al health-gate di `vps1777 update`.

Senza token (`secrets/telegram_bot_token.txt` vuoto) il bot **non va in
crash-loop**: entra in *standby* tenendo vivo l'heartbeat (container healthy),
così un update non fallisce sulle installazioni senza Telegram. Configura il
token e `docker compose restart nb1777-bot` per attivarlo.
