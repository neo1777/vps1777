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
| `ARCHIVE_DB_PATHS` | *(vuoto)* | CSV `nome:path` dei DB da montare, es. `main:/var/lib/archive/db/main.db,note:/var/lib/archive/db/note.db`. Vuoto ⇒ archivio vuoto. |
| `FASTMCP_STATELESS_HTTP` | `true` | MCP stateless mode (raccomandato) |
| `VPS1777_VERSION` | `0.0.0-dev` | versione dell'immagine (iniettata dalla CI) |

## Come popolarlo

1. Metti i file `.db` (SQLite FTS5) nel volume `archive-data` (montato su `/var/lib/archive`), tipicamente sotto `/var/lib/archive/db/`.
2. Dichiarali in `.env` con `ARCHIVE_DB_PATHS="nome:/var/lib/archive/db/<file>.db,..."`.
3. Riavvia `archive-mcp`. `list_databases()` mostrerà i nomi caricati.

Gli indexer (`tools/` nel repo principale: `index_build.py`, `build_cc_archive.py`, ecc.) sono un modo per costruire questi DB, non un requisito: qualunque SQLite con tabelle FTS5 conformi allo schema va bene.

## Stati e messaggi d'avvio

- **`ARCHIVE_DB_PATHS` vuoto** → archivio vuoto (stato normale, log `INFO`).
- **Path dichiarato ma file assente** → warning esplicito (config da correggere); il server parte comunque, rimuovendo dalla registry i DB mancanti.
- Un tool che cerca un DB inesistente ritorna un errore esplicito.

## Tool MCP esposti

- `search(query: str, db: str = "", limit: int = 20)` — FTS5 + BM25
- `list_databases()` — elenca i DB disponibili
- `get_conversation(uuid: str, db: str = "")` — recupera record completo
