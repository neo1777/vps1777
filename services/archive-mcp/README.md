# archive-mcp

Search MCP server su FTS5 multi-DB.

## Variabili d'ambiente

| Var | Default | Descrizione |
|---|---|---|
| `ARCHIVE_HTTP_HOST` | `0.0.0.0` | bind |
| `ARCHIVE_HTTP_PORT` | `8002` | porta |
| `ARCHIVE_DB_PATHS` | `main:/var/lib/archive/db/archive.db,cc:.../archive-cc.db,cc-dash:.../archive-cc-dash.db` | CSV `name:path` |
| `FASTMCP_STATELESS_HTTP` | `true` | MCP stateless mode (raccomandato) |

## Degraded mode

Se uno o più DB mancano, il server **parte comunque**: rimuove i DB mancanti dalla registry e stampa un warning. Tool che cercano un DB inesistente ritornano errore esplicito.

## Popolamento DB

Vedi `tools/` nel repo principale per gli indexer (`index_build.py`, `build_cc_archive.py`, ecc.). MVP fornisce solo lo schema base.

## Tool MCP esposti

- `search(query: str, db: str = "", limit: int = 20)` — FTS5 + BM25
- `list_databases()` — elenca i DB disponibili
- `get_conversation(uuid: str, db: str = "")` — recupera record completo
