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
bassi). La campagna `v0.19.1 → v0.30.2` (14 release) ha chiuso **i due critici** e la sostanza
della fascia alta. Non ha chiuso tutto, e qui sta la lista vera — verificata
contro il codice, non contro i buoni propositi:

| | |
|---|---|
| **chiusi** | 8 |
| **parziali** | 16 |
| **aperti** | 19 |

I due **critici** — owner-gating fail-closed (`H1`) e verifica cosign obbligatoria
(`H2`) — sono chiusi e verificati in produzione. Sotto, i residui che pesano di
più; il piano completo sta nel dossier di review.

- **I cookie Google finiscono in chiaro nello snapshot pre-update** (`H14`).
  `vps1777 update` fa uno snapshot **non cifrato** dei volumi dati prima di agire
  (serve all'auto-rollback, che non può dipendere dalla chiave age), e fra quei
  volumi c'è `nlm-auth`. Erode una parte di ciò che la `v0.30.0` ha chiuso: il
  gateway non tocca più quei cookie, ma un dump di `backups/pre-update/` sì. Lo
  snapshot è a `0700` e viene potato dopo 72h — sono mitigazioni, non il fix.
- **I tag `v*` non sono protetti** (`H24`). Le release sono firmate cosign keyless
  *dal workflow*, quindi chiunque possa pushare un tag `v*` conia una release
  **regolarmente firmata**. La firma prova *da quale workflow* viene un artefatto,
  non che qualcuno abbia autorizzato quel rilascio.
- **La sessione admin non si revoca davvero** (`H20`). Il logout cancella il
  cookie; il token `admin` non ha `jti` e non c'è revoke-list — un token rubato
  resta valido fino alla scadenza (8h).
- **L'operator ha `sudo NOPASSWD: ALL`** (`H12`), ed è nel gruppo `docker` (che è
  root-equivalente). Il blast radius di una compromissione dell'operator è l'host.
- **Nessun secondo fattore sul pannello admin** (`H28`): password + lockout per-IP.
- **Il `TS_AUTHKEY` resta in `.env`** dopo l'uso (`H15`), e `.env` non è `chmod 600`.
- **La password admin nasce sulla VPS** e torna sullo stdout SSH (`H16`).
- **Nessuna pagina di consenso OAuth** (`H8`, parziale: la verifica dell'audience e
  i limiti al DCR ci sono).
- **`archive-data` è montato `rw`** in archive-mcp (`H42`), la sola-lettura è
  applicativa.
- Due parzialità sono **scelte deliberate**, non dimenticanze: il *contatore
  globale* di `H4` (introdurrebbe un auto-lockout dell'owner) e il *push off-site*
  di `H5` (la cartella `backups/` la porta dove vuole chi installa).

L'hardening è difesa in profondità, non una garanzia, e il progetto è **pre-1.0**.
Se trovi qualcosa, [scrivimi](#reporting-a-vulnerability).

## Out of scope

- Vulnerabilità in immagini base (Python, Tailscale, Caddy) — segnalale a monte
- Misconfigurazioni del DEPLOYER (es. lasciare la VPS aperta su altre porte)
- Account claude.ai compromessi (responsabilità Anthropic)
- Account Google compromessi (responsabilità Google)
