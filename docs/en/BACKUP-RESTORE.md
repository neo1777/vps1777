# Backup & Restore — vps1777

> English translation of [`docs/BACKUP-RESTORE.md`](../BACKUP-RESTORE.md). Translations are freshness-checked in CI against the Italian source (see [`MANIFEST.json`](MANIFEST.json)): if this note is red in CI, the Italian moved first.

Strategy: age-encrypted backups of volumes + secrets, in `backups/`, on **two tiers**
separated by the nature of the data — because 99.99% of the weight is regenerable and
0.01% is not.

## The two tiers (since `0.43.13`)

| Tier | What it contains | When | Retention | Where |
|---|---|---|---|---|
| **core** | all volumes **except** the archive (`gateway-data`, `gateway-uploads`, `nlm-auth` — which since v0.44.0 also carries the local layers of the 1777 memory, `memoria-1777/{fatti,errata}.md` —, `nlm-artifacts`, …), `secrets/`, `.env` + compose + `ingress/`, and **the `description` files of the archive DBs** (`descrizioni/<db>.txt`) | **every night** (03:00 UTC) and on every `vps1777 update` | 7 distinct dailies + 4 weeklies + last 3 versions | `backups/vps1777-<ts>.tar.age` |
| **archive** | only the archive volumes (`archive-data`: the FTS DBs), **compressed** before encrypting | **every 7 days** (from the nightly cron, when due) | the last **2** copies — n and n-1 | `backups/archivio/vps1777-archivio-<ts>.tar.age` |

> **Why two tiers** — measured on 29/08/2026 on the VPS: one backup weighed 9.7 GB, and
> 9.7 GB was `archive-data` alone. The archive DBs are **regenerable** from the
> bundles/exports the owner keeps off the VPS (re-ingest ≈ 2h); everything else —
> users, OAuth clients, audit, NotebookLM profile, secrets — weighs 250 KB and is
> **irreplaceable**. We were paying 9.7 GB a night to protect 250 KB (≈ 70 GB at steady
> state on a 118 GB disk). The only part of the archive that re-ingest does **not**
> regenerate is the hand-written notes made with `set_description`: that's why they
> travel every night in the core. Owner decision: *«basta n, n-1 per paranoia… dobbiamo
> farci stare quel che serve»* ("n, n-1 is enough for paranoia… we have to fit what we
> need"). Between one archive backup and the next the net is double: the sources off the
> VPS + the pre-update snapshot (`backups/pre-update/`, unencrypted, n and n-1).

> **"All volumes" depends on WHERE `backup.sh` runs**, and the two contexts don't save
> the same thing:
>
> - **inside the `backup` container** (the nightly cron) it saves the volumes **mounted**
>   in `compose.ops.backup.yaml`: `gateway-data`, `gateway-uploads`, `nlm-auth`,
>   `nlm-artifacts` (plus `archive-data` for the archive tier). `caddy-data` and
>   `caddy-config` are **commented out** there: with the Caddy ingress the certificates
>   don't get into the nightly backup until you uncomment them by hand (and the file is
>   managed: an update rewrites it). It is **only here** that `descrizioni/<db>.txt` are
>   exported;
> - **on the host** (`./tools/backup.sh` by hand, and the backup `vps1777 update` takes)
>   it asks `docker compose config --volumes` for the volumes, so it follows the active
>   overlays; but the archive volume isn't readable from there and **`descrizioni/` are
>   not exported** — it says so in the log, and the ones in the latest archive backup
>   remain.

The name stays `.tar.age` for both even though the inside is **zstd** (or gzip, if zstd
is missing): the suffix is a contract read by retention, the CLI, `restore.sh` and the
tests. The real format lives in the `.meta` sidecar (`compressione: zstd`) and in the
first 4 bytes of the decrypted stream — `restore.sh` recognizes it from there. By hand,
with your private key: `age -d -i <private key> f.tar.age | zstd -dc | tar -x`.

## Manual backup

```bash
./tools/backup.sh                    # core + archivio SE dovuto (≥ 7 giorni dall'ultimo)
./tools/backup.sh --archivio         # core + archivio COMUNQUE
./tools/backup.sh --senza-archivio   # solo core (è ciò che fa `vps1777 update`)
./tools/backup.sh --prune-only       # SOLO la ritenzione: nessun backup nuovo
# → backups/vps1777-2026-08-29-030000.tar.age
#   backups/archivio/vps1777-archivio-2026-08-29-030000.tar.age
```

One flag at a time: with two flags, or an unknown one, it prints the usage and exits
**2**.

Variables (with their defaults): `BACKUP_DIR=backups/` (where it writes and prunes),
`VOLUMI_ARCHIVIO=archive-data` (logical names of the archive tier),
`ARCHIVIO_OGNI_GIORNI=7`, `KEEP_ARCHIVIO=2`, `KEEP_VERSIONI=3`.

What you do NOT include: container logs (they're in `/var/lib/docker/containers/*/`, managed by the json-file driver with rotation).

The `MANIFEST.txt` inside each archive records the tier (`tier:`), what it contains, the
compression, the deployed version (`VPS1777_TAG` from `.env`) and the bundle's `VERSION`.

## Automatic backup (cron) — on by default

The nightly backup is **on by default**: you don't have to do anything to have it. The
installer turns it on by reading the **declared state** of the features —
`VPS1777_FEATURES` in `.env` (default: `backup,autoupdate`). The `backup` container runs
every night (cron **03:00 UTC**) the **core** tier — and the **archive** tier when due
(every 7 days) — and keeps **7 daily cores + 4 weeklies**, plus **the latest core of each
of the last 3 versions** (read from the `.meta` sidecar), plus **2 archives**, all
`age`-encrypted. `vps1777 check` (the daily timer) warns if the latest archive backup is
more than 14 days old; as long as no archive backup exists at all, that warning doesn't
fire.

> **Why "declared" and not "remembered" — and it's the heart of never-losing-features.**
> Before (up to v0.37.x) the backup was an **opt-in** profile: a reinstall of the VPS
> didn't turn it back on, and nobody noticed — the safety net vanished silently.
> Since **v0.38.0** the choice lives in `VPS1777_FEATURES`: the installer reads it, and
> install, update and rollback **always reproduce the same features**. A reinstall
> doesn't "forget" the backup — it **reproduces it by construction**. And the installer
> closes with the **report**: an `OFF` you didn't ask for **shows up immediately in the
> log**, instead of being discovered months later. The line isn't the same across the
> three routes: the graphical installer writes
> `✓ Feature attive: backup=ON · auto-update sicuro=ON · portainer=OFF`, `deploy.sh`
> closes with `chiave age (backup): <stato>`, and `setup.sh` says
> `Backup: recipient age presente` or `Backup DICHIARATO ma NON ARMATO`.

### Turning the backup on or off

Not with a manual `docker compose` command (that doesn't survive a reinstall): you
change the **declared state**. In the VPS's `.env`:

```
VPS1777_FEATURES=backup,autoupdate    # il default: backup notturno + auto-update sicuro
# togli 'backup' per disattivarlo; l'installer/update applicheranno la scelta e la
# riprodurranno a ogni operazione. Il referto post-install ti confermerà backup=OFF.
```

> ⚠ **The `age` key is required.** The backup encrypts with the recipient's public key
> only (the private one lives **off the VPS**, `v0.26.0`). If `backup=ON` but the key
> isn't configured, the report tells you (in the graphical installer
> `⚠ chiave age da configurare per i backup`, in `deploy.sh` a `MANCANTE` state, in
> `setup.sh` `Backup DICHIARATO ma NON ARMATO`). See below for generating the pair and
> putting the public key on the server.
>
> ⚠ **And after a format / reinstall it must be PUT BACK** — the recipient lives on the
> VPS (`tools/age-recipients.txt`) and a format takes it away; the pair on your PC
> survives and remains the right one (old and new backups open with the same private
> key). The moment you find out is the **first update**: `vps1777 update` demands the
> backup, the backup demands the recipient, and without it it stops fail-safe («backup
> fallito — stack intatto, update annullato» — measured on the clean-slate trial run,
> 27/08/2026). Do NOT generate a new pair on the VPS: copy over the public key from the
> PC (`grep 'public key'` on the key file: `~/.config/vps1777/age-key.txt` if the
> installer generated it, `~/.config/age/keys.txt` if you generated it yourself as
> below).

> **No `docker.sock` (H13).** The backup container **does not mount the Docker socket**
> and **does not install `docker-cli`**: the data volumes are mounted into it **directly,
> read-only** (`/volumes/<nome>`) and `backup.sh` archives them from there. Mounting the
> socket would give a service container root-equivalent control of the host.

## Restore

A full restore is **two restores, one per tier** (order doesn't matter: each one only
touches its own volumes):

```bash
./tools/restore.sh backups/vps1777-2026-08-29-030000.tar.age                     # core
./tools/restore.sh backups/archivio/vps1777-archivio-2026-08-29-030000.tar.age   # archivio
```

> ⚠️ **`restore.sh` looks for the private key in `~/.config/age/keys.txt`** — or wherever
> the `AGE_KEY` variable says. The installers run from the PC (`deploy.sh` and the
> graphical installer) generate it instead in **`~/.config/vps1777/age-key.txt`**: with
> the defaults, a restore done with that key **stops** with `chiave age non trovata:
> …/.config/age/keys.txt` (before touching the stack). The restore runs on the machine
> that has the Docker volumes, so the private key has to be brought there for the time
> of the restore — and removed afterwards (`shred -u`). The gesture that works today:
>
> ```bash
> # la privata copiata sulla VPS, per esempio in ~/.config/vps1777/age-key.txt:
> AGE_KEY=~/.config/vps1777/age-key.txt ./tools/restore.sh backups/vps1777-2026-08-29-030000.tar.age
> ```
>
> (alternatively, copy it precisely as `~/.config/age/keys.txt` and run `restore.sh`
> with no variables). An unencrypted pre-update snapshot asks for no key.

Steps:
1. `docker compose down --remove-orphans` — the `--remove-orphans` matters: without it,
   the ingress container isn't in the model (it lives in an overlay) and **stays up**,
   serving traffic on top of volumes that are being restored. The `backup` container
   stops too (it lives in an overlay as well)
2. Decrypts the archive with your age key and recognizes the format from the bytes
   (zstd / gzip / bare tar — backups older than `0.43.13` are bare tar)
3. Restores volumes + secrets + **configuration** (the core: it also overwrites `.env`,
   `compose*.yaml` and `ingress/` with the ones from the backup) or the archive volumes
4. **It does not restart the stack**: it prints the command to run, with the ingress
   `-f` read from `INGRESS_PROFILE` in the restored `.env`. That command does **not**
   include the feature overlays (`VPS1777_FEATURES`): if the nightly backup is on, add
   `-f compose.ops.backup.yaml --profile ops.backup` yourself, or the `backup` container
   stays off until the next `vps1777 update`. With the default profile:

   ```bash
   docker compose -f compose.yaml -f compose.ingress.tailscale.yaml -f compose.ops.backup.yaml \
     --profile ingress.tailscale --profile ops.backup up -d
   ```

If you **regenerate the archive from the sources** instead of restoring it (re-ingest of
the bundles), you'll find the DB `description` files in the core under
`descrizioni/<db>.txt` — they can be reapplied with `set_description` from the
connector, or from the panel.

Default: interactive (asks for confirmation). Flags:

- `--yes` — no confirmation (for scripts/automation)
- `--volumes-only vol1,vol2` — restores ONLY the listed volumes (CSV, short or full names), skipping secrets/config
- as input it also accepts an **unencrypted snapshot directory** (`backups/pre-update/<dir>`), besides the `.tar.age`
- the `AGE_KEY=<file>` variable points to the private key (default `~/.config/age/keys.txt`)

## Pre-update snapshot

`vps1777 update` creates in `backups/pre-update/` an **unencrypted** local snapshot of the data volumes before every update — auto-rollback needs it, since it cannot depend on the age key. It contains `gateway-data` and `archive-data`; **`nlm-auth` is left out on purpose**: it holds the Google session cookies, and the snapshot is unencrypted (the NotebookLM profile is reloaded from `/admin/nlm`, and it is in the age backup anyway). Snapshots are pruned on every successful update, on every auto-rollback and on every `vps1777 check` (the daily timer): what stays is the latest of n and n-1 (owner decision of 29/08) plus the one in use as the return point. See [UPDATE.md](UPDATE.md). Manual restore:

```bash
./tools/restore.sh --yes --volumes-only gateway-data,archive-data backups/pre-update/<dir>
```

## The age key — where everything lives (important)

The backup is encrypted with the **public** key (the *recipient*); only the **restore**
needs the **private** key. So:

- **The PRIVATE key lives on YOUR PC**, never on the VPS. If you install with
  `deploy.sh` or with the graphical installer, it generates the pair itself on the PC, in
  `~/.config/vps1777/age-key.txt`, and sends only the recipient to the VPS. By hand,
  generate it there:
  ```bash
  age-keygen -o ~/.config/age/keys.txt    # sul TUO computer, non sul server
  ```
- **On the VPS put ONLY the recipient** (the `# public key:` line, `age1…`) in
  `tools/age-recipients.txt`. With that the VPS encrypts the backups without ever seeing
  the private key:
  ```bash
  grep 'public key' ~/.config/age/keys.txt   # → age1…  da incollare in age-recipients.txt
  ```

> **Why it matters**: if the private key sits on the VPS, it sits on the *same disk* as
> the backups — whoever steals or loses the disk has (or loses) both, and the encryption
> protects against nothing. Keeping it on your PC, a dump of the VPS's backup volume
> stays **undecipherable** without you.

> **Offline copy**: the private key is **unrecoverable** if you lose it (and with it,
> all the backups). Keep a safe offline copy (password manager, USB key in a drawer).

**Where you put the backups**: `tools/backup.sh` produces the `.tar.age` files in the
`backups/` folder. **You choose where to take them** (NAS, another disk, cloud): vps1777
transfers nothing automatically, but the gesture is scripted — from **your PC**:

```bash
bash tools/backup-pull.sh vps1777 /media/tu/HD/vps1777-backups
#   <host-ssh>  <cartella di destinazione>   (esce 2 se la cartella non c'è: HD non montato)
bash tools/backup-pull.sh vps1777 /media/tu/HD/vps1777-backups /srv/vps1777
#   terzo argomento facoltativo: il repo sulla VPS (default /home/vps1777/vps1777)
```

It pulls both tiers and the `.meta` sidecars, **without** `pre-update/` (the unencrypted
snapshots never leave the machine) and **without** `--delete`: the VPS prunes for space,
your disk keeps the history. A user timer on the PC can run it daily: when the HD isn't
mounted it exits 2 and says so, instead of copying to the wrong place.

> ⚠️ **Migration (existing installations)**: if you have a private key in
> `~/.config/age/keys.txt` **on the VPS** (versions up to 0.25.0 generated it
> there), **copy it to your PC and then remove it from the VPS**:
> ```bash
> # dal tuo PC:
> scp OPERATOR@VPS:~/.config/age/keys.txt ~/.config/age/keys.txt   # salvala sul PC
> ssh OPERATOR@VPS 'shred -u ~/.config/age/keys.txt'               # toglila dal server
> ```
> The recipient in `tools/age-recipients.txt` stays: existing and future backups remain
> encryptable, and now decryptable **only** with your copy on the PC.

## Rotating the age key (H37)

Rotating the age pair is called for if you suspect the **private key** has been exposed,
or as periodic hygiene. Golden rule: the private key **must never touch the VPS** —
it is generated and kept on YOUR PC; only the new *recipient* goes on the VPS.

```bash
# 1) sul TUO PC — genera la NUOVA coppia (non sovrascrivere subito la vecchia)
age-keygen -o ~/.config/age/keys-new.txt
grep 'public key' ~/.config/age/keys-new.txt        # → age1…  (il nuovo recipient)

# 2) sulla VPS — sostituisci il recipient in tools/age-recipients.txt col nuovo age1…
#    (una riga = un recipient; il commento '# created:'/altri sono ignorati)

# 3) verifica: il prossimo backup si cifra con la chiave nuova
./tools/backup.sh                                   # → un .tar.age nuovo
```

**What happens to the OLD backups.** `age` encrypts an archive toward the *recipients*
listed **at encryption time**: the `.tar.age` files already produced remain encrypted
with the **old** key and can be decrypted **only with the old private key**. Changing
the recipient does **not** re-encrypt them. Therefore:

- **Keep the old private key** (offline) for as long as backups encrypted with it
  exist — that is, until they've left the rotation or you've deleted/re-encrypted them
  yourself. The rotation has no fixed length: 7 dailies + 4 weeklies are about a month,
  but the latest backup of each of the last 3 versions stays until three newer versions
  come out, and the 2 archives stay until the next two rounds. Before retiring it, look
  at what is still in `backups/` (and in the copies on your disk).
- On the PC, promote the new key to active when you're ready:
  ```bash
  mv ~/.config/age/keys.txt ~/.config/age/keys-old.txt   # tienila, non buttarla
  mv ~/.config/age/keys-new.txt ~/.config/age/keys.txt
  ```
- **Soft transition (optional)**: list **both** recipients (old + new) in
  `tools/age-recipients.txt` during the overlap period — that way every new backup is
  decryptable with **either** of the two private keys. Remove the old recipient at the
  end of the transition.
- **Re-encrypting an old backup under the new key** (if you want a single one to
  safeguard): `age -d -i keys-old.txt vecchio.tar.age | age -r age1NUOVO… -o vecchio.rekey.tar.age`.

> The **pre-update snapshots** (`backups/pre-update/`) are **not** age-encrypted
> (they are local, unencrypted snapshots for auto-rollback): the age key rotation
> doesn't concern them.

## Disaster recovery

Scenario: dead VPS, new machine, you want to restore.

```bash
# Su nuova macchina
git clone https://github.com/neo1777/vps1777.git
cd vps1777
# La chiave privata dalla tua copia offline, nel posto dove restore.sh la cerca
# (se è quella dell'installer, age-key.txt, va bene lo stesso: cambia solo il nome)
mkdir -p ~/.config/age && cp /percorso/age-key.txt ~/.config/age/keys.txt
# backups/ non è nel repo (è ignorata da git): va creata, con la sottocartella dell'archivio
mkdir -p backups/archivio
# Copia l'ultimo backup di OGNI livello
scp tuo-backup-server:/percorso/vps1777-2026-08-29-030000.tar.age backups/
scp tuo-backup-server:/percorso/archivio/vps1777-archivio-2026-08-29-030000.tar.age backups/archivio/
# Restore, uno per livello (il core rimette anche .env, compose*.yaml, ingress/ e secrets/)
./tools/restore.sh backups/vps1777-2026-08-29-030000.tar.age
./tools/restore.sh backups/archivio/vps1777-archivio-2026-08-29-030000.tar.age
# restore.sh NON riavvia: lancia il comando che stampa, più gli overlay delle feature
# (vedi «Restore» sopra). Poi togli la chiave privata dalla macchina:
shred -u ~/.config/age/keys.txt
# Lo stack riparte uguale alla data dei backup (l'archivio: alla data del suo, ≤ 7 giorni
# prima; se hai i bundle sorgente, il re-ingest lo porta a oggi).
```
