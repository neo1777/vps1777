# nb1777-mcp

NotebookLM MCP wrapper — espone i tool del CLI `nlm` come MCP streamable-http.

## Variabili d'ambiente

| Var | Default | Descrizione |
|---|---|---|
| `NB1777_HOST` | `0.0.0.0` | bind |
| `NB1777_PORT` | `8003` | porta |
| `NB1777_TRANSPORT` | `streamable-http` | `streamable-http`, `stdio`, `sse` |
| `NB1777_ALLOWED_ORIGINS` | `https://claude.ai,https://web.telegram.org` | CSV |
| `NLM_HOME` | `/var/lib/nlm` | volume col profilo `profiles/default/` + `AUTH_PENDING.flag` |
| `FASTMCP_STATELESS_HTTP` | `true` | MCP stateless mode |
| `VPS1777_VERSION` | `0.0.0-dev` | versione dell'immagine (iniettata dalla CI) |

## Auth NotebookLM (post-install)

`nlm` 0.7.x salva l'auth come profilo `${NLM_HOME}/profiles/default/cookies.json`. Se manca (o esiste `${NLM_HOME}/AUTH_PENDING.flag`), ogni tool MCP ritorna `RuntimeError` con le istruzioni.

Sul tuo PC: `nlm login` → `cd ~/.notebooklm-mcp-cli && tar czf nlm-profile.tgz profiles/default` → carica il tar.gz dal pannello `<PUBLIC_BASE>/admin/nlm`.

## Tool MCP esposti (MVP)

Sono un sottoinsieme dei ~60 del vecchio stack; gli altri arriveranno in una
release successiva.

- `nb_list()` — elenca notebook
- `nb_get(id)` — dettagli notebook
- `nb_create(title)` — crea
- `source_list(id)`, `source_add_url(id, url)`, `source_add_text(id, title, text)`
- `notebook_query(id, question)` — RAG chat
- `studio_create_audio(id, ...)`, `studio_list(id)`, `studio_download(...)`

Per gli altri (mindmap, slide, infografica, ecc.) vedi tracker.
