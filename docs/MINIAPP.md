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
  più nuova), connettori MCP con l'URL **mascherato** di default: quello vero
  (da incollare in claude.ai → Settings → Connectors) contiene il
  `gateway_secret`, e si scopre o si copia con un tap esplicito, un connettore
  per volta, che resta nell'audit (H26); riassunto scadenze secret.
- **Notebook** — lista dei notebook NotebookLM; tap su uno → domanda RAG
  direttamente dal telefono (le query lunghe mostrano il tempo trascorso). Dalla
  0.75.0 la risposta porta le **fonti** (numero, titolo, anteprima del passo citato) e
  dice quanti paragrafi **non hanno citazioni** (generati dal modello, non letti dalle
  fonti). La domanda **si ritrova**: se il telefono va in tasca a metà, riaprendo la Mini
  App la riprende, e l'ultima risposta resta in cima alla lista.
- **Archivio** — ricerca **per parole** (FTS5) o **per senso** (`search_ibrida`, dalla
  0.75.0) nell'archivio personale: senza scegliere un DB cerca nel perimetro di default
  (primari e non dichiarati, mai i riservati), o in un DB specifico; snippet evidenziati,
  e per le righe trovate per senso il pezzo che ha colpito. Su ogni risultato
  **contesto** apre i messaggi attorno (`get_context`, tre prima e tre dopo) e **copia
  rif.** copia `db·uuid·ts`, il riferimento da citare in una chat. **Lista dei DB caricati** con scheda
  (messaggi, etichette principali, dimensione, ultimo aggiornamento) ed
  **eliminazione** con conferma (irreversibile; per resettare un archivio:
  elimina e ricarica la fonte con lo stesso nome).
- **Sistema** — scadenze secret in dettaglio, **update a un tap** (stesso
  meccanismo del pulsante admin: intent + CLI host, con conferma e progress in
  tempo reale), ultimi eventi audit.

## Autenticazione — initData HMAC + owner-only

1. Telegram inietta nella webview `initData`: i dati dell'utente **firmati
   HMAC-SHA256** con una chiave derivata dal token del bot,
   `HMAC_SHA256("WebAppData", token)`.
2. Il frontend la POSTa a `/app/auth`; il server ricalcola l'HMAC
   (`miniapp_core.verify_init_data`, spec Telegram), scarta initData più
   vecchie di 12h (H27), e verifica che l'utente sia **l'owner**
   (`TELEGRAM_OWNER_ID`): chiunque altro riceve 403, anche con initData valida.
   Il gateway **non ha il token** (H54): ha solo la chiave derivata, dal secret
   `telegram_webapp_secret` (`TELEGRAM_WEBAPP_SECRET_FILE`). La derivazione è a
   senso unico — chi ha la chiave può verificare le firme di questa Mini App ma
   non risalire al token, quindi non può parlare come il bot. Se non c'è né la
   chiave né il token, `/app/auth` risponde **503 `bot_token_not_configured`**.
   L'endpoint `/app/auth` è **rate-limited** (20 richieste / 5 min per-IP, dal
   v0.25.0): oltre la soglia risponde 429.
3. Se ok, emette un **JWT `typ=miniapp`** (1h) che il frontend usa come Bearer
   su `/app/api/*`. Alla scadenza la pagina si ri-autentica da sola (initData
   vale 12h; oltre, bisogna riaprire il pannello dal bot).
4. Su **ogni** richiesta `/app/api/*` il server riverifica che il `sub` del
   token sia ancora l'owner configurato (H27): la firma prova solo che il token
   è stato emesso, non che l'owner sia lo stesso. Se l'owner cambia o viene
   tolto dal `.env`, i token già emessi smettono di valere subito (401, con un
   evento `miniapp_bearer_not_owner` nell'audit), senza aspettare la scadenza.

Perché è solido:
- l'HMAC non è forgiabile senza la chiave derivata dal token del bot; il
  server non si fida di `initDataUnsafe` (dati lato client) ma solo della firma
  verificata;
- l'owner-check è **server-side**, all'emissione e a ogni richiesta: il bot
  mostra il bottone solo all'owner, ma non ci si fida del client (difesa in
  profondità);
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
| `/app/api/plugins` | GET | Bearer | connettori MCP con URL **mascherato** di default; l'URL vero solo con `?reveal=<nome>` e un tap esplicito (H26) |
| `/app/api/notebooks` | GET | Bearer | lista notebook (via nb1777-mcp) |
| `/app/api/ask` | POST | Bearer | domanda RAG su un notebook: un giro aspetta al massimo 20 s e risponde `{stato: "in_corso"}` o `{stato: "pronta", answer, fonti, senza_citazioni?, nota?}`; la pagina rilancia con `ripresa: true` (nb1777 si aggancia alla query in corso, nessuna riga d'audit nuova) e il gateway tiene la risposta pronta 30 minuti |
| `/app/api/archive/dbs` | GET | Bearer | DB dell'archivio con scheda (righe, etichette, top, dimensione, mtime) |
| `/app/api/archive/db/delete` | POST | Bearer | elimina un DB (irreversibile, con audit) |
| `/app/api/archive/search` | POST | Bearer | ricerca per parole (`modo: "parole"`, FTS5, default) o per senso (`modo: "senso"`, `search_ibrida`, timeout 120 s per il primo caricamento del modello); `{results, modo, saltati?}` |
| `/app/api/archive/context` | POST | Bearer | i messaggi attorno a un risultato `{db, uuid}` (`get_context`, 3+3, righe troncate a 2000 caratteri) |
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
- **`secrets/telegram_webapp_secret.txt`**: la chiave derivata dal token con
  cui il gateway verifica `initData`. La scrivono `deploy.sh` (anche con
  `--apply`, quando il pannello gli passa il token) e l'installer; la CLI
  `vps1777` la ricalcola dal token prima dei suoi `compose up`, così segue
  anche una rotazione del token. Senza, `/app/auth` risponde 503
  `bot_token_not_configured`.
- **HTTPS obbligatorio**: Telegram apre le Mini App solo su URL https con
  certificato valido. Con `PUBLIC_BASE` non-https il bot non mostra il bottone
  (e `/pannello` spiega il perché).
- Il **menu button** del bot viene impostato automaticamente all'avvio del bot
  (`set_chat_menu_button` → "Pannello" → `PUBLIC_BASE/app`). Non serve
  configurare nulla in BotFather; se in BotFather esiste una *Main Mini App* o
  un menu button legacy con un URL vecchio, quello **vince sul client** finché
  non lo aggiorni/disabiliti lì (Bot Settings → Configure Mini App).

## Limiti noti

- La domanda in corso e l'ultima risposta stanno nel `localStorage` della webview, solo
  su quel telefono; il gateway tiene le risposte pronte in memoria per 30 minuti, quindi
  un riavvio del gateway le perde (riaprendo, la Mini App rifà la domanda). Oltre i 30
  minuti anche nb1777 dimentica la query, e la domanda riparte da capo.
- `Same-Origin Restriction` di Telegram (auto-on da luglio 2026) è già
  rispettata: la pagina chiama solo il proprio origin.
- Il token miniapp dura 1h e non è revocabile singolarmente prima della
  scadenza (ruotare `oauth_signing_secret` invalida tutto).
