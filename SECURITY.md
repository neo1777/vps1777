# Security Policy

> **English overview.** vps1777 is a self-hosted OAuth 2.1 gateway for MCP servers.
> Security posture in brief: only the gateway faces the network (backend on an
> `internal:true` Docker network); non-root containers with `cap_drop: ALL`;
> secrets via Docker `secrets:` on tmpfs, never env vars; releases are
> cosign-signed and verified **fail-closed**, images pinned by digest; age-encrypted
> two-tier backups with the private key off the VPS; pre-update snapshots with
> automatic rollback; per-IP rate limiting and proxy-only `X-Forwarded-For` trust;
> weekly Trivy scans (actionable-only) plus a monthly image-rebuild workflow;
> among the running services, the NotebookLM Google-session volume is mounted only
> by `nb1777-mcp` (the backup job reads it solely to encrypt it).
> **Reporting a vulnerability**: please open a GitHub Security Advisory (private)
> on this repository, or a minimal issue asking for a private channel — do not post
> exploit details publicly. The rest of this document is in Italian (the project's
> native language — see the README's language policy): it is the full defensive
> review of July 2026, the threat model, the third-party data flows and the known
> residuals, and it is kept current release by release.


## Supported Versions

Pre-1.0: solo l'ultima `main` riceve security fix.

## Reporting a Vulnerability

**Non** aprire una issue pubblica.

Mandami un'email a `antigravity1777@gmail.com` (oppure apri una *GitHub Security
Advisory* privata sul repo) con:
- Descrizione della vuln
- Step di riproduzione (PoC se possibile)
- Impatto stimato
- Tuo nome/handle per il credit (se desideri)

Mi impegno a:
- Confermare ricezione entro **48h**
- Valutare e rispondere con un piano entro **7 giorni**
- Patchare e disclosure coordinata: 90 giorni se la severity lo richiede, prima se è semplice

## Security model

vps1777 espone su Internet **solo** il gateway (porta 443 via Tailscale Funnel / Caddy /
Cloudflared) — rimisurabile con `tools/tests/test_porte_con_bind.py` (nessuna porta
pubblicata nuda nei compose) e con `tools/tests/test-onboarding-8080-bind.sh` (la
finestra 8080 dell'onboarding, l'eccezione nota di questa riga).

> ⚠️ **QUATTRO PERCORSI CAMBIANO QUESTA RIGA, e NESSUNO chiede il permesso.** Quando il
> Funnel non risponde, l'installazione scrive `GATEWAY_BIND=0.0.0.0` nel `.env` e il
> gateway finisce in ascolto **su tutte le interfacce, sulla 8080 in HTTP** — non più solo
> sulla 443 via tunnel.
>
> | dove | quando scatta |
> |---|---|
> | [`deploy.sh`](deploy.sh) ramo `TS_FALLBACK` | il Funnel è configurato ma **non risponde da questo PC** — ed è `deploy.sh` stesso a mettere `TS_FALLBACK=1`, non l'operatore |
> | [`installer/engine.py`](installer/engine.py) | il **login Tailscale** non si completa entro 90s |
> | idem | il Funnel risulta attivo sulla VPS ma **non raggiungibile dal PC** |
> | idem | il Funnel **non è confermato** (MagicDNS/HTTPS o `nodeAttr funnel` mancanti) |
>
> ⚠️ **`TS_FALLBACK` non è un interruttore da attivare: è una variabile interna** che lo
> script si imposta da solo. Chi cerca «come si abilita» non trova niente da abilitare —
> il fallback **è già automatico**, e scatta proprio quando il Funnel fallisce, cioè nel
> momento in cui chi installa sta guardando un messaggio d'errore e non un `.env`.
>
> Il *soggetto* della garanzia resta vero (è sempre e solo il gateway); cambiano **la porta
> e il canale**, e passare da HTTPS-via-Funnel a HTTP-in-chiaro sull'indirizzo pubblico è
> precisamente la proprietà che questa riga promette.
>
> Non è un difetto dell'installer: l'alternativa (una VPS irraggiungibile, e dire
> all'utente «entra e sistema» dopo avergli detto che non serviva) è peggiore. **È un
> difetto della frase**, che descrive lo stato normale e tace su quello d'eccezione — e chi
> legge un modello di sicurezza sta leggendo proprio per sapere quando la garanzia non vale.
>
> 🔎 Come si controlla, su una macchina qualsiasi: `grep ^GATEWAY_BIND= ~/vps1777/.env`
> (`0.0.0.0` = il fallback è attivo) e `ss -tlnp | grep :8080`.

> **La porta del pannello di setup: dalla 0.41.0 è sul loopback su tutti e tre i profili.**
> `compose.onboarding.yaml` pubblica il pannello su **`${ONBOARDING_BIND:-127.0.0.1}:8080`**: raggiungibile dalla macchina, non dalla rete. **Con `caddy` e `cloudflared` al pannello si arriva dal dominio HTTPS del proxy**, che è servito dal primo avvio perché la destinazione è configurata prima — `CADDY_DOMAIN` è obbligatorio in `.env` ([`compose.ingress.caddy.yaml:26`](compose.ingress.caddy.yaml), `${CADDY_DOMAIN:?…}`), e per cloudflared il tunnel è pre-creato con l'hostname che punta a `http://gateway:8080` e il token in `secrets/cloudflared_token.txt`. **In ogni caso, e per `tailscale` prima che il tunnel esista, resta la via del tunnel SSH**: `ssh -L 8080:127.0.0.1:8080 <utente>@<vps>`, poi `http://127.0.0.1:8080/admin/setup` dal proprio computer.
>
> | profilo | l'overlay onboarding | la 8080, per default | chi la lega al loopback |
> |---|---|---|---|
> | `tailscale` | **escluso** da `deploy.sh` | **loopback** | `${GATEWAY_BIND:-127.0.0.1}` sul gateway |
> | `caddy` | **incluso** | **loopback** | `${ONBOARDING_BIND:-127.0.0.1}` nell'overlay |
> | `cloudflared` | **incluso** | **loopback** | idem |
>
> **La porta sull'host non serve ai due proxy**: `ingress/Caddyfile` fa `reverse_proxy gateway:8080` **per nome**, e `cloudflared` sta sulla rete `ingress` — entrambi raggiungono il gateway dalla rete Docker. Il chicken-and-egg che l'aveva motivata è di **tailscale**, dove l'authkey si mette dal pannello e quindi prima del pannello non c'è tunnel.
>
> Il ramo è in [`deploy.sh`](deploy.sh) (`if [ "$INGRESS" = "tailscale" ]`): per tailscale l'esposizione la gestisce `GATEWAY_BIND` e l'overlay pubblicherebbe una seconda porta in conflitto; per gli altri due l'overlay resta nel comando di avvio. **Il risultato è lo stesso — loopback — ma per due vie diverse: chi tocca una delle due non ha toccato l'altra.**
>
> **`ONBOARDING_BIND=0.0.0.0` rimette la porta su tutte le interfacce**, ed è un tradeoff dichiarato, non una scorciatoia: il form di primo setup chiede `tailscale_authkey`, `telegram_bot_token`, `telegram_owner_id`, `public_base` ([`onboarding.py`](services/gateway/app/onboarding.py)), e il login admin viaggia in HTTP — con `PUBLIC_BASE` non ancora `https` il cookie di sessione **non è `Secure`** ([`admin.py:105`](services/gateway/app/admin.py)), quindi password e sessione passano in chiaro sulla rete. Serve davvero in un caso: **il certificato ACME che non arriva** (DNS non propagato, porta 80 chiusa), in cui il pannello non è raggiungibile via HTTPS. Chi lo usa richiude rilanciando senza quella variabile.
>
> 🔴 **Questa garanzia vale dalla `0.41.0` in avanti, e non è retroattiva.** Una macchina installata con una versione precedente e **non ancora aggiornata** ha la 8080 su `0.0.0.0` come prima: il default sta nel `compose.onboarding.yaml` che ha sul disco, non in questo documento. Chi vuole sapere se la propria è esposta guarda lì, non qui. *E chi aggiorna deve saperlo prima: se accedeva al pannello via `http://<IP>:8080`, dopo l'aggiornamento non ci arriva più — serve l'HTTPS del proxy o il tunnel SSH (vedi [`CHANGELOG.md`](CHANGELOG.md), 0.41.0).*
>
> 🖐️ *Perché questo blocco è cambiato tre volte in ventiquattro ore (02→03/08): prima diceva che l'eccezione «dura quanto il primo setup» — falso, `deploy.sh` includeva l'overlay in base al **profilo**, non allo stato dell'onboarding; poi è stato corretto in «stato di esercizio» — vero fino alla 0.41.0; ora il default è cambiato e quella riga sarebbe falsa dall'altro verso. **Se tocchi il bind della 8080, questo paragrafo fa parte della modifica.***
>
> 🖐️ *Il pannello resta dietro autenticazione: `setup_view` chiama `_require_admin` come prima istruzione — non c'è una finestra in cui chiunque arrivi possa configurarlo.*

Threat model dichiarato:
- Backend (archive-mcp, nb1777-mcp, bot) su rete Docker `internal: true` — non raggiungibili dall'esterno (nb1777-mcp e bot hanno anche l'uscita `egress`, senza porte pubblicate: possono uscire, non essere raggiunti — [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)); nessun servizio pubblica `ports` in `compose.yaml` (`H48`)
- OAuth 2.1 + DCR + PKCE per tutti i client OAuth (claude.ai, Mini App, future integrazioni)
- JWT con `typ` separati: access_token (15min), refresh_token (30gg), admin (8h), miniapp (1h)
- Path namespacing via `GATEWAY_SECRET`: l'URL contiene un segreto rotabile (se compromesso, rota e cambi URL)
- Bcrypt rounds=12 per password admin (file `secrets/admin_password_bcrypt.txt`)
- Pannello admin: token **CSRF** (synchronizer, verificato centralmente su ogni POST),
  **CSP** con nonce per-risposta, lockout per-IP sul login, `Cache-Control: no-store`
- Mini App: `initData` Telegram **verificata server-side** (HMAC col token bot,
  scadenza 24h) + **owner-only** (`TELEGRAM_OWNER_ID`); API dietro Bearer `typ=miniapp`
  — vedi [docs/MINIAPP.md](docs/MINIAPP.md)
- Container non-root (UID 1000 `app`), `cap_drop: ALL`, `no-new-privileges`
- Il gateway (unico servizio esposto) non ha accesso al Docker socket né al filesystem dell'host (`H44`);
  vede i 5 secret Docker a lui assegnati (`telegram_bot_token` incluso — la radice di fiducia della Mini
  App, vedi [docs/SECRETS.md](docs/SECRETS.md))
- `archive-data` è condiviso: `archive-mcp` lo monta `:ro` (`H46`), il gateway `:rw` — privilegio
  funzionale (`/admin/archive` scrive i `.db` indicizzati), tracciato invece di taciuto
- Hardening host automatico all'install: `unattended-upgrades` + `fail2ban` (`H45`)
- Strumenti di management (Portainer) mai esposti: solo loopback + tunnel SSH (vedi [docs/OPS.md](docs/OPS.md)) (`H47`)

## Rassegna difensiva — l'hardening applicato

Il modello sopra è il design; questa sezione è **cosa è stato reso fail-closed
per costruzione**, dopo una review difensiva a tappeto (luglio 2026) registrata
voce per voce in `security/findings.yml`. Il pattern ricorrente che la review ha
trovato — e chiuso, con l'evidenza di ogni chiusura verificata a ogni PR da
`security/check_findings.py` — è *un default o un residuo che degrada in
silenzio verso l'aperto*: il disegno era già fail-closed, non lo erano
tutti i default. Ogni voce cita la versione in cui è entrata.

### Autenticazione & accesso (i due punti critici)

- **Owner-gating fail-closed** (`v0.22.0`, critico). Con `TELEGRAM_OWNER_ID`
  assente o malformato la Mini App ora **nega tutti** (`/app/auth` → 503), invece
  di lasciar passare chiunque apra il bot. `is_owner` ritorna `False` se l'owner
  non è configurato; il bot applica `owner_only` allo stesso modo; warning
  esplicito all'avvio se manca.
- **Token del proxy legato al proprietario** (`v0.25.0`; rinominata nel vaglio
  del 03/09/2026 — prima questa voce diceva «audience verificata», che
  prometteva più di ciò che il codice fa). Un access token valido non basta: il
  suo `sub` deve essere fra le email ammesse (`OAUTH_ALLOWED_EMAILS`),
  altrimenti il proxy MCP rifiuta. Un token emesso per un altro soggetto non
  raggiunge gli upstream. L'**audience nel senso di RFC 8707** (aud = singolo
  resource server, confrontata a ogni chiamata) invece **non è implementata, di
  proposito**: la scelta e le sue condizioni sono dichiarate in
  [§Postilla](#postilla--lhardening-che-faremo-al-100-più-avanti).
- **Audit della chiamata proxata con `sub` e `client_id`** (`v0.45.0`, dal
  vaglio corso1777). Ogni riga `proxy_request` ora dice CHI (l'utente, `sub`) e
  CON QUALE AGENTE (`client_id`, l'identità DCR del client): da un accesso
  sospetto si risale all'agente, non solo all'utente. Nota di classe del dato:
  un identificativo di persona entra in un log che prima non ne aveva — la
  retention resta quella dell'audit (`AUDIT_RETENTION_DAYS`, default 90 giorni)
  e il log vive nel volume dati, dentro il backup cifrato.
- **Il bearer si ferma al gateway** (`v0.45.0`, dal vaglio corso1777). Prima
  l'header `Authorization` del client attraversava il proxy fino al backend —
  che non lo legge, ma lo riceveva (token passthrough). Ora viene rimosso dopo
  la verifica: un token non viaggia dove non serve.
- **Rate-limit sugli endpoint auth pubblici** (`v0.25.0`). Finestra scorrevole
  per-IP (in-memory, stdlib): `/register` 10/5min, `/token` 60/min, `/app/auth`
  20/5min — sopra al lockout del login admin. Ferma la raffica da singola sorgente.
- **Quick-wins OAuth/admin** (`v0.21.0`): `code_challenge` vuoto → 400 (niente
  PKCE aggirabile); `state` url-encoded; redirect `next` con `//` o `/\` rifiutati
  (no open-redirect); CORS senza wildcard (fail-closed, default `https://claude.ai`,
  non `*`); header `Permissions-Policy` + `Cross-Origin-Opener-Policy`; il login
  fallito logga un booleano `email_known`, non l'email.

### Rete — l'IP client non è più falsificabile

- **`forwarded_allow_ips` ristretto** (`v0.28.0`). uvicorn girava con `"*"`:
  si fidava dell'header `X-Forwarded-For` da **qualunque** peer, quindi l'IP
  client era spoofabile → rate-limit e lockout evadibili, audit avvelenabile.
  Ora `GATEWAY_FORWARDED_ALLOW_IPS` (default `127.0.0.1,10.0.0.0/8,172.16.0.0/12,
  192.168.0.0/16`) si fida dell'XFF **solo** dai range privati + loopback, **mai**
  da un IP pubblico. Il reverse-proxy (tailscale sull'host, caddy/cloudflared in
  container) arriva sempre da una bridge Docker privata; un client pubblico
  diretto non è fidato e il suo XFF viene ignorato. Verificato sul campo: un
  `X-Forwarded-For` iniettato dal client viene scartato, resta il vero IP.

### Segreti — mai in chiaro dove non serve

- **`GATEWAY_SECRET` redatto dai log** (`v0.24.0`). Il secret vive nel path del
  proxy MCP (`/<SECRET>/<service>/mcp`) e finiva negli access-log di uvicorn. Un
  filtro di logging lo maschera (`/***/…/mcp`) prima che qualunque riga sia
  scritta.
- **Segreti fuori dall'argv nel deploy** (`v0.29.0`). `deploy.sh` passava i
  segreti (tailscale authkey, bot token, password) nell'argv di comandi remoti,
  visibili via `ps`. Ora lo script viaggia nello STDIN di `bash -s`; `set_kv`
  scrive con builtin (niente valore all'argv di `sed`); bcrypt legge da stdin;
  `tailscale up` usa `--authkey=file:`.
- **Chiave age fuori dalla VPS** (`v0.26.0`). Il backup si cifra con la sola
  chiave **pubblica** (recipient, da `tools/age-recipients.txt` — `tools/backup.sh`
  non nomina mai una chiave privata); la privata vive sul PC dell'owner e serve solo
  al restore. `backup.sh` non genera più la coppia sulla VPS (che avrebbe messo
  la privata sullo stesso disco dei backup). Vedi [docs/BACKUP-RESTORE.md](docs/BACKUP-RESTORE.md).
- **Secrets sempre file-mounted** (baseline, `H68`): password, signing key, token via
  Docker `secrets:` in `tmpfs /run/secrets/`, **mai** in env var — un env var lo mostra
  `docker inspect` e lo ereditano tutti i processi figli. Vedi [docs/SECRETS.md](docs/SECRETS.md).
  ⚠️ **Quanto ne è PRESIDIATO, perché la promessa è più larga della copertura:**
  `tools/tests/test_secrets_file_mounted.py` aggancia la variabile al segreto **per
  nome** (`GATEWAY_SECRET_FILE` ↔ `gateway_secret`), quindi verifica «mai in env var
  **col nome che lo rende riconoscibile**». Un segreto passato sotto un nome scollegato
  (`BOT_TOKEN` per `telegram_bot_token`) **esce verde**: misurato col gruppo di
  controllo il 10/08, stesso valore e stessa posizione, cambia solo il nome.
  Non è curato di proposito — riconoscere per FORMA del nome (`*TOKEN*`, `*SECRET*`)
  griderebbe su `OAUTH_ACCESS_TOKEN_LIFETIME: "900"`, che è una durata, *e un guardiano
  che grida viene spento*. Il legame nome↔segreto regge per **convenzione**, e la
  convenzione non è presidiata: chi aggiunge un segreto tenga il nome della variabile
  uguale a quello del secret. Residuo completo in `security/findings.yml`, voce `H68`.
- **Il repo è pubblico, e un gate lo tratta come tale** (`security/check_no_leaks.py`,
  in CI a ogni PR). Fa fallire la build se entra un **export di sessione** (il `.txt`
  di `/export`: nome innocuo, dentro il detto-e-fatto di una sessione di lavoro) o del
  materiale credenziale vero — distinguendolo dai segnaposto della doc, perché un gate
  che grida al lupo viene disattivato e allora non protegge più niente. Riporta *dove*,
  mai *cosa* — la promessa è scritta in testa a `security/check_no_leaks.py`,
  dove chi lo modifica se la ritrova davanti: i log della CI di un repo
  pubblico sono pubblici. Il `.gitignore` da solo
  non basta — non ferma `git add -f` e non fa nulla per un file già tracciato. Regola
  che il gate ricorda a chi lo incontra: **un segreto passato non si toglie, si ruota.**

### Contenimento dei container

- **Il gateway non tocca i cookie Google** (`v0.30.0`). Era l'ultimo finding
  aperto. Il gateway — l'unico servizio esposto su Internet — montava in
  **scrittura** il volume `nlm-auth` (i cookie di sessione Google di NotebookLM),
  perché `/admin/nlm` ci estraeva dentro il profilo caricato: compromettere il
  gateway voleva dire leggerli **e** riscriverli. Ora, **fra i servizi in
  esercizio, quel volume lo monta solo `nb1777-mcp`** (in lettura-scrittura): è
  il servizio che quei cookie li usa davvero, e non è esposto. Ma «solo lui» vale
  per i servizi, non per il sistema: due lavori **a tempo** lo montano in **sola
  lettura**, e vanno contati nel modello di minaccia —
  - il **backup** (container `backup` con la feature omonima, attiva per
    impostazione predefinita, oppure `tools/backup.sh` sull'host): dumpa il
    volume dentro l'archivio cifrato con la sola chiave pubblica `age`. È anche
    il motivo per cui `nlm-auth` è **escluso dallo snapshot pre-update**, che
    invece è in chiaro: nel backup la protezione dei cookie non è l'assenza, è la
    cifratura — chi ha la chiave privata `age` e accesso agli archivi li vede;
  - il **check settimanale delle scadenze** (`vps1777 secrets-status`, unit
    `vps1777-secrets-check`): monta il volume in un `busybox` con `--network
    none` e ne legge **solo l'mtime** del file dei cookie, mai il contenuto.

  Gateway e bot hanno **accesso zero** — né lettura né scrittura — e gli
  chiedono su rete interna (`/internal/nlm/status` dice solo *se* c'è un profilo,
  mai il contenuto; `/internal/nlm/profile` riceve il tar e lo installa),
  autenticandosi con un segreto condiviso e fail-closed.
  - **Il proxy non attraversa `internal/`**: il reverse proxy MCP è un catch-all,
    quindi senza un blocco esplicito quegli endpoint sarebbero stati raggiungibili
    da Internet via `/<SECRET>/<service>/internal/…` — proprio la via di scrittura
    che il fix chiude. Ogni sotto-path `internal/` è rifiutato con 404 **prima di
    ogni altro controllo**, per **tutti** gli upstream: un prefisso riservato di
    cui i plugin possono fidarsi.
  - **Upload non distruttivo**: staging → validazione → swap con rollback. Un tar
    sbagliato non ti scollega da NotebookLM.
- **`docker.sock` rimosso dal container di backup** (`v0.29.0`). Montare il
  socket dà al container il controllo root-equivalente dell'host. Il container
  `ops.backup` ora monta i volumi dati **direttamente in sola lettura** e li tara
  da lì — niente `docker.sock`, niente `docker-cli`.
- Container **non-root** (UID 1000), `cap_drop: ALL`, `no-new-privileges`,
  backend su rete `internal: true`, gateway senza accesso al socket Docker né al
  filesystem dell'host (baseline). I 5 secret Docker assegnati al gateway, però,
  lui li **vede** — `telegram_bot_token` incluso, la radice di fiducia della
  Mini App: la superficie reale di un gateway compromesso è quella (`docs/SECRETS.md`).

### Supply-chain & aggiornamenti

- **Scansione vulnerabilità delle immagini** (`v0.44.2`): Trivy ogni lunedì
  sulle 5 immagini **pubblicate** (ciò che gli utenti eseguono, non un build
  ad-hoc), con `--ignore-unfixed`: in pagina Security va **solo ciò su cui si
  può agire** — le CVE con una versione corretta pubblicata. Le CVE senza fix
  (il rumore di fondo di ogni immagine Debian: al 01/09/2026 erano ~1.400
  alert, critical comprese, tutte non azionabili) non fanno pagina: si
  assorbono quando Debian pubblica il fix, alla ricostruzione successiva.
  E la ricostruzione non dipende dal ritmo delle release: **il 3 di ogni mese**
  `rebuild-mensile.yml` riconta le CVE con fix e, se ce ne sono, tagga la patch
  successiva → release firmata con immagini fresche → il check della VPS avvisa
  l'owner (il deploy resta suo). Senza il secret `RELEASE_PAT` il workflow non
  tagga: apre una issue con l'elenco — fallback dichiarato, mai silenzioso.
- **Firma cosign obbligatoria di default** (`v0.23.0`, critico). Il self-update
  verifica la firma keyless del bundle di release **fail-closed**: se la verifica
  non passa (o `cosign` manca e non si installa), l'update si ferma. La via
  d'emergenza è esplicita e rumorosa: `VPS1777_REQUIRE_COSIGN=0` /
  `--no-require-cosign`. (Prima la verifica era opt-in e saltata in silenzio.)
- **GitHub Actions pinnate a SHA** (`v0.27.0`). Ogni action è pinnata al commit
  SHA (non al tag mobile): un tag ripuntato a monte non può iniettare codice (`H65`).
  `Dependabot` (github-actions + docker + docker-compose) tiene freschi gli SHA/i
  digest. Permessi `least-privilege` per-job in `release.yml`. Le immagini di
  terzi nei compose sono digest-pinnate (`H66`).
- **Digest immutabili** (baseline): le immagini si pullano da GHCR e si verificano
  contro `images.lock` del bundle; nessun build-in-place.

### Privacy & osservabilità

- **Retention dell'audit** (`v0.24.0`): `AUDIT_RETENTION_DAYS` (default 90) con
  pruning opportunistico — l'audit non cresce all'infinito.
- **Comandi RAG del bot disattivabili** (`v0.24.0`): `BOT_RAG_COMMANDS=0` spegne
  `/lista`·`/chiedi` (che passerebbero da Telegram). Con la sola Mini App i
  notebook non transitano da terzi — vedi la tabella *Flussi di dati verso terzi*.

### Canale di aggiornamento

L'aggiornamento (`vps1777 update` / pulsante admin) è progettato attorno allo
stesso invariante: **il gateway non esegue nulla di privilegiato**.

- **Collect→apply disaccoppiato**: il pulsante admin scrive solo un *intent file*
  in `onboarding/` (bind-mount); l'update vero lo esegue la CLI host via systemd
  path unit. Il gateway non tocca mai Docker (`H67`) — né montandone il socket, né
  parlandogli via `DOCKER_HOST`, né con una SDK nel proprio codice.
- **Intent validato e consumato**: schema, SemVer, TTL 10 min, nonce anti-replay,
  e cancellazione **prima** di agire (nessun loop di ri-trigger) — i controlli
  FERMANO invece di spegnersi quando il dato manca, provato in
  `tools/tests/test_intent_fail_closed.py`.
- **Anti-downgrade**: dal pulsante il target non può essere una versione più
  vecchia di quella in esecuzione (version-floor SemVer, provato nei due versi
  da `tools/tests/test_version_floor_non_confrontabile.py` che cita questa
  riga) — così un gateway compromesso non può forzare un downgrade a una
  release con vuln nota. Il
  downgrade intenzionale resta possibile solo da terminale, con
  `vps1777 update --version` esplicito (chi ha la shell ha già ogni privilegio). **E se la versione in esecuzione non è confrontabile**
  (`VPS1777_TAG` vuoto o non SemVer) **il pulsante viene rifiutato**: una
  versione illeggibile non è «più vecchia» né «più nuova», e una guardia che
  promette *non può* deve negare quando non sa.
- **Supply-chain**: le immagini si pullano da GHCR e si verificano contro
  `images.lock` (digest immutabili) del runtime bundle di release; il bundle è
  firmato (`cosign sign-blob` keyless) e la verifica è **obbligatoria di default**
  (`VPS1777_REQUIRE_COSIGN=0` la disattiva solo come via d'emergenza esplicita).
  Nessun aggiornamento build-in-place — nessun compose di esercizio porta una
  chiave `build:`, e `tools/tests/test_nessun_build_in_place.py` lo verifica
  su tutti i compose del repo, eccezioni dichiarate una per una.
- **Reversibilità**: backup age + snapshot locale prima di ogni update;
  auto-rollback se lo stack non torna healthy. Nessuna finestra in cui i dati
  restano senza rete di sicurezza — misurata dal vivo da
  `tools/prove-empiriche/prova-9-il-fail-closed-torna-indietro-davvero.sh`,
  che sabota il health-check di un update reale e verifica che il rollback
  riporti la versione di partenza (prima esecuzione verde al collaudo del
  27/08/2026, sul salto reale 0.43.1→0.43.2).
- **Zero telemetria di vps1777**: vps1777 non ti traccia; il check versione è una
  GET non autenticata a GitHub. Ma **per funzionare, alcuni dati escono verso
  servizi terzi** — vedi la sezione seguente: non è telemetria, è il servizio che
  usi, e va saputo.

Dettaglio completo: [docs/UPDATE.md](docs/UPDATE.md) e [docs/SELF_UPDATE_PLAN.md](docs/SELF_UPDATE_PLAN.md).

## Flussi di dati verso terzi

vps1777 non è un'isola: per erogare le sue funzioni fa transitare dati verso due
servizi esterni. Nessuno è telemetria, ma è bene sapere **cosa esce verso chi** —
e il confine che lo applica è la rete `egress` di `compose.yaml`: chi non ci sta
sopra non esce affatto.

| Quando | Cosa esce | Verso | Note |
|---|---|---|---|
| Domanda RAG, aggiunta fonte, OCR (nb1777) | domande, contenuto delle fonti, documenti | **Google (NotebookLM)** | l'OCR manda il documento intero; è il funzionamento di NotebookLM |
| Comandi **testuali** del bot (`/lista`, `/chiedi`) | titoli notebook, risposte RAG | **Telegram** | la Bot API **non è E2E**; disattivabili con `BOT_RAG_COMMANDS=0` |
| Mini App (`/app/*`) | — | **nessun terzo** | parla solo col tuo gateway: è la superficie più privata |
| Notifiche update (opzionali) | "v… disponibile" | **Telegram** | solo se `--notify` |
| Check versione | — | GitHub | GET pubblica, nessun dato personale |

**Massima privacy**: imposta `BOT_RAG_COMMANDS=0` e usa la Mini App per i notebook
(non fa passare nulla da Telegram); l'archivio (`archive1777`) e il gateway restano
interamente sulla VPS.

## Residui noti — cosa NON è ancora chiuso

> **Questo conteggio è verificato dalla CI.** I 64 rilievi vivono in
> [`security/findings.yml`](security/findings.yml): ognuno con il suo stato e, se
> chiuso, con l'**evidenza puntuale** nel codice.
> [`security/check_findings.py`](security/check_findings.py) gira a ogni PR e
> **fallisce** se l'evidenza di una voce chiusa è sparita, se un residuo non
> dichiara cosa manca, o se i numeri qui sotto non combaciano col registro.
>
> Esiste perché questa sezione, una volta, ha dichiarato «nessun rilievo è rimasto
> aperto» quando i chiusi erano 8 su 43. Un claim senza coordinata è
> infalsificabile: marcisce in silenzio. Ora non può più.

Il registro conta **70 voci** (2 critiche, 10 alte, 39 medie, 19 basse): 43 dalla
campagna originaria (`v0.19.1 → v0.33.0`, affrontate tutte), 7 (`H44`-`H50`) dal
ciclo di audit con misure sul sistema vivo culminato nella `v0.40.3`, 4 che non
vengono da una review ma da quello che è successo dopo (`H51` da un guasto in
produzione, `H52` e `H54` da un'analisi esterna, `H53` dall'aver misurato la
copertura dei controlli invece di leggerla) — 10 (`H55`-`H64`) dal loop di audit
in corso, che è la fonte più produttiva delle quattro, e 4 (`H65`-`H68`) da una
quinta fonte aperta il 10/08: **rileggere le garanzie scritte in prosa in questi
documenti e chiedersi chi le tiene**. Le prime due erano vere e senza alcun presidio;
la terza era vera, presidiata, e il presidio non copriva tutte le forme
dell'oggetto — che è l'esito meno visibile dei tre, perché somiglia a un verde.
Una (`H69`) viene dal collaudo su macchina vergine del 27/08: il primo azzeramento
vero ha esercitato per la prima volta un ramo (la consent OAuth col bottone) che
stava in produzione da settimane senza che nessun client lo attraversasse.
Nessuna è aperta. Il conteggio, verificato contro il codice dal gate in CI:

| | |
|---|---|
| **chiusi** | 59 |
| **parziali** | 9 |
| **accettati** | 2 |
| **aperti** | 0 |

I due **critici** — owner-gating fail-closed (`H1`) e verifica cosign obbligatoria
(`H2`) — sono chiusi e verificati in produzione, come tutta la fascia alta.

L'unico **accettato**: niente 2FA sul pannello admin (`H28`) — è un gateway
mono-utente dietro Tailscale Funnel, con password bcrypt-12 + lockout per-IP + CSRF
+ revoca reale della sessione; il 2FA aggiungerebbe attrito per un guadagno marginale
su questo profilo. È una decisione, non una dimenticanza.

L'ottavo **parziale** è `H50`, il primo trovato da una misura invece che da una
lettura: il gateway — il servizio esposto, quello che monta i secret — aveva
un'uscita verso qualunque host su Internet. Ora è **chiusa in produzione**, e non
per un commit: l'aggiornamento automatico ha installato il fix di `H50` da sé e
`tools/prove-empiriche/prova-1-gateway-non-esce.sh` è passata da FAIL a PASS
senza che nessuno toccasse la macchina, con la
controprova che dallo stesso momento un altro container esce regolarmente (senza
quella, un timeout non distingue un blocco mirato da una rete guasta). Resta
parziale perché negli altri due profili d'ingresso (caddy, cloudflared) il gateway
riprende la rete condivisa col proxy, e lì l'uscita è ancora aperta.

Il nono è `H51`, e non viene da un audit: viene da un **guasto vero**. Quel fix di
`H50`, applicato, ha reso il servizio irraggiungibile da Internet per un'ora e
ventotto minuti — misurati fra i due istanti, non stimati fra due orari comodi —
il gateway era rimasto solo su una rete interna, e **da una rete interna
una porta non si può pubblicare**: Docker accetta l'istruzione e non la esegue,
senza dirlo. La parte che conta non è l'errore, è che **tre controlli indipendenti
hanno dato verde mentre il servizio era giù**: il controllo di salute del container
(che interroga sé stesso dall'interno, dove la porta risponde sempre), il comando
che mostra la configurazione (che dice cosa è *dichiarato*, non cosa Docker riesce
ad applicare) e il cancello dell'aggiornamento automatico — che per questo **non ha
fatto marcia indietro**. Se ne è accorta una persona, aprendo l'indirizzo. Ora esiste
una prova che guarda la porta **da fuori** del container, ed è stata verificata sui
due esiti: verde sul servizio sano, rossa su uno rotto apposta. **Il cancello
dell'aggiornamento ora la esegue** — è `prova-7-porta-pubblicata-davvero.sh`, e lo
stesso guasto di `H51` farebbe tornare indietro l'aggiornamento da sé — e da oggi la
stessa domanda viene fatta anche **una volta al
giorno**, quando non si sta aggiornando niente: se il servizio smette di rispondere
arriva un avviso, e quando torna su arriva la **durata misurata fra i due istanti**,
che è precisamente il numero che quel giorno nessuno aveva. E il controllo giornaliero non si ferma
alla porta sulla macchina: **esce su Internet e rientra dall'indirizzo pubblico**,
perché con la porta viva e il tunnel caduto, per chi apre l'indirizzo il servizio è
giù e un controllo interno direbbe che va tutto bene. *Quella sonda del tunnel
(`H51`) l'avevo data per
impossibile — pensavo che dalla macchina la richiesta girasse su sé stessa: misurata,
esce davvero, e la stessa richiesta fatta all'indirizzo interno non risponde. Un
limite dedotto invece che misurato è la stessa classe di errore che questo rilievo
racconta.* Il controllo del tunnel **non** entra nel cancello dell'aggiornamento, ed è
una scelta: quel cancello giudica ciò che l'aggiornamento può rompere, e un
singhiozzo del tunnel farebbe tornare indietro una versione sana — nel controllo
giornaliero, invece, un falso allarme costa un avviso e non un ripristino. Dal
`v0.43.4` il bundle di rilascio porta con sé `tools/prove-empiriche/`, quindi sulla
macchina le prove vanno solo lanciate, non più copiate a mano — e il primo collaudo
completo sul sistema in esercizio (27/08/2026) le ha viste 8 verdi su 8 eseguibili.

Il decimo è `H52`, e non l'abbiamo trovato noi: l'ha nominato l'analisi esterna del
round-7. Le garanzie di irrobustimento dei servizi di sistema erano certificate
**leggendo una stringa nel file di configurazione**, non chiedendo al sistema che
cosa applica davvero: un file può dichiarare una protezione che il sistema ignora, e
il controllo restava verde lo stesso. Ora una prova interroga il sistema
(`systemctl show`) e confronta la risposta con ciò che il file dichiara, con la
controprova dentro — cerca anche una protezione *non* dichiarata e pretende che il
sistema dica di no, altrimenti la prova starebbe misurando se stessa. Resta parziale
perché copre i servizi di sistema e non ancora i file dei container né il Python.

L'undicesimo è `H53`, e riguarda i controlli stessi. Il passo che analizza gli script
di shell girava con un `|| true` in coda: qualunque cosa trovasse, il risultato veniva
buttato via e il passo restava verde. **Un controllo che per costruzione non può
fallire non è un controllo, è una riga di log.** Tolto quel pezzo, il risultato è
uscito subito: sette segnalazioni, e una era un **difetto vero nella conservazione dei
backup** — un file col nome fuori formato non veniva scartato come previsto e si
prendeva uno dei quattro posti riservati ai backup settimanali, buttandone fuori uno
buono. Presente da quando lo script esiste, visibile allo strumento dal primo giorno,
invisibile a chi guardava la build. Corretto, e ora quel passo può diventare rosso
davvero — verificato rimettendo il difetto apposta. Nella stessa misura è emerso che
il controllo di stile del Python guardava due percorsi su quattro: esteso, e fuori non
c'era nulla di rotto — che è il motivo per cui la lacuna poteva durare. Resta parziale
perché la ricerca di altri controlli nella stessa condizione non è esaustiva.

Il dodicesimo è `H54`, e ci è arrivato per una strada storta che vale la pena dire:
l'analisi esterna ha osservato che il gateway monta **cinque credenziali in chiaro**,
compreso il token del bot Telegram. Il registro copriva il terreno di `H54` solo di
sponda — c'era una voce **chiusa**, ma chiudeva una lacuna *nella documentazione*,
non il rischio. Chi scorreva l'elenco cercando cosa resta scoperto non trovava nulla.
Misurato, però, il numero giusto è **uno, non cinque**: quattro di quelle credenziali
sono del gateway stesso — firma le proprie sessioni, verifica la password — e chi
prende il gateway le ha già per definizione. Il token del bot no: quello non gli serve
per *essere sé stesso*, gli serve per **parlare come il bot**, e chi lo prende può
impersonarlo anche fuori da qui. *«Cinque» risponde a «cosa vede»; «uno» risponde a
«cosa si guadagna a prenderlo»*. Resta parziale perché la difesa possibile — un
processo separato che tenga il token e accetti solo «manda questo messaggio» — **non
copre tutto il segreto: lo stesso token ha DUE usi, e vanno separati prima di ragionare
sulla difesa — perché uno dei due si toglie di mezzo SENZA aggiungere niente.**
`nb1777-bot` lo usa per **parlare** come il bot (è il rischio descritto qui sopra); il
`gateway` lo usa come **chiave di verifica** — `services/gateway/app/miniapp_core.py:43`
fa `hmac.new(b"WebAppData", bot_token, sha256)`, l'algoritmo con cui Telegram valida
l'`initData` della Mini App. **Ma per verificare NON serve il token: basta la chiave
DERIVATA, e il gateway la accetta già** — `settings.py:227` (`effective_webapp_secret`),
`settings.py:238` (*«serve UNA delle due, non entrambe»*), `miniapp.py:162`
(`verify_init_data(…, webapp_secret_hex=…)`). È l'esito di **H54, 27/07**, e la
derivazione è **a senso unico**: chi ha quella chiave può verificare *e forgiare* una
`initData` per questa Mini App, ma **non può risalire al token, quindi non guadagna la
voce del bot** — che è il surplus di cui parla tutto questo paragrafo.
⇒ Le opzioni sono **tre**, e lo decide chi possiede la macchina, non un rilievo:
**(a)** delegare al processo separato *anche* la verifica; **(b)** accettare che il
gateway tenga il token e limitare la difesa all'invio; **(c)** — la più economica, e
**già scritta e collaudata in questo repo** — montare `telegram_webapp_secret` sul
gateway *al posto di* `telegram_bot_token`: non costa né un container né un canale.

> ⚠️ **PERCHÉ QUESTO PARAGRAFO È STATO RISCRITTO — 16/08/2026, issue #61.**
> Prima diceva che la difesa «costa un pezzo in più da mantenere su una **macchina
> piccola**». *Era vero quando fu scritto.* Misurato oggi sul `compose.yaml` di `main`:
> **4 servizi** (`gateway`, `archive-mcp`, `nb1777-mcp`, `nb1777-bot`), 3 reti, 5 secret
> — e `nb1777-bot`, cioè **il processo separato, esiste già**. Un processo in più non è
> più l'eccezione: è la modalità normale del sistema. *(E infatti: dal 28/08,
> v0.43.10, i servizi sono **5** — si è aggiunto `ocr`, il tesseract in una
> stanza sua proprio per questo principio.)*
> 🔑 **La decisione non era sbagliata: era la sua motivazione a essere invecchiata** — e
> una motivazione scaduta non lo dichiara, perché sta nel corpo della decisione e non in
> un campo che qualcuno rivede. *Chi rileggeva la decisione di `H54` la valutava su una
> premessa morta senza avere modo di accorgersene.*
> ⇒ **Ogni premessa che descrive la FORMA del sistema** — «è piccolo», «è uno solo»,
> «non c'è ancora X» — **va riletta quando il sistema cresce: a scadere è la premessa,
> non la scelta.** Se un giorno i servizi tornassero a essere uno, questo paragrafo
> andrebbe riscritto di nuovo: è la sua natura, non un difetto.
>
> 🪞 **E la prova più forte della regola è arrivata da questo stesso paragrafo, in
> revisione: la premessa NUOVA era a sua volta scaduta.** La prima stesura diceva *«per
> verificare serve il token stesso»* e ne deduceva **due** opzioni. Falso da venti
> giorni: H54 (27/07) ha introdotto la chiave derivata, il gateway la accetta già, e
> l'opzione **(c)** — la più economica delle tre — era **scritta e collaudata in questo
> repo mentre io scrivevo che non esisteva**. *(rilievo della revisione non-autrice
> in issue `#61`; verificato alla fonte prima di accoglierlo.)*
> 🔑 **Chi corregge una premessa scaduta la sostituisce con quella che ha in testa — ed è
> vecchia quanto la sua ultima lettura del codice.** Non c'è una versione definitiva di
> un paragrafo che descrive il sistema: c'è solo la sua data. ⇒ **il presidio non è
> scrivere meglio, è farlo leggere a una mano che non l'ha scritto** — qui è costato una
> revisione e ha trovato l'opzione migliore delle tre.

`H55` **è stato chiuso il 01/08/2026**, e la sua storia vale più del conteggio: non
l'ha trovato una lettura, è saltato fuori **aggiornando
davvero la macchina**. Il comando che questa documentazione consiglia moriva a metà
strada con un errore di programma, perché non riusciva a scrivere il file che i
pannelli leggono per **disegnare la barra di avanzamento**. Il motivo è
un'asimmetria: l'aggiornamento automatico gira con privilegi diversi da quelli di chi
lancia il comando a mano, e lascia dietro un file (`update_progress.json`, quello dei
pannelli) che l'altro non può più riscrivere.
**Il punto di `H55` non è il permesso: è che una riparazione è stata abortita da un
file che serve solo a raccontarla.** Rifiutarsi di installare qualcosa la cui firma
non torna è giusto; rifiutarsi di riparare perché non si riesce a scriverne il
resoconto non lo è.
Ora avvisa e prosegue — una volta sola, non a ogni passo — e quando può rimette il
file nella disponibilità di chi userà il comando dopo. Il pezzo che riallinea i permessi resta verificato
leggendolo e non dai test (servirebbero altri privilegi) — ma **la causa a monte è
caduta**, ed è la parte che teneva aperta la voce.

Per mesi il registro ha attribuito quell'asimmetria a «la unit gira come root perché le
servono docker e l'installazione del binario». **Era falso, e nessuno l'aveva verificato**:
nel repository nessuna unit dice `User=root` — tutte portano un segnaposto. La causa vera
è che il codice **deduceva l'operatore da chi lanciava l'installer** invece di dichiararlo:
un'installazione fatta da amministratore produceva unit amministrative, in silenzio. Lo
stesso difetto viveva in due dei tre installer, scritto in due linguaggi diversi, mentre
il terzo fissava già il nome giusto da sempre.
Ora entrambi **si rifiutano** di rendere le unit come amministratore, e dicono come uscirne.
Sulla macchina in produzione le quattro unit sono state riportate all'operatore e una di
esse **è stata eseguita davvero**, uscendo con successo e senza fermare nessun servizio —
perché «il file dice la cosa giusta» non è «il servizio funziona».

Il quattordicesimo è `H56`, ed è **la seconda metà di un rilievo che risultava
chiuso**. Prima di ogni aggiornamento la macchina prende una copia di sicurezza locale
per poter tornare indietro; una voce chiusa raccontava che da quella copia erano stati
esclusi i cookie di Google. Vero — ma era **un archivio su due**, e quello che resta è
dodicimila volte più grande: circa 2,58 GB di archivio **in chiaro**, mentre gli stessi
dati, per l'altra strada, viaggiano cifrati. *Il difetto di `H56` non è il chiaro:
quella copia serve al ripristino automatico, che gira sulla macchina e non può
dipendere da una chiave che sta altrove — cifrarla la renderebbe illeggibile proprio
a chi deve usarla.*
**Il difetto è che chi leggeva il registro concludeva che il problema fosse chiuso.**
Ora è scritto, col residuo dichiarato: cresce di una copia a ogni aggiornamento e
ciascuna resta 72 ore, e l'unica cura che non rompe il ripristino è cifrare il disco —
che si fa sul disco e non nel codice, quindi è una decisione di chi possiede la
macchina. È la **seconda** volta che troviamo questa forma — una voce chiusa
il cui titolo nomina un elemento invece della categoria — ed è il motivo per cui vale
la pena rileggere le altre. *(La prima stesura di questa riga diceva «la terza», e ci
metteva dentro un caso che ha una forma diversa: là lo stato era vero di un altro
oggetto, non di un sottoinsieme. Si somigliano nell'effetto sul lettore e si curano in
modi opposti — contarli insieme faceva un pattern più grosso e un rimedio più confuso.)*

Il quindicesimo è `H58`, e nasce dalla stessa domanda di `H57` — *quanti giorni
indietro si può davvero tornare?* — che invece è **chiuso e verificato sulla macchina**.
Li racconto insieme perché sono lo stesso pomeriggio.

`H57` — la macchina tiene **sette copie**, e la riga che le governa promette «sette
giorni». Sono due cose diverse, e coincidono soltanto finché arriva una copia per notte.
Il 27 luglio la macchina è stata aggiornata quattro volte in una mattina perché qualcosa
si era rotto, e **ogni aggiornamento fa la sua copia**: quattro dei sette posti sono
finiti alla stessa mattina, e le notti dal 20 al 24 sono state cancellate. Sul disco
c'erano sette copie — il conteggio tornava — ma coprivano **tre giorni invece di sette**,
e nulla lo segnalava. *Il secondo livello, quello che tiene una copia a settimana, non
poteva rimediare: dal 20 al 26 luglio è tutta la stessa settimana.* ⭐ La cosa da
ricordare è la forma: **la finestra di ripristino si accorcia proprio nel giorno in cui
qualcosa si rompe** — l'evento che consuma i posti è lo stesso che rende quelle copie
necessarie. Ora se ne tiene **una per giorno**, la più recente, per sette giorni distinti:
stessi sette posti sul disco, stessi 18 GB, ma sette giorni di storia. *Tenerne di più
non era la strada: le copie sono già il 69% del disco occupato di quella macchina.*

`H58` — due difetti trovati misurando **quanto pesa una copia** (2,58 GB). Il primo: se
la scrittura si interrompe a metà — disco pieno, processo ucciso — resta sul disco un
file **col nome giusto e il contenuto a metà**, e la ritenzione lo conta come la copia di
quel giorno. Una copia rotta che occupa il posto di una buona è peggio di una copia
mancante, perché il conteggio non le distingue. Ora il file incompleto viene rimosso se
la scrittura non arriva in fondo, *col residuo dichiarato: contro uno spegnimento brutale
servirebbe scrivere su un nome provvisorio e rinominare alla fine, e non è stato fatto in
questo giro.* Il secondo: prima di aggiornare, la macchina controllava di avere **5 GB
liberi** — ma le due copie che quell'aggiornamento scrive ne occupano circa 5. ⭐ Il
difetto non è che 5 fosse poco: è che era **un numero fisso messo a guardia di dati che
crescono**. Il giorno in cui una copia peserà il doppio, quella soglia direbbe di sì a
un'operazione che non ci sta — e sembrerebbe verde fino a quel giorno. Ora la soglia **si
calcola dalla copia più grande che c'è** e cresce da sola.

🔴 **E l'installazione della cura ha mostrato il difetto un'ultima volta**, che è il
dato più onesto di questa pagina: ogni aggiornamento fa la sua copia *prima* di
sostituire i file, quindi quella copia è stata fatta e potata dal codice **vecchio** —
ha preso un posto e ha cancellato il 25 luglio. Prima dell'aggiornamento tre giorni,
subito dopo due. *Era inevitabile, ma andava previsto e scritto, non scoperto guardando
l'elenco dopo.* ⚠️ **E i giorni già cancellati non tornano**: dal 20 al 25 luglio non
esiste più una copia giornaliera. La finestra riparte da due giorni e si riempie una
notte per volta, tornando a sette il 2 agosto. Non è un residuo del rimedio di `H57`:
è il danno che il difetto aveva già fatto, e sta scritto perché nessuno legga qui una
riparazione più completa di quella che è.

`H59` è **il difetto di `H57` salito di un piano**, ed è chiuso e verificato sulla macchina. Lo script dei
backup chiudeva dicendo «copie totali mantenute: 7». Un **conteggio**, mentre la promessa
che quello script mantiene è in **giorni**. Il 27 luglio ha detto «7» quando i giorni
erano tre, e poi ancora «7» quando erano due: *quel «7» di `tools/backup.sh` non ha
mai mentito e non ha mai detto niente*. ⭐ **Un controllo che rendiconta in un'unità
diversa dalla propria promessa tace
nel momento esatto in cui dovrebbe parlare** — e il momento esatto è quello in cui il
numero torna e la garanzia no. La seconda metà di `H59` è più grande della prima:
anche scritta giusta, quella riga finisce in un file di log dentro un container che
nessuno apre. La
finestra si è dimezzata e se n'è accorta una sessione che stava misurando altro.

Ora lo script dice **quanti giorni distinti** copre e da quando a quando, e il controllo
giornaliero — quello che già ogni giorno verifica se il servizio risponde — guarda anche
quel numero e **avvisa su Telegram**. 🔑 **Ma avvisa di una regressione, non di una
finestra non ancora piena**, ed è la scelta che decide se questo controllo verrà letto o
messo a tacere: dopo un'installazione nuova la copertura è 1, poi 2, poi 3, ed è normale.
Quello che non è mai normale è che la copertura di `H59` *scenda* sotto il massimo già
raggiunto — a regime le copie si sostituiscono, non si perdono. *Residuo dichiarato di
`H59`: quel massimo non scende mai, quindi accorciare di proposito la conservazione
lascerebbe l'avviso acceso finché qualcuno non tocca lo stato.*

`H60` è **una nostra regola violata da noi**, e il controllo che ora la applica è in produzione. La regola dice:
nessun indirizzo, nome o URL della macchina, in nessuna forma — nemmeno in un esempio,
nemmeno nell'output di una prova; oggi la applica la regola R3 del gate, provata caso
per caso (falsi rossi compresi) in `tools/tests/test_no_leaks.py`. La regola di `H60`
era scritta, la applicavamo a mano, e **nessun controllo la faceva rispettare**. Il 27 luglio un indirizzo pubblico è entrato nel repo dentro una
nota che documentava una misura, ed è rimasto visibile per otto ore, in `main` e in tre
versioni pubblicate.

⚖️ **Quanto è grave, detto senza gonfiarlo — e chi scrive è l'autrice del commit.** Quel
numero **non è la macchina** e non è la rete privata: è un ingresso pubblico e condiviso
di Tailscale. Il valore uscito con `H60` non dà accesso a niente e non identifica la
rete di nessuno; che il servizio
stia dietro quel tipo di ingresso, il repo lo dichiara ovunque per scelta. *Decisione del
proprietario: resta nella storia, «di monito ai posteri» — riscrivere la storia di un repo
pubblico costa più di quanto valga il dato.* Lo stato onesto è **«non più in vista»**, non
«rimosso».

⭐ **Il difetto vero non è l'indirizzo: è che una regola scritta non era presidiata da
nulla.** E la stessa classe era già emersa cinque settimane fa: allora fu tolto il valore
e non fu costruito il controllo, così è tornata in un'altra forma. Ora c'è: indirizzi
pubblici e nomi di rete reali fanno fallire la build, con le esclusioni giuste — reti
private, indirizzi che esistono apposta per la documentazione, e i bersagli di test
dichiarati **uno per uno col perché**, perché un controllo che grida al lupo viene spento.

🔴 **E provando `security/check_no_leaks.py` sono uscite tre cose su di lui**, che è
il motivo per cui un controllo
si prova invece di scriverlo: è diventato rosso su un campo dell'installer che aveva come
esempio un indirizzo pubblico vero; la regola sui nomi di rete **non funzionava affatto**
per un errore di scrittura, quindi era verde per costruzione; e la prima stesura del suo
test **riscriveva l'indirizzo dentro il file che esiste per impedirlo** — con il controllo
che diceva verde, perché guardava solo i file già registrati e quello era nuovo. *Ora
`check_no_leaks.py` guarda anche ciò che si sta per aggiungere: un controllo che non
vede quello vede solo gli errori passati.*

`H61` è **un difetto del rimedio di `H59`, trovato il giorno stesso in cui è nato** — e
lo teniamo come voce separata invece di correggere quella vecchia, perché riscriverla
farebbe sparire il fatto che il controllo è nato con questo buco. Il controllo sulla
copertura, quando la cartella delle copie **non è leggibile**, otteneva «zero» e non
«non lo so»: avrebbe mandato il messaggio più allarmante che sappia produrre — *«la
finestra di ripristino si è accorciata: zero giorni»* — per un problema di permessi.
⚠️ *Su questa macchina non è un caso di scuola: la stessa forma, permessi fra utente e
amministratore, ha ucciso un aggiornamento vero la mattina del 27 luglio.* ⭐ E colpisce
esattamente il criterio che quel controllo si era dato: **un allarme che grida al lupo
brucia la fiducia prima della volta in cui è vero**. Ora distingue tre stati — non
misurato, misurato e vuoto, N giorni — e sul *non misurato* non allarma: **segnala di
essere cieco**, che è un'altra cosa e va saputa lo stesso. *Una domanda senza risposta non
è una risposta cattiva.*

Il registro ha imparato una cosa su sé stesso, ed è `H62`. Ogni voce **parziale** racconta
il difetto per esteso — com'era, cosa si è fatto, cosa si è scartato e perché — e il pezzo
che dice *cosa non è ancora fatto* finiva in fondo a quel racconto. Chi legge prende la
denuncia lunga e si ferma lì. 🔴 **Non è un timore: è successo, e due volte lo stesso
giorno.** Un'analisi esterna ha chiuso il suo intervento profetizzando un disastro
imminente su una soglia che *nella versione che stava esaminando era già stata corretta* —
aveva letto il difetto e non il rimedio, che stava nello stesso paragrafo, più in basso. E
prima ancora due di noi avevano classificato quella stessa riga in modo **opposto**, in
buona fede. *Quando un documento produce due letture contrarie fra chi l'ha scritto, il
difetto non è nel lettore.*

Ora ogni voce parziale porta **una riga sola** che dice cosa resta aperto oggi, separata dal
racconto — con un tetto di lunghezza, *perché se serve un paragrafo quello che hai scritto è
un altro racconto e il problema torna identico*. Tutte e quattordici sono state compilate
rileggendo la loro storia, non a memoria. ⚠️ *Limite dichiarato: questo cura le voci
parziali. Una voce chiusa il cui titolo nomina una cosa sola di un insieme che ne ha due
resta illeggibile allo stesso modo — ed è una forma che abbiamo già incontrato due volte.*

E `H53` — i controlli che non controllavano — **si chiude stasera con la terza scoperta
dello stesso difetto in un giorno solo**: l'elenco dei file da analizzare era scritto a
mano. Al mattino ci mancava la cartella delle prove; al pomeriggio quella dei test; alla
sera **`deploy.sh` — lo script che installa sulla macchina** — che non c'era mai stato, con
sedici rilievi dentro di cui cinque su una virgoletta di troppo che annullava le altre due
attorno al nome dell'utente. 🔑 *Un elenco scritto a mano invecchia in silenzio, e chi lo
allarga guarda ciò che sta aggiungendo, non ciò che manca: l'ho allargato io stessa quel
pomeriggio senza vedere un file che era lì da sempre.* Ora l'elenco non esiste più: i file
li chiede a **git**, che non può dimenticarne uno. *Le correzioni sono state verificate
confrontando il comando che finisce sulla macchina prima e dopo — identico.*

**Fix scritto e fix che gira sono due stati diversi — e un fix che gira può rompere
altro. Il registro tiene tutte e tre le cose** invece di dichiarare chiuso ciò che è
soltanto committato. `H57`, `H59` e `H60` sono **chiusi e misurati sulla macchina**; `H58` è **chiuso**: la copia ora si scrive
accanto, con un nome provvisorio, e prende il nome definitivo solo quando è finita — la
rinomina è istantanea e indivisibile, quindi *sparisce l'istante in cui poteva esistere una
copia a metà*. **Non era stato fatto subito apposta**: la modifica precedente toccava la
conservazione delle copie e doveva andare in produzione da sola e misurabile. La cura di
`H58` ci è andata, è stata misurata, e solo allora si è toccato il secondo pezzo. *Residuo più stretto,
dichiarato: se lo strumento di sistema non accetta di spingere su disco quel singolo file,
si prosegue senza — e lì una mancanza di corrente lascerebbe un file provvisorio, non una
copia monca. Il danno peggiora nel modo giusto.*

⭐ **E installando il controllo sulla copertura è arrivata la conferma che serviva**: quel
secondo aggiornamento **non è costato un giorno**. La copia fatta prima di aggiornare ha
*sostituito* quella dello stesso giorno invece di aggiungersi — prima due giorni, dopo
due. *Aggiornare non consuma più la storia*, ed è la prova sul campo che il primo rimedio
funziona, arrivata da un'operazione fatta per tutt'altro. ⚠️ Resta vero che oggi la
copertura è di **due giorni** e tornerà a sette il 2 agosto: il controllo adesso lo **dice
a ogni giro** invece di lasciarlo dedurre, che è tutto quello che poteva fare.

📌 E su `H60`, «chiuso» significa **il controllo**, non il dato: l'indirizzo resta nella
storia del repo e nelle tre versioni, per decisione del proprietario.

Gli altri **7 parziali** non sono lavoro a metà: sono **scelte** o **rinvii dichiarati**, con
il loro *perché* nel registro:

- **Scelte deliberate** (resteranno tali): il *contatore globale* di `H4` (auto-lockout
  dell'owner); il *push off-site* di `H5` (la cartella `backups/` la porta dove vuole
  chi installa); il gruppo `docker` dell'operator in `H12` (toglierlo romperebbe
  l'update — la whitelist sudo è comunque fatta); il *chiaro-in-avanti* della password
  in `H16` quando il PC non ha bcrypt (per non imporre una dipendenza al PC di deploy);
  `frame-ancestors`/`unsafe-inline` della CSP Mini App in `H35` (servirebbe un client
  Telegram reale per verificare che non rompano la pagina).
- **Rinviati alla postilla** (sotto): il pinning ai digest delle immagini vps1777 (una per servizio)
  in `H22` (oggi l'invariante lo impone la CLI post-pull, non il file compose) e
  l'approvazione manuale dei rilasci in `H24` (i tag pubblicati sono già immutabili).

L'hardening è difesa in profondità, non una garanzia, e il progetto è **pre-1.0**.
Se trovi qualcosa, [scrivimi](#reporting-a-vulnerability).

## Dati a riposo

Onestà su cosa **non** è cifrato a riposo, perché è facile darlo per scontato:

- **Il volume dell'archivio** (`archive-data`) e il **disco della VPS** non sono
  cifrati. Chi ottiene un dump del disco legge l'archivio in chiaro. Se ti serve la
  cifratura a riposo, va fatta a livello di disco/volume dall'infrastruttura (LUKS,
  volume cifrato del provider) — vps1777 non la impone per non gestire un'altra
  chiave sulla macchina.
- **Gli strati locali della memoria 1777** (`fatti.md`, `errata.md` in
  `/var/lib/nlm/memoria-1777/`, il volume dati di nb1777-mcp, da `0.44.0`) sono
  dati personali dell'owner **in chiaro sul disco** come tutto il volume; non
  stanno nel repo per costruzione. Fra i servizi in esercizio li monta solo
  `nb1777-mcp` — il container di backup li legge in sola lettura per cifrarli — e
  li restituisce solo il tool `canonico(full=true)` a una sessione autenticata; nel
  backup notturno viaggiano cifrati. Cosa NON metterci è scritto
  in [docs/MEMORIA-1777.md](docs/MEMORIA-1777.md): persone terze, famiglia, il personale.
- **I secret** (`secrets/*.txt`) sono in chiaro sul disco (mode 600), montati in
  `tmpfs /run/secrets/`. Stessa storia: la protezione è nei permessi e nel non
  finire nei log/argv/backup-non-cifrati (vedi sopra), non nella cifratura a riposo.
- **I backup** (`.tar.age`) invece **sono** cifrati (age), con la chiave privata
  fuori dalla VPS — dal `0.43.13` su due livelli, core notturno e archivio
  settimanale compresso, entrambi cifrati allo stesso modo
  ([docs/BACKUP-RESTORE.md](docs/BACKUP-RESTORE.md)). **Lo snapshot pre-update no**, ed è una scelta: contiene
  `archive-data.tar` (~2,6 GB, l'archivio **in chiaro**) e `gateway-data.tar`, e
  **non** contiene più i cookie Google (`H14`, `H56`). *Dire solo cosa non contiene
  sarebbe la metà comoda della verità: lo stesso contenuto viaggia cifrato per una
  strada e in chiaro per l'altra.*
  - 🔒 **Perché non è cifrato, e perché cifrarlo sarebbe un peggioramento**: quello
    snapshot serve all'**auto-rollback** di `vps1777 update`, che gira **sulla VPS**,
    mentre la chiave privata age vive sul PC dell'owner e deve restarci. Cifrarlo
    renderebbe il rollback incapace di leggere ciò che gli serve **proprio nel momento
    in cui serve** — durante un aggiornamento andato male. Vedi `tools/restore.sh:9-13`
    e il blocco `H14` in `tools/vps1777.py:58-82`. ⚠️ Vale anche per la variante
    «escludiamo `archive-data` dallo snapshot»: l'archivio **è** il dato che il
    rollback deve poter ripristinare.
  - 📏 **Quanto resta in chiaro, e per quanto**: `snapshot_prune`
    (`tools/vps1777.py:1021-1032`) pota uno snapshot solo quando è più vecchio di
    **72h** *e* non è quello da conservare — «il più tardivo dei due». Non tiene
    «l'ultimo»: **ogni giro di `vps1777 update` aggiunge ~2,6 GB in chiaro che
    restano 72 ore.**
    Misurato il 27/07/2026: due snapshot conviventi, 4,9 GB, con la stessa copia
    dell'archivio due volte (dimensione identica al byte — nessuna deduplicazione).
    Con rilasci frequenti il totale è dell'ordine di (aggiornamenti in 72h) × 2,6 GB,
    e pesa sul disco oltre che sulla riservatezza.
- **Cancellazione**: l'archivio si cancella per **DB intero** (`/admin/archive`,
  con conferma e audit). La cancellazione per singola conversazione non c'è: è una
  scelta, non una dimenticanza.

## Postilla — l'hardening che faremo al 100% più avanti

Alcune protezioni sono state **rimandate di proposito**, non scartate, perché in
questa fase i rilasci sono frequenti e aggiungerebbero attrito:

- **Cifratura del disco della VPS** (voce `H56` del registro: chiuderebbe in un
  colpo archivio, secret e snapshot pre-update, **senza toccare l'auto-rollback**,
  perché il decifrato è trasparente alla macchina — vedi §Dati a riposo per il
  perché cifrare il solo snapshot non si può). La traiettoria, per data, perché ognuna era vera alla sua:
  **27/07/2026** — decisione dell'owner: *«cripteremo il disco quando lo formatto
  la prossima volta»*. **22-23/08/2026** — il format è arrivato e la cifratura è
  stata **provata davvero**: su Debian 13 con volumi cifrati la VPS risultava
  instabile, ed è stata rimessa Debian 12 coi dischi in chiaro. La decisione è
  registrata come **rischio accettato** in `security/findings.yml`, voce `H56`:
  non più un rinvio, una scelta con la sua prova. Se un'immagine cifrata stabile
  tornerà disponibile per questa macchina, la voce si riapre — sul disco, non nel
  codice: `vps1777` non la impone né gestisce un'altra chiave.
- **Approvazione manuale dei rilasci** (parte di `H24`): un GitHub *environment*
  `release` con reviewer richiederebbe una tua approvazione a ogni tag. I tag
  pubblicati sono già **immutabili** (ruleset in `security/rulesets/`); manca solo
  l'approvazione sulla *creazione* di un tag nuovo. Lo attiveremo quando il ritmo dei
  rilasci sarà più regolare.
- **rootfs read-only su `nb1777-mcp`** (parte di `H43`): il servizio con Chromium è
  escluso dal read-only finché non verifichiamo un giro NotebookLM reale con tutte le
  tmpfs necessarie.
- **Pinning ai digest delle immagini vps1777 nel compose, una per servizio** (`H22`): oggi l'invariante
  «gira solo il digest verificato» lo impone la CLI *dopo* il pull (contro `images.lock`);
  farlo vivere anche nel file compose (override generato all'`up`) chiuderebbe il caso di
  un `docker compose pull` lanciato a mano fuori dalla CLI. Tocca il percorso di update,
  quindi lo faremo con un momento dedicato.
- **Audience restriction (RFC 8707) non implementata — scelta dichiarata**
  (vaglio corso1777, 03/09/2026). Oggi l'`aud` dei nostri access token è il
  `client_id` del client DCR, il proxy verifica il bearer **senza** confrontare
  l'audience, e i server MCP dietro il gateway non validano il token in proprio:
  un token buono per un servizio è buono per l'altro. È difendibile **in questo
  assetto**: installazione single-owner (il token è legato al `sub`
  dell'owner), backend su rete Docker `internal` non raggiungibile da fuori,
  container non-root con `cap_drop ALL` e rootfs read-only, path-secret sul
  gateway. Le condizioni che riaprono la voce sono due, e vanno prese sul
  serio: **più utenti/tenant** sullo stesso gateway, o **un backend esposto
  senza il gateway davanti**. La contromisura è nota e piccola per gradi:
  prima `expected_aud` fisso del gateway nel `verify()` del proxy, poi — se
  serve davvero — `resource` (RFC 8707) e un token per servizio, con il
  costo dichiarato (più giri al token endpoint, e il token exchange RFC 8693
  se un backend dovrà chiamare l'altro).

## Out of scope

- Vulnerabilità in immagini base (Python, Tailscale, Caddy) — segnalale a monte
- Misconfigurazioni del DEPLOYER (es. lasciare la VPS aperta su altre porte)
- Account claude.ai compromessi (responsabilità Anthropic)
- Account Google compromessi (responsabilità Google)
