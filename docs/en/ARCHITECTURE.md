# Architecture — vps1777

> English translation of [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md). Translations are freshness-checked in CI against the Italian source (see [`MANIFEST.json`](MANIFEST.json)): if this note is red in CI, the Italian moved first.

## Three hearts

```
┌────────── INGRESS (1 a scelta) ──────────┐
│  Tailscale Funnel | Caddy | Cloudflared  │
└─────────────────┬────────────────────────┘
                  ▼  (HTTPS pubblico → :8080 nel container)
┌──────────────── GATEWAY (core stabile) ──────────────┐
│  - OAuth 2.1 + DCR + PKCE                            │
│  - /admin/*: login, logout, setup, secrets, nlm,     │
│              audit, archive, update                  │
│  - /app/* (Mini App Telegram)                        │
│  - Reverse proxy: /<SECRET>/<name>/<path>            │
│  - Plugin registry: legge GATEWAY_UPSTREAMS da env   │
└─────────────────┬────────────────────────────────────┘
                  ▼  (rete backend, internal: true)
┌─ archive-mcp ─┬─ nb1777-mcp ──┬─ nb1777-bot ──┬─ ocr ────────┬─ PLUGIN ──┐
│ FTS5 multi-DB │ nlm (CLI)     │ Telegram poll │ images →     │ your MCP  │
│ + vectors     │ no browser    │ no port       │ text         │ or bot    │
│ :8002 /mcp    │ :8003 /mcp    │               │ :8004 /ocr   │ :8010…    │
└───────────────┴───────────────┴───────────────┴──────────────┴───────────┘
```

## Network

| Network | Driver | `internal` | Connected services |
|---|---|---|---|
| `backend` | bridge | ✅ true | all services (internal communication), except the `indice-notturno` job, which has no network |
| `ingress` | bridge | ❌ false | **only** the ingress proxy (caddy/cloudflared) and, with its profile, the gateway |
| `egress` | bridge | ❌ false | nb1777-mcp, bot — they go out to the Internet, **outside** of `ingress` |
| `funnel` | bridge without masquerade | ❌ false | only with the Tailscale profile: the gateway. Ingress yes, egress no (H50) |

In `compose.yaml` the gateway sits **only** on `backend` (H50): declaring `ingress` for it
gave it a NAT exit towards any host, measured live on 26/07. The ingress network is given
back by the overlay of the chosen profile (`compose.ingress.caddy.yaml`,
`compose.ingress.cloudflared.yaml`); with the Tailscale profile the gateway publishes a
port on the host's loopback and sits on the `funnel` network, which accepts incoming
connections and lets nothing out.

Three base networks, three distinct roles (H25):
- **`backend`** is `internal: true` → world-isolated: whoever lives only here (`archive-mcp`) cannot exfiltrate anything.
- **`ingress`** hosts **only** the proxy that publishes the gateway and, with the caddy or cloudflared profile, the gateway itself. Nothing else.
- **`egress`** provides the Internet exit for the backends that need one (`nb1777-mcp` → NotebookLM, `bot` → Telegram) while **separating** them from the ingress network: a compromised ingress proxy does not sit on the same network as these services. It is a bridge with no published ports → it allows egress (NAT), not ingress.

## Persistent volumes

| Volume | Container path | Contents |
|---|---|---|
| `gateway-data` | `/var/lib/gateway` | audit log, audit.jsonl |
| `archive-data` | `/var/lib/archive` | `data/` (sources) + `db/` (SQLite FTS5: the messages and, from Session Recovery bundles, the `sessioni`/`archi`/`memorie` tables — see [ARCHIVE.md](ARCHIVE.md)) + `models/` and the `<db>.vec.db` indexes of search by meaning ([RICERCA-IBRIDA.md](RICERCA-IBRIDA.md)). Written by the gateway (ingest) and by the `indice-notturno` job (the indexes); `archive-mcp` mounts it read-only |
| `nlm-auth` | `/var/lib/nlm` | NotebookLM profile `profiles/default/` + `AUTH_PENDING.flag` |
| `nlm-artifacts` | `/var/lib/nlm-artifacts` | the Studio artifacts downloaded by nb1777-mcp and the in-transit files of `archive-ingest`. No secrets |
| `gateway-uploads` | `/var/lib/uploads` | the gateway's upload spool (`TMPDIR`): on disk and not in the `/tmp` tmpfs, which a 2.6 GB bundle used to fill |
| Tailscale (host) | `/var/lib/tailscale` on the **host** | node state (not in a container; see INGRESS.md) |
| `caddy-data`, `caddy-config` (if Caddy) | `/data`, `/config` | ACME certificates and Caddy's configuration |
| `portainer-data` (opt-in profile) | `/data` | Portainer's state |

Cloudflared has no volumes: the tunnel token is the `cloudflared_token` secret.

## Secrets

See [SECRETS.md](../SECRETS.md) (Italian). All file-mounted at `/run/secrets/<name>`: with Docker
Compose (not Swarm) a `file:` secret is a read-only bind-mount of the file on the host,
not a tmpfs. No env vars for anything sensitive. Each service sees only its own: the
gateway has five (`gateway_secret`, `oauth_signing_secret`, `admin_password_bcrypt`,
`telegram_webapp_secret`, `archive_desc_secret`), and the Telegram bot token is mounted
only by `nb1777-bot`.

## Contracts between services

| Caller → Callee | Protocol | Path |
|---|---|---|
| Internet → gateway | HTTPS (ingress) | `/<SECRET>/<name>/mcp` |
| gateway → MCP servers | HTTP on the `backend` network | `http://<service>:<port>/mcp` |
| gateway → nb1777-mcp (nlm profile, Studio artifacts) | internal HTTP + shared secret | `/internal/nlm/{status,profile,artifacts,artifact}` |
| bot → nb1777-mcp (profile status) | internal HTTP + shared secret | `/internal/nlm/status` |
| bot → nb1777-mcp (notifications #30) | internal HTTP + shared secret | `/internal/{notifications,canonico/ack}` |
| nb1777-bot → nb1777-mcp | MCP client HTTP | `http://nb1777-mcp:8003/mcp` |
| archive-mcp → gateway (DB card: `set_description`, `set_ruolo`) | internal HTTP + shared secret | `/internal/archive/{description,ruolo}` — archive-mcp's only writes, since it has the volume read-only |
| gateway → ocr (image ingest) | internal HTTP, bytes→text | `http://ocr:8004/ocr` (env `OCR_URL`; the gateway does NOT run processes — guarded by `test_gateway_non_tocca_docker`) |
| Telegram cloud → bot | long-poll outbound HTTPS | `api.telegram.org` |
| claude.ai → gateway | OAuth 2.1 + MCP streamable-http | `/<SECRET>/<name>/mcp` |

## Plugin pattern

See [PLUGINS.md](../PLUGINS.md) (Italian). In short:

1. Create `plugins/<nome>/` with `Dockerfile` + `compose.<nome>.yaml`
2. Expose an MCP endpoint on an internal port (e.g. `8010` — 8002/8003/8004 belong to the base services)
3. Add to `.env`: `GATEWAY_UPSTREAMS=archive=archive-mcp:8002,nb1777=nb1777-mcp:8003,<nome>=<container>:8010`
4. Recreate the gateway: `docker compose up -d gateway` (`restart` does not re-read `.env`, and the new `GATEWAY_UPSTREAMS` would not get in)
5. Your plugin's URL: `<PUBLIC_BASE>/<SECRET>/<nome>/mcp`

## Update channel

The update engine lives **on the host**, not in the containers: the CLI
`/usr/local/bin/vps1777` (installed by `deploy.sh`, in the repo root) is the only
place that touches images and stack. The gateway stays **unprivileged**: the
*Update* button in the admin panel only writes an **intent file** into `onboarding/`
(validated: schema, semver, TTL, anti-replay nonce); a systemd **path unit**
(`vps1777-update.path` → `vps1777-update.service`) sees it and launches the same
`vps1777 update`. A daily timer (`vps1777-check-update.timer`) performs the
release check + Telegram notification to the owner. A second daily timer
(`vps1777-auto-update.timer`) installs the latest release by itself, but only once it
has been published for at least 48 hours (`vps1777 auto-update --eta-minima 48`): a
bad release has two days to be withdrawn before it arrives. A third
(`vps1777-secrets-check.timer`) checks the secrets' expiry dates.

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

Verification of the bundle's **cosign** signature has been **required (fail-closed) by
default** since v0.23.0: if cosign is missing and cannot be installed, the update stops
instead of proceeding — the only *deliberate* emergency escape is setting
`VPS1777_REQUIRE_COSIGN=0` in the `.env`.

Images come **only from GHCR** (`compose.yaml` is pull-only; local builds exist
only in the `compose.build.yaml` overlay, dev/CI). After an update the `.env` carries,
next to the tag, the digest of every image (`VPS1777_DIGEST_<SERVICE>`, H22): even a
hand-made `docker compose up` runs the verified images. A fresh installation does not
have them until its first update. Besides the five of the stack, the release publishes
an **optional** image, `vps1777-caddy-dns01` (Caddy with Cloudflare's DNS plugin, for the
`caddy-dns01` feature: see [INGRESS.md](../INGRESS.md) (Italian)): signed and in the lock like the
others, it runs only where the feature is declared with the Caddy ingress. Full user manual:
[UPDATE.md](UPDATE.md).

## Healthcheck

Every service has a compose healthcheck (also used by the update's health-gate):

| Service | Probe |
|---|---|
| gateway | `/health` → minimal public body `{"ok":true}`. With `?deep=1` it TCP-probes the MCP upstreams (503 if down), but this is **reserved for internal callers**: from outside it answers 403 (H33). The updater calls it via `compose exec` *inside* the gateway, hence from loopback. |
| archive-mcp / nb1777-mcp | HTTP `GET /health` (since `v0.45.0`; previously a TCP-connect, which declared healthy a process with the port open and the app broken). The probe exercises the service's actual job — the DB registry for archive, the data volume for nb1777 — never NotebookLM; it also exposes `mcp_sdk` and `mcp_protocol_max`, so "which MCP revision does your gateway speak?" has an observable answer. |
| ocr | internal HTTP `GET /health` |
| nb1777-bot | long-poll, no port: heartbeat file `/tmp/nb1777-bot.heartbeat` (unhealthy if mtime > 90s) |

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

JWT typ is the key: an `access_token` does not work where an `admin_cookie` is required, and vice versa. See [../../SECURITY.md](../../SECURITY.md).

## Security model

The posture is **fail-closed**: in the absence of configuration the gateway denies,
it does not open — proven on the simplest case (no `gateway_secret` → the proxy denies
everything) by `services/gateway/tests/test_fail_closed_senza_config.py`. What follows is the summary of the hardening: first the defensive review (July 2026,
`v0.19.1 → v0.33.0`, which at the closing of the dossier counted **35 closed · 7
partial · 1 accepted · 0 open** out of 43), then what came after. Today the register
holds 80 findings: 68 closed, 9 partial, 3 accepted, 0 open. The operational detail
lives in [../../SECURITY.md](../../SECURITY.md), which is the source of truth — here is
the summary, there the register that CI verifies.

### Baseline (from the beginning)

- Backends on an `internal: true` network — world-isolated. *(True for all of them at the
  start; since v0.33.0 `nb1777-mcp` and the bot have a dedicated exit on the `egress`
  network — see **Network** above. Whoever stays only on `backend`, like `archive-mcp`,
  cannot exfiltrate anything: that is the point, and for it this still holds to the letter.)*
- OAuth 2.1 + DCR + PKCE; JWTs with separate `typ` values (`access` ≠ `admin_cookie` ≠ miniapp).
- `GATEWAY_SECRET` as the path-namespace of the MCP proxy.
- Stack services non-root, `cap_drop: ALL`, `no-new-privileges`. The operational
  overlays are exceptions and say so: `backup` runs without these options
  (`watchtower` was the second case, removed in 0.67.0), `portainer` has only `no-new-privileges` (and the Docker socket: it is root
  access to the host, which is why it is an opt-in profile on loopback).
- Gateway **without** `docker.sock`; of the host it sees only the `onboarding/` folder
  (bind-mount, where the update's intent and status go through). It sees the 5 Docker
  secrets assigned to it: not the bot token, but the derived key `telegram_webapp_secret`
  (H54): compromise the gateway, and the Mini App's `initData` becomes forgeable, but
  you cannot speak as the bot — see `SECRETS.md`. Images pinned to digest (`images.lock`).

### Hardening from the defensive review (v0.22.0 → v0.33.0)

This table is the history of the July dossier: each row says what went into that
version, not today's state (for that, the table after it and SECURITY.md).

| Version | Hardening |
|---|---|
| v0.22.0 | **Fail-closed owner-gating**: without `TELEGRAM_OWNER_ID` the Mini App and the bot deny EVERYONE (`/app/auth` → 503, `is_owner` → False). |
| v0.23.0 | **cosign REQUIRED by default** on self-update (see *Update channel*); deliberate escape `VPS1777_REQUIRE_COSIGN=0`. |
| v0.24.0 | `GATEWAY_SECRET` redacted from access logs (redaction installed before serving the first request). |
| v0.25.0 | **Per-IP rate-limit** on the auth endpoints: `/register` 10/5min, `/token` 60/min, `/app/auth` 20/5min. The MCP proxy verifies the **audience**: the access token's `sub` must be in `OAUTH_ALLOWED_EMAILS`, otherwise it refuses (401 `subject_not_allowed`). |
| v0.26.0 | **The backup key off the VPS** (`age`): no auto-keygen on the server — the private key is born and stays on the PC, the backup container encrypts with the public key only. A private key on the same disk as the backups protects against nothing. |
| v0.27.0 | **CI supply-chain**: GitHub Actions pinned to **full SHA** (no more moving tags — `trivy-action@master` was the worst case), Dependabot so the pins don't age, least-privilege per-job permissions, third-party images pinned to digest. |
| v0.28.0 | **`forwarded_allow_ips` restricted** — see below. |
| v0.29.0 | **Backup** container **without `docker.sock`**: volumes mounted directly `:ro`. Secrets out of argv in the deploy. |
| v0.30.0 | **The gateway does not touch the Google cookies**: in operation, `nlm-auth` is mounted only by nb1777-mcp (rw); read-only for the backup (encrypted archive) and the expiry check (busybox with no network, mtime only); gateway and bot at zero-access, via the internal channel. The proxy refuses `internal/` sub-paths. |
| v0.31.0 | **The findings register**: `security/findings.yml` (43 findings, each with evidence anchored to *content* rather than line numbers) + `security/check_findings.py` in CI. "Declared done but absent" becomes a red build: a security claim without coordinates cannot rot silently. |
| v0.32.0 | **Real** admin session revocation (`jti` + revoke-list: before, logout only deleted the cookie, H20); Google cookies out of the pre-update snapshot (H14); caps on the **decompressed** size (H39); **open-redirect** H30 marked closed yet actually bypassable (`startswith` is a *prefix* match, not an *origin* match) → truly closed with 12 attack tests; **immutable `v*` tags** (H24). |
| v0.33.0 | A real **OAuth consent page** (H8); **separate `egress` network** (H25); CORS scoped to OAuth+`/app` only, `/health` with a minimal body and `?deep` internal-only, global CSP `default-src 'none'` (H31/H33/H34/H36); constant-time PKCE (H32); `read_only` rootfs on gateway/archive-mcp/bot (H43). Dossier closed: **0 open findings**. |

### After the dossier (v0.34.0 → today)

| Version | Hardening |
|---|---|
| v0.40.x | The gateway **loses its Internet exit** (H50, measured live); the gateway no longer mounts the bot token (H54, fully closed with #61); no service publishes ports in `compose.yaml` (H48); Portainer only on loopback and opt-in (H47); host hardening in all three installers (H45); backup retention counted in days (H57-H59). |
| v0.43.1 | Four true but unguarded guarantees become tests (actions pinned to SHA H65, third-party images to digest H66, gateway without Docker H67, secrets only as files H68); the account's personal details leave the archive tools redacted (H64). |
| v0.58.0 | `read_only` rootfs on nb1777-mcp too: now on **all** services (H43); a **48-hour quarantine** for auto-update; H24 (tag protection) becomes an **accepted risk** until 27/12/2026. |
| v0.59.0 | Image **digests** in the `.env` and in the compose (H22, partial: a fresh installation gets them from its first update). |
| v0.61.x | nb1777-mcp **without Chromium** (902 → 221 MB); base images of the Dockerfiles pinned to digest; workflow permissions inside the jobs; **immutable releases** on GitHub. |
| v0.62.x | **Required CI on main** (9 checks, for administrators too); the archive's redaction covers credentials in a recognisable format and the path of trycloudflare tunnels, even inside the snippet's highlights. |

> Versions v0.34.0 → v0.36.0 are the nb1777
> features (studio fix, canonico, `memoria_check`; since v0.44.0 the canonico is a file
> of the product and `canonico(full=true)` serves its text, while `memoria_ack` records
> the ack) — see [NB1777.md](../NB1777.md) (Italian)
> and [MEMORIA-1777.md](MEMORIA-1777.md).
> The `accepted` state in the register (v0.33.0) is the third box next to
> `closed`/`open`: a risk **decided not to close** is neither done nor
> forgotten, and the gate demands it carry its rationale. The first one is the
> no-2FA (H28).

### Client IP and proxy headers (v0.28.0)

uvicorn runs with `proxy_headers=True` but `forwarded_allow_ips` **restricted** to
`GATEWAY_FORWARDED_ALLOW_IPS` (default
`127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16`), no longer `*`.
The `X-Forwarded-For` is trusted ONLY from the private ranges + loopback: the
reverse-proxy (Tailscale/Caddy/Cloudflared) always arrives from a private Docker
bridge (e.g. `172.21.0.1`), NEVER from a public IP. uvicorn walks the XFF from the
**right** and takes the first untrusted host, so an `X-Forwarded-For` injected by a
public client is discarded. Consequence: the client IP is no longer spoofable, and
rate-limit, lockout and audit are no longer evadable.

> **What this guarantee rests on — the two legs, and one of them is not ours.**
> ① *the trust-list is not `*`* — that one is ours, it lives in `settings.py`, and it is
> guarded by `services/gateway/tests/test_xff_trust_list.py`.
> ② *"uvicorn walks the XFF from the right"* — **that is not ours**: it is the behavior of
> `ProxyHeadersMiddleware`, and **it has historically changed** (older versions took
> the first element **from the left**, i.e. the part a client can inject). The constraint
> in `services/gateway/pyproject.toml` is `>=`, open upwards, and `uvicorn` is `0.x`:
> even a minor can change behavior.
> ⇒ *The consequence written above holds as long as ② holds.*
> ✅ **And since 09/08, ② is guarded too** — `services/gateway/tests_runtime/`
> `test_gamba2_xff_da_destra.py`, which EXECUTES `ProxyHeadersMiddleware` with the trust-list
> read from `settings.py` and verifies that an injected XFF does not win. *Here it used to
> say "a test cannot verify this: the gateway suite runs without the gateway's
> dependencies": that was true for THAT suite (`uvx pytest`, stdlib only), not for the
> problem. The way was to run where the dependencies exist* — a dedicated job in `ci.yml` with
> `uv sync --frozen`, so what gets measured is the `uvicorn` the image actually installs and
> not one grabbed on the side. This closes register entry `39b5a89d`.
> ⚠️ *The test measures the BEHAVIOR, it does not ratify the VERSION: the constraint remains `>=`
> and majors keep coming in without anyone deciding them (`starlette>=0.45.0` had reached
> 1.3.1 crossing 1.0 in silence; today the constraint is `>=1.6.0`). If one day the client IP becomes spoofable again,
> CI will now tell you; if a dependency's versioning regime changes,
> **no** — that remains a decision to be made by hand.*

### The NotebookLM profile and the internal channel (v0.30.0)

The Google session cookies (volume `nlm-auth`): among the services in operation it is
mounted **only by `nb1777-mcp`** (rw), the one that uses them. Outside the services, two
time-bounded jobs mount it **read-only**: the **backup** (container `backup`, a feature
active by default, or `tools/backup.sh` on the host) which puts it into the archive
encrypted with the `age` public key — and that is why `nlm-auth` is excluded
from the pre-update snapshot, which is not encrypted — and the **expiry check**
(`vps1777 secrets-status`), which in a `busybox --network none` reads only the mtime
of the cookies file. The gateway (the only one exposed to the Internet) and the bot have
**zero access**: they ask it.

```
gateway (esposto) ──┐
                    ├─ HTTP interno + segreto condiviso ─► nb1777-mcp ─► [ nlm-auth ]
bot               ──┘   X-Vps1777-Internal (constant-time)   (unico mount)
```

| Endpoint (`backend` network only) | Caller | What it does |
|---|---|---|
| `GET /internal/nlm/status` | gateway, bot | says **whether** a valid profile exists (`{ok, has_cookies, pending}`) — never the content |
| `POST /internal/nlm/profile` | gateway | receives the tar.gz, **validates**, installs (staging → swap with rollback) |
| `GET /internal/nlm/artifacts` | gateway | the list of downloaded Studio artifacts (`nlm-artifacts`) |
| `GET /internal/nlm/artifact?name=` | gateway | one artifact, for `/admin/nlm/artifact/{name}` |
| `GET /internal/notifications` | bot | fetches the notification queue (memory drift + canonico reminders, v0.36.0) |
| `POST /internal/canonico/ack` | bot | records the ack of the «✓ Fatto» button (v0.36.0) |

Without a configured `gateway_secret` → **403**: fail-closed here too. *These six
endpoints are served by `nb1777-mcp`, and the guard is `_internal_ok` (`server.py`): "with no
secret configured, everything is denied".* The detail of the two memory endpoints and why
they exist lives in [NB1777.md](../NB1777.md) (Italian) §6-§7.

> **403 here, 404 from the proxy — and it is not an inconsistency.** They are two different
> doors: *from inside* the `backend` network, without the secret, `nb1777-mcp` answers **403**
> (declared fail-closed); *from outside*, the gateway's reverse-proxy refuses every
> `internal/` sub-path with **404**, because a 403 would confirm the route's existence to
> whoever is hunting for it (`proxy.py`, and the choice is written down in `routes.py`:
> "every step answers 404, not 403"). Whoever reads a log must be able to tell them apart:
> a **403** says *the secret doesn't match*, a **404** says *this surface, for you,
> does not exist*.

Two properties to keep in sight if you touch this area:

- **`internal/` cannot be traversed.** The MCP reverse proxy is a catch-all on
  `{path:path}`: without an explicit block, those endpoints would be reachable
  from the Internet via `/<SECRET>/<service>/internal/…`. `proxy.py` refuses every
  `internal/` sub-path with 404 **before any other check** (secret, bearer),
  for **all** upstreams. It is a **reserved prefix**: a plugin can use it for
  its own private endpoints knowing the proxy will not expose them. See [PLUGINS.md](../PLUGINS.md) (Italian).
- **The upload is non-destructive** (the staging→validate→replace flow lives in
  `services/nb1777-mcp/app/nlm_profile.py`, `install_profile`; the gateway only
  forwards): the tar is
  extracted into staging, validated, and only then does it replace the good profile —
  a wrong file does not disconnect you from NotebookLM.
