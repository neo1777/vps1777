# vps1777

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.12+-blue.svg)
![Docker](https://img.shields.io/badge/docker-compose%20v2-2496ED.svg)
![MCP](https://img.shields.io/badge/MCP-streamable--http-d97757.svg)
![Status](https://img.shields.io/badge/status-pre--1.0-orange.svg)

> Gateway personale per **i tuoi MCP, bot, e servizi LLM**, dietro un solo URL HTTPS pubblico, protetto da OAuth 2.1.
> Pensato per girare su una VPS Linux, con Docker, e crescere via plugin.

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                  │
│   claude.ai ──┐                                                  │
│   Claude Code ├──► https://<host>/<SECRET>/<service>/mcp         │
│   Mini App ───┤        │                                         │
│   Telegram ───┘        │                                         │
│                        ▼                                         │
│            ┌───────────────────┐                                 │
│            │  Tailscale Funnel │  (o Caddy, o Cloudflared)       │
│            └─────────┬─────────┘                                 │
│                      ▼                                           │
│            ┌───────────────────┐    /admin/login                 │
│            │     gateway       │    /admin/secrets               │
│            │  (OAuth 2.1 + DCR)│    /admin/nlm                   │
│            │     +/app/* UI    │    /app/* (Mini App)            │
│            └─────────┬─────────┘                                 │
│                      ▼                                           │
│      ┌───────────────┼───────────────────────┐                   │
│      ▼               ▼                       ▼                   │
│  archive-mcp     nb1777-mcp             your-plugin              │
│  (FTS5 multi-DB) (NotebookLM)        (MCP/bot a piacere)         │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

## 🚀 Install one-click (dal tuo PC)

Hai una VPS Linux fresh (solo IP + password root)? Dal tuo PC:

```bash
# 1. Ottieni il repo (clone o scompatta il tarball)
git clone https://github.com/<owner>/vps1777.git && cd vps1777

# 2. Lancia il deploy: chiede IP/user/password + config, fa TUTTO via SSH
./deploy.sh
```

`deploy.sh` (dal tuo PC, serve `sshpass` per auth password):
1. Chiede IP, user, password VPS + config (email admin, OWNER_ID, ingress)
2. Installa Docker + Compose v2, crea utente `operator`
3. Trasferisce il repo via SSH
4. Genera `.env` + secrets (random + bcrypt) sulla VPS
5. `docker compose up -d --build`
6. **Riavvia la VPS e verifica che i container ripartano da soli**
7. Stampa gli URL finali

Niente da fare a mano sulla VPS. Vedi [docs/INSTALL.md](docs/INSTALL.md) per dettagli + metodo manuale.

## 🛠 Install manuale (sulla VPS)

Se preferisci controllare ogni passo, oppure sei già sulla VPS:

```bash
git clone https://github.com/<owner>/vps1777.git && cd vps1777
./setup.sh                                          # wizard interattivo
docker compose --profile ingress.tailscale up -d    # o caddy / cloudflared
```

## 🧩 Cosa include

| Servizio | Cosa fa | Porta interna |
|---|---|---|
| **gateway** | OAuth 2.1 + DCR + reverse proxy MCP + pannello `/admin/*` + Mini App `/app/*` | 8080 |
| **archive-mcp** | Search FTS5 multi-DB (claude.ai web export, Claude Code sessions) | 8002 |
| **nb1777-mcp** | NotebookLM via CLI `nlm` (60+ tool: list, query, 9 artefatti) | 8003 |
| **nb1777-bot** | Bot Telegram owner-only + Mini App | (long-poll) |

Più tutti i **plugin** che ci aggiungerai dopo (vedi [docs/PLUGINS.md](docs/PLUGINS.md)).

## 🛡 Sicurezza per design

- Backend su rete Docker `internal: true` — solo il gateway è esposto verso fuori
- Secrets via Docker `secrets:` (tmpfs `/run/secrets/`), MAI in env var
- OAuth 2.1 con PKCE + refresh, JWT con `typ` separati (no cross-token-use)
- Container non-root (UID 65532), `cap_drop: ALL`, `read_only: true`, healthcheck obbligatorio
- Hardening: backup age-encrypted, rotate secrets senza downtime, auto-update via Watchtower

## 📖 Documentazione

- [INSTALL.md](docs/INSTALL.md) — installazione passo-passo + scelta ingress
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) — flussi, contratti, security model
- [PLUGINS.md](docs/PLUGINS.md) — aggiungere un MCP o un bot tuo
- [SECRETS.md](docs/SECRETS.md) — gestione/rotation/backup secrets
- [BACKUP-RESTORE.md](docs/BACKUP-RESTORE.md) — backup volumi age-encrypted
- [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) — quando qualcosa va male

## 🛠 Sviluppo locale

```bash
docker compose -f compose.yaml -f compose.dev.yaml up --watch
```

Hot-reload via Compose Watch. Vedi [CONTRIBUTING.md](CONTRIBUTING.md).

## 📜 License

MIT — vedi [LICENSE](LICENSE).

---

*vps1777 nasce dalla seconda generazione dello stack 1777, dopo aver capito che bash + python + sudo + service user erano troppe cose intrecciate. Docker pulisce tutto.*
