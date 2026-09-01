# vps1777

> 🇮🇹 **Italiano**: [README.it.md](README.it.md) — the project's native language is Italian
> (see [Language policy](#language-policy)); this README is its English translation,
> freshness-checked in CI like every page in [docs/en/](docs/en/).

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.12+-blue.svg)
![Docker](https://img.shields.io/badge/docker-compose%20v2-2496ED.svg)
![MCP](https://img.shields.io/badge/MCP-streamable--http-d97757.svg)
![Status](https://img.shields.io/badge/status-pre--1.0-orange.svg)

> **Your personal gateway for MCP servers, bots and LLM services** — behind a single
> public HTTPS URL, protected by OAuth 2.1 (full architecture in
> [docs/en/ARCHITECTURE.md](docs/en/ARCHITECTURE.md)), up on a Linux VPS in minutes
> without typing a command.

You connect **your** MCP servers (and Telegram bots) to [claude.ai](https://claude.ai),
Claude Code and the desktop app, from one secure endpoint. vps1777 puts a gateway in
front of your services — authentication, reverse proxy, admin panel, HTTPS ingress —
and grows with the plugins you add.

You install it from a **graphical UI** on your own PC (Windows / Mac / Linux): fill a
form, click **Install**, and at the end you get the HTTPS URL and the connectors ready
to paste into claude.ai. No Docker to manage by hand, no shell on the VPS.

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                  │
│   claude.ai ──┐                                                  │
│   Claude Code ├──► https://<host>/<SECRET>/<service>/mcp         │
│   Mini App ───┤        │   the Mini App enters via /app/*,       │
│   Telegram ───┘        │   not via the MCP path                  │
│                        ▼                                         │
│            ┌───────────────────┐                                 │
│            │  Tailscale Funnel │  (or Caddy, or Cloudflared)     │
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
│  archive-mcp     nb1777-mcp     ocr     your-plugin              │
│  (FTS5 multi-DB) (NotebookLM)        (any MCP/bot)               │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

## Why

Exposing an MCP server to claude.ai usually means dealing with TLS, a reverse proxy,
authentication, a domain, and keeping it all alive across reboots. vps1777 does that
work once, properly: an OAuth 2.1 gateway in front, a free HTTPS URL via Tailscale
Funnel (or Caddy/Cloudflare if you prefer), and every new service becomes one entry in
the routing. You think about your MCP; the rest is already here.

## Installation

All you need is a **fresh Linux VPS** (Debian 12 recommended — it's what the full
clean-machine acceptance test of 2026-08-27 ran on; on Debian 13 with encrypted
volumes the same VPS proved unstable, see `H56` in `security/findings.yml`) with an
IP and a root password. Three ways, same repo.

### 🖱 Graphical installer — zero commands (recommended)

On **your PC**:

| System | Launch |
|---|---|
| Windows | double-click `installer/launch.bat` |
| Linux / Mac / WSL | double-click `installer/launch.sh` |

A page opens in your browser (`127.0.0.1:8777`): fill the form, press **Verify
connection**, wait for green lights, click **Install**. Follow the live progress; at
the end you see the **public URL, the admin password and the connectors** to paste
into claude.ai. Details: [installer/README.md](installer/README.md) (Italian).

> **Truly cross-OS**: the engine is pure Python (paramiko over SSH) — it runs on
> **native Windows**, Mac and Linux, no bash, no WSL. Credentials never leave your PC
> (bound to `127.0.0.1`). The deploy **survives a page refresh**.

### 🚀 CLI — one command from your PC

```bash
git clone https://github.com/neo1777/vps1777.git && cd vps1777
./deploy.sh        # asks IP/user/password + config, does EVERYTHING over SSH
```

`deploy.sh` (Linux/Mac/WSL; password auth needs `sshpass`) prepares the VPS (Docker +
Compose v2 + hardening), transfers the repo, generates `.env` + secrets (random +
bcrypt), starts the stack, **installs Tailscale on the host and enables the HTTPS
Funnel**, reboots the VPS and verifies everything comes back at boot, then prints the
URL and the connectors.

### 🛠 Manual — on the VPS

```bash
git clone https://github.com/neo1777/vps1777.git && cd vps1777
./setup.sh                                          # interactive wizard
# if you answered "no" to "Proceed now?" (setup.sh already starts the stack, same -f):
docker compose -f compose.yaml -f compose.ingress.tailscale.yaml \
  --profile ingress.tailscale up -d                 # or caddy / cloudflared
```

For public HTTPS (Tailscale / Caddy / Cloudflare) and the prerequisites, see
[docs/INGRESS.md](docs/INGRESS.md) (Italian). To hook the connectors to claude.ai and
load the NotebookLM auth, [docs/en/INSTALL.md](docs/en/INSTALL.md).

## What's inside

| Service | What it does | Internal port |
|---|---|---|
| **gateway** | OAuth 2.1 + DCR + MCP reverse proxy + `/admin/*` panel + `/app/*` Mini App | 8080 |
| **archive-mcp** | FTS5 search across multiple DBs (claude.ai web exports, Claude Code sessions) | 8002 |
| **nb1777-mcp** | NotebookLM via the `nlm` CLI — **38 tools** (notebooks, sources, chat, 9 studio artifacts, doctor, canonico/memory). Also serves the **1777 memory canon** ([docs/en/MEMORIA-1777.md](docs/en/MEMORIA-1777.md)). See [docs/NB1777.md](docs/NB1777.md) (Italian) | 8003 |
| **nb1777-bot** | Owner-only Telegram bot + Mini App launcher | (long-poll) |
| **ocr** | Tesseract in an internal container: the ingest's eyes (images → `[ocr]` text). The gateway calls it over HTTP, it never spawns processes | 8004 |

Plus the **plugins** you add — an MCP server or a bot in a few files, without touching
the core. See [docs/PLUGINS.md](docs/PLUGINS.md) (Italian).

And the **Telegram Mini App** — the mobile bridge: opens from the bot (*Pannello*
button), no password (auth via Telegram identity, owner-only server-side). RAG
questions to your notebooks from your phone, archive search, copyable connector URLs,
secret expirations, one-tap update. See [docs/MINIAPP.md](docs/MINIAPP.md) (Italian).

## Updates

Images are **published to GHCR by the release CI** (cosign-signed, with SBOM): the VPS
only does `docker compose pull`, **never builds** (4GB constraint). To update:

```bash
vps1777 update      # backup → pull + digest verification → migrations → health gate
```

or one click from the **admin panel → Update tab**. When a release comes out the
Telegram bot notifies you; if the new version doesn't come up healthy, **automatic
rollback**. Full manual: [docs/en/UPDATE.md](docs/en/UPDATE.md).

And by default **it takes care of itself**: `vps1777-auto-update.timer` applies the
same safe update **once a week** — feature `autoupdate` in `VPS1777_FEATURES`, on by
default; to turn it off see [docs/OPS.md](docs/OPS.md) (Italian).

## Security by design

- Backend on an `internal: true` Docker network — **only the gateway** faces the outside
- The gateway has **no** access to the Docker socket or the host filesystem
  (unprivileged container), **nor to the Google cookies** of NotebookLM: among the
  running services, that volume is mounted only by `nb1777-mcp`, the one that uses
  them (the backup job also mounts it read-only to encrypt them, and the expiry check
  reads only their date — see [SECURITY.md](SECURITY.md)). It does see the **5 Docker
  secrets assigned to it** — including `telegram_bot_token`, the Mini App's root of
  trust ([docs/SECRETS.md](docs/SECRETS.md), Italian): a compromised gateway can read
  them, which is why its perimeter is the most defended
- Sensitive secrets (passwords, signing keys, tokens) via Docker `secrets:` (tmpfs
  `/run/secrets/`), **never** in env vars; the `GATEWAY_SECRET` is redacted from access logs
- OAuth 2.1 with PKCE + refresh; JWTs with separate `typ` (no cross-token use); bcrypt
  rounds=12; the proxy also verifies the token **audience**
- Mini App and bot are **owner-only fail-closed**: without `TELEGRAM_OWNER_ID` they deny
  everyone rather than open up
- Per-IP rate limiting on auth endpoints; `X-Forwarded-For` trusted **only** from the
  proxy (client IP can't be spoofed)
- Non-root containers (UID 1000 `app`), `cap_drop: ALL`, `no-new-privileges`,
  healthchecks on every service
- Automatic host hardening at install: `unattended-upgrades` + `fail2ban` (`H45`)
- Updates **cosign-signed** and verified **fail-closed by default**; immutable digests
  (`images.lock`); age-encrypted backups + snapshots + **automatic rollback**
  ([docs/en/UPDATE.md](docs/en/UPDATE.md))
- CI with GitHub Actions **pinned to SHAs** + Dependabot across actions, base images,
  compose images and Python dependencies; the backup key lives **off the VPS** (only
  the public recipient on the server)
- Optional visual management (Portainer) **loopback-only** + SSH tunnel — see
  [docs/OPS.md](docs/OPS.md) (Italian)

All of this went through a **wall-to-wall defensive review** (July 2026): the full
hardening record, the threat model, third-party data flows and the known residuals are
in [SECURITY.md](SECURITY.md) (English overview at the top).

## Engineering culture (why this repo is different)

You can judge the code by opening the files; these are the guarantees you can't see at
a glance:

- **The feature ledger** ([features.yaml](features.yaml)): every product feature is
  declared together with its *proof* (an MCP tool that answers, a file that contains,
  a wired-up CLI command), and CI checks the picture **in both directions** — a
  feature without proof, or a proof without a feature, is a red build.
- **The documentation is guarded by tests**: the CLI reference fails CI if a command
  lacks a section and an example; cross-references between docs go through a linter;
  English translations record the hash of their Italian source and CI flags them when
  the original moves ([docs/en/MANIFEST.json](docs/en/MANIFEST.json)).
- **Over 800 tests across six suites**, many of them *structural guards* — each one
  born from a real incident. The [CHANGELOG.md](CHANGELOG.md) tells every guard's
  story: what bit us, and how it became a test.
- **Signed releases and an update that knows how to retreat**: fail-closed cosign
  bundles, digest-pinned images, pre-update snapshots (n and n−1), a health gate and
  automatic rollback ([docs/en/UPDATE.md](docs/en/UPDATE.md)).
- **Actionable security**: weekly Trivy scans filtered to what actually has a fix, and
  a monthly workflow that rebuilds images when Debian fixes land — the Security tab
  shows what you can act on, not noise.
- **The 1777 memory discipline** ([docs/en/MEMORIA-1777.md](docs/en/MEMORIA-1777.md)):
  the product ships the rules by which an AI assistant judges its own memories,
  versioned and served by a tool — with the user's personal facts outside the repo,
  by construction.

## Documentation

English pages live in [docs/en/](docs/en/) and are kept honest by CI
(`tools/tests/test_traduzioni_fresche.py`): each records the hash of its Italian
source, and a moved original turns the build red until the translation catches up.

| Doc | English | Italian |
|---|---|---|
| Architecture: flows, contracts, security model | [docs/en/ARCHITECTURE.md](docs/en/ARCHITECTURE.md) | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Step-by-step install + post-install | [docs/en/INSTALL.md](docs/en/INSTALL.md) | [docs/INSTALL.md](docs/INSTALL.md) |
| Updates: `vps1777 update`, admin button, rollback | [docs/en/UPDATE.md](docs/en/UPDATE.md) | [docs/UPDATE.md](docs/UPDATE.md) |
| Age-encrypted backup & restore, two tiers | [docs/en/BACKUP-RESTORE.md](docs/en/BACKUP-RESTORE.md) | [docs/BACKUP-RESTORE.md](docs/BACKUP-RESTORE.md) |
| The `vps1777` CLI, every command with examples | [docs/en/CLI.md](docs/en/CLI.md) | [docs/CLI.md](docs/CLI.md) |
| The 1777 memory discipline (canon, local layers) | [docs/en/MEMORIA-1777.md](docs/en/MEMORIA-1777.md) | [docs/MEMORIA-1777.md](docs/MEMORIA-1777.md) |
| Public HTTPS: Tailscale Funnel / Caddy / Cloudflare | — | [docs/INGRESS.md](docs/INGRESS.md) |
| Adding your own MCP or bot | — | [docs/PLUGINS.md](docs/PLUGINS.md) |
| Secrets: management, rotation, backup | — | [docs/SECRETS.md](docs/SECRETS.md) |
| Hardening + optional profiles | — | [docs/OPS.md](docs/OPS.md) |
| Search archive: `/admin/archive`, formats, OCR ingest | — | [docs/ARCHIVE.md](docs/ARCHIVE.md) |
| NotebookLM: the 38 MCP tools, studio, auth, bot | — | [docs/NB1777.md](docs/NB1777.md) |
| Glossary: the project's words, two lines each | — | [docs/GLOSSARIO.md](docs/GLOSSARIO.md) |
| Telegram Mini App | — | [docs/MINIAPP.md](docs/MINIAPP.md) |
| Clean-machine acceptance test | — | [docs/COLLAUDO-VERGINE.md](docs/COLLAUDO-VERGINE.md) |
| Post-deploy onboarding panel | — | [docs/ONBOARDING.md](docs/ONBOARDING.md) |
| Troubleshooting | — | [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) |

## Local development

```bash
docker compose -f compose.yaml -f compose.build.yaml -f compose.dev.yaml up --watch
```

Hot reload via Compose Watch. `compose.yaml` references only published images (pull):
local builds exist only with the `compose.build.yaml` overlay (dev/CI, never in
production). Guidelines in [CONTRIBUTING.md](CONTRIBUTING.md); community pact in
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Language policy

This project is **documented in Italian by design** — engineering prose is part of the
craft here, and Italian is its native voice: code comments, tests, the CHANGELOG and
the deep docs speak it. English is provided where it matters most: this README,
[CONTRIBUTING.md](CONTRIBUTING.md), the security overview, and the key pages in
[docs/en/](docs/en/) — each one hash-pinned to its Italian source and checked by CI,
so an English page can never silently drift behind the original. For everything else,
any modern browser translates a page in one click; the tests and the ledger speak for
themselves in any language.

## Status

Pre-1.0: the core works and is **validated end-to-end on a real VPS** — cross-OS
installer (including **native Windows**) → Docker + Tailscale Funnel HTTPS →
reboot-survival → OAuth+MCP connector attached from claude.ai. News is tracked in the
[CHANGELOG.md](CHANGELOG.md) (Italian — it's the project's engineering diary).

## License

[MIT](LICENSE) © neo1777

---

*vps1777 is the second generation of the 1777 stack: after learning that bash +
python + sudo + service-users, all intertwined, explode in non-reproducible ways, here
Docker keeps everything clean and immutable. Built by
[neo1777](https://github.com/neo1777).*
