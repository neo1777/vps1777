# Archivio di ricerca (archive1777)

`archive1777` è un motore di ricerca full-text (SQLite FTS5 + BM25) sui tuoi
corpora: chat, sessioni, note, documenti. **Nasce vuoto**: lo popoli tu, dal
pannello admin o da riga di comando. I DB caricati sono cercabili **subito**,
senza riavvii, via i tool MCP `search` e `list_databases`.

## Dati sensibili e privacy — leggi prima di caricare

L'archivio indicizza **tutto ciò che carichi, verbatim** (il filtro sta a valle,
non all'ingest: un ingestore che scarta metà del file mente su cosa contiene).
Le tue chat e sessioni contengono, di fatto, **dati personali e segreti**: email,
numeri di telefono, e — capita — **credenziali, chiavi SSH, IP e token incollati
durante il lavoro**. Dalla v0.20.0 viene indicizzato anche il **contenuto pieno**
dei messaggi (le *azioni*: comandi lanciati, file aperti, output di tool), quindi
anche quei segreti diventano **cercabili**. È corretto — li hai caricati tu — ma
va saputo.

**La protezione, oggi, è l'ACCESSO — non la redazione.** L'archivio è raggiungibile
solo attraverso il gateway (**OAuth 2.1 + path-secret**) ed è **owner-only**: chi
non ha i token MCP non entra. Non c'è cifratura del contenuto né mascheramento
dei segreti in output: **chiunque abbia accesso all'archivio trova tutto con una
query.**

**La regola pratica** (finché l'archivio resta tuo e dei modelli a cui dai *tu* il
connettore, questa è una scelta difendibile):

- Non caricare nell'archivio materiale che non vuoi ritrovare cercabile in chiaro.
- Se prepari un export **da condividere o pubblicare**, ripuliscilo *prima* di
  caricarlo — l'archivio non lo farà per te.
- Il giorno in cui l'archivio dovesse essere **condiviso, esposto o dato in pasto
  a un modello di terzi**, servirà prima una strategia di redazione o cifratura
  (mascheramento in output, o marcatura `sensitive` con esclusione di default):
  **è una decisione da prendere prima di crescere l'archivio in quella direzione,
  non dopo.**

## Popolare dall'admin — `/admin/archive`

Pannello admin → tab **Archive**. Carichi una fonte, viene indicizzata in un DB
FTS5 e diventa cercabile. Dispatch automatico per estensione:

| Formato | Cosa indicizza |
|---|---|
| `.zip` | riconosciuto dal **contenuto**: export account **claude.ai** (`conversations.json` + `design_chats/` + `projects/docs`) oppure export chat **Telegram Desktop** — `result.json` *o* `messages*.html`, anche zippato come cartella `ChatExport_*/`. **Fallback**: uno zip che non è un export ma contiene documenti `.md`/`.txt` viene indicizzato doc-per-doc (come i `.md`/`.txt` sciolti) |
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

## Cercare — i tool MCP

`archive-mcp` espone cinque tool via MCP (usabili dal connettore claude.ai e
dalla Mini App):

| Tool | Cosa fa |
|---|---|
| `search(query, db_name, limit, …)` | ricerca FTS5; ritorna `{db, uuid, project, ts, rank, snippet, snapshot}` |
| `count(query, db_name, …)` | quanti messaggi corrispondono (non limitato): `{total, per_db}` |
| `get_context(uuid, db_name, before, after)` | i messaggi **attorno** a un risultato, col **contenuto pieno** (supera il troncamento dello snippet) |
| `list_databases()` | i nomi dei DB caricati |
| `describe_databases()` | scheda per DB: righe, intervallo date, etichette, **snapshot** (freschezza) |

**Sintassi della query FTS5** (le stesse regole sono nella docstring che il
modello legge prima di cercare):

- Operatori **in MAIUSCOLO**: `AND`, `OR`, `NOT`, `NEAR(a b, 5)` — in minuscolo
  diventano termini.
- Nessuno stemming, quindi **doppia lingua**: `errore OR error`.
- Famiglie di nomi col **prefisso**: `palant*` (i numeri attaccati non si
  separano: `1777` non trova `N1777`).
- Termini con caratteri speciali (`- . / @ : # '`) **tra virgolette**:
  `"flutter-elinux"`, `"0.7.9"`. In modalità *smart* (default) il server li quota
  da sé; con `raw=true` la query passa intatta (per NEAR/parentesi complesse).
- `sort`: `rank` (rilevanza, default), `newest`, `oldest`. Filtri `since`/`until`
  (ISO) e `project` (etichetta esatta). Su più DB il `limit` è **globale**.

> **Superficie d'errore parlante.** Una query malformata **non** restituisce
> lista vuota (che sarebbe indistinguibile da "nessun match" — un falso negativo
> silenzioso): solleva un errore che spiega come correggerla. Resta valido il
> *protocollo dello zero*: 0 risultati non prova assenza — riprova quotando il
> termine prima di concludere che "non c'è".

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

Schema corrente (v2, dal PR #23):

```sql
messages(uuid PRIMARY KEY, project, ts, content,
         sender, tools, thinking, attachments, parent_uuid)
messages_fts USING fts5(uuid, project, ts, content, tools, attachments,
                        content='messages', ...)   -- external-content
```

È quello che producono `archive_indexer` e `archive-ingest`. In FTS finiscono
`content`, `tools` (le azioni: `tool_use` + `tool_result`) e `attachments`;
`thinking` e `parent_uuid` si **conservano** nella tabella (leggibili via SQL /
`get_context`) ma **non** si indicizzano — vedi la nota sullo schema in
`archive_indexer.py`.

Un `.db` drop-in è accettato se è un SQLite con la tabella `messages_fts`
(controllo in `admin.py`). Anche un DB **v1** (le sole 4 colonne
`uuid, project, ts, content`) resta valido: `migrate_v1_to_v2()` gli aggiunge le
colonne nuove e ricostruisce l'FTS: le righe vecchie restano (con `tools`/`thinking`
vuoti finché non ri-esegui l'ingest sulla fonte, idempotente per `uuid`).

## Come funziona sotto (confine no-docker.sock)

Il gateway monta il volume `archive-data:rw` e scrive i `.db` in
`/var/lib/archive/db/`; `archive-mcp` scansiona quella dir (**scan-mode**) e
scopre i DB nuovi senza riavvio. Per l'ingest via NotebookLM, l'orchestrazione è
sull'host (`vps1777 archive-ingest`): il gateway non parla a Docker né a nlm — il
CLI host copia il file in `nb1777-mcp` (che ha l'auth nlm), ne ricava il testo, e
lo passa al gateway per l'indicizzazione. Vedi [ARCHITECTURE.md](ARCHITECTURE.md).
