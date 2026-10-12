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
| RAM / disk | 4 GB / ~2 GB free | the project is sized for a 4 GB VPS; the images take ~2 GB |
| `curl`, `sudo` | — | `setup.sh` asks GitHub for the latest release with `curl`; run it as a normal user with `sudo`, not as root (see step 5 below) |
| Tailscale account **or** Caddy+domain **or** Cloudflare | one of the three | chosen at setup. With **Caddy**, ports 80 and 443 must be open inbound. With **Cloudflare**, **before** `./setup.sh` create the tunnel on the dashboard (one.dash.cloudflare.com → Networks → Tunnels): `setup.sh` asks for the public hostname and the token (without showing it, it saves it to `secrets/cloudflared_token.txt` with mode 600). If you leave the token empty the stack starts without the tunnel, and `setup.sh` tells you at the end how to add it. With **Tailscale** see [below](#if-you-chose-tailscale-you-turn-on-the-funnel) |
| Telegram bot + OWNER_ID | from [@BotFather](https://t.me/BotFather) + [@userinfobot](https://t.me/userinfobot) | optional for dev, mandatory for prod |
| Google account with NotebookLM | free | login happens **after the install** via `/admin/nlm` |

## 4 steps

```bash
git clone https://github.com/neo1777/vps1777.git
cd vps1777
./setup.sh                                      # interactive wizard
# only if you answered "no" to "Procedo ora?": run the command setup.sh printed for you
# (it also carries the feature overlays). With Tailscale and the default features:
docker compose -f compose.yaml -f compose.ingress.tailscale.yaml -f compose.ops.backup.yaml \
  --profile ingress.tailscale --profile ops.backup pull
docker compose -f compose.yaml -f compose.ingress.tailscale.yaml -f compose.ops.backup.yaml \
  --profile ingress.tailscale --profile ops.backup up -d      # or caddy / cloudflared
```

The final stage prints the URLs for you. With Tailscale, until you turn on the Funnel,
you get the `<PUBLIC_BASE>` placeholder instead of the URL: see
[below](#if-you-chose-tailscale-you-turn-on-the-funnel).

If you answer "no" to "Procedo ora?", `setup.sh` also skips step 5 below (`vps1777`
CLI, systemd units, hardening): starting the stack by hand does not bring them back.
To get them, re-run `./setup.sh` and answer "yes": the steps already done are skipped.

## What `setup.sh` does

1. Checks Docker + Compose v2 + python3
2. Creates `.env` (asks for: admin email, TG_OWNER_ID, ingress; with Caddy the domain,
   with Cloudflare the tunnel's public hostname)
3. Generates `secrets/*.txt`:
   - `gateway_secret.txt` (32 url-safe characters = 24 bytes of entropy)
   - `archive_desc_secret.txt` (32 url-safe characters = 24 bytes of entropy)
   - `oauth_signing_secret.txt` (64 url-safe characters = 48 bytes of entropy)
   - `admin_password_bcrypt.txt` (bcrypt rounds=12 of the password you choose/it generates)
   - `telegram_bot_token.txt` (you paste the token, which is not shown; empty = bot on
     standby, to be activated later with `./tools/rotate-secret.sh telegram_bot_token`)
   - `cloudflared_token.txt`, only with Cloudflare (you paste the tunnel token, which is
     not shown; empty = the stack starts without the tunnel, and re-running `./setup.sh`
     asks for it again)
   - `telegram_webapp_secret.txt` — the key **derived** from the token
     (HMAC-SHA256 keyed with `WebAppData`), the only one the gateway mounts: it is
     regenerated on every run, so it follows the token if that changes (empty if the
     token is empty)
4. Runs `docker compose -f compose.yaml -f compose.ingress.<scelta>.yaml --profile
   ingress.<scelta> up -d`, plus the overlay and profile of every feature declared in
   `VPS1777_FEATURES` (by default `backup`: `-f compose.ops.backup.yaml --profile ops.backup`;
   `portainer` the same way; `caddy-dns01` only adds the `compose.ops.caddy-dns01.yaml`
   overlay, and only with the Caddy ingress and a non-empty `secrets/cf_api_token.txt`,
   otherwise it warns and Caddy starts with HTTP-01; see [OPS.md](../OPS.md) (Italian)) — the `-f` flags are not decorative: without them, the ingress
   overlay is not mounted (the `gateway` is left with no `ports:` and the `funnel` network
   is missing) — the images are **pulled from GHCR** (`compose.yaml` is pull-only: on the
   VPS nothing ever gets built; the local build is dev-only, with the
   `compose.build.yaml` overlay)
5. If you answered "yes" to "Procedo ora?", **with `sudo`** (it asks for the password):
   installs the `vps1777` CLI in `/usr/local/bin`; installs **all** the
   `systemd/vps1777-*` units in `/etc/systemd/system` and **enables** four of them —
   `vps1777-check-update.timer`, `vps1777-update.path`, `vps1777-secrets-check.timer`,
   `vps1777-ingest.path` (the indexing queue of the Archive page)
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

## If you chose Tailscale: you turn on the Funnel

`setup.sh` does not install Tailscale and does not turn on the Funnel: only the
graphical installer and `deploy.sh` do. Without this step the panel answers only on the
VPS's `127.0.0.1:8080` and `<PUBLIC_BASE>` stays a placeholder. At the end `setup.sh`
prints these same commands, with your compose command.

First prepare the account as in [INGRESS.md](../INGRESS.md) (Italian) §1 (MagicDNS,
HTTPS Certificates, `nodeAttr funnel` in the ACL), then on the VPS:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --hostname=vps1777 --accept-dns=false   # or --authkey=file:<file holding the tskey-auth-…>
sudo tailscale serve reset && sudo tailscale funnel --bg --https=443 http://127.0.0.1:8080
tailscale status --json | python3 -c 'import sys,json;print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))'
```

The Funnel is turned on in a single command: `tailscale serve --https=443 …` followed by
`tailscale funnel 443` makes it answer 502.

Write the URL you get into `.env` (`PUBLIC_BASE=https://<name>.<tailnet>.ts.net`) and
recreate the services that read it (the gateway, `nb1777-mcp` and `nb1777-bot`) with the
same `-f` and `--profile` flags `setup.sh` printed, for example with the default features:

```bash
docker compose -f compose.yaml -f compose.ingress.tailscale.yaml -f compose.ops.backup.yaml \
  --profile ingress.tailscale --profile ops.backup up -d gateway nb1777-mcp nb1777-bot
```

## Post-install

1. **Admin login**: `<PUBLIC_BASE>/admin/login` → admin email + password
2. **NotebookLM auth**: on YOUR PC install the `nlm` CLI, log in, then upload the **profile** (tar.gz) to `<PUBLIC_BASE>/admin/nlm`. The `nlm` CLI (0.7 and later) saves the auth as a `profiles/default/` folder (no longer a single `auth.json`):
   ```bash
   uv tool install notebooklm-mcp-cli==0.15.4 --python 3.12   # needs uv (astral.sh)
   nlm login                                             # opens the browser → NotebookLM login
   # if it asks "Protected or plain file?" choose the FILE: the VPS cannot open the encrypted login
   cd ~/.notebooklm-mcp-cli && tar czf nlm-profile.tgz profiles/default
   ```
   The version is the one the server runs with (`services/nb1777-mcp/pyproject.toml`): a different CLI may save the profile in another shape. Upload `nlm-profile.tgz` to `<PUBLIC_BASE>/admin/nlm` (admin login). The gateway forwards it to `nb1777-mcp` over the internal channel (the gateway doesn't mount the cookies), which extracts it onto its volume and uses it from the next call.
   If `nlm` comes up "not found": `uv tool update-shell` (puts `~/.local/bin` in the PATH) and reopen the terminal.
3. **claude.ai connector**: Settings → Connectors → Add custom connector → paste the URL `<PUBLIC_BASE>/<SECRET>/archive/mcp` (and `/nb1777/mcp`); `<SECRET>` is the content of `secrets/gateway_secret.txt` (`cat secrets/gateway_secret.txt`). Authorize → admin login. `archive` exposes the archive search tools (list and details in [ARCHIVE.md](ARCHIVE.md)), `nb1777` exposes **55** of them ([NB1777.md](../NB1777.md) (Italian)). Connectors **persist** across gateway restarts (DCR saved to disk).
4. **Telegram bot**: `/start` to your bot
5. **Mini App**: in the bot, the **Pannello** button next to the text field (or
   `/start`) → the mobile control deck: notebooks, archive, secrets, update.
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

First turn off the systemd units and remove the CLI that `setup.sh` installed, otherwise
the auto-update and the other timers keep running on a dismantled installation:

```bash
for u in /etc/systemd/system/vps1777-*; do sudo systemctl disable --now "$(basename "$u")"; done
sudo rm -f /etc/systemd/system/vps1777-* /usr/local/bin/vps1777 && sudo systemctl daemon-reload
```

(`fail2ban` and `unattended-upgrades` stay: remove them like any other package.) Then:

```bash
# `--remove-orphans` is not optional: the ingress container lives in an overlay, it is
# not in the model `down` builds on its own, and without it IT STAYS UP. We use this and
# not the `-f` flags because here we don't know which ingress you chose — and a line that
# has to guess is wrong for whoever picked the other one.
docker compose down -v --remove-orphans               # -v deletes the volumes
rm -rf secrets/                                       # deletes the secrets
```
