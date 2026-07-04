# Architettura — vps1777

## Tre cuori

```
┌────────── INGRESS (1 a scelta) ──────────┐
│  Tailscale Funnel | Caddy | Cloudflared  │
└─────────────────┬────────────────────────┘
                  ▼  (HTTPS pubblico → :8080 nel container)
┌──────────────── GATEWAY (core stabile) ──────────────┐
│  - OAuth 2.1 + DCR + PKCE                            │
│  - /admin/{login,secrets,nlm,audit}                  │
│  - /app/* (Mini App Telegram)                        │
│  - Reverse proxy: /<SECRET>/<name>/<path>            │
│  - Plugin registry: legge GATEWAY_UPSTREAMS da env   │
└─────────────────┬────────────────────────────────────┘
                  ▼  (rete backend, internal: true)
┌─── archive-mcp ──┬── nb1777-mcp ──┬── nb1777-bot ──┬─── PLUGIN ───┐
│  FTS5 multi-DB   │ nlm + Chromium │ Telegram poll  │  your MCP    │
│  :8002 /mcp      │ :8003 /mcp     │ no porta       │  your bot    │
└──────────────────┴────────────────┴────────────────┴──────────────┘
```

## Rete

| Rete | Driver | `internal` | Servizi connessi |
|---|---|---|---|
| `backend` | bridge | ✅ true | tutti i MCP, bot, gateway |
| `ingress` | bridge | ❌ false | gateway + sidecar ingress |

Backend è "world-isolated" — niente container interno può fare egress su internet (se servisse, si aggiunge `extra_hosts:` mirato).

## Volumi persistenti

| Volume | Path container | Contenuto |
|---|---|---|
| `gateway-data` | `/var/lib/gateway` | audit log, audit.jsonl |
| `archive-data` | `/var/lib/archive` | `data/` (sources) + `db/` (SQLite FTS5) |
| `nlm-auth` | `/var/lib/nlm` | profilo NotebookLM `profiles/default/` + `AUTH_PENDING.flag` |
| Tailscale (host) | `/var/lib/tailscale` sull'**host** | stato del nodo (non in container; vedi INGRESS.md) |
| `caddy-data` (se Caddy) | `/data` | certificati ACME |
| `cf-data` (se CF) | (nessuno) | token cred ephemeral |

## Secrets

Vedi [SECRETS.md](SECRETS.md). Tutti file-mounted in `/run/secrets/<name>` (tmpfs RO). Niente env var per cose sensibili.

## Contratti tra servizi

| Caller → Callee | Protocollo | Path |
|---|---|---|
| Internet → gateway | HTTPS (ingress) | `/<SECRET>/<name>/mcp` |
| gateway → MCP servers | HTTP loopback container | `http://<service>:<port>/mcp` |
| gateway → nb1777-mcp filesystem | volume condiviso | `/var/lib/nlm/profiles/default/` |
| nb1777-bot → nb1777-mcp | MCP client HTTP | `http://nb1777-mcp:8003/mcp` |
| Telegram cloud → bot | long-poll outbound HTTPS | `api.telegram.org` |
| claude.ai → gateway | OAuth 2.1 + MCP streamable-http | `/<SECRET>/<name>/mcp` |

## Plugin pattern

Vedi [PLUGINS.md](PLUGINS.md). In sintesi:

1. Crei `plugins/<nome>/` con `Dockerfile` + `compose.<nome>.yaml`
2. Esponi un endpoint MCP su porta interna (es. `8004`)
3. Aggiungi a `.env`: `GATEWAY_UPSTREAMS=archive=archive-mcp:8002,nb1777=nb1777-mcp:8003,<nome>=<container>:8004`
4. Restart gateway: `docker compose restart gateway`
5. URL del tuo plugin: `<PUBLIC_BASE>/<SECRET>/<nome>/mcp`

## Canale di aggiornamento

Il motore degli update vive **sull'host**, non nei container: la CLI
`/usr/local/bin/vps1777` (installata da installer/deploy.sh) è l'unico punto
che tocca immagini e stack. Il gateway resta **senza privilegi**: il pulsante
*Aggiorna* del pannello admin scrive solo un **intent file** in `onboarding/`
(validato: schema, semver, TTL, nonce anti-replay); una systemd **path unit**
(`vps1777-update.path` → `vps1777-update.service`) lo vede e lancia lo stesso
`vps1777 update`. Un timer giornaliero (`vps1777-check-update.timer`) fa il
check release + notifica Telegram al owner.

```
admin UI ──intent──► onboarding/update_pending_update.json
                        │  (systemd path unit, host)
                        ▼
   vps1777 update ──► backup age + snapshot locale
                  ──► pull + verifica digest (images.lock dal
                      bundle firmato cosign della GitHub Release)
                  ──► migrazioni ──► health-gate 180s
                  ──► ✅ ok  │  AUTO-ROLLBACK
```

Le immagini arrivano **solo da GHCR** (`compose.yaml` è pull-only; il build
locale esiste solo nell'overlay `compose.build.yaml`, dev/CI). Manuale utente
completo: [UPDATE.md](UPDATE.md).

## Healthcheck

Ogni servizio ha un healthcheck compose (usati anche dal health-gate dell'update):

| Servizio | Probe |
|---|---|
| gateway | `/health`; con `?deep=1` proba TCP gli upstream MCP (503 se giù) |
| archive-mcp / nb1777-mcp | TCP sulla porta MCP |
| nb1777-bot | long-poll, nessuna porta: file heartbeat `/tmp/nb1777-bot.heartbeat` (unhealthy se mtime > 90s) |

## OAuth flow

```
claude.ai                     gateway                    user browser
   │                            │                            │
   │ POST /register             │                            │
   │ (Dynamic Client Reg)       │                            │
   │ ◄──────────── client_id ───┤                            │
   │ POST /authorize ───────────┼──── 302 → /admin/login ───►│
   │                            │ ◄────── email+pwd ─────────│
   │                            │  bcrypt verify ↓           │
   │                            │  set admin_cookie          │
   │                            ├──── 302 → consent page ───►│
   │                            │ ◄────── approve ───────────│
   │                            │  emit access+refresh JWT   │
   │ ◄─── 302 + code ───────────┤                            │
   │ POST /token                │                            │
   │ ◄─── access + refresh ─────│                            │
   │ GET /<SECRET>/archive/mcp  │                            │
   │       Bearer <access> ─────►│                            │
   │       verify JWT typ=access │                            │
   │       proxy → archive-mcp:8002                          │
```

JWT typ è la chiave: `access_token` non funziona dove serve `admin_cookie` e viceversa. Vedi [SECURITY.md](../SECURITY.md).
