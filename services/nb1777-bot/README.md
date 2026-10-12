# nb1777-bot

Bot Telegram owner-only: apre il pannello (la Mini App) e recapita i promemoria di nb1777
(sessione Google scaduta, canonico).

## Variabili d'ambiente

| Var | Default | Descrizione |
|---|---|---|
| `TELEGRAM_BOT_TOKEN_FILE` | — (in `compose.yaml` `/run/secrets/telegram_bot_token`) | path al file con il token di BotFather (in dev: `TELEGRAM_BOT_TOKEN`) |
| `TELEGRAM_OWNER_ID` | (none) | il TUO Telegram numeric ID |
| `GATEWAY_PUBLIC_BASE` | (none; in `compose.yaml` viene da `PUBLIC_BASE`) | URL pubblico del gateway: il bottone della Mini App (`<base>/app`, solo se https) e il link `/admin/nlm` |
| `NLM_INTERNAL_BASE` | `http://nb1777-mcp:8003` | dove chiedere lo stato dell'auth, le notifiche e l'ack (`/internal/*`); il bot non monta i cookie (H6) |
| `GATEWAY_SECRET_FILE` | — (in `compose.yaml` `/run/secrets/gateway_secret`) | segreto condiviso per gli `/internal/*` di nb1777-mcp: senza, stato dell'auth, notifiche e ack falliscono |
| `BOT_HEARTBEAT_FILE` | `/tmp/nb1777-bot.heartbeat` | il file della prova di vita |
| `LOG_LEVEL` | `INFO` | livello dei log |
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
così un update non fallisce sulle installazioni senza Telegram. Per attivarlo,
dalla radice del repo: `./tools/rotate-secret.sh telegram_bot_token`. Scrive il
token, rideriva la chiave della Mini App e riavvia bot e gateway. Scrivere solo
il file e riavviare il bot non basta: il bot risponde, ma la Mini App resta
senza chiave.
