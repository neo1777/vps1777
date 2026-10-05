# The `vps1777` CLI — every command

> English translation of [`docs/CLI.md`](../CLI.md). Translations are freshness-checked in CI against the Italian source (see [`MANIFEST.json`](MANIFEST.json)): if this note is red in CI, the Italian moved first.

> This page is the guide with the examples; the short-form help is `vps1777 help`
> (or `--help`), and `vps1777 help <comando>` shows a command's options.
> **A test keeps this page aligned with the code** (`tools/tests/test_cli_doc.py`):
> a new command without its section here fails CI.

Where to run it: **on the VPS host**, as the operator user (never as bare root:
if you are root, `sudo -u <operatore> vps1777 …`). Glossary terms:
[GLOSSARIO.md](../GLOSSARIO.md) (Italian).

One option applies to every command and goes **before** the command: `--home FOLDER`, the
root of the repo on the VPS. Without it, the CLI uses `$VPS1777_HOME` and, if that is
missing too, `/home/vps1777/vps1777`.

```bash
vps1777 --home /srv/vps1777 status
```

## vps1777 help

The help, in full or for a single command. It reuses the real parser: what it
prints is, by construction, what the code accepts.

```bash
vps1777 help              # elenco dei comandi
vps1777 help memoria      # opzioni e sotto-comandi di `memoria`
```

## vps1777 check

Checks whether a release newer than the installed one exists (it asks GitHub). It is
the command of the daily timer `vps1777-check-update.timer`, and it is **not read-only**:
before asking GitHub it also does the maintenance and the watches that live on its round.

- **It prunes the pre-update snapshots** (`backups/pre-update/`): what stays is the latest
  of each of versions n and n-1, plus the most recent one overall — the return point of
  the running version ([BACKUP-RESTORE.md](BACKUP-RESTORE.md)).
- **Five watches**, always, with the outcome in the log: whether the service is
  reachable from outside (the port on the host, then the public address — the Funnel or
  `PUBLIC_BASE`; the outcome also goes into `onboarding/raggiungibilita.json`, read by
  `/admin/setup`), the backup **coverage** (distinct days; it warns if it drops below the
  maximum already reached) the **age** of the latest archive backup (it warns past 14
  days; if no archive exists yet, it stays silent), the **age** of the latest core backup
  (it warns past 2 days: a stopped nightly backup no longer prunes, so coverage alone
  doesn't see it) and the **free space** on the backups' disk (it warns below 10%).
  Notifications go out on the transition, once, and again when the thing recovers.
- **It writes the state**: `onboarding/update_status.json` (the admin card and the Mini
  App read it) and `last_check` in `var/state.json`.

With GitHub unreachable it still exits 0: the error ends up in `update_status.json`, not
in a notification.

```bash
vps1777 check             # stampa: installata vs ultima release
vps1777 check --notify    # in più: messaggio Telegram all'owner se c'è una nuova
```

`--notify` sends the new release to Telegram (once per version) and the **state changes**
of the three watches — the fall and the recovery, not the state every day. Without
`--notify` the watches run anyway and only write to the log.

## vps1777 update

Updates to the most recent release (or to an explicit version): backup,
volume snapshots, download of the **signed** bundle (cosign verification), image
pull by digest, restart, health gate — and automatic rollback if anything
doesn't check out. This is the command the `vps1777-auto-update.service` unit
runs: from the host you normally start **that one**, not this by hand.

**The quarantine kicks in only with `--eta-minima HOURS`**, and it is the unit that
passes it (`--eta-minima 48`): it installs the latest release only if it was published at
least 48 hours ago, otherwise it does nothing and tries again on the next round (see
[UPDATE.md](UPDATE.md)). A `vps1777 update` run by hand **with no options has no
quarantine**: it installs the latest release right away, after asking for confirmation.
With `--version` the quarantine is ignored even if you pass `--eta-minima`, and the
explicit target may also be **older** than the installed one (it is the only way to
downgrade; from the admin button it is refused).

The options:

- `--version vX.Y.Z` — explicit target (e.g. an rc).
- `--yes` — no confirmation.
- `--eta-minima HOURS` — the quarantine, only on the path without `--version`.
- `--from-intent FILE` — the intent file written by the admin button: the
  `vps1777-update.service` unit uses it, it is not run by hand. With it there is no
  confirmation.
- `--no-require-cosign` — **emergency route**: skips the bundle signature check (same as
  `VPS1777_REQUIRE_COSIGN=0` in `.env`). `secrets-status` flags it for as long as it stays
  open.
- `--require-cosign` — redundant: the check is already mandatory by default.

What it leaves on disk: in `.env` the tag (`VPS1777_TAG`) and one digest per service
(`VPS1777_DIGEST_<SERVICE>`, e.g. `VPS1777_DIGEST_ARCHIVE_MCP`), written together at step
10; in `onboarding/update_progress.json` the last step (the panels' progress bar) and in
`onboarding/update_journal.ndjson` **one line per step**, even for a successful update —
that is where you read, the morning after, what the nightly auto-update did.

If another update (or a rollback) is already running it exits with **75** ("try again
later"), which the units count as success: it isn't a fault and doesn't send the failure
alert.

```bash
sudo systemctl start vps1777-auto-update.service   # the normal way (with the quarantine)
vps1777 update                                     # by hand: the latest release, right away (asks for confirmation)
vps1777 update --version v0.44.0 --yes             # explicit target, right away (e.g. an rc)
```

## vps1777 rollback

Goes back to the previous version (images + managed files, and in `.env` the tag and
digests of the previous version). With `--with-data` it also restores the volumes from
the pre-update snapshot — that is the invasive option. **It always asks for
confirmation**, with or without `--with-data`: only `--yes` skips it.

It exits **75** if an update or another rollback is running (the same lock as `update`),
and **2** if the rollback is applied but the health gate doesn't turn green (alert on
Telegram).

```bash
vps1777 rollback
vps1777 rollback --with-data --yes
```

## vps1777 status

The state of the update channel: current version, previous one, latest known release
(`latest_known`), time of the last check, the check error if any, and the update in
progress (`update_in_progress`: present from step 10 on, and it stays if an update dies
after that point of no return). With `--json` there is also the release channel
(`channel`); with `--probe` the state of each container and the deep health. It does not
show snapshots or the outcome of the last update: they live in `backups/pre-update/` and
in `onboarding/update_journal.ndjson`.

```bash
vps1777 status
vps1777 status --probe    # interroga anche i container
vps1777 status --json     # per gli script
```

## vps1777 version

The deployed versions: repo tag and the version inside each container of the stack. An
optional image the stack does not use (`caddy-dns01` with the feature off) shows as
"non attivo".

```bash
vps1777 version
```

## vps1777 migrate

The data-migration runner (`migrations/` folder): it lists or applies the
migrations not yet executed. `vps1777 update` applies them on its own; this one
is for inspecting them or recovering by hand.

```bash
vps1777 migrate --pending   # cosa manca
vps1777 migrate --run       # applica
```

## vps1777 bootstrap

One-shot cutover from a legacy installation (pre-update-channel) to the managed
channel: it imports the state, takes the first full backup, hooks up the units.
It is used exactly once, following [INSTALL.md](INSTALL.md). It finds the bundle on its
own when the CLI runs from the extracted bundle; otherwise you point it there with
`--bundle`.

```bash
vps1777 bootstrap --yes
vps1777 bootstrap --bundle /tmp/vps1777-bundle --yes   # bundle estratto altrove
```

## vps1777 archive-ingest

Indexes a file into the search archive. The extension picks the route:

- **text files** (`.md` `.txt` `.markdown` `.rst` `.log` `.csv` `.json` `.jsonl`) →
  **straight to the gateway's indexer**, without NotebookLM;
- **everything else** (scanned PDFs, photos of documents…) → **going through NotebookLM**
  (multimodal/OCR reading). ⚠️ The file is sent to Google.

For the normal formats uploaded from the browser (zip/jsonl/md/pdf-with-text) there is
also the gateway's `/admin/archive` page ([ARCHIVE.md](ARCHIVE.md)).

The options: `--db NAME` (the target DB; default from the file name), `--project LABEL`
(the project label; default the DB name), `--verify` (asks NotebookLM to verify the
transcription), `--nlm` (forces the NotebookLM round even on a text file — for instance a
`.txt` that is the dump of a scan).

```bash
vps1777 archive-ingest scansione.pdf --db documenti --verify
vps1777 archive-ingest note.md --db documenti --project studio   # testo: diretto
```

## vps1777 archive-retag

Re-classifies the `voice` column (whose voice speaks in the content) on the
archive DBs, using the current heuristic. **Dry-run by default**: it prints the
delta and touches nothing; it writes only with `--scrivi`.

```bash
vps1777 archive-retag                     # anteprima su tutti i DB
vps1777 archive-retag --db cc --scrivi    # applica su un DB solo
```

## vps1777 indice-modello

Downloads the model for search by meaning (`intfloat/multilingual-e5-small`, the
official ONNX) **at a pinned revision**, verifies bytes and sha256 of each file and
puts it into the archive volume, where archive-mcp reads it. Idempotent: if the
right model is already there, it downloads nothing. A **different** model already
present (a hand-made export) is not replaced without `--sostituisci`, because the
index built with that one is tied to its fingerprint. With `--dest FOLDER` it
downloads only there: that's how you get it on the PC for the index builder
([RICERCA-IBRIDA.md](RICERCA-IBRIDA.md)).

```bash
vps1777 indice-modello                                         # sulla VPS, nel volume
python3 tools/vps1777.py indice-modello --dest ~/e5-small      # sul PC, dal checkout
```

## vps1777 indice-notturno

Incrementally updates the search-by-meaning indexes that **already exist**, only for the
DBs more recent than their index. The nightly timer runs it; by hand it is for trying it
or turning it on and off. The builder runs in the `indice-notturno` compose service
(memory limit 1300m, one CPU, no network). It never does a first build. Details and
costs: [RICERCA-IBRIDA.md](RICERCA-IBRIDA.md).

```bash
vps1777 indice-notturno --abilita          # accende il timer (opt-in)
vps1777 indice-notturno --disabilita       # lo spegne
vps1777 indice-notturno                    # un giro adesso
vps1777 indice-notturno --db X --tutti     # un DB solo, anche se già allineato
```

## vps1777 archive-migra

Brings the migrations of the derived columns to the DBs **already loaded**, without
an ingest: today, Claude Code tool outputs written as `human` by an indexer older
than 0.52.0 become `speaker='tool'`, and the program's turns (notifications,
local command outputs, compactions) written as `human` before 0.53.0 become
`speaker='system'` ([ARCHIVE.md](ARCHIVE.md)). Where it is missing, it also creates
the project-label index (`idx_project`). The text doesn't
change: FTS and semantic index stay valid. **Dry-run by default**: it measures the
delta on a real transaction, rolls it back and doesn't touch the data; it writes
only with `--scrivi`. The `.vec.db` files (semantic indexes) are not archives and
are skipped.

```bash
vps1777 archive-migra                                  # anteprima su tutti i DB
vps1777 archive-migra --db recupero-20260924 --scrivi  # applica su un DB solo
```

With `--telegram` (and `--db`, required) it gives `speaker` to the messages of a
**Telegram group** already loaded: the owner `human`, the other members `other`. The owner
is given by their Telegram names in `ARCHIVE_TELEGRAM_PROPRIETARIO` in the `.env` (without
it, exit 2); run it only on DBs that are Telegram exports ([ARCHIVE.md](ARCHIVE.md)).

```bash
vps1777 archive-migra --db gruppo-telegram --telegram           # anteprima
vps1777 archive-migra --db gruppo-telegram --telegram --scrivi  # applica
```

## vps1777 secrets-status

Age and expiry of the secrets (keys, tokens, NotebookLM cookies): it lists what
is due for rotation. The same list shows the **cosign emergency route** when it is open
(`VPS1777_REQUIRE_COSIGN=0` in `.env`), with a one-day threshold. It lists separately the
**expected secrets not found** in `secrets/` — `cloudflared_token` only with the
Cloudflare profile (up to 0.62.2 it showed up among the missing ones on every install),
`cf_api_token` only with the `caddy-dns01` feature. With `--notify` it alerts about the expired
ones on Telegram. The result also appears in `/admin/secrets` (from the file
`onboarding/secrets_status.json`).

The **NotebookLM session** row (since 0.73.1) gives the real age of the Google session: it
asks nb1777-mcp, which reads the expiry of the SID cookie and moves it back by 400 days.
Before, it was the date of the cookie file, which reset every time `nlm` rewrote it. It is
"due for reload" when the probe (`docs/NB1777.md` §4) finds it expired; the 14-day threshold
applies only when the probe has no result. If nb1777-mcp does not answer, it falls back to the
file date.

If it finds **no** secret to measure it exits **2**: that is not "all good", it is "I
couldn't look" (wrong path or permissions), and with `--notify` it says so on Telegram.

```bash
vps1777 secrets-status
vps1777 secrets-status --notify
```

## vps1777 memoria

The **local layers of the 1777 memory** ([MEMORIA-1777.md](MEMORIA-1777.md)):
the discipline (the rules, inside the product) plus the two installation files,
`fatti.md` (who the user is) and `errata.md` (corrected falsehoods). Three
sub-commands:

```bash
vps1777 memoria stato                      # versione della disciplina, strati presenti, ack cloud
vps1777 memoria mostra disciplina          # stampa il canonico servito dal tool
vps1777 memoria mostra fatti               # stampa uno strato locale (o: errata)
vps1777 memoria importa fatti mio-file.md  # carica (SOSTITUISCE) uno strato (o: errata)
```

`importa` writes inside the nb1777-mcp container as the right user, atomically,
and verifies the bytes written; an empty file is rejected (it would silently
wipe the good layer).

## vps1777 avvisa-fallimento

Sends «unit X failed» to Telegram with the last journal lines. Not meant to be
run by hand: the systemd units use it via `OnFailure=`.

```bash
vps1777 avvisa-fallimento --unit vps1777-auto-update.service --righe 12
```

## vps1777 campanello

Sends Neo the count of the «things to do» on Telegram (pages and decisions on the frontier,
red spots) with the link to the page. One message per round: the same count never rings
twice. It accepts only numbers and an `https://claude.ai/…` link. The PC calls it over SSH
after every rebuild of the page; `--prova` prints the message without sending it.

```bash
vps1777 campanello --pagine 3 --decisioni 114 --rossi 0 --url https://claude.ai/artifact/… --prova
```
