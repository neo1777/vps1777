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

## Come popolarlo

**Via UI (consigliato)**: pannello admin del gateway → tab **Archive** (`/admin/archive`). Carichi una sessione Claude Code `.jsonl`, viene indicizzata in un DB FTS5 e diventa **cercabile subito** — nessun restart, nessuna modifica a `.env`.

**A mano**: metti un `.db` (SQLite FTS5, schema sotto) in `/var/lib/archive/db/` (volume `archive-data`). Lo **scan-mode** lo scopre alla prossima ricerca. In alternativa, dichiara path espliciti con `ARCHIVE_DB_PATHS`.

**Costruire un DB da linea di comando**: l'indexer `services/gateway/app/archive_indexer.py` è stdlib-only e gira standalone:
```
python3 archive_indexer.py sessione.jsonl out.db --project nome
```

### Schema atteso
Un DB valido ha una tabella `messages(uuid PRIMARY KEY, project, ts, content)` + indice FTS5 esterno `messages_fts(uuid, project, ts, content)`. È quello che produce `archive_indexer`.

## Stati e messaggi d'avvio

- **Dir vuota / `ARCHIVE_DB_PATHS` vuoto** → archivio vuoto (stato normale, log `INFO`).
- **Path dichiarato ma file assente** → warning esplicito (config da correggere); il server parte comunque.
- Un tool che cerca un DB inesistente ritorna un errore esplicito.

## Tool MCP esposti

- `search(query: str, db_name: str = "", limit: int = 20)` — FTS5 + BM25 su uno o tutti i DB
- `list_databases()` — elenca i DB disponibili
