# Archivio di ricerca (archive1777)

`archive1777` è un motore di ricerca full-text (SQLite FTS5 + BM25) sui tuoi
corpora: chat, sessioni, note, documenti. **Nasce vuoto**: lo popoli tu, dal
pannello admin o da riga di comando. I DB caricati sono cercabili **subito**,
senza riavvii, via i tool MCP `search` e `list_databases`.

## Popolare dall'admin — `/admin/archive`

Pannello admin → tab **Archive**. Carichi una fonte, viene indicizzata in un DB
FTS5 e diventa cercabile. Dispatch automatico per estensione:

| Formato | Cosa indicizza |
|---|---|
| `.zip` | riconosciuto dal **contenuto**: export account **claude.ai** (`conversations.json` + `design_chats/` + `projects/docs`) oppure export chat **Telegram Desktop** — `result.json` *o* `messages*.html`, anche zippato come cartella `ChatExport_*/` |
| `.jsonl` | sessione **Claude Code** (`~/.claude/projects/<progetto>/<id>.jsonl`) |
| `.json` | export **Telegram Desktop** (formato *Machine-readable JSON*) |
| `.pdf` | documento **con testo** (estratto via `pypdf`) |
| `.md` / `.txt` | testo/markdown generico (ponte per l'output di altri tool) |
| `.db` | drop-in di un archivio SQLite già indicizzato (schema validato) |

> L'export chat di Telegram Desktop funziona **così com'è**: comprimi la
> cartella `ChatExport_*` in zip e caricala — sia il formato **HTML** (il
> default, `messages.html`) sia il **JSON** (`result.json`) vengono
> indicizzati. Se ci sono entrambi, vince il JSON (più fedele). Unica
> avvertenza: non mischiare HTML e JSON della *stessa* chat nello stesso DB —
> le chiavi di dedup sono diverse e i messaggi si duplicherebbero. Uno zip non
> riconosciuto, o senza messaggi estraibili, viene **rifiutato con un errore
> chiaro** — mai un "ok, 0 record".

Campi del form: **nome DB** (vuoto = dal nome file) e **progetto** (etichetta;
vuoto = dedotta dalla fonte). Ricaricare lo stesso nome DB non duplica (dedup per
id); fonti diverse sullo stesso nome si accumulano.

## Gestire i DB — lista ed eliminazione

La pagina mostra per ogni DB la **scheda completa**: messaggi, etichette
distinte (le "provenienze": titoli chat, `project:<nome>`, `design:<nome>`…),
le etichette principali, la dimensione su disco e l'ultimo aggiornamento.

Il bottone **Elimina** (con conferma) rimuove il DB: la ricerca su quell'archivio
smette subito (archive-mcp se ne accorge da solo, scan-mode) e l'azione finisce
nell'audit. È **irreversibile** — per *resettare* un archivio (es. ricaricarlo
da zero dopo che la fonte è cambiata): elimina e ricarica la fonte con lo
stesso nome DB. Lista ed eliminazione sono disponibili anche dalla **Mini App**
(tab Archivio).

## Documenti e immagini (PDF-scansione, screenshot) — via NotebookLM

Un PDF **senza testo** (scansione, screenshot) non ha nulla da estrarre con
`pypdf`. Ma **NotebookLM lo legge** (OCR multimodale). Dall'host:

```bash
vps1777 archive-ingest <file> --db <nome> --verify
```

Cosa fa: crea un notebook usa-e-getta, ci mette il file (NotebookLM lo processa),
chiede la **trascrizione integrale** via query, con `--verify` chiede a NotebookLM
di **verificare la fedeltà** della propria trascrizione (doer + checker), poi
indicizza il testo nell'archivio e pulisce il notebook. Funziona con PDF-immagine,
scansioni e qualunque file che NotebookLM sappia leggere.

> ⚠️ La trascrizione è generata da LLM, **non è OCR deterministico**: ottima per
> ritrovare contenuti, non garantita fedele al 100% su layout complessi. La query
> di verifica (`--verify`) segnala parti incerte/mancanti.

Richiede l'auth NotebookLM configurata (profilo nlm — vedi `/admin/nlm`).

## Costruire un DB da riga di comando (locale)

L'indexer è stdlib-only e gira anche standalone (utile per batch grossi sul PC,
poi carichi il `.db` col drop-in):

```bash
python3 services/gateway/app/archive_indexer.py <input> out.db --project nome
```

## Schema di un DB valido

Tabella `messages(uuid PRIMARY KEY, project, ts, content)` + indice FTS5 esterno
`messages_fts(uuid, project, ts, content)`. È quello che producono `archive_indexer`
e `archive-ingest`. Un `.db` drop-in deve avere questo schema (validato all'upload).

## Come funziona sotto (confine no-docker.sock)

Il gateway monta il volume `archive-data:rw` e scrive i `.db` in
`/var/lib/archive/db/`; `archive-mcp` scansiona quella dir (**scan-mode**) e
scopre i DB nuovi senza riavvio. Per l'ingest via NotebookLM, l'orchestrazione è
sull'host (`vps1777 archive-ingest`): il gateway non parla a Docker né a nlm — il
CLI host copia il file in `nb1777-mcp` (che ha l'auth nlm), ne ricava il testo, e
lo passa al gateway per l'indicizzazione. Vedi [ARCHITECTURE.md](ARCHITECTURE.md).
