# Changelog

Formato [Keep a Changelog](https://keepachangelog.com/it/1.1.0/), versioning [SemVer](https://semver.org/).

## [0.15.0] — 2026-07-08

### Sicurezza — gestione secret (scadenze/notifiche) + oauth refresh rotation

- **oauth: rotazione del refresh token + revoca durevole** (OAuth 2.1 BCP). A ogni uso del refresh il vecchio è revocato e ne viene emesso uno nuovo; la revoca è **persistita su disco** (sopravvive ai restart) e il **riuso di un refresh revocato viene rilevato** (segnale di furto → rifiuto + audit). Prima il refresh non ruotava e la revoca era in-memory (persa al restart). Validato live.
- **Monitoraggio scadenze secret**: nuovo `vps1777 secrets-status [--notify]` — età di ogni secret (dall'mtime), confronto con soglia (signing 90g, admin_pw 90g, gateway 180g, bot 365g), scrive `onboarding/secrets_status.json` e **notifica su Telegram** i scaduti. Timer systemd **settimanale** `vps1777-secrets-check.timer` (installato/abilitato dall'installer).
- **`/admin/secrets`**: da placeholder a pagina vera — età, ultima rotazione e stato di ogni secret + istruzioni di rotazione.
- Roadmap dichiarata: l'auto-rotazione trasparente dei secret di sistema (signing/gateway) richiede un *key-ring con grazia* — rimandata. La gran parte dei secret resta a rotazione **manuale con notifica** (ruotarli a caso romperebbe i connettori attivi).
- Doc: [docs/SECRETS.md](docs/SECRETS.md) → "Scadenze e monitoraggio".

## [0.14.0] — 2026-07-08

### Sicurezza — token CSRF sui form admin (difesa in profondità)

- **Token CSRF** (synchronizer token firmato, legato alla sessione) su tutti i form admin autenticati, sopra a `samesite=lax`. Un form ostile cross-origin non può leggerlo né forgiarlo (non ha la chiave di firma) → la POST fallisce anche se il cookie arrivasse. La verifica è **centralizzata in `_require_admin`**: ogni POST admin — anche uno aggiunto in futuro — è protetto **d'ufficio**, senza doverselo ricordare handler per handler. Il token è iniettato automaticamente in ogni `<form>` da `_layout`.
  - Motivazione (principio): non ci si fida del fatto che "oggi le azioni sono solo POST" — un prodotto in evoluzione può introdurre GET/plugin/contenuto same-site; la difesa deve reggere **a prescindere** dai cambi futuri.
- `jwt_helpers`: nuovo `typ="csrf"`. Il login (pre-auth) resta senza CSRF (login-CSRF non applicabile a un singolo admin noto).

## [0.13.0] — 2026-07-08

### Sicurezza — hardening dell'autenticazione admin

Da audit dell'auth ("sicurezza al massimo"):
- **Password forti obbligatorie** (`rotate-secret.sh admin_password`): policy **min 16** caratteri, **≥3 classi** (minuscole/MAIUSCOLE/cifre/simboli), niente pattern comuni/prevedibili. Le deboli sono **rifiutate a monte**; la generata di default è forte (24 char).
- **`/admin/login`**: rimossa la **pre-compilazione dell'email** admin (non si espone l'utente valido); **rate-limit/lockout per-IP** (5 tentativi / 5 min → blocco 15 min) contro il brute-force da singola sorgente.
- **Content-Security-Policy** stretta sulle pagine admin: `script-src 'self' 'nonce-…'` (**niente `unsafe-inline`** per gli script), niente origini esterne, `frame-ancestors 'none'` (anti-clickjacking), `base-uri 'none'`, `form-action 'self'`, `object-src 'none'`. Gli script inline portano un **nonce** per-risposta.
- **Google Fonts (CDN esterno) rimossi** → font di sistema, nessuna richiesta esterna dal browser admin.
- **Header di sicurezza globali** (middleware **pure-ASGI**, non rompe lo streaming del proxy MCP): `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Strict-Transport-Security` (https). `X-Frame-Options: DENY` + CSP **solo** sulle pagine admin — la mini-app Telegram resta frameable.

La postura preesistente era già solida (bcrypt cost-12, cookie JWT httponly/secure/samesite=lax, errori login generici, secret 0600, anti-open-redirect). CSRF: difeso da `samesite=lax` (i POST cross-site non portano il cookie admin); token CSRF espliciti restano un rafforzamento futuro opzionale.

## [0.12.2] — 2026-07-08

### Sicurezza

- **`/admin/login`**: il delay anti-brute-force ora è **asincrono** (`await asyncio.sleep`, non `time.sleep`). Il `time.sleep` sincrono bloccava l'intero event loop del gateway per 0,5s a ogni login fallito → un attaccante che martellava l'endpoint pubblico poteva renderlo irraggiungibile (DoS). Da audit dell'autenticazione admin (il resto della postura — bcrypt cost-12, cookie JWT httponly/secure/samesite, errori generici, secret 0600, anti-open-redirect — è risultato solido).

## [0.12.1] — 2026-07-08

### Fix

- `vps1777 archive-ingest`: la pulizia dei file temporanei nei container ora usa `compose exec -u root` — i temp sono creati da `docker cp` (root) e l'utente app (uid 1000, con `cap_drop: ALL` → niente `DAC_OVERRIDE`) non poteva rimuoverli. Nessun residuo in `/tmp` dopo l'ingest.

## [0.12.0] — 2026-07-08

### Aggiunto — Archive: OCR/lettura documenti via NotebookLM (`vps1777 archive-ingest`)

- Nuovo comando host **`vps1777 archive-ingest <file> --db <nome> [--verify]`**: usa **NotebookLM come motore OCR/lettura multimodale** per estrarre il testo di file che `pypdf` non sa leggere (PDF-immagine, scansioni, screenshot) e indicizzarlo nell'archivio FTS. NotebookLM è **doer + checker**: trascrive il documento e, con `--verify`, verifica la fedeltà della propria trascrizione. Validato sul reale: PDF-immagine → ~13k caratteri estratti, cercabili in `archive1777`.
  - Orchestrazione che rispetta il confine no-docker.sock: il CLI host copia il file in `nb1777-mcp` (che ha l'auth nlm) → `app.ingest` trascrive su un notebook usa-e-getta (cleanup incluso) → il testo passa al gateway → `archive_indexer` lo indicizza → `archive-mcp` lo scopre (scan-mode).
- `nb1777-mcp`: nuova `core.transcribe_document()` + entrypoint `app.ingest`.
- Pagina `/admin/archive`: box informativo sulla via NotebookLM per documenti/immagini; il messaggio d'errore sui PDF-immagine ora rimanda a `vps1777 archive-ingest`.
- Doc: nuova guida [docs/ARCHIVE.md](docs/ARCHIVE.md) (pagina, formati, ingest via NotebookLM) + link dal README.
- Caveat dichiarato: la trascrizione è generata da LLM, non OCR deterministico → ottima per ritrovare contenuti, non garantita fedele al 100% su layout complessi (per questo il `--verify`).

## [0.11.0] — 2026-07-08

### Aggiunto — Archive: formati PDF e Telegram

- `/admin/archive` ora accetta anche:
  - **`.pdf`** (documenti con **testo**): estratto via `pypdf` e indicizzato. Uno screenshot-PDF (immagine, senza layer di testo) non è indicizzabile senza OCR → messaggio d'errore **chiaro** invece di un DB vuoto silenzioso ("serve OCR — carica il testo sorgente").
  - **`.json`** export **Telegram Desktop** (formato *Machine-readable JSON*): messaggi indicizzati con le *entities* del testo appiattite; i record `service` (pin, join, …) saltati. Il dispatch distingue Telegram (oggetto con `messages`/`chats`) da Claude Code (JSONL) per struttura.
- Nuova dipendenza del gateway: **`pypdf`** (solo per l'estrazione testo dai PDF; gli altri formati restano stdlib).

## [0.10.0] — 2026-07-08

### Aggiunto — Archivio di ricerca popolabile dall'admin (`/admin/archive`)

- Nuovo tab **Archive** nel pannello admin: carichi una fonte, viene indicizzata in un DB SQLite FTS5 cercabile da `archive1777` **subito**, senza restart. Formati (dispatch per estensione):
  - **`.jsonl`** — sessione Claude Code (record user/assistant)
  - **`.zip`** — export account claude.ai: `conversations.json` + `design_chats/` + `projects/docs` (un export reale ≈ 13k messaggi indicizzati in ~6s)
  - **`.md` / `.txt`** — testo/markdown generico, spezzato in chunk (ponte per l'output di altri tool: web2md, lettoremd, pulizia-transcript)
  - **`.db`** — drop-in di un archivio già indicizzato (validato: schema `messages_fts`)
- **Indexer condiviso** `services/gateway/app/archive_indexer.py` (stdlib-only, streaming, idempotente per id): usato server-side dalla pagina **e** runnabile standalone (`python3 archive_indexer.py <input> out.db --project nome`).
- **`archive-mcp` scan-mode**: scansiona `ARCHIVE_DB_DIR` (default `/var/lib/archive/db`) per `*.db` e li scopre **senza restart** (refresh su mtime). `ARCHIVE_DB_PATHS` resta come override per path espliciti fuori dalla dir.
- Il gateway monta `archive-data:rw` (come `nlm-auth`): scrive i `.db` che archive-mcp legge. Confine no-docker.sock rispettato — il gateway scrive un file, archive-mcp lo scopre.
- Fix doc: rimosso `get_conversation` (tool inesistente) dal README di `archive-mcp`; documentati scan-mode e pagina di upload.

## [0.9.3] — 2026-07-05

### Aggiunto — State card NotebookLM opzionale (hook post-update)

- Se `.env` definisce **`VPS1777_STATECARD_NB`** (id notebook), dopo ogni `vps1777 update`/rollback riuscito la VPS fa **upsert idempotente** di una "state card" (versione + contratto tool + rimando a `doctor`, datata) come fonte testuale del notebook — via il nuovo entrypoint `app.statecard` nel container nb1777-mcp. **Best-effort**: un fallimento (auth assente, MCP giù, notebook rimosso) non blocca mai l'update. **Vuoto di default** ⇒ feature spenta. Serve ai contesti che leggono un notebook *senza* l'MCP; la verità viva resta il tool `doctor`. Riusa (dogfooda) i fix `source` di 0.9.1 — list/delete/add.
- `.env.example`: documentati gli opzionali `VPS1777_STATECARD_NB` e `ARCHIVE_DB_PATHS` (come popolare l'archivio che dalla 0.9.1 nasce vuoto).

## [0.9.2] — 2026-07-05

### Aggiunto — `doctor` come verità viva (anti-memoria-stale)

- Il tool **`doctor`** (nb1777) ora riporta **`vps1777_version`** (da `VPS1777_VERSION`, iniettata a ogni release → si aggiorna **da sola** a ogni update del gateway) e un **`contract_note`** che invita a fidarsi degli schemi live dei tool e di `doctor`, non di quirk memorizzati. Una sessione che chiama `doctor` all'inizio vede *quale* build sta interrogando e che i contratti `source`/`studio` sono pinnati e verificati dal contract-test. Rompe la dipendenza dalla memoria per i fatti volatili dell'MCP: la verità del gateway si aggiorna a ogni release, la memoria no.

## [0.9.1] — 2026-07-05

### Fix — nb1777-mcp: famiglia `source` + `studio_download` allineate a nlm 0.7.7

La 0.9.0 aveva **pinnato** `notebooklm-mcp-cli==0.7.7` ma il wrapper (`services/nb1777-mcp/app/core.py`) costruiva ancora gli `argv` di alcuni sottocomandi all'interfaccia precedente. Cinque tool erano di fatto rotti (scoperti da un health-check MCP live, verificati contro l'`--help` del binario):

- **`source_get_content`**: passava `notebook_id` posizionale, ma `nlm source content` 0.7.7 vuole solo `SOURCE_ID` → *"Got unexpected extra argument(s)"*. Fix: `content SOURCE_ID`.
- **`source_rename`**: `nlm source rename` 0.7.7 richiede il notebook come opzione `-n/--notebook` → *"Missing option --notebook"*. Fix: `rename -n NOTEBOOK SOURCE_ID TITLE`.
- **`source_delete`**: passava `notebook_id` come primo `SOURCE_ID` → *"Failed to delete sources"* (failure-mode: cancellare l'oggetto sbagliato). Fix: `delete SOURCE_ID --confirm`.
- **`source_add_*` (return-id)**: ritornavano `sources[-1]`, assumendo che l'ultima fonte in lista fosse quella appena creata — falso con ≥2 fonti (`source_add_url` restituiva l'id della fonte testo). Fix: `_add_and_resolve_id` ricava l'id per **differenza** degli id prima/dopo l'add (fallback loggato in caso di concorrenza sullo stesso account).
- **`studio_download`**: passava `--no-progress`, opzione inesistente in `nlm download` 0.7.7 → download fallito (nell'health-check originale mascherato dal blocco-approvazione MCP a monte). Fix: rimosso.

Tutti e cinque validati **live** su un notebook usa-e-getta (ciclo reversibile, cleanup completo).

### Aggiunto — Contract-test anti-drift wrapper↔`nlm`

- **`services/nb1777-mcp/tests/test_source_cli_contract.py`** + job CI **`contract`**: installa il pin `nlm 0.7.7` e verifica, parsando `--help`, che le firme dei sottocomandi `source *` e `download report` siano quelle su cui `core.py` si appoggia. Un futuro bump di `nlm` che cambia una firma fallisce **in CI**, non in produzione — il pin da solo non basta (la 0.9.0 lo dimostra).

### Cambiato — `archive-mcp` nasce vuoto (first-class)

- `compose.yaml` non cabla più DB SQLite specifici: `ARCHIVE_DB_PATHS` ha default **vuoto**, overridabile da `.env`. Un archivio vuoto è lo **stato normale** di un'installazione nuova (log `INFO`, non più *"degraded mode / SENZA DB"*): ogni utente lo popola coi propri DB FTS5. Il warning resta solo per la misconfig reale (path dichiarato ma file assente). README di `archive-mcp` riscritto in chiave generica.

## [0.9.0] — 2026-07-04

### Aggiunto — Canale di self-update gestito

- **CLI host `vps1777`** (`check`, `update`, `rollback [--with-data]`, `status [--json --probe]`, `version`, `migrate`, `bootstrap`) — il motore unico degli aggiornamenti: backup age + snapshot locale pre-update (`backups/pre-update/`), pull con verifica digest contro `images.lock` del bundle di release, migrazioni, health-gate 180s, **auto-rollback** su fallimento, esito su Telegram. Installata in `/usr/local/bin` da installer/deploy.sh. Manuale utente: [docs/UPDATE.md](docs/UPDATE.md).
- **Pannello admin → tab Update**: card con versione corrente / ultima release / changelog + pulsante **Aggiorna** con progress. Il gateway resta senza privilegi: il pulsante scrive un **intent file** (`onboarding/update_pending_update.json`, validato: schema, semver, TTL, nonce anti-replay) che la systemd **path unit** `vps1777-update.{path,service}` raccoglie ed esegue sull'host. Il footer admin mostra la versione deployata.
- **Check giornaliero + notifica Telegram**: `vps1777-check-update.{service,timer}` — una GET a `api.github.com/releases/latest`, **zero telemetria**; messaggio al owner (una volta per release) + badge nella card admin.
- **Migrazioni idempotenti** (`migrations/`): applicate una volta sola durante l'update, registro nel volume `gateway-data`; contratto in [migrations/README.md](migrations/README.md).
- **Bootstrap one-shot** (`tools/bootstrap.sh` / `vps1777 bootstrap`): converte un'installazione legacy (immagini buildate in locale) al modello pull, senza mai toccare i volumi named.
- **Healthcheck `nb1777-bot`**: file heartbeat `/tmp/nb1777-bot.heartbeat` (unhealthy se mtime > 90s) — il bot long-poll non espone porte.
- **`/health?deep=1`** sul gateway: proba TCP gli upstream MCP (503 se giù); usato dal health-gate dell'update.
- **`tools/restore.sh`**: nuovi flag `--yes` (nessuna conferma) e `--volumes-only <csv>`; accetta anche una **directory snapshot non cifrata** (`backups/pre-update/<dir>`) oltre al `.tar.age`. Default resta interattivo.

### Cambiato — Distribuzione registry-pull

- **`compose.yaml` è PULL-ONLY**: immagini `${VPS1777_IMAGE_BASE:-ghcr.io/neo1777}/vps1777-<svc>:${VPS1777_TAG:-dev}` pubblicate dalla CI di release (firmate cosign, con SBOM). Nessun `build:` in compose.yaml: il build locale vive solo nel nuovo overlay **`compose.build.yaml`** (dev/CI: `docker compose -f compose.yaml -f compose.build.yaml -f compose.dev.yaml up --watch`). Sulla VPS non si builda **mai** (vincolo 4GB).
- **`release.yml`** ora crea anche la **GitHub Release** col runtime bundle (`vps1777-runtime-vX.Y.Z.tar.gz` + `SHA256SUMS` + firma cosign) e marca prerelease i tag `-rc.*`; `:latest` segue solo le stable. trivy scansiona le immagini ghcr `:latest` pubblicate.
- **File `VERSION`** nel repo (specchio del tag, guard in CI). `.env`: `VPS1777_TAG` = versione deployata (scritta **solo** da update/rollback/bootstrap/installer), nuova var `VPS1777_IMAGE_BASE`.
- **Installer (`engine.py`) e `deploy.sh`**: installano l'ultima release via pull (STEP "Immagini + avvio") e il canale di aggiornamento (CLI + unit systemd). Escape hatch build locale: `DEV_BUILD=1` (deploy.sh) / `VPS1777_DEV_BUILD=1` (installer); override versione per rc: `VPS1777_INSTALL_VERSION`. Fallback automatico a build locale se nessuna release esiste.
- **Watchtower (`ops.autoupdate`) declassato**: resta opt-in ma dichiarato **non supportato in concomitanza** col canale gestito (bypassa backup/migrazioni/health-gate/changelog/rollback). Il canale primario è `vps1777 update` / pulsante admin.
- **`tools/backup.sh`**: il MANIFEST registra anche `VPS1777_TAG` e `VERSION`.

### Fix — NotebookLM (nlm 0.7.x) + connector nb1777 (421)

- **Auth NotebookLM allineata a `notebooklm-mcp-cli` 0.7.x**: la CLI non crea più un singolo `auth.json` ma un **profilo** `profiles/default/{cookies.json,metadata.json}`. Aggiornati TUTTI i punti che controllavano `auth.json` (gate `nb1777-mcp/server.py` — il gate reale dei 35 tool — e `auth.py`, semaforo `gateway/onboarding.py`, `nb1777-bot`), il pannello **`/admin/nlm`** (ora accetta un **tar.gz** del profilo, estratto in sicurezza), e i doc (INSTALL, TROUBLESHOOTING, ONBOARDING, ARCHITECTURE, README servizi). Dipendenza **pinnata** a `notebooklm-mcp-cli==0.7.7` (riproducibilità). Trasferimento profilo: `cd ~/.notebooklm-mcp-cli && tar czf nlm-profile.tgz profiles/default` → upload su `/admin/nlm`.
- **Connector nb1777: 421 Misdirected Request** → `nb1777-mcp` aveva la DNS-rebinding protection di FastMCP attiva con `allowed_hosts` che non includevano l'`Host` inoltrato dal gateway (`nb1777-mcp:8003`). Disabilitata (coerente con `archive-mcp`: entrambi dietro il gateway su rete interna; la sicurezza è OAuth + path-secret al gateway). Connector nb1777 ora aggancia i 35 tool.
- **`nlm` non eseguibile nel container** (`No such file or directory: /opt/venv/bin/nlm`) → il venv era costruito in `/build/.venv` e copiato in `/opt/venv`, ma gli **shebang** dei console-script restavano `#!/build/.venv/bin/python` (inesistente nel runtime) → ENOENT all'exec di `nlm`. **Fix**: `UV_PROJECT_ENVIRONMENT=/opt/venv` in tutti i Dockerfile → venv costruito nel path finale, shebang corretti. (Manifesto solo su nb1777-mcp che esegue `nlm`; corretto su tutti per coerenza.)
- **Bot `/lista` muto (KeyError)** → `nb_list` serializza i notebook come N blocchi `content` (uno per notebook, ciascuno un dict); `cmd_lista` leggeva solo `content[0]` e faceva `dict[:30]` → `KeyError` non catturato → handler morto in silenzio. Fix: parsa TUTTI i blocchi (gestisce sia multi-dict che array). Aggiunto **error handler globale** al bot (niente più silenzi: ogni crash di un handler manda un messaggio).
- **Bot Telegram → nb1777-mcp: 406 Not Acceptable** → `_mcp_call` faceva POST senza header `Accept` (MCP streamable-http richiede `application/json, text/event-stream`) e non parsava la risposta SSE. Fix: header corretti + parsing della riga `data:` dell'SSE. Validato: `/lista` ritorna i notebook.
- **`nb1777-mcp` e `nb1777-bot` senza egress** → erano solo sulla rete `backend` (`internal: true`): `nlm` non raggiungeva NotebookLM e il bot non raggiungeva Telegram ("Temporary failure in name resolution"). **Fix**: aggiunti alla rete `ingress` (egress). `archive-mcp` resta solo `backend` (dati locali). Validato live: `nb_list` ritorna i notebook reali.

### Fix — Connector claude.ai end-to-end (OAuth + proxy MCP) — validato live

Catena di 5 bug che impedivano al connector di funzionare, tutti trovati e corretti su VPS reale, ciascuno verificato dal vivo prima del successivo:

1. **PKCE persa** (`"PKCE S256 required"`): il redirect `/authorize → /admin/login` interpolava `next` non-encodato → i parametri PKCE dell'authorize finivano come parametri di `/admin/login` e si perdevano. Fix: `quote(url, safe="")` + guard anti open-redirect.
2. **Loop di login**: il cookie admin era su `path=/admin`, ma dopo il login il flusso va a `/authorize` (fuori da `/admin`) → cookie non inviato → sessione non vista. Fix: cookie su `path=/`.
3. **Proxy MCP rotto** (`"archive1777 returned an error"`): `proxy.py` usava `client.request()` (bufferizza il body) e poi `aiter_raw()` → `httpx.StreamConsumed` su OGNI richiesta MCP. Fix: `build_request` + `send(stream=True)` → streaming corretto (SSE inclusa). Validato: `initialize` → 200 + risposta MCP reale.
4. **DCR in-memory**: le registrazioni connector (Dynamic Client Registration) erano in RAM → ogni restart/rebuild del gateway le perdeva, costringendo a ri-aggiungere il connector. Fix: persistite in `/var/lib/gateway/oauth_clients.json` (volume `gateway-data`). Validato: register → restart → sopravvive.
5. (Vedi sotto) il **502 del Funnel** col comando serve/funnel.

Nota: `archive-mcp` espone **2 tool** (`search`, `get_conversation`) by design; i **35 tool** sono di `nb1777-mcp`.

### Fix — Funnel 502: comando serve/funnel corretto (validato pubblico, HTTP 200)

Primo deploy host-mode riuscito (Funnel "on", cert ok), ma il pubblico dava **502 Bad Gateway**: il `serve status` mostrava `proxy http://127.0.0.1:443` invece di `:8080`. Causa: lanciare `tailscale serve --https=443 <t>` **e poi** `tailscale funnel --bg 443` fa interpretare "443" come *target* (proxy a :443) e sovrascrive il mapping. **Fix**: un solo comando combinato `tailscale funnel --bg --https=443 http://127.0.0.1:8080` (+ `tailscale serve reset` prima, per idempotenza). Validato dal vivo: `https://<host>.ts.net/health` → **HTTP 200** dal pubblico. Corretto in engine.py e deploy.sh.

### Cambiato — Tailscale spostato SULL'HOST (via il sidecar Docker)

Decisione architetturale dopo il debug: **Tailscale non gira più in un container sidecar, ma come servizio sull'host** (installato da installer/deploy.sh). Elimina alla radice i due bug peggiori incontrati: il crash-loop di `containerboot` (bug immagine) e il netns orfano (`network_mode: service:gateway`). `tailscaled` sull'host è robusto, sopravvive ai reboot nativamente, e la config serve/funnel persiste.

- **`engine.py`**: `step_tailscale_host` installa Tailscale sull'host (`install.sh`), fa `tailscale up` con la key, poi `tailscale serve --bg --https=443 http://127.0.0.1:8080` + `tailscale funnel --bg 443` + pre-provisiona il cert. Niente più sidecar, `_relink_tailscale` rimosso. Verifica HTTPS post-reboot via `curl` dall'host.
- **`compose.ingress.tailscale.yaml`**: niente più container tailscale; pubblica solo il gateway su `${GATEWAY_BIND:-127.0.0.1}:8080` (loopback in produzione → solo Funnel; `0.0.0.0` come fallback se il Funnel non parte). Rimosso `ingress/tailscale-serve.json`.
- **`deploy.sh`**: stesso flusso host-mode (main + `--apply`).
- **UI + INGRESS.md**: due metodi auth a pari livello — **auth-key** (semplice, dalla pagina "Add Linux server") e **OAuth client** (automatizza il nodeAttr nell'ACL). Prerequisiti account (MagicDNS/HTTPS/nodeAttr funnel) invariati.
- ⚠ Refactor non testato E2E su deploy pulito (validato a pezzi sul campo) — da verificare al primo deploy da VPS vergine.

### Fix — Funnel Tailscale: crash containerboot + netns + cert (debug su VPS reale)

Sessione di debug end-to-end su VPS reale (con accesso root). Trovati e corretti **tre** problemi che impedivano al Funnel HTTPS di servire (l'URL restava `http://IP:8080`):

1. **[BLOCCANTE] Crash-loop del sidecar Tailscale.** L'immagine `tailscale/tailscale:v1.78.1` ha un bug di `containerboot` (nil pointer in `kubeClient.storeHTTPSEndpoint`) quando `TS_SERVE_CONFIG` è impostato **fuori da Kubernetes** → panic → restart-loop infinito (visto: RestartCount 27). Il nodo lampeggiava in Machines ma non serviva mai il Funnel. **Fix: immagine pinnata a `v1.98.4`** (bug fixato da v1.78.3, PR tailscale/tailscale#14357). Validato dal vivo: dopo il bump il Funnel si attiva.
2. **[BLOCCANTE] netns orfano.** Il sidecar usa `network_mode: service:gateway` (condivide il netns del gateway). Ricreare il gateway (per `PUBLIC_BASE`, o per chiudere :8080) lascia tailscale agganciato al **netns vecchio/morto** → niente DNS, niente proxy verso il gateway. **Fix: `_relink_tailscale()`** — dopo ogni ricreazione del gateway l'engine ricrea anche il sidecar. Validato: il `/health` interno tornava raggiungibile solo dopo il relink.
3. **[MEDIO] Cert Funnel pigro + finestra URL troppo corta.** Il cert HTTPS del Funnel veniva emesso solo alla 1ª richiesta pubblica → timeout. E il polling dell'URL `.ts.net` (60s, prima del reboot) scadeva su VPS fresca. **Fix**: `_warm_ts_cert()` pre-provisiona il cert (`tailscale cert`); finestra di polling estesa a 150s; **l'URL viene ri-derivato e l'HTTPS verificato DOPO il reboot** (stato a regime, netns sano), non solo prima.

Diagnostica del Funnel migliorata (riconosce crash-loop/panic, nodeAttr, cert).

### Fix — Provisioning Tailscale robusta + login admin su HTTP

Dopo un deploy reale: la auth-key non veniva generata (Funnel mai attivo, URL HTTP) e il login admin non procedeva. Diagnosi via API: l'OAuth client falliva la creazione della key con `requested tags [tag:vps1777] are invalid or not permitted` (il client non aveva il tag assegnato), ma l'engine **proseguiva in silenzio** con key vuota → sidecar in standby → HTTP. E su HTTP il cookie admin `Secure` non veniva salvato dal browser → login a vuoto.

- **`step_ts_provision` ora fallisce FORTE e SUBITO** (STEP 3, prima della build): token OAuth e creazione key sono fatali (`DeployError`), con messaggio **azionabile**. Caso-tag riconosciuto esplicitamente: *"l'OAuth client NON è autorizzato al tag tag:vps1777 — assegnaglielo nello scope auth_keys"*. L'ACL resta warning non-fatale (l'attributo può già esserci). Niente più fallback HTTP silenzioso.
- **Cookie admin `Secure` condizionato a `PUBLIC_BASE` https** (`admin.py`): su HTTP (setup locale / onboarding su :8080) il login ora funziona; su HTTPS resta `Secure`. Risolve il "login che non procede senza errore".
- **Checklist UI + INGRESS.md**: reso esplicito il passo critico — nello scope `auth_keys` dell'OAuth client bisogna **selezionare il tag `tag:vps1777`** (la causa reale del fallimento). TROUBLESHOOTING: nuove voci per l'errore-tag e per il login su HTTP.

### Aggiunto — Hardening host + profilo Portainer opzionale

- **Hardening automatico** in `step_prepare`: l'installer ora installa e abilita **`unattended-upgrades`** (patch di sicurezza automatiche) e **`fail2ban`** (anti brute-force SSH). Scelta sicura: **non** tocca `sshd_config` (niente disabilitazione di password/root login), perché il deploy gira via password e si riconnette dopo il reboot — disabilitarli ti chiuderebbe fuori. La disabilitazione password/root è documentata in [OPS.md](docs/OPS.md) come passo manuale post-install (dopo aver caricato una chiave).
- **`compose.ops.portainer.yaml`** (profilo `ops.portainer`): Portainer CE come cruscotto visuale dei container, **mai esposto a internet** — pubblicato solo su `127.0.0.1`, accesso via **tunnel SSH** (`ssh -L 9443:127.0.0.1:9443 ...`). Sta su rete `backend` (internal). Monta il Docker socket (motivo per cui resta locale); il gateway pubblico resta senza socket.
- **`docs/OPS.md`** — nuovo doc che centralizza hardening + profili opzionali (Portainer, Watchtower, backup) e come combinarli. Linkato da README, INSTALL, SECURITY.

### Docs — Sync di coerenza pre-pubblicazione

Audit completo di tutta la documentazione contro il codice attuale. Corretti:

- **Refusi di sicurezza nel README e SECURITY.md** (importante prima del pubblico): UID dichiarato `65532` → in realtà **1000 `app`**; `read_only: true` dichiarato ma **non impostato** nel compose → rimosso, sostituito con i fatti reali (`cap_drop: ALL`, `no-new-privileges`, gateway senza Docker socket). Nome file password `admin_password.txt` → `admin_password_bcrypt.txt`.
- **INGRESS.md**: riscritta la sezione Tailscale — la vecchia "Modalità A" aveva scope errati (`devices:read/write`) e citava un `secrets/ts_oauth.txt` inesistente. Ora descrive il flusso reale: OAuth client con scope `policy_file`+`auth_keys`, tag `tag:vps1777`, i 3 prerequisiti account, e l'automazione ACL+key dell'installer.
- **TROUBLESHOOTING.md**: nuova diagnosi "Funnel non si attiva" coi 3 prerequisiti + comandi e messaggi d'errore reali.
- **SECRETS.md / secrets/README.md / .env.example**: `ts_authkey` non è un Docker secret → vive in `.env` come `TS_AUTHKEY`; rimossi i riferimenti al file inesistente.
- **README / deploy.sh refs**: utente `operator` → `vps1777`; deploy.sh marcato come via CLI per Linux/Mac/WSL (Windows nativo → installer grafico).
- **INSTALL.md**: premesso l'installer grafico come via principale; ONBOARDING/installer README allineati al flusso OAuth.
- Verificato che tutti gli script citati nei doc esistano (`setup.sh`, `deploy.sh`, `tools/rotate-secret.sh`, launcher).

### Aggiunto — Tailscale Funnel automatico via OAuth client

Il deploy Tailscale ora attiva il **Funnel HTTPS in automatico** partendo da un **OAuth client** (invece della sola auth-key, che non bastava: il Funnel richiede prerequisiti a livello di account che la key non porta — nodeAttr `funnel` nell'ACL, HTTPS Certificates, MagicDNS).

- **Form**: la sezione Tailscale chiede **OAuth Client ID + Secret** (la auth-key diretta resta come modalità avanzata, nascosta). Aggiunta una **checklist dei 4 passi una tantum** con link diretti: crea account → abilita MagicDNS + HTTPS in admin/dns → crea OAuth client (scope `policy_file` write + `auth_keys`, tag `tag:vps1777`) → incolla le credenziali.
- **engine**: nuovo `step_ts_provision` che gira **sul PC** (urllib, niente dipendenze): ottiene il token OAuth, **scrive il nodeAttr `funnel` nell'ACL** del tailnet (merge idempotente, preserva il resto), e **genera una auth-key taggata single-use** che finisce in `.env`. **Il client-secret non lascia il PC**: sulla VPS arriva solo la key usa-e-getta.
- **Diagnostica reale**: se il Funnel non parte, l'engine legge i log del sidecar e dice la causa esatta (nodeAttr mancante / HTTPS non abilitato / prerequisiti) con il link per risolvere, invece di un avviso generico.
- I 2 toggle MagicDNS e HTTPS Certificates restano manuali (Tailscale non espone API per quelli — è un consenso umano *by design*). Resta il fallback HTTP:8080 se i prerequisiti mancano.
- ⚠ La logica di merge ACL è verificata offline; le chiamate live all'API Tailscale (token, scrittura ACL, creazione key) vanno validate al primo deploy reale con un OAuth client vero.

### Fix — La password admin viene sempre mostrata alla fine

- La schermata finale mostrava "(già impostata)" al posto della password quando la VPS aveva già `secrets/admin_password_bcrypt.txt` da un deploy precedente: la generazione era dentro un `if [ ! -s ... ]`, quindi su VPS non del tutto vergine la password non veniva rigenerata né emessa (`RESULT_ADMIN_PWD` assente → fallback inutile in UI).
- **Ora la password admin è una credenziale per-installazione: viene (ri)generata sempre fresca a ogni deploy e mostrata sempre.** `gateway_secret`/`oauth_signing` restano stabili (il primo è negli URL connector). La pipeline garantisce coerenza: il bcrypt aggiornato in STEP 3 viene riletto dal gateway dopo il reboot di STEP 7, quindi la password mostrata è quella valida.
- UI: il fallback (raro) ora rimanda alla procedura di reset invece del confuso "(già impostata)".

### Fix — Il deploy sopravvive al refresh/chiusura della pagina

- **Disaccoppiato il deploy dalla connessione HTTP.** Prima `engine.run()` veniva iterato *dentro* la risposta HTTP di `/api/deploy`: aggiornare o chiudere la pagina chiudeva la connessione → `BrokenPipeError` → il generatore si fermava a metà e l'installazione moriva, tornando al form. Era il problema ricorrente del "refresh che riazzera tutto".
- **Ora il deploy gira in un thread lato server** che accumula le righe in un buffer in memoria (`installer.py`). La UI non *esegue* più il deploy: lo *guarda*.
  - `POST /api/deploy` avvia il thread e ritorna subito; un secondo POST mentre gira **non** lo duplica.
  - `GET /api/stream?from=N` fa replay del buffer da `N` e poi segue il live (tail) fino a `__EXIT__`.
  - `GET /api/status` dice se c'è un deploy in corso/finito + secondi trascorsi.
- **`ui.html`**: al caricamento interroga `/api/status` e, se trova un deploy vivo o appena concluso, si **riaggancia** al buffer (replay completo della console + seguito) invece di ripartire dal form. Il timer riprende dal tempo reale. Se la connessione cade a metà, riconnette da sola. Rimosso il guard `beforeunload` (non più necessario: il refresh è sicuro).

### Aggiunto — Deploy production-ready con Tailscale (one-shot)

- L'engine, quando ingress=Tailscale + auth-key nel form, ora porta la VPS a **production al reboot**:
  - attende login Tailscale + Funnel, ricava URL `.ts.net`, imposta `PUBLIC_BASE`
  - **verifica il Funnel** (`tailscale funnel status`); se attivo → `production=True`
  - **STEP finalize**: in production riavvia *senza* `compose.onboarding` → **chiude la porta 8080 in chiaro** (resta solo HTTPS via Funnel)
  - **STEP reboot**: dopo il riavvio verifica che `https://<host>.ts.net/health` risponda
  - se il Funnel non parte (es. non abilitato nell'account Tailscale) → lascia 8080 come fallback + avviso
- Step rinumerati 1/7…7/7. `RESULT_HTTPS_OK` per la UI.


### Aggiunto — Motore Python cross-OS (L2b)

- **`installer/engine.py`** — deploy engine in Python puro via **paramiko**: si connette alla VPS (password o key), carica il repo via **SFTP** (tar in memoria, esclude .git/secrets/venv), ed esegue gli step **direttamente via SSH** — prepara Docker+Compose+utente, genera `.env`/secret (random + bcrypt sulla VPS), `compose up --build`, ricava URL Tailscale, reboot test, raccoglie `RESULT_*`. Niente bash/sshpass sul PC.
- **Cross-OS vero**: l'installer grafico ora gira su **Windows nativo** (senza WSL), Mac e Linux — il PC esegue solo Python, la VPS (Linux) riceve i comandi shell. `installer.py` usa l'engine al posto di `deploy.sh`+sshpass.
- I launcher `launch.sh`/`launch.bat` installano **paramiko** automaticamente se manca (`pip install --user paramiko`). Fallback robusto se paramiko assente (la UI lo segnala).
- `deploy.sh` (bash) resta come opzione CLI per Linux/Mac/WSL.

### Aggiunto — Installer grafico locale (L2)

- **`installer/`** — installer web che gira sul PC dell'utente, esperienza "app": doppio-click su `launch.sh`/`launch.bat` → si apre una UI nel browser (`127.0.0.1:8777`) → form con validazione live + semafori → pulsante **Installa** attivo solo quando tutto è verde → avanzamento live → schermata finale con URL, password admin, connector claude.ai.
  - `installer.py` — mini-server Python stdlib (zero dipendenze). Endpoint: `/api/check` (test SSH live con sshpass), `/api/deploy` (lancia `deploy.sh` in streaming ndjson), `/api/env`. Bind solo 127.0.0.1; le credenziali non lasciano il PC.
  - `ui.html` — single-file, design 1777 (Fraunces + JetBrains mono + corallo). Wizard 4 sezioni (VPS / Admin / Ingress / Bot), semafori per sezione, gating del pulsante, console live colorata, schermata risultati con copy-to-clipboard.
  - `launch.sh` / `launch.bat` — doppio-click cross-OS.
- **`deploy.sh` reso pilotabile**: `NONINTERACTIVE=1` + variabili d'ambiente (`VPS_IP`, `VPS_PASS`, `ADMIN_EMAIL`, `INGRESS_NUM`, `TS_AUTHKEY`, `TG_TOKEN`, `GEN_PWD`...) → l'installer lo guida senza prompt. `ask`/`ask_secret` saltano se la variabile è già valorizzata.
- **Auto-URL Tailscale**: se l'auth-key è fornita al deploy, dopo l'avvio `deploy.sh` ricava l'URL `*.ts.net`, imposta `PUBLIC_BASE` e riavvia il gateway — deploy one-shot con URL HTTPS già attivo.
- **Righe `RESULT_*`** machine-readable in coda al deploy (URL, SECRET, admin email/password, setup URL) — l'installer le parsa per la schermata finale.

### Aggiunto — Onboarding panel (F10)

- **`/admin/setup`** — pannello web di onboarding in timbro 1777 (Fraunces display + JetBrains mono + accent corallo, dark profondo). Mostra lo stato dei componenti a semafori (Tailscale / URL / NotebookLM / Bot) e raccoglie i dati mancanti via form: Tailscale auth-key, token bot + owner id, PUBLIC_BASE opzionale, link all'upload `auth.json`. Salva in `onboarding/pending.json` (bind-mount), senza che il gateway abbia privilegi Docker o accesso ai secret host.
- **`deploy.sh --apply`** — modalità che dal PC legge `pending.json` via SSH e applica: scrive i Docker secret + `.env`, fa `tailscale up`, ricava l'URL `*.ts.net`, imposta `PUBLIC_BASE`, riavvia i servizi **chiudendo la porta 8080** di onboarding, cancella `pending.json`. Separazione netta "raccolta dati (web)" vs "applicazione (deploy.sh con SSH+sudo)".
- **`compose.onboarding.yaml`** — override che espone il gateway su `<IP>:8080` durante il primo setup (risolve il chicken-egg: pannello raggiungibile prima che Tailscale sia attivo). `deploy.sh` lo include all'avvio, `--apply` riavvia senza, chiudendo la porta.
- **CSS admin elevato a timbro 1777**: Fraunces per i titoli, glow sui semafori, gradiente corallo, cura spaziature. Nav tabs: Setup · NotebookLM · Secrets · Audit. `/admin` ora atterra su `/admin/setup`.
- **`docs/ONBOARDING.md`** — flusso completo in 4 passi + spiegazione del perché non è tutto-web (gateway non privilegiato per sicurezza).

### Fix pre-deploy (review statica completa)

Audit statico di tutto il path di deploy prima del primo test reale. 6 problemi trovati e risolti:

- **[BLOCCANTE] Python version mismatch**: builder `python:3.12-slim` → runtime `distroless/python3-debian12` (= Python 3.11). Il venv 3.12 non gira su runtime 3.11 → container crash-loop. **Fix: abbandonato distroless**, tutti e 4 i servizi ora usano `python:3.12-slim` non-root (builder = runtime). Costo ~30MB/img, beneficio: zero mismatch, shell per debug, permessi gestibili. Distroless rivalutabile in hardening futuro.
- **[BLOCCANTE] Healthcheck `/health` sui FastMCP**: archive-mcp e nb1777-mcp espongono solo `/mcp`, nessun `/health` → `urlopen` 404 → container `unhealthy` per sempre → `nb1777-bot` (depends_on service_healthy) non parte mai. **Fix: healthcheck su TCP socket** (`socket.create_connection`).
- **[MEDIO] Permessi volumi**: volumi named root-owned vs processi non-root → scritture fallite (audit log, upload /admin/nlm, auth.json). **Fix: tutti i servizi girano come UID 1000 "app"**, i mountpoint creati con `chown app:app` nel Dockerfile (il volume vuoto eredita i permessi al primo attach). UID condiviso → volume `nlm-auth` accessibile da gateway+nb1777-mcp+bot.
- **[MEDIO] Bot crash-loop**: `TELEGRAM_OWNER_ID=""` → `ValidationError` su int; token vuoto → `sys.exit(1)` → restart-loop infinito. **Fix: validator `IntOrZero`** (""→0) + bot in **standby** (sleep) se token manca, invece di crashare.
- **[MEDIO] Pacchetto MCP incoerente**: `nb1777-mcp` importava l'SDK ufficiale `mcp.server.fastmcp` ma il pyproject dichiarava `fastmcp` (pacchetto diverso) → ModuleNotFoundError. **Fix: uniformato tutto sull'SDK ufficiale `mcp>=1.2.0`** (archive-mcp, nb1777-mcp, example-mcp), `FastMCP(host,port,stateless_http)` nel costruttore + `mcp.run(transport)`.
- **[MEDIO] PUBLIC_BASE vuoto con Tailscale**: l'URL `*.ts.net` si conosce solo post-login → OAuth issuer a loopback → connector claude.ai fallisce. **Fix: documentato** in TROUBLESHOOTING (set PUBLIC_BASE + restart gateway dopo il login Tailscale).
- **compose.ingress.tailscale.yaml**: rimosso `hostname` (conflitto con `network_mode: service:gateway`), gateway resta su rete `ingress` (egress per Tailscale), tolto `--advertise-tags` (richiede OAuth tag).

### Aggiunto

- **`deploy.sh`** — deploy one-click dal PC locale via SSH. Chiede IP/user/password + config (email admin, OWNER_ID, ingress, token), poi: installa Docker+Compose v2, crea utente `operator`, trasferisce il repo (tar over SSH), genera `.env`+secrets (random + bcrypt) in batch, `docker compose up -d --build`, **riavvia la VPS e verifica che i container ripartano al boot**, stampa gli URL finali. Supporta auth password (sshpass) o SSH key. Pulisce known_hosts stale (VPS riformattata).
- `services/nb1777-mcp`: porting completo dei 35 tool MCP dal vecchio stack (`core.py` 653 righe + `server.py` 417 righe) — notebook/source/chat/studio (9 artefatti)/doctor.
- `plugins/example-mcp` + `plugins/example-bot`: scheletri per estendere lo stack con MCP/bot propri.
- `gateway`: endpoint `/app/plugins` (JSON dei servizi attivi per la Mini App tab "I miei plugin").
- Scaffold iniziale del progetto: README, LICENSE (MIT), CONTRIBUTING, CODE_OF_CONDUCT (Covenant 2.1), SECURITY, CHANGELOG
- Struttura cartelle Docker compose: `services/` (4 servizi core) + `plugins/` (estendibile) + `secrets/` + `tools/` + `docs/`
- `compose.yaml` base + override per dev (Watch hot-reload) e ingress modulare (Tailscale | Caddy | Cloudflared)
- `setup.sh` wizard interattivo per setup primo install
- `.github/` workflows scheletro: CI (lint + test + build), release-ghcr, trivy vuln scan

## Storia precedente

Le iterazioni precedenti (snapshot installer bash) vivono nel repo `notebookllm1777` che NON è incluso in questo progetto. Lezioni apprese in quella sessione:

- Bash multi-stage + Python heredoc + sudo + service user + systemd-user = troppe cose intrecciate, esplode in modo non riproducibile
- Cross-user permission gymnastics (operatore vs service) si risolve con container isolation
- Idempotenza fragile con `set -euo pipefail` → si risolve con container immutable
- L'install OAuth flow via browser per nlm auth è il design-win da preservare (`/admin/nlm`)
