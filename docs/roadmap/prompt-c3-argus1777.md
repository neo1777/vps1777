# Prompt di onboarding — C3: argus1777 come agente browser server-side

> **Come usare questo file.** Prompt per una sessione dedicata (Claude Code, repo
> `vps1777`) che progetta e costruisce l'agente-browser che **agisce come
> l'utente**. Copia il blocco sotto la riga come primo messaggio. Scritto per
> reggere il tempo: la sessione **prima verifica lo stato reale**. Nessun
> segreto: credenziali/URL li fornisci tu.
>
> **Nota di responsabilità.** È automazione dei **propri** account dell'utente,
> con le sue credenziali e il suo consenso — legittima. Il compito della sessione
> è renderla il **più sicura e privata possibile** ed essere **onesta sui rischi
> residui**, non minimizzarli.
>
> **Rinfrescato il 2026-07-14** (base: v0.30.1). La sostanza regge. La novità:
> vps1777 ha ora **in casa il pattern collaudato** per il requisito più duro di
> questo fronte — «il servizio che possiede le credenziali è l'unico che le
> monta» — vedi §4.

---

Sei incaricato di progettare e costruire, per **vps1777**, un **agente-browser
che agisce per conto dell'utente, come l'utente**: si logga agli account che
*lui sceglie* (social, servizi, potenzialmente banche) e compie azioni al posto
suo. Neo vuole **massima libertà d'azione** sugli account che decide lui, ma —
parole sue — «la sicurezza e la privacy al massimo è già nostra regola», e tratta
**dati personali**. Il tuo lavoro è tenere insieme queste due cose con verità
tecnica: dove si può, si fa; dove il rischio è irriducibile, **lo dici**.

## 0. Come lavorare (leggi prima di tutto)

- **Questa è una fotografia, non la verità corrente.** Prima di progettare, fai
  la **ricognizione** (§5): argus1777 esiste già come prodotto locale con doc di
  sicurezza e un decision record che ti riguarda in pieno. Se scopri che ho già
  iniziato o che le priorità sono cambiate, **fermati e dillo a Neo**.
- **Hai margine, ma qui il margine è soprattutto sul COME rendere sicuro** ciò
  che Neo vuole, non sul se farlo. La direzione in §4 è una proposta; il **nodo**
  (§3) va portato a Neo.
- **Metodo 1777:** italiano, tono da pari; **fatti (file:riga) distinti dalle
  inferenze**; **niente rassicurazione** — su questo tema in particolare, la
  verità tecnica batte il "è tutto sotto controllo". Verifica alla fonte.
- **La sicurezza/privacy è il requisito PRIMARIO, non un add-on.** Ogni scelta di
  design si giustifica anche rispetto al modello di minaccia (§4). "Difesa in
  profondità di default": non ragionare dallo stato attuale, previeni.

## 1. Cos'è vps1777 (e dove entra questo)

Gateway MCP personale (Docker, HTTPS via Tailscale Funnel): OAuth 2.1 + reverse
proxy MCP + `/admin/*` + Mini App `/app/*`; upstream su rete `internal`:
archive-mcp, nb1777-mcp, nb1777-bot. **`nb1777-mcp` usa già Chromium+Playwright
headless in container** → è il modello architetturale di riferimento per questo
nuovo MCP. Rilascio: branch → PR → CI → tag → GHCR → `vps1777 update` → E2E.

## 2. Stato attuale di argus1777 (verificato — RI-VERIFICA)

Fonte: `~/Scrivania/argus1777/` (codice) e `docs/` (README, ARCHITETTURA,
**SICUREZZA.md**, **CONFINE_DEPLOY_vps1777.md**, RUNBOOK, PLAYBOOK_USO).

- argus1777 è un **wrapper locale del Playwright MCP ufficiale** (`@playwright/
  mcp@0.0.76`), **non** un MCP custom. Transport **stdio**, browser **headed**
  (finestra visibile), profilo persistente in `./profile`, si aggancia via **CDP**
  a un Chromium di test, con stealth anti-bot. Gira **solo in locale** (127.0.0.1).
- **Nato per LEGGERE**, non per agire: «pilota un browser loggato, vede cosa vede
  l'utente, legge siti dietro autenticazione». Le azioni consequenti (form che
  paga, cancella, pubblica) **si fermano e chiedono OK**.
- **Il suo muro di sicurezza è il profilo dedicato:** «logghi in quel profilo
  solo i siti che vuoi che l'agente tocchi. Banca, mail, gestore password — se non
  li logghi lì, l'agente non può farci niente» (`SICUREZZA.md`). Allowlist, headed
  e stealth sono **guardie, non il muro** (la blocklist «non è un confine di
  sicurezza»).
- **Decision record del 2026-06-23** (`CONFINE_DEPLOY_vps1777.md`): «argus1777 su
  vps1777? **No, non come drop-in**». Incompatibilità: stdio vs HTTP; locale/
  headed/umano-nel-loop vs headless/VPS; anti-bot da IP residenziale vs
  datacenter. E la conclusione che ti riguarda: **se serve browsing server-side,
  si costruisce un browser-mcp headless dedicato** (modello nb1777-mcp), che «non
  è argus1777 portato: è un altro strumento, con altri compromessi».

## 3. Il nodo (portalo a Neo, non deciderlo da solo)

Ciò che Neo vuole ora **rovescia i tre confini che rendono sicuro argus locale**:

1. **Profilo senza-banca → profilo CON-banca.** Il muro di argus era "non loggare
   la banca". Agire come l'utente significa loggarcela. **Il muro va ricostruito
   altrove**, perché il vecchio sparisce per definizione.
2. **Headed/umano-nel-loop → headless su VPS.** Nessuno guarda mentre agisce;
   nessuno sblocca a mano le challenge. Serve reintrodurre l'umano **in modo
   esplicito** (2FA/conferme instradate all'owner — vedi §4).
3. **Locale (127.0.0.1) → VPS pubblica.** Le credenziali/sessioni personali
   vivono su un server esposto. È il salto di rischio più grande.

Quindi: **non stai portando argus1777 sul server, stai costruendo il browser-mcp
headless che il decision record già prevede** — il brand "argus" può restare
(famiglia del "vedere/agire"), la macchina è nuova. Domande per Neo prima di
codificare: (a) l'argus locale **resta** (read, headed, sul PC) e questo è un
complemento server-side, o lo sostituisce? (b) quali categorie di account e
azioni sono in scope della **prima** versione? (c) quanto "umano nel loop" accetta
sul sensibile? La mia raccomandazione: **partire dal basso rischio** (un account
social o di test, azioni reversibili) e dimostrare le mitigazioni **prima** di
toccare conti bancari.

## 4. Direzione e requisiti di sicurezza (il cuore)

**Architettura (proposta):** un **MCP HTTP streamable-http headless** (FastMCP,
modello `nb1777-mcp`), container dedicato con **Chromium+Playwright headless**,
dietro il gateway OAuth, **owner-only**. Tool tipo: naviga, leggi, compila,
clicca, estrai — più la gestione sessione/login.

### Il precedente che ora esiste in casa (v0.30.0, finding H6) — usalo

Il tuo requisito più duro — *le credenziali dell'utente non devono stare a portata
del servizio esposto* — vps1777 l'ha appena risolto per un caso analogo (i cookie
di sessione Google di NotebookLM), e il pattern è **già collaudato nel repo**:

- **Il servizio che possiede le credenziali è l'UNICO che monta il volume.** Il
  gateway — l'unico esposto su Internet — ha **accesso zero**: non le legge né le
  scrive. Vale anche per il bot.
- **Chi ha bisogno di sapere, chiede.** Endpoint **interni** su quel servizio:
  uno dice solo *se* la credenziale c'è (mai il contenuto), l'altro la riceve e la
  installa. Autenticati con un **segreto condiviso** (constant-time) e
  **fail-closed**.
- **`internal/` è un prefisso riservato**: il reverse proxy rifiuta con 404 ogni
  sotto-path `internal/` — **prima** del secret e del bearer — per *tutti* gli
  upstream. Un endpoint privato del tuo MCP **non è raggiungibile da Internet**,
  mai. Questo è il contratto che ti serve (`docs/PLUGINS.md`).
- **Scrittura non distruttiva**: staging → validazione → swap con rollback.

Traduzione per argus: **il profilo browser (cookie, sessioni) lo monta solo il
container argus**; il gateway lo espone come tool ma non vede mai il profilo; le
operazioni sensibili (login, sblocco, 2FA) passano da endpoint `internal/` non
esposti. Riferimenti nel codice: `services/nb1777-mcp/app/nlm_profile.py`,
`services/gateway/app/nlm_client.py`, il blocco `internal/` in
`services/gateway/app/proxy.py`. **Attenzione:** questo pattern risolve *dove
vivono* le credenziali, **non** il fatto che vivano su una VPS — il §3.3 e i
"rischi residui" restano interi.

**Modello di minaccia da scrivere esplicitamente** (è un deliverable): *cosa
perde l'utente se la VPS o il container sono compromessi?* Risposta onesta: le
sessioni/credenziali di **ogni account loggato**. Da qui si progetta per
**contenere il blast radius**, non per sperare che non succeda.

**Requisiti (difesa in profondità):**
- **Credenziali/sessioni mai in chiaro a riposo.** Il profilo browser (cookie,
  storage, sessioni) va **cifrato at-rest**; la chiave **non deve stare sulla VPS
  in chiaro** — valuta: derivarla da un segreto che l'owner fornisce per-sessione
  (sblocco), Docker secret, o profilo montato/decifrato solo in RAM. Dimostra che
  **un dump del volume non rivela credenziali**.
- **Isolamento del container:** capabilities minime (`cap_drop: ALL`,
  `no-new-privileges`, non-root — come gli altri servizi), **nessun docker.sock**,
  nessun accesso ai secret o ai volumi degli altri servizi. Egress di rete
  **controllato** (l'agente naviga verso l'esterno: valuta un'allowlist di domini
  anche a livello rete/proxy, non solo applicativa).
- **Umano nel loop reintrodotto** (sostituisce l'headed di argus): **2FA e
  challenge instradate all'owner** — bel gancio col bot Telegram / Mini App (C2):
  l'agente incontra il 2FA, chiede il codice all'owner, prosegue. **Non** aggirare
  la 2FA: inoltrarla è più sicuro, non meno.
- **Rail sulle azioni consequenti** (pagamenti, trasferimenti, pubblicazioni,
  cancellazioni): **conferma esplicita dell'owner** anche con "massima libertà".
  Questo protegge l'utente (è il senso del suo «sappiamo come sono gli utenti»),
  non lo castra: la navigazione/lettura/azioni reversibili restano libere; il
  fermo è dove un errore costa.
- **Privacy by design / minimizzazione:** i log e l'audit **non** devono mai
  contenere credenziali né contenuti sensibili (numeri conto, messaggi privati);
  screenshot/artefatti cifrati o non persistiti; **retention breve**; di default
  si registra il meno possibile.
- **Onestà sui rischi residui:** «privacy al massimo **per quanto possibile su una
  VPS**» — quel *per quanto possibile* è un requisito di documentazione. Una VPS
  non è l'ambiente trusted del PC locale; alcuni rischi (compromissione del
  server con browser sbloccato) sono **irriducibili**. L'utente sceglie **cosa
  loggare** consapevolmente, sapendo il rischio — come il muro di argus, ma
  invertito. Scrivilo, non nasconderlo.
- **Considerazioni da segnalare (non nasconderle):** molti servizi (banche,
  social) **vietano l'automazione nei ToS** → rischio ban dell'account, che
  l'utente si assume sui propri account; l'anti-bot da **IP datacenter** è più
  ostile (nessun umano per le challenge se non via inoltro); la reputazione IP
  peggiora con l'uso ripetuto.

## 5. Ricognizione iniziale obbligatoria (prima di codice)

1. **argus1777 alla fonte:** leggi `~/Scrivania/argus1777/docs/`
   **per intero** — soprattutto `SICUREZZA.md`, `CONFINE_DEPLOY_vps1777.md`,
   `ARCHITETTURA.md`. Capisci **perché** era local-only: quelle ragioni sono i
   rischi che ora devi mitigare, non ignorare.
2. **Modello vps1777 per un MCP:** come è fatto `nb1777-mcp` (Chromium headless in
   container, FastMCP streamable-http, healthcheck, `GATEWAY_UPSTREAMS`, rete);
   `docs/PLUGINS.md` (il contratto plugin — **incluso il prefisso riservato
   `internal/`**); i confini di sicurezza in `SECURITY.md`, che ora contiene la
   **Rassegna difensiva** completa (l'esito della review a tappeto di luglio 2026:
   leggila, è la barra che questo fronte deve rispettare) e il pattern H6 (§4).
3. **Memoria:** `argus1777-resta-locale`, `vps1777-security-auth`,
   `feedback-security-build-for-evolution` (previeni, non ragionare dallo stato
   attuale).
4. **Archivio `archive1777`:** cerca la genesi e le decisioni su argus (progetto
   "Estensione browser per leggere siti con Claude", giu 2026: uuid 019ec633,
   019ec56c, 019ec638; il confine deploy 019ec5d6). `get_context` per leggere
   intero. Protocollo dello zero, doppia lingua, ricorda il lag.
5. **Chiedi a Neo** il §3: complemento o sostituto dell'argus locale; scope della
   prima versione; livello di umano-nel-loop; quali account per primi.

## 6. Criteri di accettazione

- Un **MCP headless owner-only dietro il gateway** che pilota un browser e agisce
  come l'utente **su un account di TEST/basso rischio**, dimostrato E2E — **prima**
  di qualunque account bancario reale.
- **Credenziali cifrate at-rest**, chiave non sulla VPS in chiaro: dimostri che un
  dump del volume **non** rivela credenziali.
- **2FA e azioni consequenti** passano per l'owner (inoltro/conferma via bot o
  Mini App), dimostrato.
- **Log/audit senza dati sensibili** (verificato).
- **Documenti di sicurezza:** modello di minaccia scritto + rischi residui
  onesti + guida "cosa loggare consapevolmente" (l'equivalente invertito del
  `SICUREZZA.md` di argus).
- Isolamento container (cap_drop, no-new-privileges, non-root, no docker.sock);
  egress controllato. Doc + CHANGELOG + VERSION; rilascio standard; verifica live.

## 7. Libertà e limiti

Puoi: proporre un'architettura diversa e motivarla; dire che una capacità è
**troppo rischiosa così** e va fatta diversamente o rimandata; partire da uno
scope minimo. **Non puoi:** trattare la sicurezza come un add-on da aggiungere
dopo; mettere credenziali personali su disco in chiaro; costruire per l'accesso a
account **altrui** o non autorizzati (è automazione dei **propri** account); far
parlare l'MCP con qualcosa fuori dal suo confine; lavorare su `main`; dichiarare
"sicuro" senza il modello di minaccia e senza aver dimostrato le mitigazioni;
dichiarare fatto senza E2E. Se un requisito di Neo e la sicurezza confliggono in
modo irriducibile, **portagli il trade-off**, non risolverlo in silenzio.

## 8. Riferimenti

- argus locale: `~/Scrivania/argus1777/` e `docs/` (SICUREZZA, CONFINE_DEPLOY,
  ARCHITETTURA, RUNBOOK). Zip storici: `~/Scrivania/argus1777{,_v0.2}.zip`.
- vps1777: `services/nb1777-mcp/app/` (modello browser headless), `docs/PLUGINS.md`,
  `SECURITY.md`, `docs/ARCHITECTURE.md`, `compose.yaml`.
- Memoria: `argus1777-resta-locale`, `vps1777-security-auth`,
  `feedback-security-build-for-evolution`.
- MCP: `archive1777` (v0.19.0, 5 tool) per la genesi di argus.
