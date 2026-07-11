# Prompt di onboarding — C1: Key-ring con grace window

> **Come usare questo file.** È il prompt per aprire una **sessione dedicata**
> (Claude Code, sul repo `vps1777`) che progetta e costruisce il key-ring. Copia
> il blocco sotto la riga come primo messaggio. È scritto per reggere il tempo:
> se lo lanci fra settimane, la sessione **prima verifica lo stato reale** e poi
> agisce — non dà per scontato che questa foto sia ancora esatta.
>
> Non contiene segreti: credenziali VPS, URL e password le fornisci tu a inizio
> sessione (o sono già nel contesto operativo).

---

Sei incaricato di progettare e costruire, su **vps1777**, un **key-ring con
grace window** per i secret di firma: rendere la **rotazione delle chiavi
trasparente**, cioè senza costringere nessuno a rifare login o ri-autorizzare i
connector. Oggi ruotare la chiave di firma è un evento disruptivo, e questo
scoraggia la rotazione periodica — che è invece una buona pratica di sicurezza.
Il fine ultimo è: **poter ruotare spesso, anche in automatico, senza che si
noti**.

## 0. Come lavorare (leggi prima di tutto)

- **Questa è una fotografia, non la verità corrente.** Prima di progettare,
  **fai una ricognizione dello stato reale** (§5): il codice potrebbe essere
  cambiato, potrei aver già iniziato in un'altra sessione, la memoria e
  l'archivio potrebbero avere materiale nuovo. Se scopri che è già fatto, o che
  le priorità sono cambiate, **fermati e dillo a Neo** invece di procedere.
- **Hai margine.** La direzione tecnica in §3 è una proposta motivata, non un
  binario. Se durante la ricognizione trovi un design migliore, o un problema
  adiacente che vale la pena chiudere insieme, **proponilo**. Il prompt
  indirizza; non ti vieta di pensare.
- **Metodo 1777:** italiano, tono da pari e asciutto; distingui i **fatti**
  (verificati nel codice, con file:riga) dalle **inferenze**; niente
  rassicurazione, verità tecnica; ragionamento esteso quando serve. Verifica
  sempre alla fonte, mai a memoria.
- **Confini operativi di vps1777** (non aggirarli): il gateway **non ha
  docker.sock**; i secret sono **Docker secrets** in `/run/secrets/`, mai in env
  né nel repo/history; le azioni sul sistema (restart, rotazione) le fa la **CLI
  host `vps1777`**, non il gateway. Confermare le azioni distruttive prima di
  eseguirle. Lavorare su un **branch dedicato**, mai su `main`.

## 1. Cos'è vps1777 (contesto minimo)

Gateway MCP personale self-hosted (Docker, esposto in HTTPS via Tailscale
Funnel). Il gateway fa OAuth 2.1 (DCR + Authorization Code + PKCE) + reverse
proxy MCP + pannello `/admin/*` + Mini App Telegram `/app/*`. Dietro, sulla rete
`internal`, gli upstream: `archive-mcp` (ricerca FTS5), `nb1777-mcp`
(NotebookLM), `nb1777-bot` (Telegram). Aggiornamento a immagini GHCR via
`vps1777 update` (CLI host + pulsante admin, pattern collect→apply, auto-rollback).

Repo: `~/Scrivania/vps1777` (git). Rilascio: **branch → PR → CI (lint +
contract + 4 build) → squash-merge → tag `vX.Y.Z` → release workflow (4 immagini
+ bundle su GHCR) → `vps1777 update` sul VPS → E2E live**. Versione attuale: leggi
`VERSION`.

## 2. Il problema

La firma dei JWT usa **un solo secret simmetrico** (HS256). Ruotarlo
(`tools/rotate-secret.sh oauth_signing_secret`) **sovrascrive il file e riavvia
il gateway → invalida in blocco TUTTI i token attivi**: access, refresh, cookie
admin, JWT miniapp. Conseguenza: claude.ai deve ri-autorizzare, l'admin deve
re-login, la Mini App si ri-autentica. È un martello, quindi non lo si usa —
e una chiave che non ruota mai è un rischio che cresce nel tempo.

## 3. Stato attuale verificato (fatti, con file:riga — RI-VERIFICALI)

- **Firma unica, nessun `kid`.** `services/gateway/app/jwt_helpers.py`:
  `issue()` (riga ~52) firma con `s.effective_signing_secret` in HS256;
  `verify()` (riga ~69) decodifica con lo **stesso unico secret**. L'header JWT
  non porta un `kid` (key id) → non c'è modo di sapere con quale chiave è stato
  firmato un token. 5 `typ` separati (boundary di sicurezza): `access`,
  `refresh`, `admin`, `miniapp`, `csrf` (`VALID_TYPS`, riga ~20).
- **Secret caricati da file.** `services/gateway/app/settings.py`:
  `effective_signing_secret` (riga ~143) = env `oauth_signing_secret` **oppure**
  `oauth_signing_secret_file` (Docker secret `/run/secrets/oauth_signing_secret`).
  Stesso schema per `gateway_secret` (namespace URL, un secret diverso).
- **TTL dei token** (`settings.py` ~108-111): access **900s** (15 min), refresh
  **2.592.000s** (30 giorni), admin cookie **8h**, miniapp **1h**. → La grace
  window minima è governata dal **refresh (30 giorni)**, a meno di forzare il
  refresh-rotation (vedi sotto).
- **Revoca già esistente, ortogonale.** `services/gateway/app/oauth.py`:
  refresh token con **rotazione + reuse detection**; i `jti` revocati/usati sono
  **persistiti** in `oauth_revoked.json` (riga ~55, `_revoked_refresh`). Il
  key-ring è per-**chiave** (via `kid`); la revoca è per-**token** (via `jti`):
  devono convivere senza pestarsi.
- **Rotazione manuale disruptiva.** `tools/rotate-secret.sh` (ramo
  `oauth_signing_secret`, ~84): genera nuovo, **sovrascrive**, `docker compose
  restart gateway`, avverte "invalida TUTTI i token".
- **Sistema migrazioni presente ma mai usato.** `migrations/` contiene solo un
  README; in CI le migrazioni esistenti sono **immutabili** (un `git mv`/edit di
  `migrations/*/run.py` fa fallire la CI). Il key-ring potrebbe essere la **prima
  migrazione reale** (dal file-singolo allo schema anello).
- **Zero test JWT.** `services/gateway/tests/` non ha test per `jwt_helpers`/
  `oauth`. Da colmare: la logica del key-ring (selezione per `kid`, finestra di
  grazia) va in un modulo **testabile** — e la CI gira i test gateway con
  `uvx pytest` **senza deps pesanti**, quindi la logica pura dev'essere
  **stdlib-only** (pattern: `archive_indexer`, `fts.py`, `miniapp_core`,
  `asgi_security`). Attenzione: `jwt_helpers` importa PyJWT → isola la parte
  pura (anello + kid + grace) da quella che chiama PyJWT.

## 4. Obiettivo e direzione tecnica proposta (non prescrittiva)

Costruire un **anello di chiavi** con **finestra di grazia**:

- Ogni JWT porta un **`kid`** nell'header; `issue()` firma sempre con la chiave
  **corrente**; `verify()` sceglie dall'anello la chiave che corrisponde al `kid`.
- **Rotazione = aggiunta, non sostituzione.** Una nuova chiave diventa la
  corrente (firma); la precedente resta nell'anello **solo per verificare** i
  token ancora in circolazione, per la durata della grace window; poi si ritira.
- **Retrocompatibilità in transizione:** i token già emessi **senza `kid`**
  devono restare validi finché non scadono → `verify()` con fallback alla chiave
  legacy per i token privi di `kid`. Prima migrazione = introdurre l'anello
  mantenendo valido il secret attuale come prima chiave.
- **Dimensionare la grace window:** ≥ vita del refresh (30 giorni) è la scelta
  sicura; in alternativa, sfruttare il **refresh-rotation già esistente** per
  ri-firmare i refresh con la chiave nuova al primo uso, accorciando la finestra
  (trade-off: un client inattivo oltre la grace perde la sessione). **Decidi tu**
  e motiva.
- **`rotate-secret.sh`** diventa non-disruptivo (aggiunge una chiave all'anello
  invece di sovrascrivere; ritira le scadute). Valuta se agganciare la
  **rotazione schedulata** all'infrastruttura esistente `vps1777-secrets-check`
  (timer settimanale + `cmd_secrets_status`): il key-ring rende la rotazione
  automatica finalmente sicura.
- **Domanda aperta da valutare (non obbligatoria):** restare **HS256 con anello
  di secret simmetrici** (più semplice, coerente con l'esistente) oppure passare
  ad **asimmetrico** (EdDSA/RS256 + JWKS) — più standard per il `kid`, ma scope
  maggiore e cambia il modello. Porta una raccomandazione, non farla di nascosto.
- **`gateway_secret` (namespace URL):** è un secret diverso, la cui rotazione
  cambia gli URL dei connector. Una "grace window" lì significa accettare **due
  namespace** per una finestra. **Scope secondario:** valuta se includerlo o
  lasciarlo a un follow-up; di' quale e perché.

## 5. Ricognizione iniziale obbligatoria (prima di scrivere codice)

1. **Codice, alla fonte:** rileggi `jwt_helpers.py`, `settings.py` (secret +
   TTL), `oauth.py` (revoca/reuse/refresh-rotation), `tools/rotate-secret.sh`,
   il blocco `secrets:` di `compose.yaml`, `migrations/README.md`, e come il CLI
   host gestisce i secret (`tools/vps1777.py`: `secrets-check`,
   `cmd_secrets_status`). Verifica che i numeri e le righe di §3 siano ancora
   veri.
2. **Memoria di progetto:** leggi `vps1777-security-auth`,
   `vps1777-piano-self-update`, `vps1777-update-channel-gotchas`, e ogni nota che
   parli di secret/rotazione. Potrei aver già annotato decisioni.
3. **Archivio (`archive1777`, MCP):** cerca cosa Neo ha già detto su rotazione,
   key-ring, chiavi di firma. **Avvertenza:** l'archivio ha un **lag di 2-4
   giorni** e questa feature è recente → è **probabile che non ci sia ancora
   nulla** (verificato l'11 lug: solo rumore — GPG keyring, `kid`=bambino). Usa
   il **protocollo dello zero** (0 risultati non prova assenza: riprova quotando
   i termini, `"key-ring"`, in doppia lingua `rotazione OR rotation`), e non
   costruire conclusioni sul silenzio dell'archivio. Se emerge qualcosa di
   sostanziale, `get_context` per leggerlo intero.
4. **Chiedi a Neo** ciò che il codice non dice: ogni quanto vuole ruotare, se la
   rotazione automatica è un obiettivo di questa sessione o un follow-up, se
   preferisce restare HS256.

## 6. Criteri di accettazione

- **Rotazione trasparente dimostrata E2E sul VPS reale:** ruoti la chiave, un
  token emesso *prima* resta valido durante la grace window, un token emesso
  *dopo* è firmato con la chiave nuova (`kid` diverso), e **nessuno** deve
  re-login/ri-autorizzare. Oltre la grace, il token vecchio non è più accettato.
- **Retrocompatibilità:** i token pre-key-ring (senza `kid`) restano validi fino
  alla loro scadenza naturale durante la transizione.
- **Convivenza con la revoca:** `oauth_revoked.json` (jti) continua a funzionare;
  un token revocato resta revocato anche se la sua chiave è ancora nell'anello.
- **Test:** primi test del percorso JWT — logica dell'anello (selezione `kid`,
  grace, fallback legacy) **stdlib-only**, in CI via `uvx pytest`.
- **Se tocchi lo schema dei secret:** una **migrazione** vera in `migrations/`
  (la prima), rispettando l'immutabilità di quelle esistenti.
- **Doc + CHANGELOG + VERSION**; rilascio col flusso standard; verifica live
  post-deploy con lo stack a 4 container healthy.

## 7. Libertà e limiti

Hai libertà di: proporre un design diverso e motivarlo; estendere lo scope se
scopri un problema adiacente che conviene chiudere insieme (dillo prima); dire
che una parte **non** va fatta ora. Non hai libertà di: rompere i confini di
sicurezza (docker.sock, secret in chiaro, azioni-sistema dal gateway); lavorare
su `main`; dichiarare fatto senza E2E live; introdurre un downgrade di sicurezza
(es. accettare token senza verificarne davvero la firma) in nome della
compatibilità.

## 8. Riferimenti

- Codice: `services/gateway/app/{jwt_helpers,settings,oauth,security}.py`,
  `tools/rotate-secret.sh`, `tools/vps1777.py`, `compose.yaml`, `migrations/`.
- Doc: `SECURITY.md`, `docs/ARCHITECTURE.md`, `docs/INSTALL.md`.
- Memoria: `vps1777-security-auth`, `vps1777-piano-self-update`,
  `vps1777-update-channel-gotchas`.
- MCP per la ricognizione storica: `archive1777` (search; il connettore claude.ai
  potrebbe esporre ancora la vecchia interfaccia a 2 tool — dietro risponde
  comunque il server v0.19.0 con auto-quoting ed errore parlante).
