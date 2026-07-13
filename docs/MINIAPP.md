# Mini App Telegram — la plancia mobile

La Mini App è il pannello di controllo di vps1777 **dentro Telegram**: si apre
dal bot (bottone **Pannello** accanto al campo di testo, o `/pannello`) e non
chiede password — l'identità arriva da Telegram, verificata dal server.

## Divisione delle superfici (perché non è un doppione)

| Superficie | Ruolo |
|---|---|
| **`/admin`** (web) | desktop: setup, upload profilo nlm, operazioni pesanti |
| **Mini App** | mobile: azioni frequenti, auth trasparente, un tap dalla chat |
| **bot** | notifiche, launcher della Mini App, comandi testuali rapidi |

La Mini App è *thin*: chiama endpoint JSON del gateway che riusano la stessa
logica di `/admin` (stessi file di stato, stessi upstream MCP) — zero logica
duplicata da mantenere.

## Cosa fa

- **Stato** — gateway online, versione in esecuzione (badge se c'è una release
  più nuova), connettori MCP con **URL completo copiabile** (quello da incollare
  in claude.ai → Settings → Connectors), riassunto scadenze secret.
- **Notebook** — lista dei notebook NotebookLM; tap su uno → domanda RAG
  direttamente dal telefono (le query lunghe mostrano il tempo trascorso).
- **Archivio** — ricerca FTS5 nell'archivio personale (tutti i DB o uno
  specifico), snippet evidenziati; **lista dei DB caricati** con scheda
  (messaggi, etichette principali, dimensione, ultimo aggiornamento) ed
  **eliminazione** con conferma (irreversibile; per resettare un archivio:
  elimina e ricarica la fonte con lo stesso nome).
- **Sistema** — scadenze secret in dettaglio, **update a un tap** (stesso
  meccanismo del pulsante admin: intent + CLI host, con conferma e progress in
  tempo reale), ultimi eventi audit.

## Autenticazione — initData HMAC + owner-only

1. Telegram inietta nella webview `initData`: i dati dell'utente **firmati
   HMAC-SHA256 col token del bot** (chiave che solo Telegram e il gateway
   conoscono).
2. Il frontend la POSTa a `/app/auth`; il server ricalcola l'HMAC
   (`miniapp_core.verify_init_data`, spec Telegram), scarta initData più
   vecchie di 24h, e verifica che l'utente sia **l'owner**
   (`TELEGRAM_OWNER_ID`): chiunque altro riceve 403, anche con initData valida.
   L'endpoint `/app/auth` è **rate-limited** (20 richieste / 5 min per-IP, dal
   v0.25.0): oltre la soglia risponde 429.
3. Se ok, emette un **JWT `typ=miniapp`** (1h) che il frontend usa come Bearer
   su `/app/api/*`. Alla scadenza la pagina si ri-autentica da sola (initData
   vale 24h).

Perché è solido:
- l'HMAC non è forgiabile senza il token del bot; il server non si fida di
  `initDataUnsafe` (dati lato client) ma solo della firma verificata;
- l'owner-check è **server-side**: il bot mostra il bottone solo all'owner, ma
  non ci si fida del client (difesa in profondità);
- l'owner-gating è **fail-closed** (dal v0.22.0): se `TELEGRAM_OWNER_ID` manca o
  è malformato (→ 0), `/app/auth` risponde **503 `owner_not_configured`** e NEGA
  tutti — non lascia più passare chiunque abbia una initData valida
  (`is_owner` ritorna False quando l'owner non è configurato);
- niente CSRF necessario: gli endpoint usano il Bearer header, mai cookie —
  un form cross-origin non può forgiarlo;
- `typ=miniapp` è un boundary separato: quel token non vale né come `access`
  (proxy MCP) né come `admin` (pannello web).

## Endpoint

| Endpoint | Metodo | Auth | Cosa fa |
|---|---|---|---|
| `/app` | GET | — | la pagina (CSP con nonce per-risposta) |
| `/app/auth` | POST | initData | valida + emette JWT miniapp |
| `/app/api/overview` | GET | Bearer | versione, upstreams, riassunto secret |
| `/app/api/plugins` | GET | Bearer | connettori MCP con URL (contengono il gateway secret → mai pubblici) |
| `/app/api/notebooks` | GET | Bearer | lista notebook (via nb1777-mcp) |
| `/app/api/ask` | POST | Bearer | domanda RAG su un notebook (long-running) |
| `/app/api/archive/dbs` | GET | Bearer | DB dell'archivio con scheda (righe, etichette, top, dimensione, mtime) |
| `/app/api/archive/db/delete` | POST | Bearer | elimina un DB (irreversibile, con audit) |
| `/app/api/archive/search` | POST | Bearer | ricerca FTS5 |
| `/app/api/secrets` | GET | Bearer | scadenze secret (da `secrets_status.json`) |
| `/app/api/audit` | GET | Bearer | ultimi eventi audit |
| `/app/api/update/state` | GET | Bearer | running vs latest + progress updater |
| `/app/api/update` | POST | Bearer | richiede l'update (intent → CLI host); rifiuta i downgrade |

Tutte le risposte `/app/auth` e `/app/api/*` escono con `Cache-Control:
no-store` (middleware, path-based). Gli endpoint parlano con gli upstream MCP
chiamandoli per nome (`nb1777`, `archive` — i nomi di default in
`GATEWAY_UPSTREAMS`): se un'installazione li rinomina, rispondono 503 con
messaggio chiaro.

## Configurazione

- **`TELEGRAM_OWNER_ID`** in `.env` (lo stesso usato dal bot): il gateway lo
  riceve via compose e limita `/app/auth` a quell'utente. Se è vuoto/0 (o
  malformato) la Mini App **non si apre a nessuno**: `/app/auth` risponde 503
  (`owner_not_configured`) e nega tutti — fail-closed dal v0.22.0. Configuralo
  comunque sempre in produzione, o il pannello resta inaccessibile.
- **HTTPS obbligatorio**: Telegram apre le Mini App solo su URL https con
  certificato valido. Con `PUBLIC_BASE` non-https il bot non mostra il bottone
  (e `/pannello` spiega il perché).
- Il **menu button** del bot viene impostato automaticamente all'avvio del bot
  (`set_chat_menu_button` → "Pannello" → `PUBLIC_BASE/app`). Non serve
  configurare nulla in BotFather; se in BotFather esiste una *Main Mini App* o
  un menu button legacy con un URL vecchio, quello **vince sul client** finché
  non lo aggiorni/disabiliti lì (Bot Settings → Configure Mini App).

## Limiti noti

- Le query RAG lunghe (fino a ~5 minuti) tengono aperta la richiesta: se la
  webview va in background su mobile, il sistema può sospenderla — in quel caso
  ripeti la domanda.
- `Same-Origin Restriction` di Telegram (auto-on da luglio 2026) è già
  rispettata: la pagina chiama solo il proprio origin.
- Il token miniapp dura 1h e non è revocabile singolarmente prima della
  scadenza (ruotare `oauth_signing_secret` invalida tutto).
