# gateway

OAuth 2.1 + DCR + reverse proxy MCP + pannello `/admin/*` + Mini App `/app/*`.

## Variabili d'ambiente

| Var | Default (codice; compose se diverso) | Descrizione |
|---|---|---|
| `GATEWAY_HOST` | `0.0.0.0` | bind address |
| `GATEWAY_PORT` | `8080` | porta interna |
| `GATEWAY_PUBLIC_BASE` | (none; compose: `PUBLIC_BASE` dal `.env`) | URL pubblico (`https://...`). Lasciato vuoto → loopback dev |
| `GATEWAY_UPSTREAMS` | (none; compose: `archive=archive-mcp:8002,nb1777=nb1777-mcp:8003`) | CSV `name=host:port` per ogni MCP plugin |
| `GATEWAY_SECRET_FILE` | (none; compose: `/run/secrets/gateway_secret`) | path al file contenente il namespace URL |
| `OAUTH_SIGNING_SECRET_FILE` | (none; compose: `/run/secrets/oauth_signing_secret`) | JWT signing key file |
| `OAUTH_PWD_HASH_FILE` | (none; compose: `/run/secrets/admin_password_bcrypt`) | hash bcrypt admin |
| `OAUTH_ALLOWED_EMAILS` | (none) | CSV degli email autorizzati come admin |
| `OAUTH_ACCESS_TOKEN_LIFETIME` | `900` | sec |
| `OAUTH_REFRESH_TOKEN_LIFETIME` | `2592000` | sec |
| `OAUTH_CORS_ORIGINS` | `https://claude.ai` (compose: `+ https://web.telegram.org`) | CSV |
| `OAUTH_TRUSTED_REDIRECT_HOSTS` | `claude.ai,claude.com` | CSV degli host di redirect che la pagina di consenso dà per noti; verso gli altri (tranne il loopback) chiede una conferma in più (H84) |
| `TELEGRAM_WEBAPP_SECRET_FILE` | (none; compose: `/run/secrets/telegram_webapp_secret`) | chiave derivata dal token del bot, per verificare l'`initData` della Mini App (il token intero il gateway non lo monta: `TELEGRAM_BOT_TOKEN_FILE` resta solo come ricaduta, H54) |
| `TELEGRAM_OWNER_ID` | `0` | owner della Mini App; 0 o vuoto = non entra nessuno (fail-closed) |
| `ARCHIVE_INGEST_CODA` | `false` (compose: `true`) | `/admin/archive` mette i file in coda per il job `ingest` invece di indicizzarli nel gateway |
| `OCR_URL` | (none; compose: `http://ocr:8004/ocr`) | servizio OCR per le immagini |
| `ARCHIVE_DESC_SECRET_FILE` | (none; compose: `/run/secrets/archive_desc_secret`) | segreto di `/internal/archive/*` |
| `AUDIT_LOG_PATH` | `/var/lib/gateway/audit.jsonl` | path scrittura audit |
| `AUDIT_RETENTION_DAYS` | `90` | potatura dell'audit oltre N giorni (0 = nessuna) |
| `GATEWAY_FORWARDED_ALLOW_IPS` | `127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16` | peer fidati per `X-Forwarded-For` |
| `TMPDIR` | (compose: `/var/lib/uploads`) | spool degli upload su disco |
| `VPS1777_TAG` | `dev` | versione deployata (mostrata nel footer + card Update) |
| `VPS1777_VERSION` | `0.0.0-dev` | versione dell'immagine (iniettata dalla CI di release) |

Fuori da compose `GATEWAY_UPSTREAMS` e le variabili `*_FILE` vanno passate: nel codice
(`app/settings.py`) sono vuote, e senza segreti il gateway nega (fail-closed).

## Endpoint principali

- `GET /health` — healthcheck (`?deep=1`: proba anche gli upstream MCP, 503 se giù; solo per i chiamanti interni, da fuori 403)
- `GET /.well-known/oauth-{protected-resource,authorization-server}` — discovery OAuth
- `POST /register` — Dynamic Client Registration OAuth
- `GET|POST /authorize` (pagina di consenso e decisione: dice a quale host va il permesso e, se non è noto, chiede una conferma), `POST /token` — flow OAuth 2.1
- `/admin/{login,setup,nlm,archive,update,salute,secrets,audit}` — pannello admin; in più `POST /admin/logout`, `POST /admin/archive/delete`, `POST /admin/update/check`, `GET /admin/nlm/artifact/{name}`
- `POST /admin/nlm` — upload del profilo nlm (tar.gz di `profiles/default`)
- `POST /admin/update` — scrive l'intent di aggiornamento (consumato dalla CLI host)
- `GET /admin/update/state` — JSON stato/progress per il polling della card
- `/app`, `POST /app/auth`, `/app/api/*` — Mini App Telegram (vedi [docs/MINIAPP.md](../../docs/MINIAPP.md))
- `GET /scarica/{name}?t=` e `GET|PUT|POST /carica/{t}` — link firmati di nb1777 (download di un artefatto, caricamento monouso): pubbliche, il gettone lo verifica nb1777-mcp
- `POST /internal/archive/{description,ruolo}` — solo dalla rete interna, col segreto `archive_desc_secret`
- `* /{secret}/{service}/{path}` — reverse proxy a `<host>:<port>/<path>` (`internal/` risponde sempre 404)

## Build/run locale

In produzione le immagini si **pullano** da ghcr (`compose.yaml` è pull-only).
Per buildare in locale in sviluppo, il tag corto `vps1777/gateway:dev` vive
solo nell'overlay `compose.build.yaml`:

```bash
docker build -t vps1777/gateway:dev .
docker run --rm -p 8080:8080 \
  -e GATEWAY_PUBLIC_BASE=http://127.0.0.1:8080 \
  -e OAUTH_ALLOWED_EMAILS=tu@gmail.com \
  -e GATEWAY_SECRET_FILE=/run/secrets/gateway_secret \
  -e OAUTH_SIGNING_SECRET_FILE=/run/secrets/oauth_signing_secret \
  -e OAUTH_PWD_HASH_FILE=/run/secrets/admin_password_bcrypt \
  -v $(pwd)/secrets:/run/secrets:ro \
  vps1777/gateway:dev
```
