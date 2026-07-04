# Piano: sistema di self-update "da prodotto" per vps1777

> Risposta al brief `SELF_UPDATE_BRIEF.md` §9. Rispetta integralmente le decisioni bloccate di §6; valuta e raccomanda tutte le aree aperte di §8. Tutti i fatti citati sono stati verificati alla fonte nel repo.

## Contesto

Oggi vps1777 non ha un canale di aggiornamento: l'installer (`installer/engine.py`, `deploy.sh`) trasferisce il repo via tar (escludendo `.git`) e fa `docker compose up -d --build` → build locale delle 4 immagini sulla VPS 4GB (rischio OOM, specie per Chromium in `nb1777-mcp`). `VPS1777_TAG` resta `dev` per sempre (nessuno dei due deploy la scrive — verificato), non esiste `VERSION` né `migrations/`, `release.yml` pubblica già immagini firmate su GHCR ma **non crea alcuna GitHub Release**. Aggiornare = reinstallare. Il piano introduce update numerati opt-in con backup pre-update, health-gate e auto-rollback, su modello registry-pull (decisione §6.1), con doppia superficie CLI + pulsante admin (§6.2).

**Tesi del design (una frase):** il motore è un'unica CLI host-side Python (`/usr/local/bin/vps1777`, solo stdlib, eseguita come utente `vps1777` che ha già docker+sudo NOPASSWD); tutto il resto è un trigger sottile verso di essa — il pulsante admin scrive un *intent file* consumato da una systemd path unit (lo stesso pattern collect→apply di `onboarding/pending.json`, reso istantaneo), il check versione è un systemd timer, la notifica Telegram parte dall'host col token già presente in `secrets/telegram_bot_token.txt`. I file non-immagine viaggiano in un **runtime bundle** curato allegato a una GitHub Release che `release.yml` inizia a creare; le immagini sono pullate per tag e **verificate contro un lockfile di digest** dentro il bundle. Un solo code path, una sola superficie privilegiata (quella già esistente), gateway invariato senza privilegi.

## Fatti verificati che vincolano il design

- `compose.yaml`: ogni servizio ha sia `build:` sia `image: vps1777/<svc>:${VPS1777_TAG:-dev}` (43-46, 89-92, 118-121, 150-153). Healthcheck: gateway HTTP `/health` (statico, non proba gli upstream), MCP = solo TCP port-open, **nb1777-bot senza healthcheck**. Volumi dati: `gateway-data`, `archive-data`, `nlm-auth`. Bind mount `./onboarding:/var/lib/onboarding:rw` sul gateway (compose.yaml:71).
- Overlay combinati via `-f` + `--profile` (nessun `COMPOSE_FILE`): logica in `engine.py:428-434` `_compose_cmd`, duplicata in `deploy.sh:142` e `restore.sh:115`.
- `release.yml`: su tag `v*` push `ghcr.io/${{ github.repository_owner }}/vps1777-<svc>:<VERSION>` + `:latest`, provenance+SBOM, cosign keyless solo sul tag versione. Nessuna Release, nessun asset. 4 schemi di naming incoerenti tra compose/ci/trivy/release.
- `tools/backup.sh`: hot backup non-interattivo, cifrato age (recipients = potenzialmente solo chiave sul PC utente ⇒ **l'auto-rollback non può dipendere dalla age-key**), MANIFEST con `git rev-parse || 'no-git'` (sulla VPS è sempre `no-git` ⇒ identità versione = tag/digest, mai rev git). `tools/restore.sh`: interattivo (`Procedo? [s/N]`), senza `--yes`, non fa `up`.
- Pattern consolidati riusabili: `onboarding.py:77-120` (collect→apply via `pending.json`, chmod 600, consuma-e-cancella; invariante di sicurezza a `onboarding.py:11-13`), `rotate-secret.sh` (azione host riscrive stato → `compose restart`), admin JWT cookie per l'auth del pulsante.
- Bot: python-telegram-bot **senza** extra `[job-queue]` → nessuna infrastruttura periodica; è su rete `ingress` (egress ok) ma non conosce `VPS1777_TAG`.
- L'installer non crea alcuna unit systemd/cron sull'host (solo cron dentro il container backup). `/usr/local/bin` host intonso. Il re-upload tar non cancella i file rimossi → staleness strutturale da risolvere.
- Divergenza engine/deploy.sh: engine esclude `onboarding/` dal tar, deploy.sh no.

---

## 1. Fasi, dipendenze, rischi, milestone

Si mantengono le 9 fasi del brief con due ri-scope dichiarati: la **riconciliazione naming entra in F1** (è prerequisito dello split compose, non traccia parallela) e la **notifica Telegram (F6 del brief) si fonde col check-timer** perché sono un solo artefatto; il pulsante admin (F5 del brief) diventa la fase successiva. Mappa: F1=F1, F2=F2, F3=F3, F4=F4, **F5=check+notifica (era F6)**, **F6=pulsante admin (era F5)**, F7=F7, F8=F8, F9=F9.

Grafo: `F1 → F2 → F4 → {F5 → F6, F7} → F8 → F9`, con `F3 ∥ F2` che alimenta F4. **F1+F2 nella stessa PR-window** (altrimenti la CI si rompe nel mezzo).

### F1 — Versioning + convergenza naming + split compose
Dipende da: niente. Sblocca: tutto.
- Creare `VERSION` in radice (contenuto: prossima release, es. `0.9.0`).
- `compose.yaml`: rimuovere i 4 blocchi `build:`; `image: ${VPS1777_IMAGE_BASE:-ghcr.io/neo1777}/vps1777-<svc>:${VPS1777_TAG:-dev}` (la variabile base rende fork/registry alternativi un one-liner — coerente con la nota del brief sull'owner come unico punto da correggere).
- Nuovo `compose.build.yaml`: re-aggiunge i 4 `build:` e override immagine ai nomi locali corti `vps1777/<svc>:dev` — solo dev/CI. Flusso dev documentato: `-f compose.yaml -f compose.build.yaml -f compose.dev.yaml`.
- Dockerfile (×4): `ARG VPS1777_VERSION=0.0.0-dev` → `ENV`; i servizi espongono `os.environ.get("VPS1777_VERSION", __version__)` (vedi §2.f).
- **Healthcheck per nb1777-bot** (manca oggi ed è richiesto dal health-gate): task asyncio in `post_init` che tocca un file heartbeat; healthcheck = mtime < 90s.
- `.env.example`: documentare `VPS1777_TAG` ("scritto dalla CLI vps1777, non editare a mano"), aggiungere `VPS1777_IMAGE_BASE`.
- Rischio: `compose.yaml` senza `build:` rompe `ci.yml` e i doc con `up --build` → F2 e sweep doc in F8. Milestone: `docker compose -f compose.yaml config -q` passa e referenzia solo nomi ghcr; il flusso dev con overlay build funziona.

### F2 — Riconciliazione CI/Release + runtime bundle + GitHub Release
Dipende da: F1. Sblocca: F4, F7, F9.
- `release.yml`:
  1. **Job guard**: fallisce se `VERSION` ≠ tag (`v${VERSION}` == `$GITHUB_REF_NAME`) o se `CHANGELOG.md` non ha la sezione `## [X.Y.Z]` del tag — è ciò che rende VERSION/tag *provabilmente* sincronizzati (§2.f).
  2. Matrix build invariata + `build-arg VPS1777_VERSION=${VERSION}`. Cosign resta sul solo tag versione (`:latest` non è mai ciò che l'updater consuma).
  3. **Nuovo job `bundle`** (needs: build): risolve i 4 digest pushati (`docker buildx imagetools inspect`) → `images.lock` (JSON svc→`ghcr.io/...@sha256:...`); impacchetta `vps1777-runtime-vX.Y.Z.tar.gz` con esattamente: `compose*.yaml`, `ingress/`, `migrations/`, `tools/` (backup/restore/rotate-secret/bootstrap/vps1777.py), `systemd/`, `VERSION`, `CHANGELOG.md`, `images.lock`, `bundle-manifest.json` (elenco path gestiti + sha256 per file — è ciò che permette all'updater di cancellare i file gestiti obsoleti, risolvendo la staleness del tar). Produce `SHA256SUMS` + `cosign sign-blob --yes` (keyless, upload `.sig`/`.pem`).
  4. **Crea la GitHub Release** (body = sezione CHANGELOG del tag; asset = bundle + SHA256SUMS + firme). La Release è al tempo stesso sorgente changelog, endpoint di check (`/releases/latest`) e host del bundle.
- `ci.yml`: tag → `ghcr.io/neo1777/vps1777-<svc>:ci` (push:false); valida entrambe le combinazioni compose (`compose.yaml` solo e `+compose.build.yaml`). `trivy.yml`: scansiona `ghcr.io/neo1777/vps1777-<svc>:latest` da GHCR (scansiona ciò che gli utenti eseguono davvero ed elimina il terzo schema di naming).
- Rischio: il primo tag è il test live dell'intera pipeline — è esattamente lo scopo di `v0.9.0-rc.1` in F9. Milestone: un tag produce immagini firmate + Release con bundle verificabile i cui digest combaciano con GHCR.

### F3 — Scaffold migrazioni (in parallelo a F2)
Dipende da: F1 (viaggia nel bundle).
- Cartella `migrations/` + `migrations/README.md` (contratto, §4) + runner come modulo della CLI (`vps1777 migrate --pending/--run`), registro in `gateway-data`. Inizialmente zero migrazioni; il runner e il bootstrap del registro vanno comunque esercitati in F9 (migrazione dummy nella rc).
- Milestone: runner no-op che non registra nulla, due volte di fila (test idempotenza).

### F4 — CLI `vps1777` (il motore) — percorso critico
Dipende da: F1+F2 (servono bundle e immagini pullabili), F3 (runner).
- `tools/vps1777.py` (file unico, python3 stdlib): sottocomandi `check`, `update [--version vX.Y.Z] [--yes] [--from-intent PATH] [--resume]`, `rollback [--with-data] [--yes]`, `status [--json] [--probe]`, `version`, `migrate`, `bootstrap` (la logica F7 vive qui, così viaggia in ogni bundle). Installata in `/usr/local/bin/vps1777` (decisione §6.2).
- Stato: `.env` tiene solo `VPS1777_TAG` (= versione deployata, decisione §6.5); tutto il resto in `var/state.json` (schema-versionato: `current`, `previous`, `previous_images` (digest), `history[]`, `last_check`, `last_notified_version`, `update_in_progress` + step marker). `var/` gitignorata ed esclusa dal bundle, chmod 700. Lock: `flock var/update.lock`.
- `tools/restore.sh`: aggiungere `--yes` (default resta interattivo — non indebolisce il restore manuale, §7 del brief) e `--volumes-only <lista>` (usato dall'auto-rollback); MANIFEST: sostituire il fallback `no-git` con `VERSION`/`VPS1777_TAG`.
- Gateway `/health?deep=1`: proba TCP i due upstream MCP dalla rete backend (modifica non privilegiata, vedi §2.e).
- Rischio: fase a più alta complessità; mitigazione = ogni step come funzione pura su state.json + punti di resume espliciti. Milestone: su VPS di test, `update` N→N+1 e `rollback` di ritorno a N, con state.json coerente in entrambi i casi.

### F5 — Timer di check + notifica Telegram (era F6 nel brief)
Dipende da: F4.
- `systemd/vps1777-check-update.{service,timer}`: `OnCalendar=daily`, `RandomizedDelaySec=4h`, `Persistent=true`, `User=vps1777`, esegue `vps1777 check --notify`. Check = una sola GET non autenticata a `api.github.com/repos/neo1777/vps1777/releases/latest` (timeout 10s; su errore conserva lo stato precedente e marca `error` — mai notifiche su GitHub irraggiungibile, degrada a badge "check stantio" nell'admin). Zero telemetria (§5 del brief).
- Scrive `onboarding/update_status.json` (leggibile dal gateway via il bind mount esistente): `{current, latest, changelog_excerpt, checked_at, error}` — unico canale di cui il gateway ha bisogno per mostrare la disponibilità, senza aggiungergli egress.
- Notifica: dedup su `last_notified_version`; messaggio = versione + estratto changelog + "esegui `vps1777 update` o usa il pannello". Inviata dall'host via `curl` a `api.telegram.org` con `secrets/telegram_bot_token.txt` + `TELEGRAM_OWNER_ID` da `.env` (il bot non c'entra: niente job-queue da aggiungere, vedi §2.d). Riusata da F4 per i messaggi di esito (successo/rollback).
- Milestone: il timer scatta, il file di stato appare, esattamente un messaggio Telegram per nuova release (e zero al secondo run).

### F6 — Pulsante admin "Aggiorna" (era F5 nel brief)
Dipende da: F4, F5.
- Gateway: nuova card admin (server-rendered come il resto di `admin.py`): versione in esecuzione (`VPS1777_VERSION` env, anche nel footer di `_layout`), ultima versione + changelog da `update_status.json`, pulsante POST `/admin/update` (protetto dallo stesso JWT admin di tutte le rotte `/admin/*`) → il gateway scrive `onboarding/update_pending_update.json` `{target_version, requested_by, requested_at, nonce}` chmod 600 (specchio del writer di `onboarding.py`).
- Host: `systemd/vps1777-update.path` (`PathExists=` sull'intent) → `vps1777-update.service` (`User=vps1777`, `ExecStart=/usr/local/bin/vps1777 update --from-intent … --yes`). La CLI **consuma l'intent prima di agire**: valida schema, whitelist semver sul target, rifiuta se più vecchio di 10 min o ≠ latest noto, poi cancella il file (consume-then-act = niente loop di retrigger).
- Progresso: la CLI scrive `onboarding/update_progress.json` dopo ogni step; la pagina admin fa polling ogni 2s e tollera il riavvio del gateway stesso a metà update ("gateway in riavvio…", riprende il polling); l'esito finale arriva sempre anche su Telegram (la UI può essere irraggiungibile proprio quando serve).
- Milestone: un click su VPS reale esegue il flusso completo senza che il gateway detenga mai alcun privilegio.

### F7 — Bootstrap one-shot per installazioni esistenti
Dipende da: F1–F5 rilasciate in una release reale. Dettaglio in §5.
- `tools/bootstrap.sh` (sottile: scarica+verifica il bundle della prima release capace, poi delega al `vps1777 bootstrap` incluso).
- Milestone: una VPS legacy (immagini `:dev` buildate in locale) convertita al modello pull con zero scritture sui volumi, dati verificati intatti.

### F8 — Sync installer + deploy.sh + docs
Dipende da: decisioni F1–F7 congelate.
- `engine.py`: `step_build` → `step_pull` per il path produzione (`compose pull` + `up -d`, mai `--build` in prod — vincolo 4GB); l'installer scrive `VPS1777_TAG=<ultima release>` in `step_config`; nuovo `step_selfupdate_setup` installa CLI + le 4 unit systemd (idempotente: `install -m755` + `systemctl enable --now`); escape hatch `--dev-build` con `compose.build.yaml`.
- `deploy.sh`: stesse modifiche; **sanare la divergenza** (aggiungere `onboarding/` e `var/` ai suoi exclude tar).
- `installer.py`/`ui.html`: nessun nuovo compito (la GUI è per l'installazione; gli update avvengono on-VPS by design — il pattern `/api/stream` resta disponibile per evoluzioni future).
- Docs: nuovo `docs/UPDATE.md` (manuale utente); riscrivere `docs/INSTALL.md:66-68` (canale CLI/pulsante primario, Watchtower declassato), `docs/OPS.md:55-63`, `docs/BACKUP-RESTORE.md` (fixare anche il mismatch "ultimi 14" vs codice 7+4), `docs/SECRETS.md:55`, `README.md:124`, `docs/ARCHITECTURE.md` (diagramma flusso update), `CHANGELOG.md`.
- Rischio: regressioni sul fresh install → coperto da F9. Milestone: un'installazione fresca atterra direttamente sul modello pull con self-update pre-cablato.

### F9 — Validazione E2E su VPS reale + PR
Dipende da: tutto. Dettaglio in §6. Milestone: matrice completa (fresh install, bootstrap, update, fallimento forzato con auto-rollback e restore dati, pulsante, notifica) verde su VPS 4GB reale; PR su `feat/self-update` con le evidenze.

---

## 2. Decisioni-chiave (§8): alternative, trade-off, raccomandazione

### (a) Pulsante "Aggiorna" senza privilegi sul gateway
| Opzione | Pro | Contro |
|---|---|---|
| **A. Intent file + systemd path unit → CLI privilegiata** | Riusa alla lettera il pattern `pending.json` e il suo argomento di sicurezza (`onboarding.py:11-13`); **zero nuove superfici privilegiate** (utente operatore e sudo esistono già; l'installer scrive solo 2 unit file); un solo code path (CLI) per pulsante e terminale; l'updater gira **sull'host**, quindi sopravvive al `compose down` dell'intero stack (nessun paradosso container-che-aggiorna-sé-stesso); one-click reale (la path unit scatta in <1s, non è un poll) | Richiede che installer/bootstrap creino unit systemd (nuova classe di artefatti host — ma semplici, idempotenti, ispezionabili in journald, disattivabili con `systemctl disable`); il feedback di progresso richiede file di stato + polling |
| B. Sidecar "updater" con `docker.sock` chiamato dal gateway via rete interna | Niente systemd; puro compose | Un **container root-equivalent sempre acceso raggiungibile dalla rete del gateway** — esattamente la superficie che §5/§6.10 vietano di espandere; il sidecar non può fare `down` di sé stesso (orchestrazione fragile); duplica la logica CLI; il precedente Watchtower è opt-in e label-scoped, non command-driven |
| C. Pulsante solo-stato + istruzioni | Rischio zero | Viola la decisione bloccata §6.2 (il pulsante deve applicare) |

**Raccomandazione: A.** È lo stesso trust model già documentato: il web raccoglie l'intento, l'attore privilegiato host applica e cancella. Hardening: validazione schema + whitelist semver + TTL 10 min + consume-before-act + `flock`; la service unit gira come `vps1777` (non root; sudo solo dove serve, es. self-install della CLI), con `ProtectHome=read-only` tranne il path del repo.

### (b) File non-immagine senza git
| Opzione | Pro | Contro |
|---|---|---|
| A. Tarball del tag (`/archive/refs/tags/vX.Y.Z.tar.gz`) | Zero lavoro CI | Trasporta l'intero repo (sorgenti, installer, docs) → ricrea il problema dei file stale; i source tarball GitHub **non sono byte-stabili** → nessun checksum pre-pubblicabile; nessun manifest curato; nessuna firma |
| B. `git clone` shallow in produzione | git è già installato; diff gratis | Working tree VCS convivrebbe con secrets/`.env`/`onboarding/` vivi nella stessa dir — `git clean`/checkout diventa un foot-gun; drift tra tree e realtà; contraddice la postura no-git deliberata; comunque nessun gate supply-chain |
| **C. Runtime bundle dedicato come asset di Release** | Contenuto curato (solo i ~10 path gestiti); byte-stabile, con `SHA256SUMS` e firmabile `cosign sign-blob`; trasporta `images.lock` (il gate sui digest) e `bundle-manifest.json` (permette di cancellare i file gestiti obsoleti → risolve la staleness strutturalmente); la Release che forza a esistere è anche endpoint di check e sorgente changelog | `release.yml` deve creare una Release (job piccolo); un artefatto in più da mantenere |

**Raccomandazione: C.** Il bundle è la chiave di volta: risolve distribuzione, changelog, digest pinning e file stale con un solo artefatto. Applicazione sulla VPS: download in staging `releases/vX.Y.Z/` → verifica → preflight `docker compose config -q` sui file staged → copia dei file gestiti correnti in `releases/<current>/rollback-files/` → sync per manifest (**mai** toccando `.env`, `secrets/`, `onboarding/`, `backups/`, `var/`, cert ingress dell'utente) → cancellazione dei file gestiti assenti dal nuovo manifest. Mantiene le ultime 2 release staged per rollback offline.

### (c) Naming immagini
Convergenza su `ghcr.io/neo1777/vps1777-<svc>:<tag>` ovunque, parametrizzata come `${VPS1777_IMAGE_BASE:-ghcr.io/neo1777}` nel compose (fork-friendly). `ci.yml` → `:ci` sotto lo stesso nome; `trivy.yml` → scansiona `:latest` da GHCR; i build locali dev restano `vps1777/<svc>:dev` **solo** dentro `compose.build.yaml`, così `docker images` distingue a vista locale da rilasciato. Trade-off: nomi dev ≠ prod — intenzionale, è la safety feature.

### (d) Dove gira il check-versione
- *Job nel bot*: ha egress, ma manca l'extra `[job-queue]` (nuova dipendenza), il bot non conosce `VPS1777_TAG`, e un container che annuncia un update che non può applicare spezza la logica.
- *Job nel gateway*: è deliberatamente passivo/non privilegiato; dargli polling in uscita ingrandisce proprio il componente che stiamo proteggendo.
- **Timer systemd host → `vps1777 check --notify`**: checker, notificatore, writer dello status file e updater sono lo stesso binario e vedono lo stesso stato.

**Raccomandazione: timer host**, giornaliero + `RandomizedDelaySec=4h` + `Persistent=true`. Degradazione: su GitHub down conserva l'ultimo stato e marca l'errore; l'admin mostra la staleness; mai notifiche di fallimento (niente alert fatigue). Traffico in uscita = esattamente una GET non autenticata a `api.github.com` + la chiamata Telegram del bot dell'utente: zero telemetria.

### (e) Health-gate: cosa conta "healthy"
I soli healthcheck compose sono troppo superficiali (MCP = porta TCP aperta; bot = nulla). La probe MCP `tools/call` end-to-end è troppo pesante per la v1 (richiederebbe token OAuth o un bypass = nuova superficie auth). **Raccomandazione: due livelli + fix del bot:**
1. **Livello compose**: tutti i servizi devono raggiungere `Health.Status=healthy` (il bot riceve il healthcheck heartbeat in F1) e `RestartCount` stabile nella finestra.
2. **Livello applicativo**: gateway `/health?deep=1` proba TCP i due upstream dalla rete backend; la CLI la invoca via `docker compose exec -T gateway python -c "urlopen(...)"` (funziona con qualsiasi overlay ingress, nessuna assunzione su porte host).
Parametri: poll ogni 5s, grace per-servizio ≥ il suo `start_period` (nb1777-mcp 15s, Chromium lento), **finestra totale 180s**, richiesti 2 poll all-green consecutivi. Timeout o container in restart-loop → rollback. La probe `tools/call` è annotata come miglioria post-v1 (richiederebbe un token interno scoped — rinviata con motivazione).

### (f) `VERSION` vs `VPS1777_TAG` vs `__version__`
Fonte di verità = **tag git**, con `VERSION` come suo specchio in-repo **imposto dal job guard di release** (F2) — è ciò che li rende sincronizzati per costruzione e non per convenzione. Propagazione: tag → CI `build-arg VPS1777_VERSION` → ENV nell'immagine → i servizi mostrano `os.environ["VPS1777_VERSION"]` (fallback su `__version__` hardcoded: i build dev mostrano onestamente `0.1.0`/dev). Sulla VPS, `VPS1777_TAG` in `.env` = versione *deployata*, scritta **solo** da `vps1777 update/rollback/bootstrap` (e dall'installer al primo install); tutto il resto (previous, digest, history) in `var/state.json`, tenendo `.env` minimale e human-safe. Footer admin e `vps1777 version` mostrano entrambi: tag deployato + `VPS1777_VERSION` di ogni container (un mismatch = rilevatore di drift gratis).

### (g) Backup pre-update: age vs snapshot locale
Il problema della age-key è reale: i recipient possono essere la chiave sul PC dell'utente → l'auto-rollback non può mai dipendere dal decifrare un archivio age. **Raccomandazione: due livelli, entrambi obbligatori in `update`:**
1. **Backup age via `tools/backup.sh`** (bloccato da §6.6) — livello disaster-recovery, rotation normale.
2. **Snapshot locale non cifrato** `backups/pre-update/<versione>-<ts>/` (stesso meccanismo busybox-tar, solo i 3 volumi dati), chmod 700. Retention: esattamente l'ultimo snapshot; potato al successivo update riuscito o dopo 72h (il più tardivo). Trade-off dichiarato: dati in chiaro a riposo per una finestra limitata — accettabile perché i volumi vivi sono ugualmente in chiaro sullo stesso disco; il livello age copre le minacce off-host. Preflight: `df` ≥ 2× (volumi + delta immagini) prima di iniziare.

### (h) Rollback: tag+dati vs solo-tag
**Raccomandazione: solo-tag di default; restore dati se e solo se ha girato una migrazione data-mutating.** In concreto: l'auto-rollback riporta `VPS1777_TAG` indietro, ripristina i file gestiti da `releases/<prev>/rollback-files/`, `up -d` (le immagini precedenti sono ancora locali — la CLI non pota mai le immagini della versione precedente fino al *successivo* update riuscito). Se e solo se l'update fallito ha eseguito ≥1 migrazione con `data_mutating: true`, ripristina **tutti e tre i volumi dati** dallo snapshot locale (all-or-nothing: ripristinare solo il volume toccato desincronizzerebbe il registro `applied` che vive in `gateway-data`; all-or-nothing rende registro e dati coerenti per costruzione). Trade-off documentato: i dati scritti nella finestra dell'update fallito (minuti, con servizi comunque unhealthy) si perdono nel rollback con restore. Il `vps1777 rollback` manuale è solo-tag di default e richiede `--with-data` esplicito.

### (i) Watchtower
**Mantenere come profilo opt-in, declassare formalmente.** Con tag semver pinnati è quasi inerte (polla un tag che non muta mai); il suo uso residuo è l'utente che insegue `:latest` rinunciando esplicitamente al canale controllato. Azioni: i doc dichiarano che bypassa backup/migrazioni/health-gate/changelog ed è **non supportato in concomitanza** col canale gestito; `vps1777 update` stampa un warning se il profilo `ops.autoupdate` è attivo; zero investimento di codice. Rimuoverlo romperebbe gli opt-in esistenti senza guadagno di sicurezza (è già off di default).

### (+) Gate supply-chain: cosign verify vs digest pinning
**Raccomandazione: digest lock obbligatorio, cosign opzionale-strict.** Percorso obbligatorio (zero nuove dipendenze): `images.lock` del bundle pinna i 4 digest; dopo `compose pull` la CLI confronta i `RepoDigests` di ogni immagine col lock **prima** di `up`; integrità del bundle via `SHA256SUMS` dalla stessa Release. Questo sconfigge il tampering dei tag lato registry; la debolezza residua (compromissione dell'account GitHub compromette lock e immagini insieme) è la stessa trust root del sorgente stesso. Hardening opzionale: bootstrap/installer prova a installare il binario statico `cosign`; se presente, `vps1777 update` esegue `cosign verify-blob` su `SHA256SUMS` (keyless, `--certificate-identity-regexp` pinnata al workflow `release.yml` del repo, issuer GitHub Actions) e `cosign verify` su un'immagine; `--require-cosign` / `VPS1777_REQUIRE_COSIGN=1` in `.env` lo rende fatale. Razionale: un binario Go da ~60MB non deve essere dipendenza dura di ogni VPS 4GB, ma la verifica dev'essere first-class quando c'è.

---

## 3. Flusso di update, passo per passo

### `vps1777 update` (percorso terminale)
```
 0 LOCK        flock var/update.lock (fallisce: "update già in corso")
 1 PREFLIGHT   docker attivo? disco ≥2×? stack in esecuzione? warn se profilo ops.autoupdate attivo
 2 CHECK       risolve il target (--version | releases/latest); target == current → "già aggiornato", exit 0 (idempotente)
 3 CHANGELOG   stampa il body della Release (cache in update_status.json se GitHub è down)
 4 CONFIRM     y/N interattivo salvo --yes / --from-intent
 5 FETCH       scarica bundle+SHA256SUMS(+sig) → releases/vX.Y.Z/ ; verifica sha256 (+cosign se presente/richiesto)
               └─ fallisce: abort, nulla toccato                                     [nessun rollback necessario]
 6 SELF-UPDATE CLI nel bundle ≠ CLI in esecuzione → sudo install → exec della nuova CLI con --resume
 7 BACKUP      tools/backup.sh (age) + snapshot locale dei 3 volumi dati
               └─ fallisce: abort, stack intatto                                     [nessun rollback necessario]
 8 STAGE-CHECK docker compose config -q sui file staged; parse images.lock
 9 PULL        compose pull sui file staged; verifica RepoDigests == images.lock
               └─ fallisce/mismatch: abort, elimina immagini pullate, stack sulla vecchia versione [nessun rollback]
────────────── PUNTO DI NON RITORNO: da qui ogni fallimento innesca AUTO-ROLLBACK ──────────────
10 APPLY FILES salva i file gestiti correnti → releases/<current>/rollback-files/; sync bundle per manifest;
               .env VPS1777_TAG=nuovo; state.json{previous=vecchio, in_progress=true}
11 STOP        compose down (solo container, volumi intatti)
12 MIGRATE     runner: migrazioni pendenti in ordine, container one-off sulle NUOVE immagini; registro aggiornato per-migrazione
               └─ fallisce: ROLLBACK(with-data sse una migrazione eseguita era data_mutating)
13 UP          compose up -d (nuovo tag)
               └─ fallisce: ROLLBACK
14 HEALTH-GATE finestra 180s, poll 5s: tutti compose-healthy + /health?deep=1 200, ×2 consecutivi
               └─ timeout/restart-loop: ROLLBACK
15 SUCCESS     state.json{current=nuovo, in_progress=false, history+}; pota immagini della versione N-1 (tiene N);
               pota snapshot vecchio; Telegram "✅ aggiornato a vX.Y.Z"; update_progress.json finale
```
**Routine AUTO-ROLLBACK** (da 12/13/14): `compose down` → ripristina file gestiti da `rollback-files/` → `.env VPS1777_TAG=previous` → *(sse migrazione data-mutating eseguita)* restore dei 3 volumi dallo snapshot locale (`restore.sh --yes --volumes-only`, niente age) → `compose up -d` (immagini vecchie ancora locali, nessun pull) → health-gate di nuovo → **healthy:** state.json annota `rolled_back_from`, Telegram "❌ update fallito, rollback a vN riuscito (motivo: …)" → **ancora unhealthy:** stop, nessun thrashing; Telegram "🆘 rollback non healthy — serve intervento manuale, backup age disponibile: <file>"; lascia lo stack nello stato migliore possibile, exit 2. Crash-safety: `in_progress` + step marker in state.json permettono a `vps1777 update --resume`/`status` di rilevare e completare/rollbackare un update a metà (es. power loss).

### Variante dal pulsante admin
POST del pulsante → il gateway scrive l'intent → path unit → `vps1777-update.service` esegue gli step 0–15 con `--from-intent` (valida+cancella l'intent per primo; lo step confirm è soddisfatto dal click; rifiuta se il target ≠ latest noto). Progresso in `onboarding/update_progress.json` dopo ogni step; la pagina admin polla e tollera il riavvio del gateway agli step 11–13; l'esito è sempre duplicato su Telegram.

---

## 4. Strategia di migrazione

**Layout** (viaggia nel bundle):
```
migrations/
  README.md                      # il contratto
  0001-<slug>/
    migration.json               # {id, description, volumes:[archive-data], data_mutating:bool,
                                 #   reversible:bool|"restore-only", service:"archive-mcp", introduced_in:"vX.Y.Z"}
    run.py                       # eseguito DENTRO un container one-off del `service` alla NUOVA immagine
```
**Registro:** `gateway-data:/var/lib/gateway/state/migrations.json` (in un volume come da §6.7; `gateway-data` perché esiste sempre, è nel set di backup, e il restore all-or-nothing dello snapshot lo mantiene automaticamente coerente coi dati). Il runner vi accede via `docker run --rm -v vps1777_gateway-data:/state busybox` (nessun servizio deve essere up). Entry: `{id, version, applied_at, checksum(run.py)}`.

**Contratto:** (1) idempotente internamente — rieseguibile anche se il registro fosse perso (`CREATE TABLE IF NOT EXISTS`, `ALTER` guardati); (2) dichiara `data_mutating` onestamente — pilota il restore-da-snapshot nel rollback; (3) `reversible: false` è lecito ma va dichiarato: il rollback di quell'update diventa **restore-only** (lo snapshot è comunque obbligatorio); (4) niente rete, niente accesso ai secret; gira come l'utente del servizio con montati solo i volumi dichiarati; (5) checksum registrato — un `run.py` modificato con id già usato fa fallire la CI (check da aggiungere a `ci.yml`).

**Runner su range di versioni:** pendenti = tutti gli id (ordine lessicografico `NNNN`) assenti dal registro — gestisce naturalmente i salti multi-versione (N → N+3 applica tutto in mezzo, perché il bundle del target contiene la dir `migrations/` cumulativa). Esecuzione strettamente in ordine, registro scritto dopo ogni successo; il primo fallimento abortisce e innesca il rollback dell'update. Downgrade: il runner non "esegue al contrario" mai; andare indietro = restore da snapshot/backup per definizione (documentato in README.md e `docs/UPDATE.md`).

---

## 5. Bootstrap/cutover delle installazioni esistenti

VPS esistente: immagini `vps1777/<svc>:dev` buildate in locale, nessuna CLI, nessuna Release nota. One-shot dalla shell della VPS (documentato in `docs/UPDATE.md` e annunciato nel CHANGELOG):
```
cd ~/vps1777
curl -fsSLO https://github.com/neo1777/vps1777/releases/download/vX.Y.Z/vps1777-runtime-vX.Y.Z.tar.gz
curl -fsSLO .../SHA256SUMS && sha256sum -c SHA256SUMS     # verifica esplicita, niente curl|bash
tar xzf vps1777-runtime-*.tar.gz -C /tmp/vps1777-bundle
bash /tmp/vps1777-bundle/tools/bootstrap.sh
```
`bootstrap.sh` delega al `vps1777 bootstrap` incluso, che in ordine:
1. **Preflight**: stack in esecuzione, docker/compose ok, spazio disco, rileva il profilo ingress da `.env` (stessa logica di `deploy.sh:139`).
2. **Rete di sicurezza**: `tools/backup.sh` (age) — backup completo pre-cutover.
3. **Install**: `sudo install` della CLI in `/usr/local/bin/vps1777`; installa+abilita le 4 unit systemd; installa cosign se raggiungibile (non fatale).
4. **File**: salva i `compose*.yaml` correnti → `releases/pre-bootstrap/`; sync dei file gestiti dal bundle (lo split build→pull atterra qui); **non tocca mai** i valori di `.env` (aggiunge solo `VPS1777_TAG=X.Y.Z` e il default `VPS1777_IMAGE_BASE`), né `secrets/`, né `onboarding/`, né i volumi.
5. **Pull**: `compose pull` (immagini dal registry, nessuna build — vincolo 4GB onorato) + check digest `images.lock`.
6. **Cutover**: `compose up -d` → container ricreati dalle immagini GHCR; **i volumi named non vengono mai rimossi o ricreati da `up`** — questo, più lo step 2, è la garanzia di zero perdita dati (nessun `down -v` in alcun percorso, mai).
7. **Health-gate** (stessa finestra 180s). Fallisce → ripristina i compose da `releases/pre-bootstrap/`, `up -d` (le vecchie immagini `:dev` locali sono ancora presenti) → esattamente lo stack pre-bootstrap.
8. **Chiusura**: inizializza `var/state.json` (`current=X.Y.Z, previous=null, bootstrap=true`), primo `vps1777 check`, Telegram "installazione migrata al canale update". Le vecchie immagini `:dev` restano in place fino al primo `vps1777 update` riuscito (sono il rollback del bootstrap), poi vengono potate.

Idempotente: rieseguito a conversione avvenuta stampa lo stato ed esce 0. Le installazioni nuove (installer post-F8) non ne hanno mai bisogno.

---

## 6. Test end-to-end su VPS reale

Si usano tag rc: `release.yml` scatta su qualunque `v*` da qualunque branch, e `releases/latest` **esclude le prerelease** → i test rc non notificano mai gli utenti reali; gli update rc si pilotano con `--version` esplicito.

1. **Test pipeline**: push `v0.9.0-rc.1` da `feat/self-update` → verifiche: job guard (VERSION/CHANGELOG), 4 immagini GHCR firmate, Release con bundle; da workstation `sha256sum -c`, `cosign verify-blob`, `cosign verify` su un'immagine; `docker pull` per digest da `images.lock`.
2. **Fresh install**: VPS scratch 4GB + installer nuovo → install a modello pull (nessuno step di build; `free`/`dmesg` senza memory pressure), unit abilitate, `vps1777 status` sano.
3. **Bootstrap**: seconda VPS scratch installata con l'installer di **main attuale** (legacy build locale), seminare dati marcatore (una riga via archive MCP, marker in `nlm-auth`) → bootstrap §5 verso rc.1 → marker intatti, container su immagini ghcr, `docker volume ls` invariato.
4. **Update happy-path**: tag `v0.9.0-rc.2` (modifica banale + **migrazione dummy** `0001-e2e-marker` con `data_mutating:true` che scrive un marker in `archive-data`) → `vps1777 update --version v0.9.0-rc.2` → verifiche: backup age + snapshot creati, digest verificati, migrazione applicata una volta sola (update rieseguito → no-op, registro stabile), health-gate ok, Telegram di successo, immagini rc.1 potate solo dopo il successo.
5. **Fallimento forzato / auto-rollback**: tag `v0.9.0-rc.3` da un commit col gateway `/health` deliberatamente a 500 (flag env default-on solo in quel branch) → update rc.2→rc.3 → verifiche: health-gate scade a ~180s, auto-rollback a rc.2, **volumi ripristinati** (rc.3 avrebbe eseguito un'altra migrazione dummy data-mutating — asserire il suo marker assente e i marker rc.2 presenti), stack healthy su rc.2, Telegram di fallimento+rollback, `state.json` con `rolled_back_from`. Testare anche un **fallimento allo stage pull** (digest sbagliato editato a mano nel lock staged) → abort-senza-rollback lascia lo stack intatto.
6. **Percorso pulsante**: sulla VPS a rc.2, per vedere la rc nel pannello si usa un override test-only (`VPS1777_RELEASE_CHANNEL=prerelease` o `update_status.json` scritto a mano); click su Aggiorna → path unit → flusso completo → progress JSON osservato → esito in UI + Telegram. Testare anche il rifiuto per TTL dell'intent e il rifiuto per lock concorrente.
7. **Notifica**: azzerare `last_notified_version` in state.json, `systemctl start vps1777-check-update` → esattamente un messaggio; secondo run → zero (dedup); bloccare api.github.com via hosts → il file di stato guadagna `error`, nessuna notifica, badge "check stantio" nell'admin.
8. **Cleanup**: eliminare release/tag rc, versioni GHCR rc via `gh api`, distruggere le VPS scratch; evidenze (estratti journald, screenshot) allegate alla PR finale su `feat/self-update`.

---

## 7. Tracce parallele di §7 — dove ciascuna è pianificata

- **Riconciliazione naming** → F1 (+ edit CI in F2). Decisa in §2.c.
- **Split compose build vs pull** → F1; `compose.dev.yaml` coordinato via catena `-f compose.build.yaml` documentata; la CI valida entrambe le combinazioni (nessuno dei due rompe l'altro).
- **Distribuzione file non-immagine** → bundle in F2 (decisione §2.b).
- **Migrazione installazioni esistenti** → F7 (§5), zero perdita dati per costruzione.
- **Firma & verifica** → F2 (produce) + F4 (consuma); decisione §2.+ (digest lock obbligatorio, cosign opzionale-strict).
- **Coordinamento backup/restore** → F4: `restore.sh --yes` + `--volumes-only`, default interattivo intatto; fix MANIFEST; fix doc rotation in F8.
- **Collocazione della notifica** → F5 (decisione §2.d: timer host, zero telemetria).

---

## 8. Inventario artefatti

**Nuovi:** `VERSION`, `compose.build.yaml`, `migrations/README.md`, `tools/vps1777.py`, `tools/bootstrap.sh`, `systemd/{vps1777-check-update.service,vps1777-check-update.timer,vps1777-update.path,vps1777-update.service}`, `docs/UPDATE.md`; in CI: job guard+bundle+Release in `release.yml`. Runtime solo-VPS (gitignorati): `var/state.json`, `releases/`, `backups/pre-update/`, `onboarding/update_{status,pending_update,progress}.json`.

**Modificati:** `compose.yaml`, `compose.dev.yaml` (doc header), `.env.example`, 4 `Dockerfile` (+ plumbing versione nei servizi), `services/nb1777-bot` (heartbeat healthcheck), `services/gateway/app/{admin.py,routes.py}` (card update, intent writer sul modello di `onboarding.py`, `/health?deep=1`), `.github/workflows/{release,ci,trivy}.yml`, `tools/{backup.sh,restore.sh}`, `installer/engine.py`, `deploy.sh`, `docs/{INSTALL,OPS,BACKUP-RESTORE,SECRETS,ARCHITECTURE,TROUBLESHOOTING}.md`, `README.md`, `CHANGELOG.md`.

**File critici di riferimento per l'implementazione:** `compose.yaml`, `.github/workflows/release.yml`, `installer/engine.py` (`_compose_cmd:428`, `step_build:436`), `deploy.sh` (`--apply:132-207` come modello intent), `tools/{backup,restore}.sh`, `services/gateway/app/{admin.py,onboarding.py}` (pattern collect→apply e auth JWT da riusare).

## Verifica del piano stesso

La validazione live è la F9 (sopra, §6): pipeline rc → fresh install → bootstrap → update felice con migrazione dummy → fallimento forzato con auto-rollback e restore dati → pulsante → notifica → cleanup. Ogni fase intermedia ha la propria milestone verificabile dichiarata in §1. Principio trasversale onorato: perché prima del come, idempotenza ovunque, sicurezza first, niente mock, tutto validabile su VPS 4GB reale.

---

## Note di review (4 lug 2026 — approvazione del piano)

Il piano è stato revisionato e approvato contro il brief e il repo. Quattro annotazioni **non bloccanti** da onorare in implementazione:

1. **Release rc → flag `--prerelease`**: il piano si affida a "`releases/latest` esclude le prerelease" — vero, ma il job Release deve **marcare** i tag `-rc.*` come prerelease (F2), altrimenti una rc finirebbe in `latest`.
2. **`TAR_EXCLUDE` di `installer/engine.py`**: oltre a sanare deploy.sh, anche engine deve aggiungere `var/` e `releases/` agli exclude del tar (F8).
3. **`nonce` nell'intent**: dichiarato ma senza ruolo — dargli una funzione anti-replay o rimuoverlo (F6).
4. **F9 è manuale/live**: il codice si implementa in F1–F8; i test live (VPS 4GB reale, fallimento forzato, rollback) si eseguono fuori CI, con evidenze allegate alla PR.
