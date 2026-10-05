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
| Linux x86_64 (amd64) | any recent | Release images are published **for amd64 only**: on arm64 (Raspberry Pi, Ampere VPSes) the pull finds no image for the architecture. Debian 12 recommended (full shakedown on a virgin machine, 27/08/2026 — on Debian 13 with encrypted volumes the VPS was unstable, entry `H56`) / Ubuntu 24+ / Fedora / Arch |
| Docker Engine | 24+ | with the `docker compose` plugin v2 |
| python3 **+ bcrypt** | 3.10+ | only for `setup.sh` (computes the admin password hash). On Debian/Ubuntu `python3` is a package of its own: `sudo apt install python3 python3-bcrypt`. ⚠️ **`python3-pip` is NOT enough on Debian 12+ / Ubuntu 23.04+** — that is, on the very distro we recommend: there pip is already present and it is the *installation* that is forbidden (PEP 668), so `pip install bcrypt` fails. The right package is `python3-bcrypt` (Fedora: `sudo dnf install python3-bcrypt`). If `bcrypt` is already there, nothing else is needed — the preflight checks the capability, not the name |
| Tailscale account **or** Caddy+domain **or** Cloudflare | one of the three | chosen at setup |
| Telegram bot + OWNER_ID | from [@BotFather](https://t.me/BotFather) + [@userinfobot](https://t.me/userinfobot) | optional for dev, mandatory for prod |
| Google account with NotebookLM | free | login happens **after the install** via `/admin/nlm` |

## 4 steps

```bash
git clone https://github.com/neo1777/vps1777.git
cd vps1777
./setup.sh                                      # interactive wizard
# only if you answered "no" to "Procedo ora?" — setup.sh already starts it, same -f:
docker compose -f compose.yaml -f compose.ingress.tailscale.yaml \
  --profile ingress.tailscale up -d             # or caddy / cloudflared
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
   - `telegram_webapp_secret.txt` — the key **derived** from the token
     (HMAC-SHA256 keyed with `WebAppData`), the only one the gateway mounts: it is
     regenerated on every run, so it follows the token if that changes (empty if the
     token is empty)
4. Runs `docker compose -f compose.yaml -f compose.ingress.<scelta>.yaml --profile
   ingress.<scelta> up -d`, plus the overlay and profile of every feature declared in
   `VPS1777_FEATURES` (by default `backup`: `-f compose.ops.backup.yaml --profile ops.backup`;
   `portainer` and `caddy-dns01` the same way, see [OPS.md](../OPS.md) (Italian)) — the `-f` flags are not decorative: without them, the ingress
   overlay is not mounted (the `gateway` is left with no `ports:` and the `funnel` network
   is missing) — the images are **pulled from GHCR** (`compose.yaml` is pull-only: on the
   VPS nothing ever gets built; the local build is dev-only, with the
   `compose.build.yaml` overlay)
5. If you answered "yes" to "Procedo ora?", **with `sudo`** (it asks for the password):
   installs the `vps1777` CLI in `/usr/local/bin`; installs **all** the
   `systemd/vps1777-*` units in `/etc/systemd/system` and **enables** three of them —
   `vps1777-check-update.timer`, `vps1777-update.path`, `vps1777-secrets-check.timer`
   — plus `vps1777-auto-update.timer` if `autoupdate` is in `VPS1777_FEATURES` (it is
   by default); applies the **host hardening**: `apt-get install` of
   `unattended-upgrades` and `fail2ban`, with `/etc/apt/apt.conf.d/20auto-upgrades` and
   an `sshd` jail in `/etc/fail2ban/jail.local` (if those files already exist with
   different contents it leaves them alone, and says so; without `apt-get` it warns and
   skips). The units run as the user who launches the script: if that is `root`
   (`sudo ./setup.sh`) it stops here, because the automatic updater would get the
   machine's full privileges (`H55`) — run it as the operator, or tell it who that is
   with `OPERATOR_USER=<user>`
6. Prints, as its last line, the command to verify the installation **from outside**,
   from your PC: `./tools/collaudo-da-fuori.sh <public-url>`

If you re-run `setup.sh`, it skips the steps already done.

## Post-install

1. **Admin login**: `<PUBLIC_BASE>/admin/login` → admin email + password
2. **NotebookLM auth**: on YOUR PC install the `nlm` CLI, log in, then upload the **profile** (tar.gz) to `<PUBLIC_BASE>/admin/nlm`. The `nlm` CLI (0.7 and later) saves the auth as a `profiles/default/` folder (no longer a single `auth.json`):
   ```bash
   uv tool install notebooklm-mcp-cli==0.12.0 --python 3.12   # needs uv (astral.sh)
   nlm login                                             # opens the browser → NotebookLM login
   cd ~/.notebooklm-mcp-cli && tar czf nlm-profile.tgz profiles/default
   ```
   The version is the one the server runs with (`services/nb1777-mcp/pyproject.toml`): a different CLI may save the profile in another shape. Upload `nlm-profile.tgz` to `<PUBLIC_BASE>/admin/nlm` (admin login). The gateway forwards it to `nb1777-mcp` over the internal channel (the gateway doesn't mount the cookies), which extracts it onto its volume and uses it from the next call.
   If `nlm` comes up "not found": `uv tool update-shell` (puts `~/.local/bin` in the PATH) and reopen the terminal.
3. **claude.ai connector**: Settings → Integrations → Add → paste the URL `<PUBLIC_BASE>/<SECRET>/archive/mcp` (and `/nb1777/mcp`). Authorize → admin login. `archive` exposes the archive search tools (list and details in [ARCHIVE.md](ARCHIVE.md)), `nb1777` exposes **40** of them ([NB1777.md](../NB1777.md) (Italian)). Connectors **persist** across gateway restarts (DCR saved to disk).
4. **Telegram bot**: `/start` to your bot
5. **Mini App**: in the bot, the **Pannello** button next to the text field (or
   `/pannello`) → the mobile control deck: notebooks, archive, secrets, update.
   Requires an https `PUBLIC_BASE`. See [MINIAPP.md](../MINIAPP.md) (Italian).
6. **Search by meaning** (optional): `search_ibrida` finds what you remember the
   meaning of and not the word. It needs the model (`vps1777 indice-modello`, which
   downloads and verifies it by itself) and one index per DB, built on the PC: ~7
   hours per 100,000 vectors on a 4-core PC. Until they are there, `search` works as
   before and `search_ibrida` says what is missing. Steps:
   [RICERCA-IBRIDA.md](RICERCA-IBRIDA.md), "Turning on search by meaning".

## Optional ops

Baseline hardening (automatic: `unattended-upgrades` + `fail2ban`) and optional
profiles — Portainer (visual dashboard), backup — are documented in
[OPS.md](../OPS.md) (Italian).

## Updating

Primary channel: the host CLI **`vps1777 update`** (installed by `setup.sh`,
`deploy.sh` and the graphical installer) or the button in the **admin panel → Update tab** —
automatic backup first, pull with digest verification, migrations, health-gate,
automatic rollback if the new version does not come back healthy. Full
manual: [UPDATE.md](UPDATE.md).

Watchtower (profile `ops.autoupdate`) was **removed in 0.67.0**: it bypassed
backup, migrations, health-gate and rollback, and its image is archived upstream.
Automatic updating is the `autoupdate` feature, on by default. If you had it on,
`vps1777 update` removes its container — see [OPS.md](../OPS.md) (Italian).

## Uninstalling

```bash
# `--remove-orphans` is not optional: the ingress container lives in an overlay, it is
# not in the model `down` builds on its own, and without it IT STAYS UP. We use this and
# not the `-f` flags because here we don't know which ingress you chose — and a line that
# has to guess is wrong for whoever picked the other one.
docker compose down -v --remove-orphans               # -v deletes the volumes
rm -rf secrets/                                       # deletes the secrets
```
