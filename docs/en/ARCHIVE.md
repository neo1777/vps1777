# Search archive (archive1777)

> English translation of [`docs/ARCHIVE.md`](../ARCHIVE.md). Translations are freshness-checked in CI against the Italian source (see [`MANIFEST.json`](MANIFEST.json)): if this note is red in CI, the Italian moved first.

`archive1777` is a full-text search engine (SQLite FTS5 + BM25) over your
corpora: chats, sessions, notes, documents. **It starts empty**: you fill it,
from the admin panel or from the command line. Loaded DBs are searchable
**immediately**, with no restarts, through the **15 MCP tools** of `archive-mcp`
(see [Searching — the MCP tools](#searching--the-mcp-tools)): from search
(`search`, `search_ibrida`, `count`) to reading (`get_context`,
`get_conversation`) up to session cards and lineages (`get_session`,
`get_stirpe`).

> **Translation.** This page has a complete English translation in
> [docs/en/ARCHIVE.md](ARCHIVE.md) — the one you are reading — kept aligned by a CI
> test: whoever edits the Italian must update the English too.

## Sensitive data and privacy — read before uploading

The archive indexes **everything you upload, verbatim** (filtering happens
downstream, not at ingest: an ingester that drops half the file lies about what
it contains). Your chats and sessions do contain **personal data and secrets**:
emails, phone numbers and — it happens — **credentials, SSH keys, IPs and tokens
pasted while working**. Since v0.20.0 the **full content** of messages is indexed
as well (the *actions*: commands run, files opened, tool output), so those
secrets become **searchable** too. That is correct — you uploaded them — but it
is worth knowing.

**The main protection is ACCESS.** The archive is reachable only through the
gateway (**OAuth 2.1 + path-secret**) and is **owner-only**: without the MCP tokens
nobody gets in. The DB on disk is **in clear text**: there is no content
encryption.

**On output there is a partial redaction, and it must be stated at its true size**
(since 02/08/2026, on by default; it is switched off only with `ARCHIVE_REDACT=0`
on the `archive-mcp` service). Every response of every tool goes through a masking
step that covers:

- **identifiers in a recognisable format** — emails and phone numbers — wherever
  they appear, transcripts included;
- the **account's personal-data values** (the `account:user` rows of the claude.ai
  export), even when they are typed by hand inside a message.

**It does not cover**: tokens, keys, passwords, IPs, postal addresses, names of
third parties that never appeared in the account data. *Anyone with access to the
archive finds those secrets with a query.* The phone-number pattern does **not** apply
inside a canonical uuid (8-4-4-4-12 hex) and leaves valid ISO dates with the time
(`2026-09-05 13:10`) and the `YYYYMMDD-HHMMSS` shape of bundle names intact: three strict
exemptions, since 0.51.1 (before, a uuid with digit-only groups and a date with the time
came out as "[telefono redatto]", "[phone redacted]"; measured live on 24/09/2026). Since
0.51.4 the date with the time also holds with minutes and seconds written with dashes or
dots, as in screenshot names (`Schermata del 2026-09-24 18-41-38.png` came out as
"Schermata del [telefono redatto]-38.png"); minutes and seconds must be 00-59.

**An account-data value that is public by your choice** is exempted by name, with
`ARCHIVE_REDACT_ESENTI` in `.env` (comma-separated values, case-insensitive; since
0.51.4). The case that gave rise to it: the claude.ai account's `full_name` was the
author's public handle, the same name as their repositories, and the redaction removed it
from every path and every label (`corpus-<handle>/…` came out as
"corpus-[dato personale redatto]/…", "[personal data redacted]"). Empty by default: the
policy does not change until you write it. It applies only to known values: an email or a
phone number in a recognisable format stays redacted even if you exempt it.

**The practical rule** (as long as the archive stays yours and the models *you*
give the connector to, this is a defensible choice):

- Don't upload material you don't want to find again searchable in clear text.
- If you prepare an export **to share or publish**, clean it *before* uploading —
  the archive won't do it for you.
- The day the archive were to be **shared, exposed or fed to a third-party
  model**, a complete redaction or encryption strategy would be needed first
  (masking of secrets, or a `sensitive` mark with exclusion by default): **it is a
  decision to take before growing the archive in that direction, not after.**

## Filling it from the admin — `/admin/archive`

Admin panel → **Archive** tab. You upload a source, it is indexed into an FTS5 DB
and becomes searchable. Automatic dispatch by extension:

| Format | What it indexes |
|---|---|
| `.zip` | recognised by its **content**, not its name. In order: the **Session Recovery 1777 bundle** (if it has `MANIFEST.json` **and** at least one `sessions/…` member — see [the bundle](#the-session-recovery-bundle)); the **claude.ai** account export (`conversations.json` + `design_chats/` + `projects/docs` + `memories` + `users.json`/`login_history.json` — **single** or **split into 5 zips by category**, the format claude.ai has delivered since 29/08/2026: each zip is recognised on its own, all of them go to the same *DB name*, see below); the **Telegram Desktop** chat export — `result.json` *or* `messages*.html`, also zipped as a `ChatExport_*/` folder. **Fallback**: a zip that is none of these but contains `.md`/`.txt` documents (and code, config, readable text) is indexed document by document, like loose files |
| `.jsonl` | **Claude Code** session (`~/.claude/projects/<project>/<id>.jsonl`) |
| `.json` | **Telegram Desktop** export (*Machine-readable JSON* format) |
| `.pdf` | document **with text** (extracted via `pypdf`) |
| `.md` / `.txt` | generic text/markdown (a bridge for the output of other tools) |
| `.db` | drop-in of an already indexed SQLite archive (schema validated) |

> **claude.ai export in 5 zips (since 29/08/2026).** The account no longer
> delivers a single file: it gives a `manifest-<id>-<ts>.json` with 5 **one-shot**
> links and the 5 zips by category — `conversations-000.zip`, `projects-000.zip`,
> `design_chats-000.zip`, `memories-000.zip` (persistent memory: `conversations_memory`,
> `project_memories` and the `memory_files` `/areas/*.md`), `light_metadata-000.zip`
> (`users.json` + `login_history.json`, the logins: one row per event,
> `account:login`). The `-NNN` suffix is the **part**: a large category can arrive
> in several zips. The manifest is **not** uploaded (it only holds the links).
> From the admin: select the 5 zips together (the *source* field accepts several
> files) with the same *DB name* — e.g. `claude-ai-<ddmmyy>`, one DB per export, by
> convention; from the CLI: `for z in *-000.zip; do python3 services/gateway/app/archive_indexer.py "$z" claude-ai-<ddmmyy>.db; done`.
> Order doesn't matter and re-uploading doesn't duplicate (idempotent by uuid).
> Measured on the first export in this format: 13,920 records in 15 s, 1.2 GB of
> peak RAM.
> ⚠️ Decompressed, `conversations.json` is at 58% of the per-member cap (297 MB out
> of 512): when it exceeds it the ingest **stops with an explanation**
> (`MAX_MEMBER_BYTES`), it doesn't truncate.

> The Telegram Desktop chat export works **as is**: compress the `ChatExport_*`
> folder into a zip and upload it — both the **HTML** format (the default,
> `messages.html`) and the **JSON** one (`result.json`) are indexed. If both are
> present, JSON wins (more faithful). One caveat: don't mix HTML and JSON of the
> *same* chat in the same DB — the dedup keys differ and messages would be
> duplicated. An unrecognised zip, or one with no extractable messages, is
> **rejected with a clear error** — never an "ok, 0 records".

Form fields: **DB name** (empty = from the file name), **project** (label; empty =
inferred from the source) and **description** (optional: what the archive is for /
what it contains — it shows in the card and in `describe_databases`, and can be
updated later with the MCP tool `set_description`). Re-uploading to the same DB
name doesn't duplicate (dedup by id); different sources on the same name
accumulate.

> ⚠️ **The gateway deletes the zip after ingest**: on the VPS only what entered the
> DB remains (rows, tables, tombstones). What the indexer doesn't read cannot be
> recovered later — that is why every discarded member leaves a tombstone saying
> why.

## The Session Recovery bundle

The bundle is the zip that the local **Session Recovery 1777** app (*Recupero
Sessioni 1777*) produces with "download everything": the Claude Code sessions of a
disk, deduplicated, with everything needed to find them again. The app lives
outside this repo; here is the side that **reads** it. The indexer recognises it by
`MANIFEST.json` **plus** at least one `sessions/…` member, and checks for it before
the other formats (it contains `.md` files that the "zip of documents" fallback
would swallow, ignoring sessions and logs).

### What is in the zip, and what it becomes

| member | what it becomes | `project` label |
|---|---|---|
| `sessions/<sessionId>.jsonl` (and `<sessionId>__fN.jsonl` for the strands) | conversations: one row per user/assistant message, native uuids, native `parent_uuid`; plus the titles (`sender='title'`) and attachments (`sender='attachment'`) | last folder of the session's cwd |
| `subagents/<sessionId>/agent-<hash>.jsonl` (since 16/09/2026) | sub-agent conversations; a sub-agent's user rows are `sender='mandato'` (the machine wrote them) | `subagent:<cwd-label>` |
| `mcp-logs/<sessionId>/<server>/…` | MCP server logs, in 4000-character chunks | `mcp-log:<server>` |
| `workfiles/<encoded-cwd>/…` | artefacts of the working folders: text and code in chunks, PDFs with text, images via OCR, nested zips (one level); a session backup (a Claude Code `.jsonl`) becomes a conversation; binaries leave a `non-testo` tombstone | `workfile:<encoded-cwd>/<first subfolder>` |
| `documents/…` (since 25/09/2026) | the **documents** that the app's `export` delivers next to the sessions (not conversations): the same pipeline as `workfiles/` — text and code in chunks, PDFs, images via OCR, nested zips, content sniffing; binaries leave a `non-testo` tombstone with `source` `bundle-documents`. A zip of the export folder has `MANIFEST.json` and `sessions/`, so it is a bundle: before, every document ended up in `membro-sconosciuto` | `document:<first subfolder>`, or `document` for a file in the root of `documents/`. The app (since 25/09/2026) writes `documents/<family>/<short-md5-of-the-path>__<name>`: the label is the family — `document:testo`, `document:codice`, `document:config`… —, never the original path |
| `recupero/…` (since 24/09/2026) — or the bridge `workfiles/_recupero-1777/…` | session, lineage and memory cards as rows; three `.tsv` files as tables — see [the `recupero/` prefix](#the-recupero-prefix--contract-r1) | `recupero:sessioni` · `recupero:stirpi` · `recupero:memorie` |
| `inventario/inventario-sessioni.tsv` | the session index as text, in 4000-character chunks | `inventario` |
| `inventario/inventario-sessioni.json` | **not** indexed: a tombstone saying whether its data came in another way — see [the tombstones](#tombstones-what-doesnt-get-in-and-why) | — |
| `MANIFEST.md` | the manifest's prose, in chunks | `manifest` |
| `MANIFEST.json` | does **not** become text: three keys go into the `meta` card — see [the manifest](#the-manifest-in-the-meta-card) | — |
| any other member | `membro-sconosciuto` tombstone: the bundle has grown beyond the indexer | — |

Conversation rows (from `sessions/`, `subagents/` and from the session backups found
in `workfiles/`) and the rows of the `recupero/` cards leave a **sighting** (table
`sightings`: uuid + member path). It is the only link between a uuid and the file it
came from — for instance between a message and its session's sessionId
(`sessions/<sessionId>.jsonl`), or between a sub-agent and the parent session. The
chunks of MCP logs, documents, the inventory and `MANIFEST.md` don't leave one: their
path is in the uuid key and, for documents, in the first line of the text.

### The `recupero/` prefix — contract R1

Until 24/09/2026 the **state** of each session, the **lineages** (the sessions that
continue into one another: clone, `/clear`, compact…), the **edges** between
sessions and the **memories** written while working travelled only inside
`inventario/inventario-sessioni.json`, which the indexer discarded as "redundant".
With the zip deleted after ingest, **they reached the VPS and vanished**. And the
sessionId was not a column: the archive had no "session" entity.

The `recupero/` prefix carries them in a form the indexer reads, according to a
versioned contract (**R1**) written by the side that produces them (the app's
CONTRATTO-RECUPERO.md file). Only `.md` and `.tsv`, never json:

```
recupero/sessioni/<sessionId>.md          one card per session delivered in the bundle
recupero/stirpi/<lineage-id>.md           one card per lineage touching the bundle
recupero/memorie/<k10>__<name>.md         the content of a memory (k10 = md5 of the ORIGIN path)
recupero/sessioni.tsv                     one row per delivered session
recupero/archi.tsv                        one row per edge touching a delivered session
recupero/memorie.tsv                      one row per delivered memory
```

**The `.md` cards** start with a front-matter between two `---` lines, made of
`key: value` lines (one value per line, no nested YAML), then the markdown body,
which is the text to index. Three keys are mandatory: `contratto` (must be `R1`),
`tipo` (`sessione` · `stirpe` · `memoria`, consistent with the folder) and the
field that identifies the card (`sessionId` · `id` · `path`). An example session
card (made-up data; the keys are the contract's, in Italian):

```
---
contratto: R1
tipo: sessione
sessionId: 0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0
titolo: sessione di prova
cwd: /percorso/del/progetto
first_ts: 2026-09-10T10:00:00.000Z
last_ts: 2026-09-10T10:05:00.000Z
last_uuid: <uuid dell'ultimo messaggio user/assistant>
file: sessions/0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0.jsonl
stato: turno-chiuso
stato_fonte: transcript
stirpe: <id della stirpe>
stirpe_pos: 1
n_commit: 2
n_fili: 1
---
# sessione di prova

## Stato
…
## Ultime parole
…
```

The body of a session card carries **Stato** (state), **Ultime parole** (the last
words of the user and of the assistant, marked `[verbatim]`), **Fili aperti** (open
threads), **Commit**, **Memorie scritte** (memories written) and **Stirpe**
(lineage). A lineage card carries one line per member and one per edge, with the
**full** sessionIds (so a sid, or its first 8 characters, finds the edge with FTS).
A memory card carries the memory's text as it is.

**The `.tsv` files**: first line = header, TAB-separated fields, no TAB or newline
inside values. Columns are read **by name**.

**Versions.** An extra field in the front-matter, or an extra column at the end of
a `.tsv`, doesn't change the version: the indexer ignores them. A field removed,
renamed or with a different meaning is an **R2** contract, and this indexer rejects
it with a tombstone that says so (it doesn't read it halfway).

### The bridge `workfiles/_recupero-1777/`

The app picks the root by reading `BUNDLE_PREFISSI_INDICIZZATI` from **its own**
copy of the indexer: if that copy doesn't know `recupero` yet, it puts the same
files under `workfiles/_recupero-1777/` (the "bridge", level 0 of the contract),
which even an old indexer reads — as text. `MANIFEST.json` says which root was used
and why.

**For this indexer the bridge is an alias of `recupero/`**: same reading, tables
included. Rows come out **identical** from either root: `recupero:*` labels, uuids,
text and sightings use the canonical form `recupero/…`, so the same content arriving
by the two roads doesn't double (verified: the same bundle from the two roots gives
the same DB, ingest dates aside). The **tombstones**, instead, name the real member
name in the zip, which is what whoever reads them looks for.

### Cards become rows

| card | `project` | `sender` | `uuid` | `ts` | `parent_uuid` |
|---|---|---|---|---|---|
| session | `recupero:sessioni` | `recupero` | `_uid("recupero", member, idx)` for each chunk | `last_ts` **+ (idx+1) ms** | chunk 0: **`last_uuid`** (the session's last message); the others: the previous chunk |
| lineage | `recupero:stirpi` | `recupero` | `_uid("recupero", member, idx)` | `last_ts` if present, otherwise the member's date in the zip; + (idx+1) ms | chunk 0: none; the others: the previous chunk |
| memory | `recupero:memorie` | `memory` | `_uid("recupero-memoria", path)` — **one** row | `mtime` | none |

`_uid(...)` is the sha1 of the parts (the indexer's deterministic uuid), and
`member` is always the canonical form `recupero/…`. Four properties follow:

- **The card is a leaf of the thread.** Chunk 0 of a session card hangs from the
  conversation's last message. `get_conversation`, though, finds it **by member
  name** (`recupero/sessioni/<sid>.md`), not by walking up `parent_uuid`: clones share
  uuids, and a clone's card hanging from a shared message ended up at the end of the
  wrong chat (measured on 26/09/2026). From any message of the session you reach the
  card, and from the card the whole chat.
- **The card comes after the last message.** `get_conversation` orders by
  `(ts, uuid)`: with the same ts as the last message, the sha1 would decide the
  order. So chunk `idx` has `last_ts` + (idx+1) milliseconds, written in ISO with
  `Z` and milliseconds (`2026-09-10T10:05:00.000Z` → `…00.001Z`, `…00.002Z`). If
  `last_ts` has no milliseconds it starts from the **next second** (`…05:00Z` →
  `…05:01.000Z`), because as a string `…00.001Z` would sort *before* `…00Z`. A
  format the indexer doesn't recognise is left as it is: no time is made up.
- **8000-character chunks.** A session card (~4 KB by contract, 4.5 KB measured on
  a real one) stays in a single row; a long lineage is split.
- **The indexed text starts with `[<member>]`**, like the bundle's documents: the
  member carries the sessionId, which is thus found by FTS even when the body
  doesn't repeat it.

All card rows have **`ts_source='data-export'`**: a card is a **snapshot** (it
changes between one bundle and the next, and the outgoing version goes to
`revisions`), not an event said once. Whoever computes an archive's "most recent"
filters negatively (`WHERE ts_source <> 'data-export'`), so cards don't move it.
**`speaker` is `unknown`** (a card has no sender) and **`voice` is `unknown` with the
`scheda_recupero` flag**: the card quotes word for word the user's last sentences,
and classifying it as pasted text (its headings and bold text would make it come out
`pasted_ai`) would be the most expensive false positive. Memories stay with the
heuristic, like claude.ai memories. Every row leaves a **sighting** with the
canonical member.

**A card rewritten with fewer chunks leaves no orphans.** If the new version of a
card (or of a memory) has fewer chunks than the one already in the DB, the extra
rows **of the same member** (found from its sightings, and only with the same label)
leave `messages`, FTS and the sightings; their last version stays in `revisions`, as
for any rewritten row. A memory changed between two bundles is the same row with new
text: the old version goes to `revisions`, no duplicate.

### The `sessioni`, `archi`, `memorie` tables

The three `.tsv` files do **not** become text: they fill three tables, one row per
file row (`INSERT OR REPLACE` on the key, with the ingest date). The columns are the
contract's, in the same order:

**`sessioni`** (sessions) — key `(sessionId, file)`. One row per delivered **file**: a
session in a collision has several **strands** (*filoni*) with the same `sessionId`
(`sessions/<sid>.jsonl`, `sessions/<sid>__f2.jsonl`…), and each one has its own row.
Up to 0.51.1 the key was `sessionId` alone and only one survived (measured on the
first real bundle: 1,300 rows for 1,303 cards). A row with an empty `file` leaves the
`recupero-tsv-fuori-contratto` tombstone, like one with an empty `sessionId`.

| column | content |
|---|---|
| `sessionId` | the session's full uuid |
| `titolo` | the title (custom-title or first message, one line) |
| `cwd` | the main working folder |
| `first_ts` · `last_ts` | first and last conversation timestamp (ISO UTC, `Z`) |
| `last_uuid` | the uuid of the last user/assistant record of the delivered copy — the card's parent |
| `file` | the zip member holding the conversation (`sessions/<sid>.jsonl`, `__fN` for strands) |
| `stato` · `stato_fonte` | where the session stopped, and from which source that is known (process / job / transcript) |
| `stirpe` · `stirpe_pos` | the lineage id and the session's position in it (empty if it is alone) |
| `n_commit` · `n_fili` | how many commits and how many open threads it carries |
| `ingest_date` | when it came in (or was rewritten) |

**`archi`** (edges) — key `(da, a, relazione, via)`, the same as the `archi` table
of the app's inventory: the same edge seen by two bundles is ONE row.

| column | content |
|---|---|
| `da` · `a` | the two sessionIds (from, to) |
| `relazione` | what kind of link it is (for instance `clone`, `continua`) |
| `via` | which signal it was rebuilt from |
| `livello` · `prova` · `voce` | how strong it is, the evidence, who asserts it |
| `peso` | a number (REAL) — the weight |
| `chiusura` | `1` if the edge counts for the lineage (INTEGER: `chiusura=1` finds the rows) |
| `bundle_scan` · `ingest_date` | when the app computed it, when it came in |

**`memorie`** (memories) — key `path`.

| column | content |
|---|---|
| `path` | the memory's **origin** path (not the member) |
| `sistema` · `livello` | which memory system, and how it was recognised (structural · by name) |
| `md5` · `mtime` | fingerprint and modification date (ISO UTC, `Z`) |
| `scritta_da` | the sessionIds that wrote it, comma-separated |
| `membro` | the `recupero/memorie/…` member carrying the text (the row in `messages`) |
| `ingest_date` | when it came in |

The three tables are `CREATE TABLE IF NOT EXISTS`: **every** DB receives them,
empty, at its first ingest with an indexer of this version (a claude.ai export too),
and stays readable by earlier versions. A DB never re-ingested since doesn't have
them: that is the difference the `get_session` and `get_stirpe` tools declare.

### The manifest in the `meta` card

`MANIFEST.json` doesn't become text (its prose is already carried by `MANIFEST.md`),
but three of its keys go into the DB's `meta` card, as json:

| key in `meta` | from the manifest | what it is for |
|---|---|---|
| `bundle_generated` | `generated` | when the bundle was made: it dates the other two values |
| `bundle_previsione_ingest` | `previsione_ingest` | how many rows the app expects in the table (by prefix too): the acceptance-test yardstick, now comparable inside the DB |
| `bundle_recupero` | `recupero` | contract version, root used (`recupero/` or the bridge) and why, how many cards and `.tsv` rows |

The card speaks of the **last** bundle read: any of these keys that the new manifest
doesn't carry is **removed**, because it would stay speaking for a bundle that
didn't say it. The member leaves the `manifest-in-meta` tombstone, which says where
it went; an unreadable json leaves `manifest-illeggibile`, and the ingest of the
sessions goes on.

### Tombstones: what doesn't get in, and why

A member that doesn't get in **doesn't vanish**: it leaves a tombstone in the
`skipped` table, with a reason (`reason`) and a detail (`detail`) that starts with
the member's name and says why.

| `source` | `reason` | when |
|---|---|---|
| `bundle` | `membro-sconosciuto` | a member (also inside `recupero/`) the indexer can't read: a `count(*)` on this reason tells whether the bundle has grown beyond the indexer |
| `bundle` | `manifest-in-meta` | `MANIFEST.json` read: three keys in `meta`, the rest not indexed |
| `bundle` | `manifest-illeggibile` | `MANIFEST.json` isn't json, or isn't an object |
| `bundle` | `non-indicizzato-ridondante` | the inventory json, when the bundle has `recupero/` (or the bridge): its data came in from there |
| `bundle` | `non-indicizzato-senza-recupero` | the inventory json, when the bundle has NEITHER `recupero/` nor the bridge: that bundle's lineages, edges and memories are **not** in the archive (and the zip has been deleted) |
| `bundle-recupero` | `recupero-senza-front-matter` | a card without the first `---`, or with a front-matter that never closes |
| `bundle-recupero` | `recupero-front-matter-malformato` | a front-matter line without `:` — the format is strict on purpose |
| `bundle-recupero` | `recupero-contratto-ignoto` | `contratto` missing or other than `R1` (for instance an `R2` this indexer can't read yet): the card doesn't get in |
| `bundle-recupero` | `recupero-fuori-contratto` | `tipo` inconsistent with the folder, or the field identifying the card is missing |
| `bundle-recupero` | `recupero-tsv-fuori-contratto` | a `.tsv` whose header lacks a contract column (the whole file doesn't get in: no half-filled tables), or one of its rows with the wrong number of fields or an empty key (only that row is skipped, with its line number) |
| `bundle-workfiles` | `non-testo`, `pdf-*`, `ocr-*`, `zip-*`, `membro-oltre-tetto`, … | a working file with no text to read, or that OCR / opening couldn't read |
| `bundle-documents` | the same as `bundle-workfiles` | the same, for a member of `documents/` |
| `claude-code` | `non-message`, `no-uuid-o-ts`, `empty` | a session record that isn't a message, has no uuid or ts, or is empty |

```sql
-- what did not get into this DB, by reason
SELECT source, reason, count(*) FROM skipped GROUP BY 1, 2 ORDER BY 3 DESC;
```

## Managing DBs — list and deletion

For each DB the page shows the **full card**: description, messages, distinct
labels (the "provenances": chat titles, `project:<name>`, `design:<name>`…), the
main labels, size on disk and last update.

The **Delete** button (with confirmation) removes the DB: search on that archive
stops immediately (archive-mcp notices by itself, scan-mode) and the action ends up
in the audit log. It is **irreversible** — to *reset* an archive (e.g. reload it
from scratch after the source changed): delete it and upload the source again with
the same DB name. List and deletion are also available from the **Mini App**
(Archive tab).

## Searching — the MCP tools

`archive-mcp` exposes **15 tools** over MCP (usable from the claude.ai connector
and from the Mini App). All of them go through the output redaction described
above.

| Tool | What it does |
|---|---|
| `search(query, db_name, limit, …)` | FTS5 search; returns `{db, uuid, project, ts, rank, snippet, snapshot}`. When searching **all** DBs the same uuid arrives **once**, with `anche_in` listing the other archives that contain it (no limit wasted on copies). Filters `since`/`until`, `project`, `speaker`, `voice` |
| `search_ibrida(query, db_name, limit, query_fts, …)` | search **by meaning**: FTS5 + vectors fused (RRF). For when you remember the meaning and not the wording; it needs the embedding model and a `<db>.vec.db` index on the volume, and if they are missing **it says so** instead of falling back to FTS5. See [RICERCA-IBRIDA.md](RICERCA-IBRIDA.md) |
| `count(query, db_name, …)` | how many messages match (not limited): `{total, per_db}`; if a term **collapses** it adds `warnings` |
| `check_term(term, db_name)` | diagnoses whether a term with `+`/`#` (`C++`, `C#`, `g++`) is searchable or **collapses** onto its prefix — it asks the index, not the docs |
| `get_context(uuid, db_name, before, after, max_chars)` | the messages **around** a result, with the **full content**; on Claude Code sessions the neighbours come from the **session file** (the matched row says so in `vicini_da`); elsewhere, if the message is in a thread, from the **same thread** (`parent_uuid` edge), not from mere closeness in time. `max_chars` (0 = whole) truncates each row **saying so in the text** — on giant hub messages the full payload killed the connection. A row **without text** (a tool_use, the output of a command) also carries **`tools`**, the actions that are its content (since 0.52.0: before, it came out empty), truncated by `max_chars` like the text |
| `get_conversation(uuid, db_name, limit, max_chars)` | the **whole thread** containing the uuid (`parent_uuid` tree, ancestors + descendants, in `(ts, uuid)` order) — to **read a chat** from start to end, not just the ±N window; `max_chars` and `tools` as in `get_context`. On Claude Code sessions it is the whole **session file** (`conversazione_da`), and with bundles carrying `recupero/` the session's card comes **last** |
| `get_session(sessionId, db_name, limit, max_chars)` | everything the archive knows about **one** Claude Code **session**: the `sessioni` row, the **card**, the conversation's messages, the edges, the lineage — see [Sessions and lineages](#sessions-and-lineages--get_session-and-get_stirpe) |
| `get_stirpe(sessionId, db_name, limit, max_chars)` | a session's **lineage**: the closure over the edges with `chiusura=1`, with each member's data — see [Sessions and lineages](#sessions-and-lineages--get_session-and-get_stirpe) |
| `list_projects(db_name, top)` | the `project` labels with their counts — to **browse** the archive, not just search it |
| `archive_stats(db_name)` | histogram of messages per **year** — *when* the archive is dense, worth knowing before searching. The **first** call on a DB scans everything (tens of seconds on large archives); later ones are **memoised per snapshot** |
| `list_databases(schede)` | the names of the loaded DBs; with `schede=true` each entry carries its identity card (**role**, rows, date range, description) — choosing the DB is the first fork of every search |
| `describe_databases()` | card per DB: rows, date range, labels, **snapshot** (freshness), **description**, **ruolo** (role) |
| `check_integrity(db_name)` | integrity of the archives: `ok` · `sporco` (dirty: hot journal, the writer died halfway) · `corrotto` (corrupt) · `non_misurabile` (not measurable). It costs a scan per DB: call it when a result looks odd, not on every search |
| `set_description(db_name, description)` | writes/updates the archive's **description** (touches the card, never the messages) |
| `set_ruolo(db_name, ruolo)` | declares the archive's **role** from a closed vocabulary — see below |

### An archive's `ruolo` — routing without reading prose

With many DBs loaded, "which archive to query" is the first question of every
search. As long as the answer lives only inside the `description` — "★ primary",
"⚠️ superseded, use that other one" — it is written in a language a human reads and
a client doesn't: **a rule for the machine written in prose half-works, silently.**
The `ruolo` (role) field makes it readable.

| value | meaning |
|---|---|
| `primario` | the **current** source of that side: if you don't choose, it is the one that must answer |
| `fotografia` | an **older** version of the same side, kept for history: search here when you care about how it *was* |
| `riscontro` | not queried to **find** but to **verify**: intentional redundancy, twins re-ingested with a different indexer, probe DBs with a known-case-that-must-succeed |
| `riservato` | personal material: out of technical tasks without an explicit request. It is a **declaration, not a lock** — no tool excludes it by itself |
| `non dichiarato` | **nobody has said anything** about that DB. It doesn't mean "unimportant", and it must not be guessed from the name: it is the value you read when `set_ruolo` was never called (or when the declaration was withdrawn by passing `""`) |

> **Additive, and for now only informative.** `search` and `count` without
> `db_name` touch **all** DBs as before, `riservato` included: whoever wants to
> restrict to primaries reads the field and passes `db_name`. Making the default
> draw only from primaries is a **contract change** — it would change the meaning
> of a zero ("0 on primaries" ≠ "0 everywhere") — and it lives in its own issue.

> **Concurrency.** The server serves **2 searches at a time** (`search`,
> `search_ibrida`, `count`, `archive_stats`, `get_session`, `get_stirpe`): extra
> requests queue by themselves instead of dying in a timeout. Whoever orchestrates
> several calls should group them in pairs.

> **Sources without a thread.** On chunked documents (pdf/telegram/memory) and on
> historical DBs `parent_uuid` is empty: there `get_conversation` falls back to the
> archive's linear order and `get_context` to closeness in time. A faithful
> reconstruction of the chunk order (a `seq` column) is a **declared evolutionary
> step**, out of scope today.

> **Claude Code sessions: the file, not the chain.** In Claude Code transcripts
> every record points to the previous one, even when the previous one is a record
> the indexer does not keep (a turn's duration, an empty attachment, a
> metadata-only message). In the DB that parent is missing: on the primary of
> 24/09/2026 it was missing for **82,876 rows out of 260,072 (32%)**, and a
> message's thread often shrank to the message itself — `get_context` returned just
> it. Since 26/09 the two tools, for rows seen in a `sessions/` or `subagents/` file
> (`sightings` table), use **that file**: the real conversation, with no gaps and
> without the other parallel sessions of the same project. Several copies of the
> same uuid (the `__fN` strands): the main file wins. Re-linking the chain at
> ingest (skipping the records not kept) remains a **declared** step, not done.

**FTS5 query syntax** (the same rules are in the docstring the model reads before
searching):

- Operators **in UPPERCASE**: `AND`, `OR`, `NOT`, `NEAR(a b, 5)` — in lowercase
  they become terms.
- No stemming, so **both languages**: `errore OR error`.
- Name families with the **prefix**: `palant*` (attached numbers don't split:
  `1777` doesn't find `N1777`).
- Terms with special characters (`- . / @ : # '`) **in double quotes**:
  `"flutter-elinux"`, `"0.7.9"`. In *smart* mode (the default) the server quotes
  them itself; with `raw=true` the query passes untouched (for NEAR/complex
  parentheses). **But quoting isn't enough for the suffix** — see the box below.
- `sort`: `rank` (relevance, default), `newest`, `oldest`. Filters `since`/`until`
  (ISO) and `project` (exact label). Across several DBs the `limit` is **global**.

> **Talking error surface.** A malformed query does **not** return an empty list
> (which would be indistinguishable from "no match" — a silent false negative): it
> raises an error explaining how to fix it. The *zero protocol* still holds: 0
> results don't prove absence — retry quoting the term before concluding "it isn't
> there".

> **Terms that COLLAPSE (`C++`, `C#`, `g++`) — the 11/07 defect.** The `unicode61`
> tokenizer treats `+ #` as **separators**: a term like `C++` loses its suffix and
> becomes the token `C`, extremely common (SVG coordinates, copyright, degrees).
> `count("C++")` doesn't come back empty — it comes back with **thousands of silent
> false positives**: that is how the false memory "Neo, C++ programmer" was born. It
> is the opposite twin of the talking error: there an empty list, here a list full
> of the wrong thing. **Quoting doesn't protect** — it's not the syntax, it's the
> index: no quote searches for a character the tokenizer threw away. The defect
> bites only **trailing** characters (`C++`); **in the middle** (`node.js`) quoting
> keeps the two tokens as a phrase and works.
>
> The fix is on **two layers**, because index and query are different planes:
> - **index** — FTS is created with `tokenize='unicode61 tokenchars ''+#'''`, so
>   `C++`/`C#`/`g++` are real, distinct tokens. It applies to DBs **built from now
>   on**; DBs already loaded must be rebuilt (re-ingest): `tokenize` is fixed at
>   creation, a `rebuild` doesn't change it. The `.` stays a separator on purpose
>   (it would break `node.js`, `github.com`, `0.7.9`).
> - **query** — `count` and `check_term` act as a **canary**: they compare
>   `count(term)` with `count(prefix)`; if they match, the term collapsed and they
>   **say so** (`warnings` field). It works **immediately** on live DBs without
>   re-ingest, and self-calibrates: on a rebuilt DB the counts diverge and the
>   warning doesn't fire. Ask `check_term("C++")` when a count looks absurd.

## Sessions and lineages — `get_session` and `get_stirpe`

Since the `recupero/` R1 contract the archive has a "session" entity. Two tools read
it, **read-only**, from the `sessioni` and `archi` tables and from the cards.

### How to ask for a session

`sessionId` is the **full uuid** or a **prefix of at least 8 characters** — the
short form in use (`0f1e2d3c`) — as long as it is unique. The session is looked up
among the `sessioni` rows **and** among the endpoints of the `archi` (a session can
be known only as an edge endpoint: the undelivered parent of a clone). `%` and `_`
in the input stay characters, they don't become wildcards.

- **Ambiguous prefix** → an error listing the candidates with their DBs (tool
  messages are in Italian):
  `il prefisso '0f1e2d3c' è ambiguo: 2 sessioni. Candidati: 0f1e2d3c-4b5a-… (primario); 0f1e2d3c-ffff-… (primario). Passa più caratteri o l'id intero.`
- **Fewer than 8 characters** → error: the full id or a prefix of at least 8 is
  needed.
- **Several DBs know the same session** (a primary and a snapshot, for instance) →
  the DB with the **most recent `last_ts`** for that session answers (on a tie, the
  first by name); the others are listed in **`anche_in`**, as in `search`'s dedup.
  With `db_name` you choose a single DB.

### `get_session(sessionId, db_name="", limit=200, max_chars=0)`

It answers with an object:

| field | content |
|---|---|
| `sessionId` | the full uuid (resolved from the prefix) |
| `db` · `snapshot` | the DB that answered and the last modification date of its file |
| `sessione` | the `sessioni` row (all columns); `null` if the session is known only as an edge endpoint. If the session has several **strands**, it is the row of the **main** one: the file without `__fN` (`sessions/<sid>.jsonl`) or, if missing, the one with the lowest N |
| `filoni` | **all** the `sessioni` rows for that `sessionId`, the main one first: just one for a session without collisions, `[]` if there is no row. With several strands `note` says so too |
| `scheda` | the text of the main strand's session card (`recupero/sessioni/<sid>.md`, or `<sid>__fN.md` if the main one is a strand) (state, last words, open threads, commits, memories written, lineage), rebuilt from its chunks; `null` if there is none. ⚠️ The "last words" are **quotations**: who speaks is said by the card, not by the fact that they are there |
| `conversazione` | `{messaggi, per_sender, primo_ts, ultimo_ts, fonti}`: the archive rows sighted in `sessions/<sessionId>…` (all strands; title and attachments included, told apart in `per_sender`), the first and last ts, the origin files |
| `archi` · `archi_totali` | the edges touching the session (from or to), up to `limit`, and how many there are in all |
| `stirpe` | `{id, posizione, scheda}` of the lineage declared in the row; `null` if the session is alone |
| `note` | what is missing, said: truncated edges, missing card, conversation not in this DB… |
| `anche_in` | (only when needed) the other DBs that know the session |

`max_chars` (0 = whole) truncates the text of the cards **saying so in the text**,
as in `get_context`. To **read** the conversation: `get_conversation` with
`sessione.last_uuid`.

An example response (made-up data, shortened text):

```json
{
  "sessionId": "0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0",
  "db": "recupero-bundle",
  "snapshot": "2026-09-24T19:42:50Z",
  "sessione": {"sessionId": "0f1e2d3c-…", "titolo": "sessione di prova",
               "last_ts": "2026-09-10T10:05:00.000Z", "last_uuid": "…",
               "file": "sessions/0f1e2d3c-….jsonl",
               "stato": "turno-chiuso", "stirpe": "9a8b7c6d-…", "stirpe_pos": 1,
               "n_commit": 2, "n_fili": 1, "…": "…"},
  "filoni": [{"sessionId": "0f1e2d3c-…", "file": "sessions/0f1e2d3c-….jsonl", "…": "…"}],
  "scheda": "[recupero/sessioni/0f1e2d3c-….md]\n# sessione di prova\n\n## Stato\n…",
  "conversazione": {"messaggi": 3, "per_sender": {"user": 1, "assistant": 1, "title": 1},
                    "primo_ts": "2026-09-10T10:00:00.000Z",
                    "ultimo_ts": "2026-09-10T10:05:00.000Z",
                    "fonti": ["sessions/0f1e2d3c-….jsonl"]},
  "archi": [{"da": "0f1e2d3c-…", "a": "1a2b3c4d-…", "relazione": "clone",
             "via": "uuid-condivisi", "chiusura": 1, "…": "…"}],
  "archi_totali": 1,
  "stirpe": {"id": "9a8b7c6d-…", "posizione": 1, "scheda": "…"},
  "note": []
}
```

### `get_stirpe(sessionId, db_name="", limit=200, max_chars=0)`

The lineage is the **closure over the edges with `chiusura=1`**, taken without
direction (from↔to), starting from the requested session: all the sessions that
continue into one another.

| field | content |
|---|---|
| `sessionId` · `db` · `snapshot` · `anche_in` | as in `get_session` |
| `membri` | each session of the lineage with its data from `sessioni`, in `first_ts` order; each with `in_sessioni: true/false` and `filoni` (its `sessioni` rows, the main one first — the member's data are the main one's; `[]` for a member without a row) |
| `senza_riga` | the members **without** a row in `sessioni` (known only as edge endpoints): they stay in the list — incomplete, not vanished |
| `archi` | the edges with `chiusura=1` between members |
| `stirpi_dichiarate` · `schede_stirpe` | the lineage ids written in the members' rows, and their cards |
| `note` | for instance: lineage truncated at `limit` members, lone session (with how many edges without closure touch it), members declaring different lineages |

Beyond `limit` members the walk stops, says so in `note`, and the edges towards the
members left out are not returned.

### DBs born before contract R1

A DB indexed before 24/09/2026 (and never re-ingested since) **does not have** the
`sessioni` and `archi` tables. There the two tools don't answer with an empty card —
which would say "the session has nothing" — but with a **talking error** (in
Italian, as the tool prints it):

```
questo DB ('cc-vecchio') non ha la tabella sessioni: è stato indicizzato prima del
contratto R1 (recupero/, 24/09/2026): re-ingerisci il bundle con un indexer che legge
recupero/. La CONVERSAZIONE però c'è, avvistata in sessions/0f1e2d3c… di:
cc-vecchio (412 righe) — leggila con search / get_conversation.
```

(«this DB has no sessioni table: it was indexed before contract R1: re-ingest the
bundle with an indexer that reads recupero/. The CONVERSATION is there, though,
sighted in sessions/0f1e2d3c… of: cc-vecchio (412 rows) — read it with search /
get_conversation.»)

Without `db_name`, if the session isn't found anywhere, the error tells apart the
DBs where it was **searched**, those with an **empty** table (no bundle with
`recupero/` ever came in) and those **without the table**, where searching was not
possible. "It isn't there" and "I couldn't look" stay two different answers.

### How to query sessions and lineages, in practice

1. **Find the session.** From the sessionId (or its first 8 characters):
   `get_session("0f1e2d3c")`. From the content:
   `search("word", project="recupero:sessioni")` searches only among the cards; a
   card's uuid leads to `get_conversation`, which climbs back to the whole chat.
2. **Know where it stopped.** `get_session(...)`: `sessione.stato`, the `scheda`
   (last words, open threads, commits).
3. **Read it.** `get_conversation(sessione.last_uuid)` — the whole chat, with the
   card at the end.
4. **Rebuild the family.** `get_stirpe(...)`: the members in order, and for each
   one `get_session` again.
5. **Lineages from the text.** `search('"0f1e2d3c"', project="recupero:stirpi")`
   finds the lineage cards naming that session.

Via SQL, on the DB file (for instance on the VPS, or on a copy):

```sql
-- the sessions of a bundle, most recent first
SELECT sessionId, titolo, stato, last_ts FROM sessioni ORDER BY last_ts DESC;

-- the lineage edges (chiusura = 1) touching a session
SELECT * FROM archi
 WHERE chiusura = 1 AND ('0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0' IN (da, a));

-- which session wrote a memory
SELECT path, scritta_da, mtime FROM memorie WHERE path LIKE '%nota%';

-- a session's messages, from the sightings
SELECT m.ts, m.sender, substr(m.content, 1, 80)
  FROM sightings s JOIN messages m ON m.uuid = s.uuid
 WHERE s.source LIKE 'sessions/0f1e2d3c%' ORDER BY m.ts;
```

The `memorie` table has no MCP tool yet: memories are searched with `search`
(`project="recupero:memorie"`) and the table is read via SQL.

## Documents and images (scanned PDFs, screenshots) — via NotebookLM

A PDF **without text** (scan, screenshot) has nothing to extract with `pypdf`. But
**NotebookLM reads it** (multimodal OCR). From the host:

```bash
vps1777 archive-ingest <file> --db <name> --verify
```

What it does: it creates a throwaway notebook, puts the file in it (NotebookLM
processes it), asks for the **full transcription** via a query, with `--verify` asks
NotebookLM to **check the faithfulness** of its own transcription (doer + checker),
then indexes the text into the archive and cleans up the notebook. It works with
image PDFs, scans and any file NotebookLM can read.

> ⚠️ The transcription is generated by an LLM, **it is not deterministic OCR**:
> excellent for finding content again, not guaranteed 100% faithful on complex
> layouts. The verification query (`--verify`) flags uncertain/missing parts.

It requires NotebookLM auth to be configured (nlm profile — see `/admin/nlm`).

**Images inside a bundle** (`workfiles/`) take another road: they are read by the
internal `ocr` service (tesseract), without sending anything out; if the service
isn't there, each image leaves an `ocr-non-disponibile` tombstone.

## Building a DB from the command line (local)

The indexer is stdlib-only and also runs standalone (handy for big batches on the
PC; then you upload the `.db` as a drop-in):

```bash
python3 services/gateway/app/archive_indexer.py <input> out.db --project name

# a Session Recovery bundle: same command, the zip is recognised by its content
python3 services/gateway/app/archive_indexer.py bundle.zip recupero-<ddmmyy>.db
```

The indexer prints **letti N → scritti M · deduplicati K** (read N → written M ·
deduplicated K; the difference is deduplication by uuid, not loss) and, if any, how
many tombstones it left. The rows of the `sessioni`/`archi`/`memorie` tables are not
part of those numbers: count them with a query.

## Schema of a valid DB

Current schema:

```sql
messages(uuid PRIMARY KEY, project, ts, content,
         sender, tools, thinking, attachments, parent_uuid,
         ts_source,                                -- regime of the ts (see below)
         speaker, voice, quoted_share, voice_conf, content_flags)  -- who writes / whose voice
messages_fts USING fts5(uuid, project, ts, content, tools, attachments,
                        content='messages', ...,   -- external-content
                        tokenize="unicode61 tokenchars '+#'")  -- C++/C# don't collapse
CREATE INDEX idx_parent ON messages(parent_uuid);   -- get_conversation's thread walking
revisions(uuid, ts, content, sender, project, ts_source, content_sha, superseded_date,
          PRIMARY KEY(uuid, content_sha))           -- the outgoing versions of a rewritten row
skipped(uid PRIMARY KEY, source, reason, detail, ts, ingest_date)  -- the ledger of discards
sightings(uuid, source, ingest_date, PRIMARY KEY(uuid, source))    -- where each uuid was seen
meta(key PRIMARY KEY, value)                        -- card: description, ruolo, bundle_*
-- from the Session Recovery bundle (contract recupero/ R1, 24/09/2026); empty elsewhere
sessioni(sessionId, titolo, cwd, first_ts, last_ts, last_uuid, file,
         stato, stato_fonte, stirpe, stirpe_pos INTEGER, n_commit INTEGER,
         n_fili INTEGER, ingest_date, PRIMARY KEY(sessionId, file))  -- one row per strand
archi(da, a, relazione, via, livello, prova, voce, peso REAL, chiusura INTEGER,
      bundle_scan, ingest_date, PRIMARY KEY(da, a, relazione, via))
memorie(path PRIMARY KEY, sistema, livello, md5, mtime, scritta_da, membro, ingest_date)
```

The `revisions`, `sightings`, `meta` tables and the three bundle ones are `CREATE
TABLE IF NOT EXISTS`: an existing DB receives them at its first ingest, and stays
readable by earlier versions.

**The `sessioni` key has changed (since 25/09/2026).** A DB created by 0.51.x has
`sessioni` keyed on `sessionId`. At the first ingest the indexer moves it to the key
`(sessionId, file)` (`_ensure_sessioni_filoni`): SQLite does not change a table's key
with an `ALTER`, so the table is recreated and every row copied over, inside a
`SAVEPOINT` (all or nothing). If it fails, the table stays as it was and the error
surfaces. A second run does nothing. No row is lost: the old key was unique on
`sessionId`, so it is unique on `(sessionId, file)` as well. A NULL `file` becomes
`''`. The strands the old key had already squashed do **not** come back on their own:
**re-ingest the bundle**, and now they all go in. archive-mcp also reads the old
table: on a DB not yet migrated `filoni` has a single row.

This is what `archive_indexer` and `archive-ingest` produce. FTS gets `content`,
`tools` (the actions: `tool_use` + `tool_result`) and `attachments`; `thinking` and
`parent_uuid` are **kept** in the table (readable via SQL / `get_context`) but
**not** indexed — see the schema note in `archive_indexer.py`.

**`ts_source` — the regime of the `ts`.** It says what a row's date is:

| value | meaning |
|---|---|
| `messaggio` | the ts of a real event (a message once said doesn't change). It is the default |
| `data-export` | a ts of the **snapshot**, not of the content: today the cards and memories of `recupero/` declare it (state rows, rewritten between one ingest and the next) |
| `ignoto` | rows migrated from a DB born before the column: the regime can't be rebuilt afterwards, and it isn't guessed |

Whoever computes an archive's "most recent" filters **negatively**:
`MAX(ts) WHERE ts_source <> 'data-export'`. An extractor declares the regime by
passing `write_rows` an optional **tenth column** (`messaggio` or `data-export`;
without it, it stays `messaggio`; any other value stops the ingest).

**`speaker` and `voice`** — two axes that must not be merged. `speaker` is **who
sent** the row, a fact taken from the source (`human` · `assistant` · `tool` ·
`system` · `unknown`: attachments, titles, memories and cards are `unknown`, because they don't
say who wrote them). `voice` is **whose voice** is in the content, a heuristic estimate
(`own` · `pasted_transcript` · `pasted_ai` · `character` · `mixed` · `unknown`),
with its confidence and the flags that explain it. They come out **populated** from
every ingest path.

**Tool outputs are `tool`, not `human` (since 0.52.0).** In Claude Code the output of a
command (the `tool_result`) travels in a record of type `user`: up to 0.51.4 it went in
as `sender='user'` → `speaker='human'`, and on the primary DB they were **74,818 of the
89,950** `human` rows (83%, measured on 26/09/2026). Now a `user` record made only of
tool_results goes in as `sender='strumento'` → `speaker='tool'`, and `speaker='human'`
means "words of whoever writes" again. Two exceptions stay `human`, because they are the
user's words delivered inside a tool_result: the **answers to multiple-choice questions**
(the text starts with "Your questions have been answered" or "The user answered": the
form changes with the Claude Code version) and **reasoned rejections** ("The user doesn't
want to proceed with this tool use… the user said:" followed by their words). Recognition
is anchored at the start of the text: the same sentence inside the output of a `grep`
stays `tool`. A tool_result inside a sidechain stays `mandato`, as before.

DBs **already loaded** don't need a re-ingest: the cure is a migration, because the text
doesn't change (`sender` and `speaker` are neither in the FTS nor in the vectors, and the
semantic index is tied to rowids, which the migration doesn't touch). It runs by itself
at the first ingest into an old DB; for DBs nobody writes to anymore there is
[`vps1777 archive-migra`](CLI.md) (dry-run by default, `--scrivi` to apply), which for
each DB runs inside the gateway:

```bash
python -m app.archive_indexer /var/lib/archive/db/<name>.db --migra [--scrivi]
```

and prints `{"strumenti": N, "speaker_prima": {…}, "speaker_dopo": {…}, "scritto": …}`. On
the primary: 74,818 rows, `human` from 89,950 to 15,132, 6 seconds (and, with the
program's turns below, to 3,967). ⚠️ Even a dry run can
change the file's **sha** without changing data: SQLite doesn't journal the free pages it
reuses, and after the ROLLBACK they stay free but with different bytes (measured: 638
free pages, data and `integrity_check` identical). Whoever compares a DB by sha, like a
script that loads the index only if the DB hasn't changed, should do it before `--migra`.

**The program's turns are `system` (since 0.53.0, #293).** After the tools, 14,878
`human` rows were left on the primary, and 75% of them had been written by no one: 9,643
`<task-notification>` (a sub-agent or a background command that finished), 1,115 outputs
of local commands, 151 compaction summaries, skill texts, messages from other sessions.
Claude Code injects them in a record of type `user`. Now they go in as `sender='sistema'`
→ `speaker='system'`. How it is decided:

1. **the record's fact**, where there is one: recent versions write `origin.kind`
   (`human` = whoever writes; `task-notification`, `peer`, `coordinator`… = the
   program), `isMeta` and `isCompactSummary`. `origin.kind='human'` wins over the rest;
2. **the form of the text**, only if the record says nothing: the forms only the program
   writes (`<task-notification`, `<local-command-…`, "This session is being
   continued…", "Base directory for this skill:", "Another Claude session sent a
   message", `<system-reminder>`…; the list is `_FORME_DEL_PROGRAMMA` in the indexer),
   anchored at the start of the text.

**Slash commands** (`<command-name>`) and commands run with `!` (`<bash-input>`) stay
`human`: they are gestures of whoever writes. Prompts that a script sends to a headless
session (a cron calling `claude -p`) stay `human` too: the record doesn't tell them apart
from a prompt typed by hand, and the text is the script's.

On DBs already loaded `origin` and `isMeta` were not kept: `vps1777 archive-migra`
decides by the form of the text only. A turn the program marked only with the field, with
a text of no recognizable form, stays `human` until a re-ingest reads it again from the
source. On the primary: 11,165 rows to `system`, `human` from 15,132 to 3,967.

**`revisions`** keeps the **outgoing** version when the same uuid comes back with a
different content (a rewritten memory, an updated card, a removed chunk): `messages`
stays the latest version, history is queried by uuid.

Other things the ingest produces:

- the **`summary`** of claude.ai conversations become attributed rows
  `sender='summary'`, searchable like everything else;
- from **Claude Code sessions** (`.jsonl`) the ingest also captures the **titles**
  (`ai-title` → row `sender='title'`: you find a chat by its name) and the
  **attachments** (`attachment` → row `sender='attachment'` with the file names), on
  a par with the claude.ai path. Records that **aren't messages** (`mode`,
  `system`, `last-prompt`, `queue-operation`, …) are not indexed but **don't
  vanish**: they leave a `reason='non-message'` tombstone (see below);
- every **discarded** record (no uuid, empty, non-message) leaves a **tombstone** in
  `skipped` — with the reason and the raw record — instead of vanishing in a silent
  `continue`: the count is in `db_info()["skipped"]` / `count_skipped()`, and the raw
  data stays reachable. *(A note on counting: the `skipped` table deduplicates by
  content — two identical records are one tombstone, like the dedup by `uuid` of
  messages. An acceptance test that wants to square with the number of **rows read**
  must treat duplicates as a category, not as a loss: see
  `tools/collaudo-quadratura.py`.)*
- the archive's **description** lives in `meta['description']` (written at upload,
  updatable via `set_description`); the **role** lives next to it in
  `meta['ruolo']` (written by `set_ruolo`, missing key = `non dichiarato`); from
  bundles come `bundle_generated`, `bundle_previsione_ingest` and `bundle_recupero`.
  They all travel **inside the file**: a `.db` moved or restored from a backup
  carries its own card with it, with no external registry to keep in sync.

> **Event rows vs state rows.** Chats are **events** (a `ts`, immutable);
> `memory:*`, `account:user` and the `recupero:*` cards are **states** (rewritten
> between one ingest and the next). `oldest` in `describe_databases` uses
> `min(NULLIF(ts,''))` so that undated states don't make the empty string win the
> minimum — the archive no longer says "I don't know since when" while knowing it.

A drop-in `.db` is accepted if it is an SQLite file with the `messages_fts` table
(check in `admin.py`). A **v1** DB (only the 4 columns `uuid, project, ts, content`)
is still valid too: `migrate_v1_to_v2()` adds the new columns and rebuilds FTS: the
old rows stay (with `tools`/`thinking` empty until you re-run the ingest on the
source, idempotent by `uuid`).

## Known limits

Declared, not discovered by chance:

- **Tables accumulate, they don't forget.** A session, an edge or a memory that
  disappears from a new bundle **stays** in `sessioni`, `archi` and `memorie`: the
  R1 contract has no removal semantics. Likewise, the card of a session that a new
  bundle no longer delivers stays (chunk pruning only applies when the same member
  comes back).
- **`meta` tells the last bundle.** If several bundles go into the same DB, the
  `bundle_*` keys describe only the last one; `bundle_generated` dates it.
- **Output redaction used to spoil uuids and dates — fixed in 0.51.1.** Up to 0.51.0 the
  phone-number pattern caught the digit-only groups of a uuid
  (`12345678-1234-4123-8123-123456789012` came out as `[telefono redatto]-4123-8123-[telefono
  redatto]`, "[phone redacted]") and dates with the time after a space (`2026-09-05 13:10`
  came out as `[telefono redatto]:10`). Now canonical uuids are left alone and valid dates
  with the time stay; the exemptions are strict (month 13, day 32, hour 24 are still phone
  numbers) and real phone numbers still disappear (tests in `test_redazione.py`, both ways).
- **The bridge's old rows don't go away by themselves.** A DB that had ingested
  bundles with the `workfiles/_recupero-1777/` bridge using an indexer **predating**
  the alias has `workfile:_recupero-1777/…` rows; re-ingesting with this indexer adds
  the `recupero:*` rows but doesn't remove those.
- **`memorie` without a tool.** It is read via SQL or with `search`.
- **`documents/` says what kind a document is, not where it comes from.** The app
  (since 25/09/2026) writes `documents/<family>/…`: the label is the family
  (`document:testo`, `document:codice`…). The file name is searchable, because it is
  the first line of the text; the folder of origin is only in `MANIFEST.json`
  (`documenti.consegnati[].src`), on purpose: a path in the label would carry the
  disk layout into every answer.
- **`last_ts` and the last message.** On a real bundle the card's `last_ts` turned
  out more recent than the ts of the `last_uuid` message (the last record with that
  timestamp wasn't a message). The order holds — the card comes after — but
  `last_ts` and `get_session`'s `conversazione.ultimo_ts` may differ.

## How it works underneath (the no-docker.sock boundary)

The gateway mounts the `archive-data:rw` volume and writes the `.db` files in
`/var/lib/archive/db/`; `archive-mcp` mounts it **read-only**, scans that directory
(**scan-mode**) and discovers new DBs without a restart. The only two writes a tool
can ask for — `set_description` and `set_ruolo`, which touch only the `meta` card —
go through the gateway (`/internal/archive/description`,
`/internal/archive/ruolo`, on the internal network with a shared secret). For the
NotebookLM ingest, orchestration is on the host (`vps1777 archive-ingest`): the
gateway doesn't talk to Docker or to nlm — the host CLI copies the file into
`nb1777-mcp` (which has the nlm auth), extracts the text, and hands it to the
gateway for indexing. See [ARCHITECTURE.md](ARCHITECTURE.md).
