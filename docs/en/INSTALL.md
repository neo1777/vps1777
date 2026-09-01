# Installation — vps1777

> English translation of [`docs/INSTALL.md`](../INSTALL.md). Translations are freshness-checked in CI against the Italian source (see [`MANIFEST.json`](MANIFEST.json)): if this note is red in CI, the Italian moved first.

> **The simplest path is the graphical installer** (cross-OS, zero commands): double-click
> `installer/launch.bat` (Windows) or `installer/launch.sh` (Linux/Mac/WSL), fill in
> a form and click **Installa**. See [installer/README.md](../../installer/README.md) (Italian).
> This document describes the **manual/advanced** path, for those who want to install
> by hand on the VPS or understand every step.

Step-by-step sequence from an empty host to a running stack.

## Prerequisites

| What | Version | Notes |
|---|---|---|
| Linux x86_64/arm64 | any recent | Debian 12 recommended (full shakedown on a virgin machine, 27/08/2026 — on Debian 13 with encrypted volumes the VPS was unstable, entry `H56`) / Ubuntu 24+ / Fedora / Arch |
| Docker Engine | 24+ | with the `docker compose` plugin v2 |
| python3 **+ pip** | 3.10+ | only for `setup.sh` (computes bcrypt). On Debian/Ubuntu `python3` and `python3-pip` are **two packages**: `sudo apt install python3-pip`. If `bcrypt` is already there, pip is not needed — the preflight checks the capability, not the name |
| Tailscale account **or** Caddy+domain **or** Cloudflare | one of the three | chosen at setup |
| Telegram bot + OWNER_ID | from [@BotFather](https://t.me/BotFather) + [@userinfobot](https://t.me/userinfobot) | optional for dev, mandatory for prod |
| Google account with NotebookLM | free | login happens **after the install** via `/admin/nlm` |

## 4 steps

```bash
git clone https://github.com/neo1777/vps1777.git
cd vps1777
./setup.sh                                      # wizard interattivo
# solo se hai risposto «no» a «Procedo ora?» — setup.sh avvia già, con gli stessi -f:
docker compose -f compose.yaml -f compose.ingress.tailscale.yaml \
  --profile ingress.tailscale up -d             # o caddy / cloudflared
```

The final stage prints the URLs for you.

## What `setup.sh` does

1. Checks Docker + Compose v2 + python3
2. Creates `.env` (asks for: admin email, TG_OWNER_ID, ingress)
3. Generates `secrets/*.txt`:
   - `gateway_secret.txt` (32 url-safe characters = 24 bytes of entropy)
   - `archive_desc_secret.txt` (32 url-safe characters = 24 bytes of entropy)
   - `oauth_signing_secret.txt` (64 url-safe characters = 48 bytes of entropy)
   - `admin_password_bcrypt.txt` (bcrypt rounds=12 of the password you choose/it generates)
   - `telegram_bot_token.txt` (you paste the token)
4. Runs `docker compose -f compose.yaml -f compose.ingress.<scelta>.yaml --profile
   ingress.<scelta> up -d` — the `-f` flags are not decorative: without them, the ingress
   overlay is not mounted (the `gateway` is left with no `ports:` and the `funnel` network
   is missing) — the images are **pulled from GHCR** (`compose.yaml` is pull-only: on the
   VPS nothing ever gets built; the local build is dev-only, with the
   `compose.build.yaml` overlay)

If you re-run `setup.sh`, it skips the steps already done.

## Post-install

1. **Admin login**: `<PUBLIC_BASE>/admin/login` → admin email + password
2. **NotebookLM auth**: on YOUR PC install the `nlm` CLI, log in, then upload the **profile** (tar.gz) to `<PUBLIC_BASE>/admin/nlm`. The `nlm` CLI 0.7.x saves the auth as a `profiles/default/` folder (no longer a single `auth.json`):
   ```bash
   uv tool install notebooklm-mcp-cli --python 3.12      # serve uv (astral.sh)
   nlm login                                             # apre il browser → login NotebookLM
   cd ~/.notebooklm-mcp-cli && tar czf nlm-profile.tgz profiles/default
   ```
   Upload `nlm-profile.tgz` to `<PUBLIC_BASE>/admin/nlm` (admin login). The gateway extracts it onto the volume; `nb1777-mcp` picks it up on the next call.
   If `nlm` comes up "not found": `uv tool update-shell` (puts `~/.local/bin` in the PATH) and reopen the terminal.
3. **claude.ai connector**: Settings → Integrations → Add → paste the URL `<PUBLIC_BASE>/<SECRET>/archive/mcp` (and `/nb1777/mcp`). Authorize → admin login. `archive` exposes the archive search tools (list and details in [ARCHIVE.md](../ARCHIVE.md) (Italian)), `nb1777` exposes **37** of them ([NB1777.md](../NB1777.md) (Italian)). Connectors **persist** across gateway restarts (DCR saved to disk).
4. **Telegram bot**: `/start` to your bot
5. **Mini App**: in the bot, the **Pannello** button next to the text field (or
   `/pannello`) → the mobile control deck: notebooks, archive, secrets, update.
   Requires an https `PUBLIC_BASE`. See [MINIAPP.md](../MINIAPP.md) (Italian).

## Optional ops

Baseline hardening (automatic: `unattended-upgrades` + `fail2ban`) and optional
profiles — Portainer (visual dashboard), Watchtower (demoted), backup —
are documented in [OPS.md](../OPS.md) (Italian).

## Updating

Primary channel: the host CLI **`vps1777 update`** (installed by `deploy.sh`,
in the repo root) or the button in the **admin panel → Update tab** —
automatic backup first, pull with digest verification, migrations, health-gate,
automatic rollback if the new version does not come back healthy. Full
manual: [UPDATE.md](UPDATE.md).

Watchtower (profile `ops.autoupdate`) is **demoted**: it remains opt-in but is not
supported alongside the managed channel (it bypasses backup, migrations,
health-gate and rollback) — see [OPS.md](../OPS.md) (Italian).

## Uninstalling

```bash
# `--remove-orphans` non è opzionale: il container dell'ingress sta in un overlay, non
# è nel modello che `down` costruisce da solo, e senza RESTA ACCESO. Si usa questo e non
# gli `-f` perché qui non sappiamo quale ingress hai scelto — e una riga che deve
# indovinarlo è sbagliata per chi ha scelto l'altro.
docker compose down -v --remove-orphans               # -v cancella i volumi
rm -rf secrets/                                       # cancella i secret
```
