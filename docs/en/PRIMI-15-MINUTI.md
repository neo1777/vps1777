# First 15 minutes — vps1777 on your PC, without renting a VPS

> **The fourth way.** The three installations in the [README](../../README.md) all ask for
> the same thing: a real Linux VPS, with an IP and a root password. Before you spend,
> this page shows you the product **running**, on your machine, in a few minutes
> — and tells you, plainly, **what you will not be able to see locally**.

Every command on this page was run on a clean environment on **2026-09-07**
(bare Debian 12 container, Docker 29.8.0, non-root user with uid 1000), and the times
below are the ones **measured there**. Where your result may differ, it says so.

---

## In two lines: what you get and what you don't

| ✅ Locally you see | ❌ Locally you do NOT see |
|---|---|
| The **5 services** of the stack up and `healthy`, plus the `backup` container (a feature on by default) | The **public HTTPS ingress** (Tailscale Funnel / Caddy / Cloudflare) |
| The **admin panel** and its nine tabs (Setup, Salute, NotebookLM, Archive, Update, Secrets, Connettori, Temi, Audit) | The **connectors on claude.ai**: to attach them, claude.ai must reach you from the Internet |
| The **two MCP endpoints** answering `401` (they are there, and they ask for authentication) | The **Telegram bot** (it needs a token from @BotFather) |
| That a wrong secret gives `404` and not `401` (it does not confirm the path) | **NotebookLM** (it needs the `profiles/default/` profile of the `nlm` CLI, uploaded as a tar.gz from `/admin/nlm`) |

🔑 **The difference in one sentence**: locally you assemble and start the **engine**; the
README's **promise** — *one public HTTPS URL to paste into claude.ai* — is the ingress,
and the ingress needs a machine reachable from the Internet. It is not a detail we hide
to get you to try: it is the piece that costs a VPS.

## You need

- **Linux** with **Docker Engine + Compose v2** (`docker compose version` must answer).
- **~2 GB** of disk for the images (measured: `2.001GB` with the stack up; the download is
  less, they are compressed) and a connection: 5 images are pulled from GHCR, plus `alpine`
  from Docker Hub for the backup container.
- **Your normal user, not `root`.** This is not a style recommendation: the containers
  run as **uid 1000**, and if you install as root the secrets are born `root:root 600` and
  the gateway cannot read them (the stack stays in `Restarting`). The first user of a
  desktop Linux *is* uid 1000, so as a normal user the problem does not exist. If your
  uid is different, the cure is at the bottom of this page.

---

## The five steps

### 1 · Prerequisites — `~12 seconds`

```bash
sudo apt install -y git python3 python3-bcrypt
```

`setup.sh` uses `bcrypt` to compute the hash of your admin password. On Debian 12 and
Ubuntu 23.04+ **`python3-pip` is not enough** (PEP 668 applies: pip is there, and it is the
installation that is forbidden): the right package is `python3-bcrypt`. On Fedora:
`sudo dnf install python3-bcrypt`.

> **You must see**: `python3 -c "import bcrypt"` says nothing and exits 0.
> *(measured: 12s — on my bench `git` was already installed)*

### 2 · The repo — `~6 seconds`

```bash
git clone https://github.com/neo1777/vps1777.git
cd vps1777
```

### 3 · The wizard — `~1 minute of machine time, plus the time you take to answer`

```bash
./setup.sh
```

It asks you **six questions**, in this order (the prompts are in Italian). For a local try:

| # | Question | What to answer locally |
|---|---|---|
| 1 | `Email admin OAuth (il TUO Gmail)` | any email: locally there is no Google OAuth to satisfy |
| 2 | `TELEGRAM_OWNER_ID` | **empty** — it warns you that the bot and the Mini App stay **denied to everyone**, and that is right |
| 3 | `Quale ingress? [1/2/3]` | **1** (Tailscale): it is the only one that locally **adds no container** — Tailscale would run on the host, and here we do not install it |
| 4 | `Vuoi che generi io una password admin random?` | **s** — it prints it on screen (if the output is not a terminal it writes it to `~/.config/vps1777/admin-password-<date>.txt` and tells you where, H75): **copy it now**, it will not show it again |
| 5 | `TELEGRAM_BOT_TOKEN` | **empty** |
| 6 | `Procedo ora?` | **s** |

⚠️ **Count the questions as you answer, do not prepare them in advance.** If you run
`setup.sh` a second time it skips the ones it already has an answer for (`.env` exists, the
secrets are there) — and whoever had the answers ready sees them **shift by one**. *Measured
on 2026-09-07: on a rerun my answer to question 6 ended up in question 5, and the wizard
saved an `s` as the bot token.* It does no permanent damage — you empty the file
`secrets/telegram_bot_token.txt` — but it is the easiest stumble on this page.

> **You must see**, in this order:
> `Installerò la release vX.Y.Z (pull da ghcr, nessuna build)` (X.Y.Z is the latest published
> release; on 2026-09-07 it was v0.48.1) → the secrets generated one
> by one → the image pull (the 5 of the stack, plus `alpine` for the backup) →
> `[✓] Stack avviato. Stato:` with the table of
> containers.
> *(measured: **47 seconds** from launch to the last container started, with the answers
> given by a script. Most of it is downloading the 5 images: on your network it can be
> much more, and it is the only step I cannot promise.)*

> ⚠️ **At the end it asks for your `sudo` password** («Installo il canale di aggiornamento
> (CLI vps1777 + timer)…»). **Before you give it, know what it does on your PC**, because it
> is written for a VPS and does not tell the difference:
> - it installs the `vps1777` command in `/usr/local/bin`;
> - it installs in `/etc/systemd/system` **all** the repo's `vps1777-*` units and
>   **enables** five of them: the daily release check, the secret-expiry check, the path
>   unit of the update button, the one of the archive indexing queue
>   (`vps1777-ingest.path`) and the **auto-update**, which every day
>   would update this trial installation by itself;
> - it installs with `apt-get` **`unattended-upgrades`** and **`fail2ban`**, writes
>   `/etc/apt/apt.conf.d/20auto-upgrades` and `/etc/fail2ban/jail.local` and enables them:
>   automatic security updates and SSH brute-force blocking apply to
>   **your whole system**, not to vps1777.
>
> **On a real VPS it is the piece that keeps the machine updated and defended; for a try
> on your PC you do not need it.** You can press **Ctrl-C**: *measured — `setup.sh` exits (code
> 130), **the stack stays up** and the panel answers `200`.* The stack is already running when
> that prompt arrives. If you gave it and want to go back:
> `sudo systemctl disable --now vps1777-check-update.timer vps1777-secrets-check.timer vps1777-update.path vps1777-auto-update.timer vps1777-ingest.path`
> (and `fail2ban`/`unattended-upgrades` are removed like any package).

### 4 · See that it is alive — `immediate`

```bash
docker compose -f compose.yaml -f compose.ingress.tailscale.yaml ps
```

> **You must see**: **six** containers — the five of the stack `Up … (healthy)`, `gateway`,
> `archive-mcp`, `nb1777-mcp`, `nb1777-bot`, `ocr`, and `backup`, the feature on by
> default that since 2026-09-29 `setup.sh` starts on the first run (`ps` lists it even without its
> overlay in the command: it belongs to the same project) — and under `PORTS`, for the gateway,
> **`127.0.0.1:8080->8080/tcp`**: the port is on the **loopback**, not on `0.0.0.0`.
> `nb1777-bot` shows `healthy` even with the empty token *(measured)*: the container is alive,
> and without `TELEGRAM_OWNER_ID` the bot is denied to everyone anyway — the wizard told you.

If one of the containers stays `Restarting`, jump to *[If it doesn't add up](#if-it-doesnt-add-up)* below.

### 5 · Enter the panel — `~1 minute`

Open **`http://127.0.0.1:8080/admin/login`** and sign in with the email you gave and the
password the wizard printed (or put in the file it pointed you to).

> **You must see**: the login succeeds (redirect), and the tabs answer — there are nine:
> `/admin/setup`, `/admin/salute`, `/admin/nlm`, `/admin/archive`, `/admin/update`, `/admin/secrets`, `/admin/connettori`, `/admin/temi`,
> `/admin/audit`.
> *(measured on 2026-09-07 on four of them: `GET /admin/login` → `200`; `POST` with the real
> login → `302`; `/admin/nlm`, `/admin/update`, `/admin/audit`, `/admin/archive`, with the
> session, → `200`, with the titles `vps1777 · NotebookLM`, `· update`, `· audit`,
> `· Archive`. Setup and Secrets were already there, and were not in the measurement; Salute,
> Connettori and Temi came later)*

And the two MCP connectors, which are the heart of the product:

```bash
SEC=$(cat secrets/gateway_secret.txt)
curl -s -o /dev/null -w "archive → %{http_code}\n" -X POST http://127.0.0.1:8080/$SEC/archive/mcp
curl -s -o /dev/null -w "nb1777  → %{http_code}\n" -X POST http://127.0.0.1:8080/$SEC/nb1777/mcp
curl -s -o /dev/null -w "segreto sbagliato → %{http_code}\n" -X POST http://127.0.0.1:8080/pippo/archive/mcp
```

> **You must see**: `401`, `401`, **`404`**. *(measured)* The first two say "we are here, and
> without authentication you do not get in"; the third is the detail that matters: with a wrong
> secret the gateway answers **404 and not 401**, that is, it does not confirm that the path
> exists.

---

## When you have seen enough — tearing down

```bash
docker compose -f compose.yaml -f compose.ingress.tailscale.yaml -f compose.ops.backup.yaml \
  --profile ingress.tailscale --profile ops.backup down -v
```

> **You must see**: the six containers removed and the volumes deleted (`-v`: if you omit it
> the data stays). ⚠️ The backup overlay and its profile **are needed**: without them, `down`
> does not know the `backup` service, which stays on as an orphan, and the volumes it mounts
> stay («Resource is still in use»). *Measured on 2026-10-01 on a test project with the
> same shape.* The images stay in Docker's cache: `docker image prune -a` if
> you also want those ~2 GB back. *(measured: 0 containers and 0 volumes left — on 2026-09-07
> on the stack, when the containers were five; on 2026-10-01 on the test project, with the overlay)*
> You can delete the `vps1777/` folder — your trial secrets are in there.

---

## If it doesn't add up

**One or more containers in `Restarting`, and in the logs `PermissionError: [Errno 13] Permission
denied: '/run/secrets/gateway_secret'`.** You installed as `root` (or your uid is not
1000): the containers run as uid **1000** and cannot read the secrets.

```bash
chown 1000:1000 secrets/*.txt
docker compose -f compose.yaml -f compose.ingress.tailscale.yaml --profile ingress.tailscale up -d
```

⚠️ **Not** `chown $(id -u):$(id -g)`: you need the uid **inside the container**, not yours.
If you run that command as root you change nothing and stay stuck believing you fixed it.
The full case is in [TROUBLESHOOTING.md](../TROUBLESHOOTING.md) (Italian).

**`manifest unknown` on the pull.** You are running `docker compose` **without** the `.env` that
`setup.sh` writes: without `VPS1777_TAG` the default is `dev`, which does not exist on GHCR. Run
`./setup.sh` first.

The rest: [TROUBLESHOOTING.md](../TROUBLESHOOTING.md) (Italian).

---

## And now? The piece local cannot give you

What you have in hand is the complete stack, **without the front door**. To get the
thing the README promises — *a public HTTPS URL to paste into claude.ai* — you need
a machine reachable from the Internet and an ingress:

- [INSTALL.md](INSTALL.md) — the real installation, step by step;
- [INGRESS.md](../INGRESS.md) (Italian) — the three ways to HTTPS: Tailscale Funnel, Caddy, Cloudflare;
- and **once you have it**, the question that closes the loop is asked **from outside**, from your PC:

  ```bash
  ./tools/collaudo-da-fuori.sh https://your-public-url
  ```

  four checks in five seconds — it answers from the Internet, TLS is valid, the panel is
  vps1777's, the fallback port 8080 has closed again. On a local target
  (`127.0.0.1`) **it refuses to answer**, and says so: from in here that question has
  no subject, and a verdict would be about something else.
