# Security Policy

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

vps1777 espone su Internet **solo** il gateway (porta 443 via Tailscale Funnel / Caddy / Cloudflared).

Threat model dichiarato:
- Backend (archive-mcp, nb1777-mcp, bot) su rete Docker `internal: true` — non raggiungibili dall'esterno
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
- Il gateway (unico servizio esposto) non ha accesso al Docker socket né ai secret host
- Hardening host automatico all'install: `unattended-upgrades` + `fail2ban`
- Strumenti di management (Portainer) mai esposti: solo loopback + tunnel SSH (vedi [docs/OPS.md](docs/OPS.md))

## Rassegna difensiva — l'hardening applicato

Il modello sopra è il design; questa sezione è **cosa è stato reso fail-closed
per costruzione**, dopo una review difensiva a tappeto (luglio 2026). Il pattern
ricorrente che la review ha trovato — e chiuso — è *un default o un residuo che
degrada in silenzio verso l'aperto*: il disegno era già fail-closed, non lo erano
tutti i default. Ogni voce cita la versione in cui è entrata.

### Autenticazione & accesso (i due punti critici)

- **Owner-gating fail-closed** (`v0.22.0`, critico). Con `TELEGRAM_OWNER_ID`
  assente o malformato la Mini App ora **nega tutti** (`/app/auth` → 503), invece
  di lasciar passare chiunque apra il bot. `is_owner` ritorna `False` se l'owner
  non è configurato; il bot applica `owner_only` allo stesso modo; warning
  esplicito all'avvio se manca.
- **Audience del proxy verificata** (`v0.25.0`). Un access token valido non
  basta: il suo `sub` deve essere fra le email ammesse (`OAUTH_ALLOWED_EMAILS`),
  altrimenti il proxy MCP rifiuta. Un token emesso per un altro soggetto non
  raggiunge gli upstream.
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
  chiave **pubblica** (recipient); la privata vive sul PC dell'owner e serve solo
  al restore. `backup.sh` non genera più la coppia sulla VPS (che avrebbe messo
  la privata sullo stesso disco dei backup). Vedi [docs/BACKUP-RESTORE.md](docs/BACKUP-RESTORE.md).
- **Secrets sempre file-mounted** (baseline): password, signing key, token via
  Docker `secrets:` in `tmpfs /run/secrets/`, **mai** in env var. Vedi [docs/SECRETS.md](docs/SECRETS.md).
- **Il repo è pubblico, e un gate lo tratta come tale** (`security/check_no_leaks.py`,
  in CI a ogni PR). Fa fallire la build se entra un **export di sessione** (il `.txt`
  di `/export`: nome innocuo, dentro il detto-e-fatto di una sessione di lavoro) o del
  materiale credenziale vero — distinguendolo dai segnaposto della doc, perché un gate
  che grida al lupo viene disattivato e allora non protegge più niente. Riporta *dove*,
  mai *cosa*: i log della CI di un repo pubblico sono pubblici. Il `.gitignore` da solo
  non basta — non ferma `git add -f` e non fa nulla per un file già tracciato. Regola
  che il gate ricorda a chi lo incontra: **un segreto passato non si toglie, si ruota.**

### Contenimento dei container

- **Il gateway non tocca i cookie Google** (`v0.30.0`). Era l'ultimo finding
  aperto. Il gateway — l'unico servizio esposto su Internet — montava in
  **scrittura** il volume `nlm-auth` (i cookie di sessione Google di NotebookLM),
  perché `/admin/nlm` ci estraeva dentro il profilo caricato: compromettere il
  gateway voleva dire leggerli **e** riscriverli. Ora vale un invariante secco:
  **quel volume lo monta SOLO `nb1777-mcp`**, il servizio che quei cookie li usa
  davvero. Gateway e bot hanno **accesso zero** — né lettura né scrittura — e gli
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
  backend su rete `internal: true`, gateway senza accesso al socket Docker né ai
  secret dell'host (baseline).

### Supply-chain & aggiornamenti

- **Firma cosign obbligatoria di default** (`v0.23.0`, critico). Il self-update
  verifica la firma keyless del bundle di release **fail-closed**: se la verifica
  non passa (o `cosign` manca e non si installa), l'update si ferma. La via
  d'emergenza è esplicita e rumorosa: `VPS1777_REQUIRE_COSIGN=0` /
  `--no-require-cosign`. (Prima la verifica era opt-in e saltata in silenzio.)
- **GitHub Actions pinnate a SHA** (`v0.27.0`). Ogni action è pinnata al commit
  SHA (non al tag mobile): un tag ripuntato a monte non può iniettare codice.
  `Dependabot` (github-actions + docker + docker-compose) tiene freschi gli SHA/i
  digest. Permessi `least-privilege` per-job in `release.yml`. Le immagini di
  terzi nei compose sono digest-pinnate.
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
  path unit. Il gateway non tocca mai Docker.
- **Intent validato e consumato**: schema, SemVer, TTL 10 min, nonce anti-replay,
  e cancellazione **prima** di agire (nessun loop di ri-trigger).
- **Anti-downgrade**: dal pulsante il target non può essere una versione più
  vecchia di quella in esecuzione (version-floor SemVer) — così un gateway
  compromesso non può forzare un downgrade a una release con vuln nota. Il
  downgrade intenzionale resta possibile solo da terminale (chi ha la shell ha
  già ogni privilegio).
- **Supply-chain**: le immagini si pullano da GHCR e si verificano contro
  `images.lock` (digest immutabili) del runtime bundle di release; il bundle è
  firmato (`cosign sign-blob` keyless) e la verifica è **obbligatoria di default**
  (`VPS1777_REQUIRE_COSIGN=0` la disattiva solo come via d'emergenza esplicita).
  Nessun aggiornamento build-in-place.
- **Reversibilità**: backup age + snapshot locale prima di ogni update;
  auto-rollback se lo stack non torna healthy. Nessuna finestra in cui i dati
  restano senza rete di sicurezza.
- **Zero telemetria di vps1777**: vps1777 non ti traccia; il check versione è una
  GET non autenticata a GitHub. Ma **per funzionare, alcuni dati escono verso
  servizi terzi** — vedi la sezione seguente: non è telemetria, è il servizio che
  usi, e va saputo.

Dettaglio completo: [docs/UPDATE.md](docs/UPDATE.md) e [docs/SELF_UPDATE_PLAN.md](docs/SELF_UPDATE_PLAN.md).

## Flussi di dati verso terzi

vps1777 non è un'isola: per erogare le sue funzioni fa transitare dati verso due
servizi esterni. Nessuno è telemetria, ma è bene sapere **cosa esce verso chi**.

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

> **Questo conteggio è verificato dalla CI.** I 43 rilievi vivono in
> [`security/findings.yml`](security/findings.yml): ognuno con il suo stato e, se
> chiuso, con l'**evidenza puntuale** nel codice.
> [`security/check_findings.py`](security/check_findings.py) gira a ogni PR e
> **fallisce** se l'evidenza di una voce chiusa è sparita, se un residuo non
> dichiara cosa manca, o se i numeri qui sotto non combaciano col registro.
>
> Esiste perché questa sezione, una volta, ha dichiarato «nessun rilievo è rimasto
> aperto» quando i chiusi erano 8 su 43. Un claim senza coordinata è
> infalsificabile: marcisce in silenzio. Ora non può più.

La review difensiva ha prodotto **43 interventi** (2 critici, 7 alti, 21 medi, 13
bassi). Le campagne `v0.19.1 → v0.33.0` li hanno affrontati **tutti**: nessuno è più
aperto. Il conteggio, verificato contro il codice dal gate in CI:

| | |
|---|---|
| **chiusi** | 35 |
| **parziali** | 7 |
| **accettati** | 1 |
| **aperti** | 0 |

I due **critici** — owner-gating fail-closed (`H1`) e verifica cosign obbligatoria
(`H2`) — sono chiusi e verificati in produzione, come tutta la fascia alta.

L'unico **accettato**: niente 2FA sul pannello admin (`H28`) — è un gateway
mono-utente dietro Tailscale Funnel, con password bcrypt-12 + lockout per-IP + CSRF
+ revoca reale della sessione; il 2FA aggiungerebbe attrito per un guadagno marginale
su questo profilo. È una decisione, non una dimenticanza.

I **7 parziali** non sono lavoro a metà: sono **scelte** o **rinvii dichiarati**, con
il loro *perché* nel registro:

- **Scelte deliberate** (resteranno tali): il *contatore globale* di `H4` (auto-lockout
  dell'owner); il *push off-site* di `H5` (la cartella `backups/` la porta dove vuole
  chi installa); il gruppo `docker` dell'operator in `H12` (toglierlo romperebbe
  l'update — la whitelist sudo è comunque fatta); il *chiaro-in-avanti* della password
  in `H16` quando il PC non ha bcrypt (per non imporre una dipendenza al PC di deploy);
  `frame-ancestors`/`unsafe-inline` della CSP Mini App in `H35` (servirebbe un client
  Telegram reale per verificare che non rompano la pagina).
- **Rinviati alla postilla** (sotto): il pinning ai digest delle 4 immagini vps1777
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
- **I secret** (`secrets/*.txt`) sono in chiaro sul disco (mode 600), montati in
  `tmpfs /run/secrets/`. Stessa storia: la protezione è nei permessi e nel non
  finire nei log/argv/backup-non-cifrati (vedi sopra), non nella cifratura a riposo.
- **I backup** (`.tar.age`) invece **sono** cifrati (age), con la chiave privata
  fuori dalla VPS. E lo snapshot pre-update, che non è cifrato, **non** contiene più
  i cookie Google (`H14`).
- **Cancellazione**: l'archivio si cancella per **DB intero** (`/admin/archive`,
  con conferma e audit). La cancellazione per singola conversazione non c'è: è una
  scelta, non una dimenticanza.

## Postilla — l'hardening che faremo al 100% più avanti

Alcune protezioni sono state **rimandate di proposito**, non scartate, perché in
questa fase i rilasci sono frequenti e aggiungerebbero attrito:

- **Approvazione manuale dei rilasci** (parte di `H24`): un GitHub *environment*
  `release` con reviewer richiederebbe una tua approvazione a ogni tag. I tag
  pubblicati sono già **immutabili** (ruleset in `security/rulesets/`); manca solo
  l'approvazione sulla *creazione* di un tag nuovo. Lo attiveremo quando il ritmo dei
  rilasci sarà più regolare.
- **rootfs read-only su `nb1777-mcp`** (parte di `H43`): il servizio con Chromium è
  escluso dal read-only finché non verifichiamo un giro NotebookLM reale con tutte le
  tmpfs necessarie.
- **Pinning ai digest delle 4 immagini vps1777 nel compose** (`H22`): oggi l'invariante
  «gira solo il digest verificato» lo impone la CLI *dopo* il pull (contro `images.lock`);
  farlo vivere anche nel file compose (override generato all'`up`) chiuderebbe il caso di
  un `docker compose pull` lanciato a mano fuori dalla CLI. Tocca il percorso di update,
  quindi lo faremo con un momento dedicato.

## Out of scope

- Vulnerabilità in immagini base (Python, Tailscale, Caddy) — segnalale a monte
- Misconfigurazioni del DEPLOYER (es. lasciare la VPS aperta su altre porte)
- Account claude.ai compromessi (responsabilità Anthropic)
- Account Google compromessi (responsabilità Google)
