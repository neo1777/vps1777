# nb1777-mcp

NotebookLM MCP wrapper — espone i tool del CLI `nlm` come MCP streamable-http.

## Variabili d'ambiente

| Var | Default | Descrizione |
|---|---|---|
| `NB1777_HOST` | `127.0.0.1` | bind (in `compose.yaml` è `0.0.0.0`, sulla rete interna `backend`) |
| `NB1777_PORT` | `8003` | porta |
| `NB1777_TRANSPORT` | `streamable-http` | `streamable-http`, `stdio`, `sse` |
| `NLM_HOME` | `/var/lib/nlm` | volume col profilo `profiles/default/` + `AUTH_PENDING.flag` |
| `NLM_ARTIFACTS` | `/var/lib/nlm-artifacts` | dove nascono gli artefatti di `studio_download` (volume separato, senza segreti) |
| `GATEWAY_SECRET_FILE` | — | segreto condiviso per gli endpoint `/internal/*`; senza, negano tutto |
| `NOTEBOOKLM_DISABLE_HEADLESS_REFRESH` | — (in `compose.yaml` è `1`) | spegne il refresh headless dei cookie di `nlm`, che nel container non ha il profilo di browser e può solo fallire |
| `FASTMCP_STATELESS_HTTP` | `true` | MCP stateless mode |
| `VPS1777_VERSION` | `0.0.0-dev` | versione dell'immagine (iniettata dalla CI) |

## Auth NotebookLM (post-install)

`nlm` (dalla 0.7 alla 0.12) salva l'auth come profilo `${NLM_HOME}/profiles/default/cookies.json`. Se manca (o esiste `${NLM_HOME}/AUTH_PENDING.flag`), ogni tool che parla con NotebookLM ritorna `RuntimeError` con le istruzioni; i tre tool della memoria (`canonico`, `memoria_check`, `memoria_ack`) leggono file locali e funzionano anche senza.

Sul tuo PC: `nlm login` → `cd ~/.notebooklm-mcp-cli && tar czf nlm-profile.tgz profiles/default` → carica il tar.gz dal pannello `<PUBLIC_BASE>/admin/nlm`.

## Tool MCP esposti

40 tool, in sei famiglie: notebook (6), source (9), chat (2: `notebook_query` e `notebook_query_esito`), studio —
creazione (10: i 9 artefatti + `studio_create_all_9`), studio — gestione (8), diagnostica e
memoria (4: `doctor`, `canonico`, `memoria_check`, `memoria_ack`). Firme e comportamento stanno
nelle docstring di `app/server.py`, che il client MCP mostra ai modelli; la guida è
[docs/NB1777.md](../../docs/NB1777.md).

Qualche firma, per orientarsi:

- `nb_list()`, `nb_get(notebook_id)`, `nb_create(title)`
- `source_list(notebook_id)`, `source_add_url(notebook_id, url, title?)`,
  `source_add_text(notebook_id, text, title)`
- `notebook_query(notebook_id, question, source_ids?, conversation_id?, verbose?, attesa_max?)` — RAG chat;
  aspetta al massimo `attesa_max` secondi (default 25, tetto 270), poi torna `{stato: "in_corso", query_id}`
  e la risposta si ritira con `notebook_query_esito(query_id, attesa_max?)`
- `studio_create_audio(notebook_id, ...)`, `studio_list(notebook_id)`,
  `studio_download(kind, notebook_id, output_path, artifact_id?)`

Oltre ai tool, il server espone gli endpoint `/internal/*` (solo rete interna, con segreto
condiviso) e `/health`.
