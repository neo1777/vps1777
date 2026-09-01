# The `vps1777` CLI — every command

> English translation of [`docs/CLI.md`](../CLI.md). Translations are freshness-checked in CI against the Italian source (see [`MANIFEST.json`](MANIFEST.json)): if this note is red in CI, the Italian moved first.

> This page is the guide with the examples; the short-form help is `vps1777 help`
> (or `--help`), and `vps1777 help <comando>` shows a command's options.
> **A test keeps this page aligned with the code** (`tools/tests/test_cli_doc.py`):
> a new command without its section here fails CI.

Where to run it: **on the VPS host**, as the operator user (never as bare root:
if you are root, `sudo -u <operatore> vps1777 …`). Glossary terms:
[GLOSSARIO.md](../GLOSSARIO.md) (Italian).

## vps1777 help

The help, in full or for a single command. It reuses the real parser: what it
prints is, by construction, what the code accepts.

```bash
vps1777 help              # elenco dei comandi
vps1777 help memoria      # opzioni e sotto-comandi di `memoria`
```

## vps1777 check

Checks whether a release newer than the installed one exists (it asks GitHub,
touches nothing).

```bash
vps1777 check             # stampa: installata vs ultima release
vps1777 check --notify    # in più: messaggio Telegram all'owner se c'è una nuova
```

## vps1777 update

Updates to the most recent release (or to an explicit version): backup,
volume snapshots, download of the **signed** bundle (cosign verification), image
pull by digest, restart, health gate — and automatic rollback if anything
doesn't check out. This is the command the `vps1777-auto-update.service` unit
runs: from the host you normally start **that one**, not this by hand.

```bash
sudo systemctl start vps1777-auto-update.service   # la via normale
vps1777 update --version v0.44.0 --yes             # target esplicito (es. una rc)
```

## vps1777 rollback

Goes back to the previous version (images + managed files). With `--with-data`
it also restores the volumes from the pre-update snapshot — that is the invasive
option, and it asks for confirmation.

```bash
vps1777 rollback
vps1777 rollback --with-data --yes
```

## vps1777 status

The state of the update channel: installed version, latest known release,
snapshots, outcome of the last update.

```bash
vps1777 status
vps1777 status --probe    # interroga anche i container
vps1777 status --json     # per gli script
```

## vps1777 version

The deployed versions: repo tag and the version inside each container.

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
It is used exactly once, following [INSTALL.md](INSTALL.md).

```bash
vps1777 bootstrap --yes
```

## vps1777 archive-ingest

Indexes a file into the search archive **going through NotebookLM**
(multimodal/OCR reading): it is the route for the valuable document the normal
ingest can't read — scanned PDFs, photos of documents. ⚠️ The file is sent to
Google. For normal formats (zip/jsonl/md/pdf-with-text) use the gateway's
`/admin/archive` page ([ARCHIVE.md](../ARCHIVE.md) (Italian)).

```bash
vps1777 archive-ingest scansione.pdf --db documenti --verify
```

## vps1777 archive-retag

Re-classifies the `voice` column (whose voice speaks in the content) on the
archive DBs, using the current heuristic. **Dry-run by default**: it prints the
delta and touches nothing; it writes only with `--scrivi`.

```bash
vps1777 archive-retag                     # anteprima su tutti i DB
vps1777 archive-retag --db cc --scrivi    # applica su un DB solo
```

## vps1777 secrets-status

Age and expiry of the secrets (keys, tokens, NotebookLM cookies): it lists what
is due for rotation. With `--notify` it alerts about the expired ones on
Telegram. The result also appears in `/admin/secrets`.

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
