# vps1777

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.12+-blue.svg)
![Docker](https://img.shields.io/badge/docker-compose%20v2-2496ED.svg)
![MCP](https://img.shields.io/badge/MCP-streamable--http-d97757.svg)
![Status](https://img.shields.io/badge/status-pre--1.0-orange.svg)

> **Il tuo gateway personale per MCP, bot e servizi LLM** — dietro un solo URL
> HTTPS pubblico, protetto da OAuth 2.1, in piedi su una VPS Linux in pochi
> minuti e senza scrivere un comando.

Colleghi i **tuoi** server MCP (e bot Telegram) a [claude.ai](https://claude.ai),
Claude Code e all'app desktop, da un unico endpoint sicuro. vps1777 mette davanti
ai tuoi servizi un gateway con autenticazione, reverse proxy, pannello di
amministrazione e ingress HTTPS — e cresce con i plugin che ci aggiungi tu.

Lo installi da una **UI grafica** sul tuo PC (Windows / Mac / Linux): compili un
form, clicchi **Installa**, e alla fine hai l'URL HTTPS e i connector pronti da
incollare in claude.ai. Niente Docker da gestire a mano, niente shell sulla VPS.

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
│            ┌───────────────────┐    /admin/login · /admin/nlm    │
│            │     gateway       │    /admin/update · /admin/audit │
│            │  (OAuth 2.1 + DCR)│    /app/* (Mini App)            │
│            │     +/app/* UI    │                                 │
│            └─────────┬─────────┘                                 │
│                      ▼                                           │
│      ┌───────────────┼───────────────────────┐                   │
│      ▼               ▼                       ▼                   │
│  archive-mcp     nb1777-mcp             your-plugin              │
│  (FTS5 multi-DB) (NotebookLM)        (MCP/bot a piacere)         │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

## Perché

Esporre un MCP a claude.ai significa, di solito, mettere mano a TLS, reverse
proxy, autenticazione, un dominio, e tenere tutto in piedi al reboot. vps1777 fa
quel lavoro una volta sola, bene: un gateway OAuth 2.1 davanti, un URL HTTPS
gratuito via Tailscale Funnel (o Caddy/Cloudflare se preferisci), e ogni nuovo
servizio diventa una voce nel routing. Tu pensi al tuo MCP; il resto è già qui.

## Installazione

Ti serve solo una **VPS Linux fresh** (Debian 13 consigliata) con IP e password
root. Tre modi, dallo stesso repo.

### 🖱 Installer grafico — zero comandi (consigliato)

Sul **tuo PC**:

| Sistema | Avvio |
|---|---|
| Windows | doppio-click `installer/launch.bat` |
| Linux / Mac / WSL | doppio-click `installer/launch.sh` |

Si apre una pagina nel browser (`127.0.0.1:8777`): compili il form, premi
**Verifica connessione**, attendi i semafori verdi, clicchi **Installa**. Segui
l'avanzamento live; a fine installazione vedi **URL pubblico, password admin e i
connector** da incollare in claude.ai. Dettagli: [installer/README.md](installer/README.md).

> **Cross-OS vero**: l'engine è Python puro (paramiko via SSH) — gira su
> **Windows nativo**, Mac e Linux, senza bash né WSL. Le credenziali non lasciano
> il tuo PC (bind su `127.0.0.1`). Il deploy **sopravvive al refresh** della pagina.

### 🚀 CLI — un comando dal tuo PC

```bash
git clone https://github.com/neo1777/vps1777.git && cd vps1777
./deploy.sh        # chiede IP/user/password + config, fa TUTTO via SSH
```

`deploy.sh` (Linux/Mac/WSL; per auth password serve `sshpass`) prepara la VPS
(Docker + Compose v2 + hardening), trasferisce il repo, genera `.env` + secrets
(random + bcrypt), avvia lo stack, **installa Tailscale sull'host e attiva il
Funnel HTTPS**, riavvia la VPS e verifica che tutto riparta al boot, infine
stampa URL e connector.

### 🛠 Manuale — sulla VPS

```bash
git clone https://github.com/neo1777/vps1777.git && cd vps1777
./setup.sh                                          # wizard interattivo
docker compose --profile ingress.tailscale up -d    # o caddy / cloudflared
```

Per l'HTTPS pubblico (Tailscale / Caddy / Cloudflare) e i prerequisiti, vedi
[docs/INGRESS.md](docs/INGRESS.md). Per collegare i connector a claude.ai e
caricare l'auth NotebookLM, [docs/INSTALL.md](docs/INSTALL.md).

## Cosa include

| Servizio | Cosa fa | Porta interna |
|---|---|---|
| **gateway** | OAuth 2.1 + DCR + reverse proxy MCP + pannello `/admin/*` + Mini App `/app/*` | 8080 |
| **archive-mcp** | Ricerca FTS5 su più DB (export web claude.ai, sessioni Claude Code) | 8002 |
| **nb1777-mcp** | NotebookLM via CLI `nlm` — **35 tool** (notebook, source, chat, 9 artefatti studio, doctor) | 8003 |
| **nb1777-bot** | Bot Telegram owner-only + launcher Mini App | (long-poll) |

Più i **plugin** che ci aggiungi tu — un MCP o un bot in pochi file, senza
toccare il core. Vedi [docs/PLUGINS.md](docs/PLUGINS.md).

E la **Mini App Telegram** — la plancia mobile: si apre dal bot (bottone
*Pannello*), senza password (auth via identità Telegram, owner-only lato
server). Notebook con domande RAG dal telefono, ricerca nell'archivio, URL dei
connettori copiabili, scadenze secret, update a un tap. Vedi
[docs/MINIAPP.md](docs/MINIAPP.md).

## Aggiornamenti

Le immagini sono **pubblicate su GHCR dalla CI di release** (firmate cosign,
con SBOM): la VPS fa solo `docker compose pull`, **mai build** (vincolo 4GB).
Per aggiornare:

```bash
vps1777 update      # backup → pull + verifica digest → migrazioni → health-gate
```

oppure un click dal **pannello admin → tab Update**. Quando esce una release
il bot Telegram ti avvisa; se la nuova versione non torna in salute, **rollback
automatico**. Manuale completo: [docs/UPDATE.md](docs/UPDATE.md).

## Sicurezza per design

- Backend su rete Docker `internal: true` — **solo il gateway** è esposto verso l'esterno
- Il gateway **non** ha accesso al Docker socket né ai secret dell'host (container non privilegiato), **né ai cookie Google** di NotebookLM: quel volume lo monta solo `nb1777-mcp`, il servizio che li usa
- Secrets sensibili (password, signing key, token) via Docker `secrets:` (tmpfs `/run/secrets/`), **mai** in env var; il `GATEWAY_SECRET` è redatto dagli access-log
- OAuth 2.1 con PKCE + refresh; JWT con `typ` separati (no cross-token-use); bcrypt rounds=12; il proxy verifica anche l'**audience** del token
- Mini App e bot **owner-only fail-closed**: senza `TELEGRAM_OWNER_ID` negano tutti, non aprono
- Rate-limit per-IP sugli endpoint auth; `X-Forwarded-For` fidato **solo** dal proxy (IP client non falsificabile)
- Container non-root (UID 1000 `app`), `cap_drop: ALL`, `no-new-privileges`, healthcheck su ogni servizio
- Hardening host automatico all'install: `unattended-upgrades` + `fail2ban`
- Update firmati **cosign** e verificati **fail-closed di default**; digest immutabili (`images.lock`); backup age + snapshot + **rollback automatico** ([docs/UPDATE.md](docs/UPDATE.md))
- CI con GitHub Actions **pinnate a SHA** + Dependabot; chiave di backup **fuori dalla VPS** (solo il recipient pubblico sul server)
- Gestione visuale opzionale (Portainer) **solo su loopback** + tunnel SSH — vedi [docs/OPS.md](docs/OPS.md)

Tutto questo è passato per una **review difensiva a tappeto** (luglio 2026): la rassegna completa dell'hardening applicato, il threat model, i flussi di dati verso terzi e i residui noti sono in [SECURITY.md](SECURITY.md).

## Documentazione

| Doc | Cosa trovi |
|---|---|
| [INSTALL.md](docs/INSTALL.md) | Installazione passo-passo + post-install (connector, NotebookLM) |
| [INGRESS.md](docs/INGRESS.md) | HTTPS pubblico: Tailscale Funnel / Caddy / Cloudflare |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Flussi, contratti, security model |
| [PLUGINS.md](docs/PLUGINS.md) | Aggiungere un tuo MCP o bot |
| [SECRETS.md](docs/SECRETS.md) | Gestione, rotation e backup dei secret |
| [OPS.md](docs/OPS.md) | Hardening + profili opzionali (Portainer, Watchtower, backup) |
| [UPDATE.md](docs/UPDATE.md) | Aggiornamenti: `vps1777 update`, pulsante admin, rollback |
| [ARCHIVE.md](docs/ARCHIVE.md) | Archivio di ricerca: pagina `/admin/archive`, formati, ingest via NotebookLM |
| [MINIAPP.md](docs/MINIAPP.md) | Mini App Telegram: la plancia mobile — auth initData, endpoint, sicurezza |
| [BACKUP-RESTORE.md](docs/BACKUP-RESTORE.md) | Backup/restore volumi age-encrypted |
| [ONBOARDING.md](docs/ONBOARDING.md) | Setup post-deploy dal pannello web |
| [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Quando qualcosa va storto |

## Sviluppo locale

```bash
docker compose -f compose.yaml -f compose.build.yaml -f compose.dev.yaml up --watch
```

Hot-reload via Compose Watch. `compose.yaml` referenzia solo immagini
pubblicate (pull): il build locale esiste solo con l'overlay
`compose.build.yaml` (dev/CI, mai in produzione). Linee guida in [CONTRIBUTING.md](CONTRIBUTING.md);
patti della comunità in [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Stato

Pre-1.0: il cuore è funzionante e **validato end-to-end su VPS reale** —
installer cross-OS (incluso **Windows nativo**) → Docker + Tailscale Funnel
HTTPS → reboot-survival → connector OAuth+MCP agganciato da claude.ai. Le
novità sono tracciate nel [CHANGELOG.md](CHANGELOG.md).

## License

[MIT](LICENSE) © neo1777

---

*vps1777 è la seconda generazione dello stack 1777: dopo aver imparato che bash +
python + sudo + service-user intrecciati esplodono in modo non riproducibile, qui
è Docker a tenere tutto pulito e immutabile. Costruito da [neo1777](https://github.com/neo1777).*
