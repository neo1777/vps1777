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
  firmato (`cosign sign-blob` keyless) e verificabile (`VPS1777_REQUIRE_COSIGN=1`
  rende la verifica obbligatoria). Nessun aggiornamento build-in-place.
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

## Out of scope

- Vulnerabilità in immagini base (Python, Tailscale, Caddy) — segnalale a monte
- Misconfigurazioni del DEPLOYER (es. lasciare la VPS aperta su altre porte)
- Account claude.ai compromessi (responsabilità Anthropic)
- Account Google compromessi (responsabilità Google)
