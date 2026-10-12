# archive-mcp

Search MCP server su FTS5 multi-DB. **Nasce vuoto**: è un motore di ricerca
generico su SQLite FTS5 e ogni utente lo popola coi propri DB (sessioni chat,
note, qualunque corpus indicizzato in FTS5). Vuoto = stato normale, non un
errore — i tool rispondono con liste vuote finché non aggiungi un DB.

## Variabili d'ambiente

| Var | Default | Descrizione |
|---|---|---|
| `ARCHIVE_HTTP_HOST` | `0.0.0.0` | bind |
| `ARCHIVE_HTTP_PORT` | `8002` | porta |
| `ARCHIVE_DB_DIR` | `/var/lib/archive/db` | dir **scansionata** per `*.db` (nome = nome file). Un DB qui compare **senza restart** (scan-mode). |
| `ARCHIVE_DB_PATHS` | *(vuoto)* | override: CSV `nome:path` per DB fuori dalla dir, es. `main:/data/main.db`. |
| `FASTMCP_STATELESS_HTTP` | `true` | MCP stateless mode (raccomandato) |
| `VPS1777_VERSION` | `0.0.0-dev` | versione dell'immagine (iniettata dalla CI) |
| `ARCHIVE_MODEL_DIR` | `/var/lib/archive/models/e5-small` | modello della ricerca per senso |
| `ARCHIVE_DESC_SECRET_FILE` | *(vuoto; compose: `/run/secrets/archive_desc_secret`)* | segreto per inoltrare `set_description`/`set_ruolo` al gateway |
| `GATEWAY_INTERNAL_BASE` | `http://gateway:8080` | dove inoltrarle |
| `ARCHIVE_REDACT_ESENTI` | *(vuoto)* | valori dell'anagrafica dichiarati pubblici, che la redazione non maschera (CSV) |

## Come popolarlo

**Via UI (consigliato)**: pannello admin del gateway → tab **Archive** (`/admin/archive`). Carichi un export o una sessione (`.jsonl`, `.json`, `.zip`, `.md`, `.txt`, `.pdf`, o un `.db` già indicizzato). Dalla 0.84 il file va in coda e lo indicizza il job `ingest` (lo stato è nella stessa pagina, in «Caricamenti»); il `.db` drop-in invece entra subito. Appena il DB è scritto in `db/` è cercabile, senza restart né modifiche a `.env`.

**A mano**: metti un `.db` (SQLite FTS5, schema sotto) in `/var/lib/archive/db/` (volume `archive-data`). Lo **scan-mode** lo scopre alla prossima ricerca. In alternativa, dichiara path espliciti con `ARCHIVE_DB_PATHS`.

**Costruire un DB da linea di comando**: l'indexer `services/gateway/app/archive_indexer.py` è stdlib-only e gira standalone:
```
python3 archive_indexer.py sessione.jsonl out.db --project nome
```

### Schema atteso
Il minimo per la ricerca è una tabella `messages(uuid PRIMARY KEY, project, ts, content, sender)` + l'indice FTS5 esterno `messages_fts` (il drop-in da `/admin/archive` controlla solo che `messages_fts` ci sia). `archive_indexer` produce uno schema più ricco (`tools`, `attachments`, `parent_uuid`, `ts_source`, tabelle `meta`, `sightings`, `sessioni`…): per un DB fatto a mano, partire da lì (`_SCHEMA` in `archive_indexer.py`).

## Stati e messaggi d'avvio

- **Dir vuota / `ARCHIVE_DB_PATHS` vuoto** → archivio vuoto (stato normale, log `INFO`).
- **Path dichiarato ma file assente** → warning esplicito (config da correggere); il server parte comunque.
- Un tool che cerca un DB inesistente ritorna un errore esplicito.

## Tool MCP esposti

Diciotto tool, in quattro famiglie (firme complete e descrizioni: `app/server.py`):

- **ricerca**: `search` (FTS5 + BM25 su uno o tutti i DB; anche `raw`, `sort`, `since`/`until`, `project`), `search_ibrida` (per senso), `count`, `check_term`, `precedenti`, `delta`
- **lettura**: `get_context`, `get_conversation`, `get_many`, `get_session`, `get_stirpe`
- **inventario**: `list_databases(schede)`, `describe_databases`, `list_projects`, `archive_stats`, `check_integrity`
- **scheda del DB** (la scrittura la inoltra al gateway: qui il volume è `:ro`): `set_description`, `set_ruolo`
