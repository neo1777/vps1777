# Changelog

Formato [Keep a Changelog](https://keepachangelog.com/it/1.1.0/), versioning [SemVer](https://semver.org/).

## [Unreleased]

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
