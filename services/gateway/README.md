# gateway

OAuth 2.1 + DCR + reverse proxy MCP + pannello `/admin/*` + Mini App `/app/*`.

## Variabili d'ambiente

| Var | Default | Descrizione |
|---|---|---|
| `GATEWAY_HOST` | `0.0.0.0` | bind address |
| `GATEWAY_PORT` | `8080` | porta interna |
| `GATEWAY_PUBLIC_BASE` | (none) | URL pubblico (`https://...`). Lasciato vuoto → loopback dev |
| `GATEWAY_UPSTREAMS` | `archive=archive-mcp:8002,nb1777=nb1777-mcp:8003` | CSV `name=host:port` per ogni MCP plugin |
| `GATEWAY_SECRET_FILE` | `/run/secrets/gateway_secret` | path al file contenente il namespace URL |
| `OAUTH_SIGNING_SECRET_FILE` | `/run/secrets/oauth_signing_secret` | JWT signing key file |
| `OAUTH_PWD_HASH_FILE` | `/run/secrets/admin_password_bcrypt` | hash bcrypt admin |
| `OAUTH_ALLOWED_EMAILS` | (none) | CSV degli email autorizzati come admin |
| `OAUTH_ACCESS_TOKEN_LIFETIME` | `900` | sec |
| `OAUTH_REFRESH_TOKEN_LIFETIME` | `2592000` | sec |
| `OAUTH_CORS_ORIGINS` | `https://claude.ai` | CSV |
| `TELEGRAM_BOT_TOKEN_FILE` | `/run/secrets/telegram_bot_token` | per Mini App initData HMAC |
| `NLM_AUTH_DIR` | `/var/lib/nlm` | volume condiviso con nb1777-mcp |
| `AUDIT_LOG_PATH` | `/var/lib/gateway/audit.jsonl` | path scrittura audit |

## Endpoint principali

- `GET /health` — healthcheck
- `POST /register` — Dynamic Client Registration OAuth
- `GET /authorize`, `POST /token` — flow OAuth 2.1
- `GET /admin/{login,secrets,nlm,audit}` — pannello admin
- `POST /admin/nlm` — upload del profilo nlm (tar.gz di `profiles/default`)
- `GET /app/*` — Mini App Telegram
- `* /{secret}/{service}/{path}` — reverse proxy a `<host>:<port>/<path>`

## Build/run locale

```bash
docker build -t vps1777/gateway:dev .
docker run --rm -p 8080:8080 \
  -e GATEWAY_PUBLIC_BASE=http://127.0.0.1:8080 \
  -e OAUTH_ALLOWED_EMAILS=tu@gmail.com \
  -v $(pwd)/secrets:/run/secrets:ro \
  vps1777/gateway:dev
```
