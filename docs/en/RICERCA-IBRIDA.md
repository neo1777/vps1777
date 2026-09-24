# Hybrid search — finding by meaning, not by wording

> English translation of [`docs/RICERCA-IBRIDA.md`](../RICERCA-IBRIDA.md). Translations are freshness-checked in CI against the Italian source (see [`MANIFEST.json`](MANIFEST.json)): if this note is red in CI, the Italian moved first.

> The tool prints its messages in Italian: they are quoted here verbatim, with
> the English meaning next to them where it helps.

`search` (FTS5) works very well for whoever **knows what the thing is called**.
But the use case that gave birth to the archive is the opposite one: *I remember
the meaning, not the word*. "The article where I told how much I had spent",
"the dashboard where the files were planets": there full-text stays silent,
because the word you would use is not the one written in the text.

`search_ibrida` searches **also** by meaning: it fuses the FTS5 results with
those of a vector search and returns a single list.

## What it is worth — measured, not promised

The POC bench (issue #281): 9 targets chosen **before** measuring, each with the
natural-language query of someone who does not remember and its FTS5
counterpart with the right wording. Position of the target in the first 10
results:

| | FTS5 | vectors only | **hybrid** |
|---|---|---|---|
| targets found | 5/9 | 4/9 | **6/9** |

The two engines fail in different ways: fusion keeps the best of both. On
**exact** queries hybrid search does not beat `search` — it is tuned not to make
them worse, not to win them. If you are looking for a precise term, use
`search`.

## The four pieces

| piece | where it lives | why there |
|---|---|---|
| the **search code** (query embedding + knn + fusion) | the `archive-mcp` image | ~35 MB of dependencies: onnxruntime, tokenizers, sqlite-vec, numpy |
| the **model** (`model.onnx` + `tokenizer.json`) | volume, `/var/lib/archive/models/e5-small/` | 449 MB: in the image they would weigh on every pull, and they get updated without releasing a version |
| the **index** (`<nome-db>.vec.db`) | volume, next to its DB | indexing the corpus costs tens of hours of CPU: it is done **elsewhere** and the index travels as an artifact |
| the index **builder** | repo, `services/archive-mcp/tools/costruisci_indice.py` | runs on the PC, in archive-mcp's lock environment; it does not go into the image |

Three intended consequences:
- the **archive DB is not touched**: its signature does not change, backups do
  not grow, and an archive without an index works as before;
- the index is **regenerated without rebuilding the DB** (and vice versa);
- hybrid search **degrades by declaring it**: without a model or without an
  index it does not silently fall back to FTS5 — it raises an error that says
  what is missing and how to fix it. *A halved result that looks whole is worse
  than an error.*

## Why ONNX and not torch

The server needs the model for one thing only: turning **the query** into a
vector. With torch + sentence-transformers that would be ~1 GB of image and
~1.5 GB of RAM: on a 3 GB VPS with six containers it is a tax that does not pay
off. The ONNX export of the same model gives **identical** vectors — measured:
`cosine = 1.000000` against sentence-transformers, so the bench verdict stays
valid — in ~25 ms per query.

The builder uses the **same** ONNX export for the indexed texts as well. The POC
had computed them with sentence-transformers: compared with the builder on
24/09/2026 (80 messages, 195 chunks) they still give `cosine = 1.000000`. A POC
index and a builder index speak the same space.

int8 quantization (113 MB instead of 449) was measured and **discarded**:
`cosine 0.985–0.990`, i.e. vectors different from those the index was built
with. Saving 336 MB by changing the yardstick halfway through the experiment is
not an optimization.

## The model: the export (on the PC, once)

```bash
# export ONNX con pooling e normalizzazione DENTRO il grafo
# (così il runtime non li replica e non può sbagliarli in modo diverso)
python - <<'PY'
import torch, torch.nn as nn
from transformers import AutoTokenizer, AutoModel
NOME, OUT = "intfloat/multilingual-e5-small", "e5-small"
tok = AutoTokenizer.from_pretrained(NOME); base = AutoModel.from_pretrained(NOME).eval()
tok.save_pretrained(OUT)
class E5(nn.Module):
    def __init__(s, m): super().__init__(); s.m = m
    def forward(s, input_ids, attention_mask):
        h = s.m(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
        w = attention_mask.unsqueeze(-1).float()
        e = (h * w).sum(1) / w.sum(1).clamp(min=1e-9)
        return e / e.norm(dim=1, keepdim=True).clamp(min=1e-12)
enc = tok(["query: x"], return_tensors="pt")
torch.onnx.export(E5(base).eval(), (enc["input_ids"], enc["attention_mask"]),
    f"{OUT}/model.onnx", input_names=["input_ids", "attention_mask"],
    output_names=["embedding"], opset_version=17, dynamo=False,
    dynamic_axes={"input_ids": {0:"b",1:"s"}, "attention_mask": {0:"b",1:"s"}, "embedding": {0:"b"}})
PY
```

(The comment in the script says: ONNX export with pooling and normalization
INSIDE the graph, so the runtime does not replicate them and cannot get them
wrong in a different way.)

The same folder (`model.onnx` + `tokenizer.json`) is used twice: by the builder
on the PC (`--modello`) and by the server on the volume.

## The index: the builder

### Where it runs and how to launch it

`services/archive-mcp/tools/costruisci_indice.py` lives in the repo, next to the
server that reads what it writes. Until 24/09/2026 the index was written by a
POC prototype kept outside the repo: it had the source DB written into the
code, it selected only by ts window (rows without a ts never got in, and nobody
said so) and it did not write `indice_meta`, which was added by hand.

It runs **on the PC**, **in archive-mcp's lock environment**: onnxruntime,
tokenizers and sqlite-vec have the same versions as the server, and there is no
extra dependency. It does not go into the image: the Dockerfile copies only
`app/`.

```bash
cd services/archive-mcp
uv sync --frozen
uv run python tools/costruisci_indice.py \
    --db /percorso/copia-archivio.db --modello /percorso/e5-small \
    --dal 2026-05 --al 2026-07 --senza-ts escludi
```

The DB is opened **read-only** (`mode=ro`): the builder cannot write to it.
Work on a **copy** anyway: the builder reads the DB with several queries in
sequence, and a DB that an ingest is writing could show it two different
states. The index is written next to the DB (`<nome-db>.vec.db`) or where
`--out` says, which must end in `.vec.db`: that is how the server finds it, and
how the DB scan does not mistake it for an archive.

### What goes into a vector

- **The text** of a message is `content` + `attachments` + `tools`. From the
  JSON fields only the strings are kept and binary payloads (data URIs, base64
  PNGs) are dropped. ⚠️ Useful text also lives in tool calls: an index on
  `content` alone is blind exactly where proactive discovery is needed
  (measured in the POC).
- **The chunks**: windows of 1400 characters with 200 of overlap, at most 12 per
  message. 1400 characters are ~400-460 e5 tokens, within the 512 limit. Below
  40 characters a message is not indexed, but it is counted ("troppo corti",
  too short). This is the chunking that doubled recall on long messages in the
  POC.
- **The prefix**: every chunk goes to the model as `passage: <testo>`, the twin
  of the server's `query: <domanda>`. It is e5's contract: without it, quality
  drops.

### The yardstick is the server's, imported and not copied

An index built with a yardstick different from the query's produces
nonsensical neighbours **without errors**. That is why the builder copies
nothing from `services/archive-mcp/app/semantica.py`, it imports it:

| what | from where |
|---|---|
| opening the model (tokenizer, truncation at 512) | `semantica.apri_modello`, the same function as the server |
| encoding a batch of texts | `semantica.codifica`, which `embed_query` also goes through |
| prefixes | `semantica.PREFISSO_PASSAGGIO` (`passage: `) next to `PREFISSO_QUERY` (`query: `) |
| table and dimension | `semantica.TABELLA` (`vec_chunk_small`), `semantica.DIM` (384) |

When these functions were extracted from the server (24/09/2026), the query
vectors stayed byte-for-byte identical to those of before.

On top of that the builder checks every batch: every vector must have 384
dimensions, and the first vector of each batch must have norm 1. An export
without L2 normalization in the graph, or another model, is rejected.

### The perimeter: always declared

| parameter | what gets in |
|---|---|
| `--tutto` | the whole DB |
| `--dal X --al Y` | `ts >= X AND ts < Y` (ISO strings, `al` excluded; either one may be given alone) |
| `--project ETICHETTA` | exact label, or prefix if it ends in `*` (`recupero:*`); repeatable, labels are OR-ed |
| `--senza-ts includi` / `--senza-ts escludi` | only with a window: rows without a ts get in (`includi`) or stay out (`escludi`) |

- **Window and labels combine** with AND. `--tutto` does not combine.
- **In a prefix `_` and `%` are letters, not wildcards**: `rec_x:*` does not
  match `recAx:1`.
- **Rows without a ts.** If the window would leave out rows without a ts, the
  builder **stops**, says how many there are and asks you to choose. The choice
  ends up in the declared perimeter ("righe senza ts: escluse (1147)", rows
  without ts: excluded). Without a window there is nothing to choose: no filter
  excludes them. A real example: on the copy of the primary DB of 08/09/2026
  there were **1,147** rows without a ts, and the prototype excluded all of
  them.
- **Without perimeter parameters**, an existing index is updated with the
  perimeter it declares itself (`perimetro_json`). A new index without a
  perimeter is rejected, with the list of choices.
- **An empty perimeter** (0 messages), or one with no indexable message, is
  rejected without writing anything: an empty index would look like an index.

### What is inside the `<nome-db>.vec.db` file

| table | what it contains | who reads it |
|---|---|---|
| `vec_chunk_small` | `vec0(embedding float[384], +msg_rowid integer)`: one vector per chunk, with the message's rowid | the server (knn) |
| `indice_meta` | `(chiave, valore)`: the index's record card, below | the server (4 keys) and the builder |
| `indice_righe` | `(msg_rowid, uuid, impronta, primo_chunk, n_chunk)`: the **ledger**, one message per row | the builder (incremental update) and the server (verification) |

A message's vectors have contiguous rowids (`primo_chunk` … `primo_chunk +
n_chunk - 1`), assigned by the builder: removing them does not require scanning
the table. `impronta` is the sha256 (32 hex digits) of the indexed text.

### `indice_meta`: the index's record card

The builder writes it, at every pass. The server returns `perimetro`,
`messaggi`, `modello` and `generato` with every search: without the perimeter, a
partial index produces zeros that look like absences.

| key | what it says |
|---|---|
| `perimetro` | the perimeter in plain words, as the server shows it (`ts >= 2026-05 AND ts < 2026-07 · righe senza ts: escluse (1147)`) |
| `perimetro_json` | the same, in repeatable form: the incremental update reads it back |
| `modello` | the model name (`intfloat/multilingual-e5-small`) |
| `modello_impronta` | sha256 of `model.onnx` + `tokenizer.json` (32 digits): two different exports of the "same" model have different fingerprints |
| `dim`, `tabella`, `chunk`, `prefisso` | the yardstick: 384, `vec_chunk_small`, `1400/overlap 200/cap 12`, `passage: ` |
| `messaggi`, `vettori` | the messages with at least one vector, and the vectors in the table |
| `messaggi_perimetro`, `messaggi_corti`, `righe_senza_ts` | the messages in the perimeter, those under 40 characters, the rows without a ts in the rest of the filter |
| `db_sorgente`, `db_righe`, `db_max_rowid` | the DB name (without path), its rows and its highest rowid at generation time |
| `generato` | UTC date and time of generation |
| `costruttore` | `costruisci_indice 1.0` |
| `ultimo_passaggio` | JSON: mode and numbers of the last pass (unchanged, new, changed, reassigned, orphans, out of perimeter, vectors removed and added) |
| `stato` | `completo` (complete); `in costruzione` (being built) only in the `.parziale` file |

### All the options

| option | what it does |
|---|---|
| `--db PERCORSO` | the archive DB (mandatory; opened read-only) |
| `--modello CARTELLA` | `model.onnx` + `tokenizer.json`; mandatory to build, not for `--controlla` |
| `--out PERCORSO` | the index to write (default: `<nome-db>.vec.db` next to the DB) |
| `--tutto`, `--dal`, `--al`, `--project`, `--senza-ts` | the perimeter, above |
| `--ricostruisci` | starts from scratch instead of updating; without a perimeter it rebuilds the one the index declares |
| `--controlla` | compares index and DB without writing anything |
| `--lotto N` | chunks per batch and per transaction (default 96) |
| `--thread N` | onnxruntime threads (default: all cores) |
| `--json` | the outcome as JSON on stdout, for machines |

### What it prints, and how it exits

A build on a synthetic DB of 6 messages (one without a ts, one too short):

```
indice: sintetico.vec.db  (ricostruzione)
perimetro: ts >= 2026-05 AND ts < 2026-07 · righe senza ts: incluse (1)
messaggi nel perimetro: 6 · con testo indicizzabile: 5 · troppo corti: 1
righe senza ts nel resto del filtro: 1
registro prima: 0 messaggi
  invariati: 0
  nuovi: 5
  testo cambiato (stesso uuid): 0
  rowid riassegnato a un altro uuid: 0
  orfani (rowid sparito dal DB): 0
  usciti dal perimetro: 0
vettori tolti: 0 · aggiunti: 5
dopo: 5 messaggi · 5 vettori (registro e tabella vec0 quadrano)
```

In English: index and mode (rebuild); perimeter; messages in the perimeter,
with indexable text, too short; rows without a ts in the rest of the filter;
ledger before; unchanged, new, text changed (same uuid), rowid reassigned to
another uuid, orphans (rowid gone from the DB), out of the perimeter; vectors
removed and added; after: messages and vectors (ledger and vec0 table
reconcile).

Progress goes to stderr (`1079/1203 messaggi · 3274 vettori · 2.3 vett/s`).

| exit code | meaning |
|---|---|
| 0 | index written; with `--controlla`, index in step with the DB |
| 1 | only with `--controlla`: the index is not in step (the numbers say why) |
| 2 | rejected or not measurable: the message says what is missing and how to fix it |
| 130 | interrupted (Ctrl-C): the work done stays in the `.parziale` file |

## Updating the index: incremental updates and the rowid

The index works on the `rowid` of `messages`, and the indexer does `INSERT OR
REPLACE` on the uuid: a re-ingest gives **new rowids** to the replaced rows. An
old index then has vectors hanging on rowids that no longer exist (the result
disappears without errors) or on rowids **reused** by another message (the
wrong message, returned for the meaning of another one).

The `indice_righe` ledger is there to see it. Running the builder again on an
existing index compares it with the DB and says, with numbers:

| category | what happened | what it does |
|---|---|---|
| unchanged (`invariati`) | same rowid, uuid and text | nothing |
| new (`nuovi`) | in the perimeter, not yet indexed | indexes them |
| text changed (`testo cambiato`) | same rowid and uuid, different text | removes and recomputes |
| rowid reassigned (`rowid riassegnato`) | the same rowid now holds another uuid | removes and, if in the perimeter, recomputes |
| orphans (`orfani`) | the rowid no longer exists in the DB | removes |
| out of the perimeter (`usciti dal perimetro`) | still in the DB, but outside the perimeter (or now too short) | removes |

The same mechanism grows the index **in stages**: widening the window adds only
the new messages, narrowing it removes those that left.

Before publishing, the number of vectors in the vec0 table must equal the sum
of `n_chunk` in the ledger. If it does not, the index is not published: a vector
the ledger does not explain is an orphan the server would serve.

- **`--controlla`** makes the same comparison **without writing anything** and
  exits 1 if the index is not in step. Use it after a re-ingest and before
  uploading an index to the VPS.
- **A change of yardstick** (another export of the model, recognised by its
  fingerprint; another chunking or prefix) rejects the incremental update and
  asks for `--ricostruisci`: vectors from two yardsticks in the same index give
  nonsensical neighbours without errors.
- **A POC index** has no ledger: the incremental update rejects it and asks for
  a rebuild, once only. `--controlla` on it reports only the orphans (rowids
  gone from the DB), declares that the rest cannot be verified, and exits 2 if
  it finds none, 1 if it finds some.
- **The work goes through `<nome-db>.vec.db.parziale`**, one batch per
  transaction: a message's ledger row and vectors go in together. If it is
  interrupted, running the same command again resumes without redoing what is
  done ("ripresa" mode, resume). For an incremental update the existing index
  is first copied to a separate file, renamed to `.parziale` only once the copy
  is finished. The served index is replaced only at the end, once the counts
  reconcile.

## Verification in the server: `indici[].verifica`

The builder makes the index consistent with the DB **at the moment it builds
it**. But the DB on the VPS can be re-ingested later, and then the uploaded
index goes out of step again. That is why `search_ibrida` verifies too, at every
search.

If the index has the ledger, for every vector result the server compares the
uuid recorded for that rowid with the uuid of the row in `messages`. Whatever
does not match **is discarded**: it is never returned as if it were right. The
response declares it in an **extra** field of each `indici[]` entry; the
existing fields do not change shape.

| field | what it says |
|---|---|
| `registro` | `true` if the index has the ledger, `false` if it is an old index that cannot be verified |
| `candidati` | how many knn neighbours were examined (not the whole index) |
| `scartati` | how many were removed from the results: `rowid_assenti` + `uuid_diversi` |
| `rowid_assenti` | neighbours whose rowid no longer exists in the DB |
| `uuid_diversi` | neighbours whose rowid now belongs to another message |
| `stato` | the sentence for the reader, with the fix |

The three possible states:

- `verificato: ogni risultato vettoriale combacia col DB (uuid per rowid)` —
  verified: every vector result matches the DB (uuid per rowid);
- `indice disallineato col DB: N risultati vettoriali scartati (A rowid spariti,
  B rowid ora di un altro messaggio) — lancia …costruisci_indice.py --controlla
  su una copia del DB e aggiorna l'indice` — index out of step with the DB: N
  vector results discarded (A rowids gone, B rowids now belonging to another
  message); run `--controlla` on a copy of the DB and update the index;
- `indice senza registro: l'uuid dei risultati vettoriali non è verificabile …`
  — index without a ledger, the uuid of the vector results cannot be verified:
  the POC index. It behaves as before; rowids gone from the DB, which used to be
  discarded silently, are now counted.

The server also writes a warning to the log when it discards something.

⚠️ What the verification does **not** see:
- it counts only on the candidates of that search: zero discards do not certify
  the whole index. `--controlla` does that;
- a message with the **same** uuid and the same rowid but changed text is the
  right message with an old vector: the server does not discard it, the builder
  sees it ("testo cambiato", text changed) and recomputes it.

## What it costs — measured

Measured on 24/09/2026 on an 8-core PC, on the copy of the primary DB, for a
two-day window (1,618 messages, 4,366 vectors):

| | |
|---|---|
| speed | ~2.3 vectors per second (the torch prototype, 6 threads: ~3.0) |
| RAM | 1.9 GB peak |
| CPU | ~550% |
| result | the same messages and the same number of vectors per message as the prototype on the same window |

The builder sends a batch's texts to the model **sorted by length, in groups of
16** (`EmbedderOnnx`). The first draft sent them all together, 96 at a time:
padding brought every batch to the length of its longest text, and
onnxruntime's arena had reached **~12 GB** of RAM. The result does not change:
the pooling in the graph weighs with `attention_mask`, so padding does not enter
the vector (verified again: cosine 1.000000).

Estimates, from the measured speed (they are estimates, not measurements):

| perimeter | vectors | time at ~2.3 v/s |
|---|---|---|
| May–June 2026 (today's index) | ~139,000 | **~17 h** |
| July–September 2026 (chunks counted by the prototype on the 08/09 copy) | ~282,000 | ~34 h |

## The first time on the VPS

The index on the VPS today is the prototype's: without a ledger. Search works,
but `indici[].verifica` will say `registro: false`, and the first update asks
for a rebuild. The steps, once:

1. **A copy of the DB on the PC**, taken while no ingest is running:

   ```bash
   ssh vps1777 'docker cp vps1777-gateway-1:/var/lib/archive/db/recupero-20260905.db /tmp/'
   scp vps1777:/tmp/recupero-20260905.db ./ && ssh vps1777 'rm /tmp/recupero-20260905.db'
   ```

2. **The rebuild** with today's perimeter (May–June). It takes **~17 hours**: it
   can be interrupted and resumed by running the same command again.

   ```bash
   cd services/archive-mcp
   uv run python tools/costruisci_indice.py --db /percorso/recupero-20260905.db \
       --modello /percorso/e5-small --dal 2026-05 --al 2026-07 \
       --senza-ts escludi --ricostruisci
   ```

   `--senza-ts escludi` keeps the prototype's perimeter; `includi` lets in the
   rows without a ts as well (1,147 on the 08/09/2026 copy).

3. **The check**: `--controlla` must exit 0 ("in pari col DB", in step with the
   DB).

   ```bash
   uv run python tools/costruisci_indice.py --db /percorso/recupero-20260905.db --controlla
   ```

4. **The upload**, as below.
5. **The proof**: any `search_ibrida` must answer with
   `indici[].verifica.registro: true` and `scartati: 0`.

**After every re-ingest** of that DB: a fresh copy on the PC, the builder
**without perimeter parameters** (incremental update with the perimeter the
index declares), `--controlla`, upload. If `search_ibrida` declares discards,
that is the signal that the round has to be done again.

## Uploading the artifacts to the VPS

The `archive-data` volume is mounted **read-only** on `archive-mcp` (which
reads) and **read-write** on the gateway (which writes): the artifacts go
through there.

```bash
scp recupero-20260905.vec.db vps1777:/tmp/
ssh vps1777 'docker cp /tmp/recupero-20260905.vec.db \
    vps1777-gateway-1:/var/lib/archive/db/ && rm /tmp/recupero-20260905.vec.db'

# il modello (una volta sola)
ssh vps1777 'docker exec vps1777-gateway-1 mkdir -p /var/lib/archive/models/e5-small'
ssh vps1777 'docker cp /tmp/model.onnx vps1777-gateway-1:/var/lib/archive/models/e5-small/'
```

(The comment says: the model, once only.)

No restart: the DB registry reloads by itself when the directory changes (a new
`.vec.db` changes the directory signature, so connections with the index
attached are reopened too), and the model is loaded at the first hybrid search.

⚠️ The index is valid for the DB it was born from. If the DB on the VPS has been
re-ingested since, run `--controlla` on a copy of that DB before uploading: if
it is not in step, update it there and upload that one.

## Current perimeter

`[state of the installation on 25/09/2026]`

- **The primary for Claude Code is `recupero-20260924`** (since 24/09: the first bundle
  with the `recupero/` R1 contract, see [ARCHIVE.md](ARCHIVE.md)). Its index is being
  built with the repo's builder over the **whole** DB (`--tutto`: 266,219 messages,
  logs included, with the `indice_righe` ledger), on the PC; at ~1.9 vectors/s it is
  more than two days of compute. Until it is uploaded, `search_ibrida` on that DB has
  no vectors to fuse and declares it in `indici[]`: keyword search (`search`) already
  works on everything.
- **`recupero-20260905`** (the primary until 24/09, now a cross-check) keeps the
  prototype's index: **May–June 2026** (58,322 messages, 139,011 vectors, generated on
  07/09/2026), with a hand-written `indice_meta` and **no** ledger — `verifica.registro:
  false`; updating it requires a rebuild (`--ricostruisci`, see "The first time on the
  VPS", whose examples use exactly this DB).

Outside the perimeter hybrid search has no vectors to fuse — `indici[].perimetro` in
the response declares it at every call, and it is the first thing to read before
concluding "it's not there".

## Known limits

- **Read from a copy.** The builder reads the DB with several queries in
  sequence, without a single consistent read: on a DB that an ingest is writing
  it could see two states. Work on a copy.
- **The server's verification looks at the candidates**, not at the whole
  index; and it does not see a changed text with the same uuid (see above). The
  full check is `--controlla`.
- **Speed.** ~2.3 vectors/s against the prototype's ~3.0: `--thread` and the
  group size have not been tuned yet.
- **`recupero:*` labels.** The prefix filter has been tried on synthetic data;
  the real labels come from another branch of the indexer.
