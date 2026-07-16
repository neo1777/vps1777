# vps1777 → Sistema di self-update "da prodotto" — Brief per il Piano

> ## ⚠ DOCUMENTO STORICO — questo piano è stato ESEGUITO
>
> Brief del **4 luglio 2026**, quando vps1777 **non aveva** un canale di aggiornamento:
> build locale sulla VPS, `VPS1777_TAG` fermo a `dev`, niente `VERSION` né `migrations/`,
> aggiornare = reinstallare. **Quel mondo non esiste più.** Il sistema progettato qui è
> stato consegnato in **v0.9.0** (4 luglio 2026, *«Canale di self-update gestito»*): la
> CLI host (`tools/vps1777.py`), `migrations/`, il bundle di release con `images.lock`,
> l'health-gate 180s, l'auto-rollback, il pulsante admin, il timer di check.
> Poi **irrobustito** dalla campagna di sicurezza: cosign fail-closed (v0.23.0), tag `v*`
> immutabili (v0.32.0), unit systemd senza utente hardcodato (v0.33.0).
>
> **Il testo qui sotto non descrive il presente** — descrive il punto di partenza.
> Per come funziona l'update **oggi**: [docs/UPDATE.md](docs/UPDATE.md).
> Per il piano che ne è uscito: [docs/SELF_UPDATE_PLAN.md](docs/SELF_UPDATE_PLAN.md).
>
> *Non è aggiornato di proposito: un brief riscritto a posteriori smette di essere la
> prova di cosa si sapeva quando si è deciso. Si data, non si corregge.*

> **Scopo del file.** Documento autoconclusivo che dà contesto completo e vincoli per
> **pianificare** (non implementare) un sistema di aggiornamento delle installazioni vps1777:
> versioni numerate, opt-in, con backup e rollback, sul modello "come aggiorno un software
> qualunque". Pensato per essere letto da una sessione **ultraplan** (cloud) o da plan mode,
> e per servire da prompt di lancio.
>
> **Come lanciarlo:** dalla CLI esegui `/ultraplan` e incolla le sezioni **§1–§9** (oppure:
> *"Leggi e segui `SELF_UPDATE_BRIEF.md` e tutta la documentazione del repo; produci il piano
> richiesto in §9"*). La sessione cloud clona lo **stato pushato** del repo, quindi questo file
> e i doc citati devono essere **committati e pushati** (branch `feat/self-update`).

---

## 1. Obiettivo

Produrre un **PIANO production-ready** per un sistema di aggiornamento delle installazioni
vps1777 già in campo, che permetta a un utente che ha installato vps1777 di ricevere e
applicare gli aggiornamenti in modo controllato — **come un software qualunque**: versioni
numerate, changelog, un comando (o un pulsante) per aggiornare, backup automatico prima,
e **rollback automatico** se qualcosa si rompe.

Criterio di completezza: al termine dell'esecuzione del piano, una VPS con vps1777 v*N*
installato deve poter passare a v*N+1* con **un solo comando** (o click), senza ricompilare
nulla in produzione, senza perdere dati, e tornando **da sola** alla versione precedente se
la nuova non diventa healthy. Il sistema deve reggere il vincolo hardware reale (VPS 4GB/4-core).

L'output è un **piano**, non codice. Il piano lo eseguiremo a valle, fase per fase.

## 2. Stato attuale (sorgente)

**Cos'è.** Stack Docker Compose v2 — un gateway OAuth 2.1 (reverse-proxy MCP + `/admin/*`),
tre servizi backend (`archive-mcp`, `nb1777-mcp`, `nb1777-bot`), esposto via Tailscale Funnel
(host-mode) / Caddy / Cloudflared. Repo pubblico: `github.com/neo1777/vps1777`. In produzione,
validato live end-to-end (connettori claude.ai + bot Telegram + NotebookLM operativi).

**Com'è distribuito oggi (il nodo del problema).**
- L'installer (`installer/engine.py`, cross-OS via paramiko; e `deploy.sh`, equivalente bash)
  trasferisce il repo sulla VPS via **tar over SSH**, **escludendo `.git`** → **non c'è git
  sulla VPS**. Repo remoto in `/home/vps1777/vps1777`, utente operatore `vps1777`.
- Il deploy fa `docker compose up -d --build` → **build locale sulla VPS** delle 4 immagini
  (`installer/engine.py:436` `step_build`; `deploy.sh:412`). Su 4GB, ricompilare Chromium
  (`nb1777-mcp`) è pesante: è il rischio OOM che il modello a registry elimina.
- **Nessun canale di update esiste.** Aggiornare oggi = riscaricare il tarball e ri-lanciare
  l'installer. Nessun versioning effettivo, nessun rollback, nessun changelog applicato.

**Cosa esiste GIÀ ed è riusabile o da riconciliare** (verificato alla fonte):
- **CI di release** `.github/workflows/release.yml`: su tag `v*` builda e **pubblica su GHCR**
  le 4 immagini `ghcr.io/<owner>/vps1777-<service>:<VERSION>` + `:latest`, con provenance,
  SBOM e **firma cosign keyless**. È l'unico posto che produce immagini versionate pubblicate.
- **CI di test** `.github/workflows/ci.yml`: su `main`/PR fa ruff + shellcheck (non bloccante)
  + `docker compose config` + build di verifica (`push: false`, tag `vps1777/<svc>:ci`).
- **Scansione** `.github/workflows/trivy.yml`: settimanale, immagini `vps1777-<svc>:scan`.
- **Variabile di versione** `.env.example:24` → **`VPS1777_TAG`** (default `dev`, commento
  "semver in produzione"). Il `compose.yaml` la usa: `image: vps1777/<svc>:${VPS1777_TAG:-dev}`
  (righe 46/92/121/153) — ma **ogni servizio ha ANCHE `build:`** (righe 43/89/118/150), e
  `engine.py`/`deploy.sh` non scrivono mai `VPS1777_TAG` → resta `dev` e si builda in locale.
- **Backup** `tools/backup.sh`: dump volumi Docker (`gateway-data`, `archive-data`, `nlm-auth`,
  `tailscale-state`, `caddy-*`) + `.env`/`compose*`/`ingress/`/`secrets/*.txt`, cifrato con
  **age**, output `backups/vps1777-<ts>.tar.age`, MANIFEST con **`git rev-parse HEAD`**,
  rotation 7d+4w. `tools/restore.sh`: ripristino con wipe volumi, **interattivo** (`read` di
  conferma), non riavvia da solo. `compose.ops.backup.yaml`: profilo `ops.backup`, cron 03:00.
- **Auto-update esistente** `compose.ops.watchtower.yaml` (profilo `ops.autoupdate`):
  Watchtower auto-pull+restart su nuovo tag, poll 1h, label-only sui 4 servizi. Documentato in
  `docs/OPS.md:51`. **Scartato come canale primario** (vedi §6): nessun changelog, nessun
  backup pre-update, nessun health-gate/rollback vero, nessuna migrazione.
- **Rotazione secret** `tools/rotate-secret.sh`: scrive `secrets/*.txt` + `docker compose
  restart <svc>` — pattern di "azione host che riscrive stato e riavvia".
- **Versioni pacchetto** `services/*/app/__init__.py` → tutti `__version__ = "0.1.0"`,
  **non collegati** a `VPS1777_TAG` né al tag git.
- **CHANGELOG.md** già in formato Keep a Changelog + SemVer.

## 3. Cosa leggere prima di pianificare

Nel repo (clonato da ultraplan):
- `compose.yaml` (build+image, reti backend/ingress, healthcheck, secrets, volumi) e gli
  overlay `compose.dev.yaml`, `compose.ingress.*.yaml`, `compose.onboarding.yaml`,
  `compose.ops.*.yaml`.
- `installer/engine.py` (motore deploy cross-OS, gli step `step_prepare/upload/config/build/
  tailscale_host/finalize/reboot`, `run()`) e `deploy.sh` (equivalente bash + modalità `--apply`).
- `installer/installer.py` (server web locale, deploy in thread + `/api/stream`) e `installer/ui.html`.
- `.github/workflows/{release,ci,trivy}.yml`.
- `.env.example`, `tools/{backup,restore,rotate-secret,backup-container-setup}.sh`.
- `services/gateway/app/{routes.py,admin.py,onboarding.py}` — rotte `/admin/*` e il pattern
  "collect (web, no-priv) → apply (fuori, con priv)" via `onboarding/pending.json`.
- Docs: `docs/OPS.md`, `docs/BACKUP-RESTORE.md`, `docs/ARCHITECTURE.md`, `docs/INSTALL.md`,
  `docs/SECRETS.md`, `docs/TROUBLESHOOTING.md`, `README.md`, `CHANGELOG.md`.

## 4. Requisiti del risultato

- Qualità senior. Niente mock/TODO/demo/placeholder: ogni componente del piano deve essere
  eseguibile davvero su una VPS reale.
- **Idempotenza** ovunque: rieseguire un update già applicato non deve fare danno; una
  migrazione applicata non deve riapplicarsi.
- **Sicurezza first** (è un gateway di sicurezza): update sempre **opt-in e consapevole**, mai
  silenzioso; nessuna nuova superficie privilegiata senza giustificazione esplicita; immagini
  verificate (cosign già c'è) o almeno pinnate per digest; secrets mai esposti; backup con
  permessi restrittivi.
- **Reversibilità**: nessun update senza un backup datato pre-update e senza un percorso di
  rollback verificato.
- **Nessuna perdita dati**: i volumi (`gateway-data`, `archive-data`, `nlm-auth`) sono sacri.
- Test adeguati: il piano deve includere come si **valida** un update e un rollback su VPS reale.

## 5. Vincoli (paletti)

- **Hardware reale: VPS 4GB RAM / 4-core.** Niente build in produzione durante l'update
  (rischio OOM nel momento peggiore). È l'argomento decisivo pro-registry.
- **Niente git sulla VPS** oggi (trasferimento via tar). Reintrodurlo è una *scelta da valutare*
  (§8), non un dato.
- **Il gateway NON ha privilegi Docker né `docker.sock`** e monta i secret in read-only
  (documentato in `services/gateway/app/onboarding.py:11`). Non può eseguire un update da sé.
  Qualunque azione privilegiata deve stare fuori dal gateway.
- **Zero telemetria verso di noi**: il check "c'è un aggiornamento" è una GET pubblica a
  GitHub, nient'altro. Nessun dato dell'utente lascia la sua VPS.
- **Cross-OS lato installer** (l'utente installa da Windows/Mac/Linux via l'installer grafico);
  ma il *runtime* dell'update gira sulla VPS Linux.
- **Retrocompatibilità con le installazioni già in campo**: chi ha già installato (build locale,
  immagini `vps1777/<svc>:dev`, nessun comando update) deve poter migrare al nuovo modello con
  un passo one-shot, senza reinstallare da zero.
- Poche dipendenze nuove sulla VPS; preferire ciò che c'è già (bash, docker compose, python3,
  age, curl — tutti installati dall'installer).

## 6. Scelte già prese (da rispettare — NON rivalutare)

Decise dal committente prima del piano:

1. **Modello a registry GHCR.** La CI (già presente in `release.yml`) builda e pubblica le 4
   immagini versionate su `ghcr.io`; la VPS fa **solo `docker compose pull`**. Niente build in
   produzione. (Il git-based rebuild è **escluso**.)
2. **Doppia superficie di aggiornamento**: (a) una **CLI** `/usr/local/bin/vps1777` con
   sottocomandi `update` / `rollback` / `status` / `version`; (b) un **pulsante "Aggiorna"**
   nell'admin del gateway. *Come* il pulsante applichi l'update rispettando il vincolo "gateway
   senza privilegi" è materia di §8 — ma che le due superfici esistano è deciso.
3. **Notifica Telegram** al owner quando esce una nuova versione (GET pubblica a GitHub, zero
   telemetria). È **solo notifica**: l'update resta manuale/opt-in.
4. **Auto-rollback su health-fail**: se dopo l'update i servizi (gateway + MCP) non tornano
   healthy entro una finestra, la VPS torna **da sola** alla versione precedente.
5. **Versioning SemVer** ancorato ai tag git `vX.Y.Z` (già il trigger di `release.yml`) e a un
   file **`VERSION`** nel repo come fonte-di-verità della release; la versione in esecuzione
   sulla VPS è tracciata dalla variabile **`VPS1777_TAG`** già esistente (`.env`).
6. **Backup datato pre-update** (riusando `tools/backup.sh`) prima di toccare qualunque volume.
7. **Migrazioni idempotenti**: struttura predisposta ora (cartella `migrations/` + registro
   `applied` nel volume) anche se inizialmente vuota, per non accumulare debito al primo update
   "con schema".
8. **Bootstrap one-shot** per le installazioni esistenti (converte compose build→pull, installa
   il comando, scrive `VPS1777_TAG`/`VERSION`).
9. **Watchtower resta come profilo opt-in "avanzato"**, non è il canale primario: il canale
   primario e raccomandato è il comando/pulsante controllato.
10. **Vincoli di sicurezza del progetto invariati**: layer separati, niente `docker.sock` sul
    gateway, secrets fuori dall'env (Docker secrets), age-key dell'utente sul suo PC, nessun
    secret nel repo/history.

## 7. Tracce parallele (piano nel piano)

- **Riconciliazione naming immagini.** Oggi coesistono `vps1777/<svc>` (compose/runtime),
  `vps1777/<svc>:ci` (ci.yml), `vps1777-<svc>:scan` (trivy), `ghcr.io/<owner>/vps1777-<svc>`
  (release). Il piano deve convergere su **uno** schema (presumibilmente
  `ghcr.io/neo1777/vps1777-<svc>:<VPS1777_TAG>`) e aggiornare compose, ci, trivy di conseguenza.
- **Split compose build vs pull.** `compose.yaml` (solo `image:`, per gli utenti / produzione)
  vs `compose.build.yaml` (con `build:`, per dev e per la CI). Nessuno dei due deve rompere
  l'altro; `compose.dev.yaml` esistente va coordinato.
- **Distribuzione dei file non-immagine** (compose*.yaml, `migrations/`, il comando `vps1777`,
  gli overlay ingress). Le immagini portano il *runtime dei servizi*, ma questi file vivono sul
  filesystem della VPS e vanno aggiornati **senza git**. È una decisione-chiave (§8).
- **Migrazione delle installazioni esistenti** (la VPS attuale gira già in build-locale): il
  bootstrap è un cutover a sé, da progettare senza downtime dei dati.
- **Firma & verifica.** cosign firma già in `release.yml`; valutare `cosign verify` (o pin per
  digest) nello step di pull dell'update come gate di supply-chain.
- **Coordinamento con `backup`/`restore`.** `restore.sh` è interattivo: serve una modalità
  non-interattiva/`--yes` per l'auto-rollback, senza indebolire il restore manuale.
- **Notifica**: dove vive il check periodico (systemd timer sulla VPS? loop nel bot? nel
  gateway?) e come non diventa telemetria.

## 8. Aree che richiedono riprogettazione (candidati da valutare — NON imposizioni)

Il piano deve **valutare e raccomandare con motivazione** (perché prima del come), non dare
per scontato:

| Area | Stato attuale | Candidati da valutare |
|---|---|---|
| **Pulsante "Aggiorna" senza privilegi** | Gateway senza `docker.sock`; pattern `collect→apply` via `pending.json` + `deploy.sh --apply` | (a) il pulsante scrive un *intent* (`update_pending`) che la CLI privilegiata consuma; (b) sidecar "updater" con `docker.sock` che il gateway chiama via rete interna; (c) il pulsante mostra solo stato/disponibilità + istruzioni, l'azione la fa la CLI. Trade-off sicurezza vs "one-click reale". |
| **Come arrivano i file non-immagine** (compose, migrations, CLI) senza git | Nessun git sulla VPS; file dal tar iniziale | (a) scaricare il tarball della release GitHub del tag (`/archive/refs/tags/vX.Y.Z.tar.gz`) ed estrarre i soli file non-immagine; (b) reintrodurre un `git clone` shallow in produzione; (c) impacchettare un "runtime bundle" dedicato negli asset della release. |
| **Naming immagini** | 3-4 schemi incoerenti (§7) | convergere su `ghcr.io/neo1777/vps1777-<svc>:<TAG>` e propagare a compose/ci/trivy |
| **Dove gira il check-versione** | inesistente | systemd timer host / job nel bot / job nel gateway — con quale cadenza, e come degrada se GitHub è irraggiungibile |
| **Health-gate: cosa conta "healthy"** | healthcheck compose su gateway (`/health`) e MCP (TCP socket) | riusare gli healthcheck compose vs probe applicative (es. un `tools/call` MCP end-to-end); soglia tempo/retry prima del rollback |
| **`VERSION` vs `VPS1777_TAG` vs `__version__`** | tre nozioni scollegate | come tenerle in sync (single source of truth + propagazione); se legare `__version__` dei servizi al tag |
| **Backup pre-update: cosa e dove** | `backup.sh` cifra con age (chiave sul PC utente) | l'auto-rollback deve poter ripristinare **senza** la age-key remota? valutare uno snapshot locale non cifrato a vita breve solo per il rollback immediato, distinto dal backup age per il disaster recovery |
| **Rollback: dati vs immagini** | `restore.sh` ripristina dati/config, non seleziona un tag immagine | il rollback di un update deve tornare al **tag immagine** precedente + (se una migrazione ha toccato i dati) ripristinare il volume; definire la relazione migrazione↔reversibilità |
| **Watchtower** | profilo `ops.autoupdate` presente | mantenerlo/deprecarlo/documentarne i limiti rispetto al canale controllato |

## 9. Output atteso del piano

La FORMA esatta del piano che ci aspettiamo:

1. **Fasi con dipendenze, rischi e milestone** — a partire dalle 9 fasi già ipotizzate
   (F1 versioning + split compose; F2 CI GHCR — per lo più riconciliazione dell'esistente;
   F3 migrazioni; F4 CLI `vps1777`; F5 pulsante admin; F6 notifica Telegram; F7 bootstrap
   one-shot; F8 sync installer + docs; F9 test end-to-end + PR). Il piano può riordinare/fondere
   le fasi, ma deve dichiarare le dipendenze (es. F1↔F2 sbloccano il pull; F3/F4 sono il motore).
2. **Decisioni-chiave con alternative valutate e raccomandazione motivata** — almeno tutte le
   voci di §8, ciascuna con trade-off espliciti e la scelta consigliata col *perché*.
3. **Mappatura del flusso di update, passo per passo**: dal `vps1777 update` (check → changelog
   → conferma → backup → pull → up → migrazioni → health-gate → esito/rollback) e la variante
   dal pulsante admin. Sequence chiaro, con gli stati di errore e il punto esatto di rollback.
4. **Strategia di migrazione**: struttura `migrations/`, registro `applied`, contratto di una
   migrazione (idempotente, reversibile o esplicitamente no), e come il runner le applica tra
   versione vecchia e nuova.
5. **Strategia di deploy + cutover delle installazioni esistenti**: il bootstrap one-shot, in che
   ordine converte compose→pull / installa il comando / scrive i tag, e come garantisce zero
   perdita dati sulla VPS già in produzione.
6. **Strategia di test end-to-end su VPS reale**: come si pubblica una release di prova (es.
   `v0.9.0-rc`), come si verifica il pull dalle immagini GHCR, come si **forza un fallimento**
   per validare l'auto-rollback, come si verifica la notifica Telegram.
7. **Le tracce parallele di §7**, ciascuna pianificata (non scoperta a metà esecuzione).
8. **Trade-off espliciti** per ogni scelta delicata (sicurezza, one-click vs controllo,
   git-in-produzione vs tarball, cifratura backup vs velocità di rollback).

> Principio guida trasversale: **perché prima del come**, qualità senior, idempotenza,
> sicurezza first (è un gateway), niente mock/TODO/demo, tutto validabile live su VPS reale.

---

### Note oneste (assunzioni di chi ha allestito il brief)

- Le voci di §6 sono **decisioni del committente** raccolte prima del piano; le voci di §8 sono
  **deliberatamente lasciate aperte** perché toccano sicurezza e UX e vanno motivate, non
  imposte. La distinzione §6/§8 è load-bearing: non spostare una voce da §8 a §6 senza il via.
- Il branch d'implementazione e quello del brief coincidono (`feat/self-update`) per pragmatismo:
  il brief è il primo commit, l'implementazione segue sullo stesso branch, la PR ne è la sede.
- Il naming registry assunto è `ghcr.io/neo1777/vps1777-<svc>` (coerente con `release.yml`); se
  l'owner GHCR effettivo differisse, è l'unico punto da correggere a tappeto.
