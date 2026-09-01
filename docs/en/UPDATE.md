# Updates — vps1777

> English translation of [`docs/UPDATE.md`](../UPDATE.md). Translations are freshness-checked in CI against the Italian source (see [`MANIFEST.json`](MANIFEST.json)): if this note is red in CI, the Italian moved first.

vps1777 updates **like any ordinary piece of software**: numbered versions
([SemVer](https://semver.org)), a changelog, one command (or one click) to
update, an automatic backup beforehand, **automatic rollback** if the new
version doesn't come back healthy.

Model: **registry-pull**. Images are built and signed by CI at every release
and published to GHCR; your VPS only runs `docker compose pull`.
**No builds in production** — on a 4GB VPS, compiling Chromium in the middle of
an update is the perfect moment for an OOM, so it never happens.

## TL;DR

```bash
vps1777 status          # dove sono, c'è una versione nuova?
vps1777 update          # aggiorna (chiede conferma, mostra il changelog)
vps1777 rollback        # torna alla versione precedente
```

Or from the **admin panel → Update tab**: same thing, one click.
When a release comes out the Telegram bot notifies you (once only).
And if you do nothing, **it takes care of itself**: by default
`vps1777-auto-update.timer` applies the safe update once a week (feature
`autoupdate`, can be turned off via `VPS1777_FEATURES` — see
[OPS.md](../OPS.md) (Italian)).

## What happens during `vps1777 update`

```
lock → preflight → changelog+conferma → download bundle (sha256 + cosign)
  → backup age + snapshot locale volumi → pull immagini → verifica digest
  ── punto di non ritorno ──
  → sync file gestiti → stop → migrazioni → start → health-gate (180s)
  → ✅ esito su Telegram        (oppure: AUTO-ROLLBACK alla versione di prima)
```

Guarantees:

- **Before touching anything**: an age-encrypted backup of the **core** tier
  (`tools/backup.sh --senza-archivio`: small volumes, secrets, config, the DB
  `description` files) + an unencrypted local snapshot of the 3 data volumes
  (`backups/pre-update/`). The encrypted archive has its own weekly pass from
  the nightly cron — here the snapshot covers it (see
  [BACKUP-RESTORE.md](BACKUP-RESTORE.md), "The two tiers").
  The snapshot exists because auto-rollback **cannot depend on the age key**
  (which often lives only on your PC); it is pruned on the next successful update.
- **Supply chain**: the release bundle carries `images.lock` with the immutable
  image digests (one per service); after the pull, the local digests MUST match.
  The bundle's keyless signature is verified with `cosign` **by default and in
  fail-closed mode**: if verification doesn't pass — or if `cosign` is missing
  and cannot be auto-installed — the update stops. `cosign` is auto-installed
  when absent (pinned version). Deliberate emergency escape hatch:
  `VPS1777_REQUIRE_COSIGN=0` in `.env` or `--no-require-cosign`.
- **`v*` tags are immutable** (H24, v0.32.0): a GitHub ruleset forbids moving
  or deleting them. This is the piece that makes everything else *trustworthy*:
  if a tag could be re-pointed, the signed bundle the update anchors itself to
  could be swapped out from under it, and the digest verification would be
  comparing the wrong thing with itself. (The `non_fast_forward` rule alone
  wasn't enough: moving a tag *forward* is a fast-forward.)
- **Automatic rollback**: if after the update the stack doesn't come back
  healthy within 180s (compose healthchecks + the gateway's `/health?deep=1`
  probe), the VPS goes back **on its own** to the previous version — the old
  images are still local, no new download. If a migration touched the data,
  the volumes are restored from the snapshot (all-or-nothing, so the registry
  and the data stay consistent). Outcome always reported on Telegram.

## The button in the admin panel

The gateway **has no Docker privileges** (by design — see
`docs/ARCHITECTURE.md`): the *Update* button only writes an **intent file**
in `onboarding/`; a systemd path unit on the host sees it in <1s and launches
the very same `vps1777 update`. The intent is validated (schema, semver, 10
minute TTL, anti-replay nonce, target = latest known release) and **deleted
before acting**. Progress is shown in the card (the page tolerates the gateway
itself restarting mid-update); the outcome arrives on Telegram either way.

## Notifications and checks

**Three** systemd timers run on the VPS, at different cadences: two **watch**
things that age at different speeds, the third **applies**.

**1. New releases** — `vps1777-check-update.timer`, **once a day**. It makes an
**unauthenticated** GET to `api.github.com/repos/neo1777/vps1777/releases/latest`
— **zero telemetry**: no data leaves your VPS. If there's a new version:
Telegram message to the owner (once per release) and a badge in the admin card.
If GitHub is unreachable: no noise, just a "stale check" badge.

**2. Secret expirations** — `vps1777-secrets-check.timer`, **weekly**
(secrets age slowly: one nudge a week is enough; `RandomizedDelaySec`
spreads the load, `Persistent=true` catches up on checks missed while the VPS
was off). It runs `vps1777 secrets-status --notify`: reads the mtime of the
files in `secrets/`, writes `onboarding/secrets_status.json` (which feeds
`/admin/secrets`) and notifies on Telegram any secrets past their threshold.
The thresholds and the *why* behind each one are in
[SECRETS.md](../SECRETS.md) (Italian). You can run it manually any time:

```bash
vps1777 secrets-status          # a schermo
vps1777 secrets-status --notify # + notifica Telegram se qualcosa è oltre soglia
```

**3. Safe auto-update** — `vps1777-auto-update.timer`, **weekly**.
This one doesn't watch: it **applies** `vps1777 update --yes`, with the entire
safety net of the managed channel (backup, digest verification, migrations,
health-gate, rollback) — and only if the `autoupdate` feature is in the
declared state (`VPS1777_FEATURES`, default yes). It's the reason the daily
check can limit itself to notifying: application already has its own safe
channel. Details and how to turn it off: [OPS.md](../OPS.md) (Italian).

> The units have no hardcoded user or path: the CLI substitutes
> `@OPERATOR_USER@` / `@REPO@` with the real values at every update (H43). It
> was a real bug: with an operator other than `vps1777`, the expiration check
> stopped running **silently**.

## Manual rollback

```bash
vps1777 rollback              # torna alla versione precedente (solo immagini+file)
vps1777 rollback --with-data  # anche i volumi dallo snapshot pre-update
```

The default does NOT touch the data. `--with-data` restores the 3 volumes from
the pre-update snapshot: data written after that update is lost — it's the
right choice only if the update corrupted the data.

## Migrations

If a release changes the data schema, it ships a migration
(`migrations/NNNN-slug/`) that the update applies **exactly once**, in a
one-off container with no network, before restarting the stack. Multi-version
jumps (N → N+3) apply everything missing, in order. The full contract:
[`migrations/README.md`](../../migrations/README.md) (Italian). There are no
downgrade scripts: going back = restore from snapshot/backup.

## I have an old installation (pre-update-channel)

A "legacy" installation (locally built images, no `vps1777` command) is
converted **once** with the bootstrap:

```bash
# dalla shell della VPS, utente vps1777, dentro ~/vps1777
VER=X.Y.Z   # ultima release: https://github.com/neo1777/vps1777/releases
curl -fsSLO "https://github.com/neo1777/vps1777/releases/download/v${VER}/vps1777-runtime-v${VER}.tar.gz"
curl -fsSLO "https://github.com/neo1777/vps1777/releases/download/v${VER}/SHA256SUMS"
sha256sum -c SHA256SUMS                    # verifica esplicita — mai curl|bash
mkdir -p /tmp/vps1777-bundle && tar xzf "vps1777-runtime-v${VER}.tar.gz" -C /tmp/vps1777-bundle
bash /tmp/vps1777-bundle/tools/bootstrap.sh
```

The bootstrap: full backup → installs CLI + timers → converts the compose
files to the pull model → pull + digest verification → restarts from the ghcr
containers → health-gate. Named volumes are **never touched** (`up` doesn't
recreate them; no code path ever runs `down -v`): zero data loss. If something
goes wrong, it restores the previous stack on its own (the old images remain
as a parachute until the first successful `vps1777 update`). It's idempotent:
run again, it says "already converged".

## Channels

- **stable** (default): stable releases only — `releases/latest` excludes
  prereleases, so the test `-rc.*` versions never reach you.
- **prerelease** (testing only): `VPS1777_RELEASE_CHANNEL=prerelease` in
  `.env`, or an explicit update with `vps1777 update --version vX.Y.Z-rc.1`.

## What about Watchtower?

The `ops.autoupdate` profile (Watchtower) still exists but is **demoted and
unsupported alongside** the managed channel: it bypasses backups, migrations,
health-gate, changelog and rollback. With pinned SemVer tags it's nearly inert
anyway. `vps1777 update` warns you if it finds it active. Use the managed
channel.

## Files and state (where everything lives)

| What | Where |
|---|---|
| Deployed version | `.env` → `VPS1777_TAG` (written ONLY by update/rollback/bootstrap/installer) |
| Channel state (previous, history, nonce…) | `var/state.json` (chmod 700) |
| Staged releases (bundle + rollback-files) | `releases/vX.Y.Z/` (kept: current + previous) |
| Pre-update snapshots | `backups/pre-update/` (kept: the latest of the last **2 versions** — n and n-1; the rest is pruned immediately. Owner decision of 29/08: the old 72h+3-versions rule didn't look at the WEIGHT, and 7 releases in 36h × 10 GB volumes filled the disk) |
| Check / intent / progress state (for the admin card) | `onboarding/update_{status,pending_update,progress}.json` |
| Migration registry | volume `gateway-data` → `state/migrations.json` |
| Updater logs | `journalctl -u vps1777-update -u vps1777-check-update` |

## Quick troubleshooting

- **"update già in corso"** — there's a lock (`var/update.lock`). If it's a
  leftover from a crash: `vps1777 status` shows `update_in_progress`; no active
  process → retry, the lock is per-process.
- **Digest mismatch on pull** — something doesn't add up between the registry
  and the release (attack or corrupted release): the update aborts BEFORE
  touching the stack. Check the release on GitHub and retry.
- **Rollback not healthy (exit 2)** — the CLI stops without thrashing and
  writes to you on Telegram. You have: the snapshot in `backups/pre-update/`,
  the core age backup in `backups/` (and the archive one in `backups/archivio/`),
  and `docs/BACKUP-RESTORE.md` for disaster recovery.
