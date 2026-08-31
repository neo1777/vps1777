# Changelog

Formato [Keep a Changelog](https://keepachangelog.com/it/1.1.0/), versioning [SemVer](https://semver.org/).

## [0.44.1] — 2026-08-31

**La documentazione per chi arriva ora — e un test che non la lascia invecchiare.**

### ✨ Nuovo

- **`docs/CLI.md`**: tutti i comandi di `vps1777` con descrizione ed esempi, e
  **`docs/GLOSSARIO.md`**: le parole del prodotto (container, release, tool MCP,
  canonico…) in due righe l'una. Nate da una richiesta dell'owner che vale come
  criterio: «non lo capisco io, figurati un utente che arriva ora sul repo».
- **`vps1777 help [comando]`**: l'aiuto come comando; riusa il parser vero
  (`build_parser()`, estratto da `main()`), quindi stampa per costruzione ciò
  che il codice accetta.
- **Il presidio** (`tools/tests/test_cli_doc.py`): comando senza sezione in
  CLI.md, sezione su un comando rimosso, o sezione senza esempio → CI rossa.
  Una pagina di riferimento senza un test è il «35 tool» del README: giusta
  alla nascita, mai più guardata.
- **`docs/MEMORIA-1777.md`**: sezione «In parole semplici» in testa (cos'è un
  tool, chi chiama cosa) e il **pattern del puntatore** per le superfici cloud
  — le regole in UNA superficie (le preferenze account), nei Project un
  puntatore fisso senza versione: a ogni bump si aggiorna una superficie sola.

### 🐛 Fix

- La `note` del canonico è la voce di «Storia» **intera**: prima usciva solo la
  prima riga, troncata a metà frase, nel verdetto di ogni `memoria_check`.

## [0.44.0] — 2026-08-30

**Il canonico della memoria 1777 esce dal notebook ed entra nel prodotto.**

### ✨ Nuovo

- **`disciplina.md` è il canonico** (`services/nb1777-mcp/app/memoria_1777/`,
  spedito nell'immagine): la disciplina di memoria 1777 in tre tagli (PIENO /
  LITE / MICRO), **v2.5 · 2026-08-30**, NEUTRA per qualunque utente — «di Neo» →
  «di chi ti parla», via i riferimenti locali; le regole non cambiano. Versione e
  data stanno nella riga di titolo; lo storico v2.2 → v2.4 resta nel notebook
  NotebookLM `claudemd1777`, in sola lettura. Guida: `docs/MEMORIA-1777.md`.
- **`canonico(full=true, taglio=…)` è la cura, non solo il verdetto**: restituisce
  il testo della disciplina nel taglio chiesto più i due strati LOCALI
  dell'installazione, ognuno con la sua `origine` — una sessione stale si allinea
  in contesto, subito. Prima sapeva il numero e non il testo.
- **Gli strati locali `fatti.md` ed `errata.md`** vivono nel volume `nlm-auth`
  (`/var/lib/nlm/memoria-1777/`): fuori dal repo per costruzione, dentro il backup
  notturno cifrato, nessun git richiesto all'utente. Due esempi con le istruzioni
  dentro (`fatti.esempio.md`, `errata.esempio.md`). Cosa NON metterci — persone
  terze, il personale, lo stato dei progetti, il passato — è scritto nella guida.
- **`vps1777 memoria stato | importa <fatti|errata> <file> | mostra <…>`**: gli
  strati si caricano DA DENTRO il container (`compose exec`, non `docker cp`: il
  file nasce dell'utente `app`), scrittura atomica, esito = byte riletti dal volume
  confrontati col file; uno strato vuoto non si carica.
- **`memoria_ack(versione)`**: l'ack «superfici cloud aggiornate» da una sessione,
  stesso campo di stato del bottone «✓ Fatto» del bot. Solo su dichiarazione
  esplicita dell'owner.

### 🔧 Cambia

- L'ack ha **una sede sola** (lo stato in `nb1777-state/memoria.json`): la fonte
  `cloud-ack vX.Y` nel notebook non conta più. Il testo del promemoria Telegram
  dice dove prendere il testo nuovo (`canonico(full=true)`) e come chiudere.
- `canonical.py` non chiama più `nlm`: niente cache, fail-open sul file. I parser
  dei titoli del notebook restano (storico) con un test che vieta al prodotto di
  essere indietro rispetto a esso.
- nb1777-mcp: 38 tool (era 37). Doc allineate: NB1777.md §2/§6/§8/§10, README,
  ARCHITECTURE, SECURITY §Dati a riposo, BACKUP-RESTORE (il core porta gli strati).

### 📝 Perché adesso, e perché non prima

A luglio il notebook era la scelta giusta: con un format della VPS imminente, un
canonico su Google sopravviveva alla macchina e un file *sulla* VPS no. La terza
via — un file *nel repo*, servito dalla VPS — non era sul tavolo. Ricostruito in
una chat claude.ai del 29/08 con `archive1777`; decisione dell'owner: repo
pubblico, prodotto per tutti, «neutro per tutti gli utenti, sulla mia installazione
riempito con le mie cose».

## [0.43.16] — 2026-08-29

**L'export claude.ai non è più un file: è un manifest e cinque zip.**

### ✨ Nuovo

- **L'indexer riconosce l'export claude.ai spezzato in 5 zip per categoria**
  (`conversations-000`, `projects-000`, `design_chats-000`, `memories-000`,
  `light_metadata-000`, più un `manifest-*.json` coi link one-shot che non si
  carica). Misurato sul primo export di questo formato (29/08): i tre zip grandi
  entravano già, i due piccoli — proprio la **memoria persistente** dell'account
  e l'anagrafica — venivano rifiutati come «zip non riconosciuto», perché
  l'export lo si riconosceva da `conversations.json`/`design_chats/`/`projects/`
  e loro non ne hanno nessuno. Ora ogni zip è un export da solo
  (`_e_export_claude`), nel layout nuovo (`memories/<account>.json`) e in
  quello vecchio (`memories.json` alla radice), e il suffisso `-NNN` (le parti)
  non conta: si caricano tutti sullo stesso nome DB, in qualunque ordine,
  idempotenti per uuid. 13.920 record in 15 s, 1,2 GB di RAM di picco.
- **Due fonti nuove dentro l'export**: i `memory_files` (`/areas/*.md`, la forma
  nuova della memoria di claude.ai — etichetta `memory:file:<path>`, ts =
  `updated_at`) e `login_history.json` (gli accessi: una riga per evento,
  `account:login`, ts = timestamp; IP, metodo, user-agent, paese — verbatim,
  come `users.json`: l'ingestione non filtra, chi carica sa cosa carica).
- **`/admin/archive` accetta più file in un gesto** (`<input multiple>`): tutti
  sullo stesso nome DB, in ordine, ognuno con le sue guardie (spazio disco,
  tetto) e la sua pulizia del temporaneo; l'esito è per file, e un errore a
  metà dice cosa è già entrato (ogni file è la sua transazione). Prima erano
  cinque upload col nome DB ribattuto uguale — o, lasciandolo vuoto, cinque DB.

### 📝 Note

- `conversations.json` decompresso è al 58% del tetto per membro (297 MB su
  512): quando lo supererà l'ingest si fermerà **parlante** (`MAX_MEMBER_BYTES`),
  non tronca. Voce da riaprire al prossimo export che lo buca — o che arriva
  a parti (`conversations-001.zip`), che già passerebbe.

## [0.43.15] — 2026-08-29

### 🐛 Fix

- **Il container backup monta anche `gateway-uploads` e `nlm-artifacts`**
  (misurato aprendo sul PC il primo core notturno a due livelli: dentro c'erano
  `gateway-data` e `nlm-auth`, non gli altri due). È il difetto del 10/08 su
  `backup.sh` — la lista enumerata a mano che perdeva proprio questi due —
  riapparso un anello più in là: lo script li salva tutti, ma nel container vede
  solo ciò che il compose gli monta sotto `/volumes`, e quella lista non la
  governava nessuno. Ora la tiene un test: ogni volume del compose base deve
  essere montato `:ro` nel backup (`test_il_container_backup_monta_i_volumi_del_base`).

## [0.43.14] — 2026-08-29

**Il primo update verso la 0.43.13 si è fermato da solo, e aveva ragione.**

### 🐛 Fix

- **Il backup pre-update usa il `backup.sh` della release in arrivo** (misurato
  sul vivo: update 0.43.12 → 0.43.13 via unit, fail-closed, stack intatto). La
  CLI si auto-aggiorna dal bundle allo step 4 e chiama `backup.sh` allo step 7,
  ma lo script nel repo veniva sincronizzato dal bundle solo *dopo*, oltre il
  punto di non ritorno: la CLI nuova ha passato `--senza-archivio` allo script
  vecchio, che conosceva solo `--prune-only` — «uso:», exit 2. *Ogni flag nuovo
  a `backup.sh` rompeva l'update in cui nasceva.* Ora `backup_sh_della_release`
  copia nel repo lo script del bundle (già verificato cosign — lo stesso che il
  sync gestito copierebbe comunque) **prima** di lanciarlo; non si lancia dal
  bundle perché lo script deriva repo, `.env` e recipient dalla propria
  posizione. Test a risposta nota sui tre casi (bundle con script, senza
  bundle, bundle senza script).

## [0.43.13] — 2026-08-29

**Il backup impara cosa vale la pena cifrare.** Misurato sulla VPS: un backup
notturno pesava 9,7 GB, e 9,7 GB erano il solo `archive-data` — rigenerabile in
due ore dai bundle che l'owner tiene fuori dalla macchina. Tutto ciò che è
insostituibile pesava 250 KB. Si pagavano 9,7 GB a notte per 250 KB.

### ✨ Migliorato

- **Backup su due livelli** (`tools/backup.sh`, decisione owner del 29/08:
  *«basta n, n-1 per paranoia… dobbiamo farci stare quel che serve»*). Il
  **core** — tutti i volumi tranne l'archivio, secret, config, e le
  `description` dei DB (l'unica parte dell'archivio che il re-ingest non
  rigenera, esportate ogni notte con sqlite3 nel container) — ogni notte, con la
  ritenzione di sempre. L'**archivio** — i volumi dei DB — ogni 7 giorni, in
  `backups/archivio/`, **compresso zstd prima di cifrare** (2-3× su SQLite+FTS),
  ultime 2 copie. `--archivio` lo forza, `--senza-archivio` lo salta: `vps1777
  update` usa il secondo (ha già lo snapshot pre-update), il bootstrap il primo.
  Il nome resta `.tar.age` per contratto; il formato sta nel sidecar `.meta` e
  nei primi byte — `restore.sh` lo riconosce da lì, e un disaster recovery è
  due restore, uno per livello. Il ciclo backup→restore in CI ora prova i due
  livelli, la divisione dentro il tar, l'export delle description, il passo
  settimanale e il forzato; la ritenzione ha quattro casi nuovi (⑯-⑲).
- **La stima spazio di `vps1777 update` legge lo snapshot, non il backup**: col
  backup compresso «2 × backup» avrebbe sottostimato lo snapshot pre-update, che
  è il volume in chiaro. Ora chiede snapshot precedente + backup più grande
  (su entrambi i livelli) + 1 GiB.
- **`vps1777 check` sorveglia anche l'archivio**: avvisa (e notifica alla
  transizione) se l'ultima copia ha più di 14 giorni.
- **`tools/backup-pull.sh`**: il gesto «porta i backup su un disco tuo» scritto
  una volta — rsync dei due livelli dal PC, senza `pre-update/`, senza
  `--delete`; esce 2 se la destinazione non c'è (HD non montato).
- Il container backup installa `zstd` e `sqlite` (pinnati, come age/bash);
  `deploy.sh` e l'installer grafico aggiungono `zstd` ai pacchetti host.

## [0.43.12] — 2026-08-29

**«Dobbiamo farci stare quel che serve»: la retention impara il peso.**

### ✨ Migliorato

- **Snapshot pre-update: restano n e n-1, il resto si pota subito** (#245,
  decisione owner del 29/08). La regola precedente (72h + ultime 3 versioni,
  f9818614) era vera sul tempo e sulle versioni ma cieca sul PESO: 7 release
  in 36 ore × volumi da 10 GB = 48 GB di snapshot legittimi, disco 24→92 GB.
  L'ultimo snapshot delle ultime 2 versioni non è mai cancellabile da qui;
  una dir senza versione nel nome resta sulla vecchia regola a 72h (l'errore
  di parsing costa spazio, mai un rollback perduto).

## [0.43.11] — 2026-08-28

**La lapide al posto dell'abort: l'apriscatole incontra il mondo reale.**

### 🐛 Corretti

- **Un membro-zip oltre il tetto uccideva l'ingest intero** (#243): al primo
  re-ingest vero, `mcp_dash_bak040826.zip` (>512 MB decompressi) dentro i
  workfiles ha fatto propagare il ValueError di `_read_capped` e l'intero
  bundle è morto. Ora i rami occhi+apriscatole rispondono con la lapide
  `membro-oltre-tetto` e proseguono; il tetto globale del budget (anti
  zip-bomb) propaga sempre. Test col caso reale in miniatura.

## [0.43.10] — 2026-08-28

**Occhi e apriscatole — e l'occhio vive nella sua stanza.**

### ✨ Migliorato

- **OCR locale all'ingest, come servizio interno** (#237, #239): le immagini
  nei bundle (775 scartate come non-testo: molti sono screenshot) passano da
  tesseract nel nuovo container `ocr` — SOLO rete interna, nessuna porta,
  nessun volume né segreto. Il gateway lo chiama via HTTP e NON esegue
  processi: la prima stesura con subprocess nel gateway è stata bocciata dal
  presidio `test_gateway_non_tocca_docker`, e il rosso aveva ragione — un
  parser di immagini non vive nel servizio esposto. Servizio assente →
  lapide `ocr-non-disponibile`; immagine senza testo → `ocr-vuoto`; testo →
  righe marcate `[ocr]`. Il percorso NotebookLM (`archive-ingest`) resta per
  il file pregiato singolo. Smoke reale: uno screenshot vero letto fedele.
- **Zip annidati a profondità 1** (#237): gli archivi dentro i workfiles
  (71 zip + 52 `.skill`, che SONO zip — le skill ora sono cercabili) si
  aprono e i membri passano dalla stessa trafila (testo, jsonl, pdf,
  immagini→OCR, sniff). Zip dentro l'annidato → lapide anti-bomba; tetto
  2000 membri; il budget globale anti zip-bomb propaga sempre.

## [0.43.9] — 2026-08-28

**La cornice decide: il confine mixed↔transcript impara il criterio dell'owner.**

### ✨ Migliorato

- **Voice: gold da 30/37 a 35/37** (#235): i 5 disaccordi confidenti sul
  confine mixed↔pasted_transcript avevano la stessa struttura — con una
  cornice dell'owner prima del materiale («ottengo quanto segue:») è `mixed`;
  col materiale al carattere zero (prompt di shell, local-command-caveat) è
  `pasted_transcript`. Guardiani stretti («flutter:» non è una cornice),
  `own` mai toccata (21/21, falsi cari 0). I 2 disaccordi residui sono
  dichiarati e accettati: curarli creerebbe falsi cari. ACCORDO_MIN 30→35.

## [0.43.8] — 2026-08-28

**L'indexer impara i nomi, le date, e chi parla davvero.**

### ✨ Migliorato

- **Etichette-progetto vere** (#232): i path Windows non si spezzavano coi
  backslash (l'intero path diventava l'etichetta), le sessioni local-agent
  collassavano su «outputs», e tutta la Scrivania stava in un secchio unico da
  126k righe. Ora: `local-agent:<uuid8>`, workfile a due livelli
  (`workfile:<cwd>/<progetto>`), path Windows normalizzati. Vale dai prossimi
  ingest; i DB esistenti conservano le etichette di nascita.
- **I titoli hanno una data** (#232): `ai-title` non porta timestamp — il
  titolo ora eredita l'ultimo ts di sessione visto (1.147 titoli senza data
  nel bundle 20260811). Ordine di resa invariato: è un contratto.
- **Il mandato non è Neo — AN-11 modellata** (#232): la riga di tipo user
  scritta dalla macchina (isSidechain nei transcript, parent_tool_use_id
  negli audit) diventa `sender=mandato` → `speaker=assistant`.
  `speaker=human` torna a voler dire «parole del committente» — l'errore che
  il Laboratorio dell'11/07 ha scoperto, chiuso nello schema.
- **`check_integrity` multi-DB con budget** (#233): 20s, poi risponde con ciò
  che ha misurato e dichiara `non_misurato` il resto (con il come-ottenerlo).
  La chiamata mirata su un DB non ha budget. Prima: minuti di scansione in
  coda, proxy in timeout, server occupato per tutti.

## [0.43.7] — 2026-08-28

**Il describe che mollava la linea.**

### 🐛 Corretti

- **`describe_databases` rispondeva «connection lost»** (#230): le statistiche
  (count, min/max ts, etichette distinte) venivano ricalcolate su TUTTI i DB a
  ogni chiamata — 74,6 s a freddo e 53,9 s a caldo misurati nel container su
  12 DB (5,7 GB) — e il proxy MCP molla molto prima. Ora: memo per snapshot
  (la scansione si paga una volta per versione del file, si invalida da sola
  a ogni upload o set_description) + warmup in avvio (la prima scansione dopo
  un riavvio la paga il server, non il primo client). Test sull'effetto nei
  due versi: il memo morde a file fermo, e invalida il solo DB toccato.

## [0.43.6] — 2026-08-28

**I bug che si trovano solo usando: la fase USO ripaga al primo giorno.**

### 🐛 Corretti

- **`check_integrity` rispondeva `AttributeError` alla prima chiamata vera**
  (#228): `server.py` registrava il tool e chiamava `db.integrita_archivi`
  dal giorno della sua nascita, ma l'adattatore non era mai stato scritto —
  la logica pura aspettava in `integrita.py`, e i due test di presidio
  guardavano registrazione e chiamata, mai la definizione. Ora l'adattatore
  esiste (risolve i nomi con `_targets`, delega a `integrita.verifica`,
  smoke sui tre versi) e il presidio nuovo è DERIVATO: ogni `db.X` chiamata
  da un tool registrato deve avere `def X` in `db.py` — un tool futuro entra
  da solo nel controllo.
- **La redazione mangiava i nomi dei DB** (#228): la sagoma `YYYYMMDD-HHMMSS`
  (`20260811-190343`) ha 14 cifre e un separatore — il pattern telefono la
  ingoiava e le description degli archivi uscivano `[telefono redatto]`.
  Esenzione stretta (solo data-ora con secolo plausibile), provata nei due
  versi: il timestamp sopravvive, il telefono vero continua a sparire.

## [0.43.5] — 2026-08-27

**La stretta che la prova-6 ha reso possibile, e i documenti che non promettono
più nulla senza dire dove si rimisura.**

### 🔒 Sicurezza

- **La stretta filesystem sulle unit di update** (#225, `H43`):
  `ProtectSystem=strict` + `ReadWritePaths` sui quattro terreni che l'update
  tocca davvero (CLI, unit, `/tmp` del backup, home dell'operatore), su
  `vps1777-update.service` e `vps1777-auto-update.service`. Misurata PRIMA di
  essere scritta, con unit transitorie sulla macchina in esercizio — la storia
  di questa unit lo impone (03/08: il seccomp accese NNP e uccise sudo):
  `NoNewPrivs` resta 0 sotto strict+RWP (mount namespace, non seccomp), i
  `sudo` whitelisted funzionano, fuori dai RWP il kernel nega con EROFS, e il
  dump docker del backup era già misurato dalla prova-6 §③ (2,7 GB reali).
  Tre guardiani aggiornati nello stesso gesto, o la release si sarebbe
  rifiutata da sola: `SANDBOX_PROVATE_INNOCUE` nella CLI (elenco unico, con la
  misura accanto; il preflight-unit assolve `ProtectSystem` e becca ancora il
  seccomp), il test NNP che ora importa l'allowlist invece di copiarla, e la
  prova-6 §① che da «delta con la proposta» diventa il guardiano della stretta
  applicata. Il placeholder `@OPERATOR_HOME@` è reso da tutti e tre gli
  installer.

### 📖 Documentazione

- **Le garanzie dei 4 documenti misurati sono 107/107 con ancora** (#226,
  lavoro `a80025f1`): ogni frase che promette qualcosa cita ora il file, il
  test o la voce di registro che la rimisura — comprese due garanzie che un
  test non l'avevano e ora ce l'hanno
  (`services/gateway/tests/test_fail_closed_senza_config.py`,
  `tools/tests/test_nessun_build_in_place.py`). E i residui superati corretti
  nel merito: le prove empiriche VIAGGIANO col bundle dal 0.43.x (il doc
  diceva il contrario), la cifratura del disco porta la traiettoria datata
  fino alla decisione `H56`, il consiglio di piattaforma è Debian 12 ovunque.

## [0.43.4] — 2026-08-27

**La prima release il cui contenuto è stato giudicato da una misura, non da chi
l'ha scritto**: il campione cieco del collaudo (46 messaggi, giudice l'owner) ha
bocciato due regole del voice-tagging e la taratura che ne esce porta il gold
come test di accettazione. Con lei: le tabelle admin che non sfondano più il
riquadro, e la prova-6 che per la prima volta può dare un PASS pieno.

### 🐛 Fix

- **`classify_voice` tarata sul golden set** (#221). La prima misura vera —
  campione cieco, 37 giudizi confidenti — dava accordo 20/37 con due difetti
  strutturali: `character` decisa dal solo NOME del progetto (0/8, con 4 own
  veri marcati «personaggio»: i falsi che il principio vieta) e `pasted_ai`
  mai emessa contro 8 casi veri, perché la regola assumeva AI=inglese in un
  corpus dove le AI scrivono italiano. Ora `character` vuole il progetto **e**
  la recitazione nel testo; `pasted_ai` riconosce i tick di automazione e i
  prompt-template italiani («Sei un…», «Ruolo:», heading+elenchi — anche con
  le newline collassate in doppi spazi da uno degli ingest). Dopo: 30/37,
  falsi cari 0, own 21/21. Il gold è il test di accettazione
  (`tools/tests/test_voice_golden.py`, si arma dove l'archivio c'è). ⚠️ Le
  righe già classificate nei DB vivi restano col verdetto vecchio finché non
  si esegue `retag_voice` (Fase 4): il retag è un gesto esplicito, non un
  effetto della release.
- **Le tabelle larghe dell'admin scorrono nel proprio riquadro invece di
  sfondarlo** (#218) — il fix UI segnalato dall'owner al collaudo.

### 🧪 Prove

- **La prova-6 §③ misura invece di dichiarare** (#221, #222): dove il prodotto
  è in esercizio, il caso silenzioso del backup (mktemp + bind-mount sotto la
  sandbox proposta) viene ESEGUITO e giudicato in **dimensione del dump**, coi
  due versi — sotto la stretta proposta il dump ha contenuto, sotto
  `PrivateTmp=yes` esce il vuoto-con-rc-0 che la unit dichiara da mesi: quella
  riga ora è una misura. Due sonde corrette strada facendo, entrambe beccate
  da un banco: il mktemp fatto FUORI dalla sandbox rendeva la controprova
  cieca, e il glob sui volumi prendeva anche i volumi di prova del ciclo
  backup→restore in CI (la fase-b l'ha marcato «PASS senza il sistema sotto»);
  ora il volume si sceglie dai Mounts dei container in esecuzione.

### 📖 Documentazione

- Il **verbale del primo collaudo vergine** (#219, #220): quattro fasi con
  numeri — 6 verifiche/6 verdi, quadratura archivio 10/10 per sha256, campione
  cieco con esiti per classe — e il golden-set dichiarato fuori dal repo con
  la ragione (porta giudizi su messaggi privati).

## [0.43.3] — 2026-08-27

**Il resto del raccolto del collaudo vergine** — la 0.43.2 curava il bottone;
qui arrivano la card update che non si fa oscurare, l'installer che allestisce
da solo la chiave dei backup, e la doc che ha imparato gli intoppi veri.

### 🐛 Fix

- **La card Update non nasconde più un aggiornamento noto quando il «Ricontrolla
  adesso» fallisce** (#212, `H70`). Il refresh dal gateway fallisce *per
  progetto* (senza egress da `H50`), ma il suo ramo d'errore scriveva
  `error`+`checked_at=now` sopra il verdetto del check host: il bottone update
  spariva con un «0.43.1 → 0.43.2» fresco e valido nel file, e il check mai
  avvenuto ri-datava l'anti-stantio. Ora il fallimento scrive i SUOI campi
  (`refresh_error`/`_at`) e il verdetto resta del check host. Il ramo era nato
  in `v0.39.1` col gateway ancora connesso; `H50` ha reso il fallimento
  sistematico e nessuno ha riletto quel ramo — misurato dal vivo al collaudo.

### ✨ Installazione

- **L'installer grafico allestisce da solo la chiave `age` dei backup** (#214),
  come `deploy.sh` già faceva — la classe «la cura in una via» a parti
  invertite rispetto a `#208`, trovata dal primo `vps1777 update` fermo
  fail-safe sul backup. La coppia nasce **sul PC** (`age-keygen` se c'è,
  altrimenti fallback Python X25519+bech32 provato contro un golden vector di
  `age-keygen` vero), condivide il file di `deploy.sh`, sulla VPS va solo la
  pubblica — e prima di dichiararla buona la giudica `age` sulla VPS con un
  round-trip: se rifiutata viene rimossa, rumorosamente.

### 📖 Documentazione

- Gli **intoppi reali del primo collaudo su macchina vergine** (#213, #211,
  #212): cache DNS negativa sull'URL `ts.net` appena nato, connector claude.ai
  doppiamente morti dopo un format, «Autorizza» muto su Chrome fino alla
  0.43.1, recipient age da rimettere — in TROUBLESHOOTING, ONBOARDING e nel
  runbook `COLLAUDO-VERGINE`. Registro: `H69` chiusa col bottone vero
  (l'owner, da Chrome, sulla 0.43.2 in produzione), `H56` decisa (rischio
  accettato: dischi in chiaro, Debian 13+LUKS instabile), `H70` nuova.

## [0.43.2] — 2026-08-27

**Il primo fix nato dal collaudo su macchina vergine che serviva una release per
arrivare in produzione** (i primi due, #208 e #209, vivevano nei sorgenti che si
scaricano da `main`; questo vive nell'immagine del gateway).

### 🐛 Fix

- **La consent OAuth non blocca più il redirect post-«Autorizza» su Chrome** (#211,
  `H69`). `form-action 'self'` — la CSP di `_layout`, giusta per l'admin — viene
  applicata da Chrome **anche al 302 che segue il submit**: il POST `/authorize`
  rispondeva col redirect verso il client e Chrome lo uccideva in silenzio; il
  bottone «non faceva nulla», unico segno in console. La consent page ora allarga
  `form-action` all'**origin del `redirect_uri` già validato** contro i client
  registrati — mai un jolly, solo su quella pagina. Il ramo era in produzione dalla
  `0.33.0` senza che nessun client l'avesse mai attraversato: i connettori
  esistenti giravano su token emessi *prima* della consent, e solo l'azzeramento
  vero del format l'ha esercitato. Test con prova a contrario (rosso senza fix);
  voce `H69` nel registro con evidence verificate dal gate.

## [0.43.1] — 2026-08-22

**La release che allinea `latest` allo stato dell'arte prima del collaudo su macchina
vergine.** Nessuna feature nuova: performance, dipendenze e il runbook che mancava.

### ⚡ Performance

- **Connessioni SQLite persistenti per-thread in `_open()`** (#204). Ogni chiamata ai 13
  tool apriva e chiudeva la propria connessione; ora una cache per-thread la riusa, con
  due scelte che valgono più del risparmio: la cache si **invalida sulla firma della dir
  DB** (un DB rigenerato è un file nuovo — una connessione sul vecchio inode risponderebbe
  con i dati di prima, *senza errore*), e il `close()` dei nove chiamanti resta scritto ma
  è **no-op documentato** — toglierlo avrebbe funzionato oggi e si sarebbe rotto alla
  prima riscrittura di un chiamante. 216 righe di test, anche stdlib-only.

### 📦 Dipendenze

- Bump del gruppo python-runtime nei tre servizi (#203, dependabot): `pyproject` +
  `uv.lock` di gateway, archive-mcp, nb1777-mcp.

### 📖 Documentazione

- **`docs/COLLAUDO-VERGINE.md`**: il runbook del test definitivo su VPS formattata —
  l'ordine deciso il 02/08 (format → install → verifiche → re-ingest → campione cieco)
  con una verifica mirata **per cura** (fail2ban #200, unit da `VPS1777_FEATURES`,
  auto-update #101/#104/#125, self-update CLI, reboot-survival, connector) e l'esito
  atteso accanto a ogni comando. *Il criterio è quello della 0.43.0: rileggere lo stato
  dell'oggetto, mai fidarsi dell'exit 0 di chi lo attiva.*

## [0.43.0] — 2026-08-17

**Nove commit, e cinque toccano ciò che la macchina fa quando NASCE.** Non è una scelta
editoriale: `setup.sh` installa da `releases/latest`, quindi finché questa release non
esiste, **una VPS reinstallata riparte con i difetti che sono già curati in `main`** — il
più grave dei quali è stato misurato sulla macchina viva, non ipotizzato.

> **Il filo:** *un comando che attiva non è la prova che una cosa sia attiva.* `systemctl
> enable --now fail2ban` esce **0** anche se il servizio muore un istante dopo, e
> l'installer stampava «Hardening host attivo» mentre ssh era pubblico e senza
> anti-brute-force. **La prova è rileggere lo stato dell'oggetto** — ed è la stessa forma
> che in questa release ricompare su tre livelli diversi: un servizio, un preflight, una
> frase di documentazione.

### 🛡️ Sicurezza — quello che una macchina appena installata si porta dietro

- **`fail2ban` partiva e moriva subito su Debian 12** (#200). Misurato sulla VPS viva:
  `Have not found any log file for sshd jail`, `status=255`, **al boot di quattro settimane
  prima** — cioè mai ripartito, mentre `ss -ltn` mostrava `LISTEN 0.0.0.0:22`. La causa non
  è un guasto: su Debian 12 i log di sshd stanno **solo nel journal**, `/var/log/auth.log`
  non esiste, e la jail di default cerca un file. *La configurazione non è invecchiata: non
  è mai stata adatta alla distribuzione che installiamo.* Ora `jail.local` con
  `backend = systemd` **e** un `is-active --quiet` dopo l'enable, in **tutti e tre** gli
  installer — perché da sole le due cure non bastano.
- **Il gateway non monta più il token del bot, ma la chiave derivata** (#194; la issue #61 è stata chiusa dal suo merge il 16/08).
  Per verificare l'`initData` serve `HMAC_SHA256("WebAppData", token)`, non il token: la
  strada era nel codice dal 27/07, mancava solo che qualcuno gliela desse. Il bot il token
  ce l'ha ancora, e deve — *gli serve per parlare*. `assicura_webapp_secret()` deriva il
  secret prima di ogni `up`, così la migrazione non lascia un compose che non parte.

### 🧱 L'installazione — il verso in cui si muore conta

- **Il preflight verificava il nome `python3`, non la capacità di calcolare bcrypt** (#193).
  Su Debian/Ubuntu `python3` e `python3-pip` sono **due pacchetti distinti**, quindi
  `command -v python3` passava su macchine dove quel comando sarebbe morto — e moriva
  **dopo** aver scritto `.env` e tre secret, cioè **a metà installazione**. *Il requisito
  vero non era il nome del comando: era ciò che il comando deve saper fare.*

### 🔍 I presìdi che ora girano davvero

- **Il ciclo backup → restore viene ESEGUITO** (#196). Nessun test lo faceva: i tre che
  nominano `restore.sh` lo leggevano con `read_text()`. Ora il test fa il giro intero —
  backup, cifratura `age`, svuotamento, restore, **confronto sha256 dei byte ripristinati**
  — in un albero isolato, perché `restore.sh` fa un `docker compose down` incondizionato.
  *Una prova a mano non lascia un presidio.*
- **Le coordinate `file:riga` nei documenti devono puntare dentro il file** (#198). Nasce
  da un caso vero (`SECURITY.md` mandava a una riga dove c'era un'altra funzione) e su un
  difetto **già curato**: 27 coordinate, zero fuori. *Una coordinata sbagliata non rompe
  niente — manda solo la persona sbagliata nel posto sbagliato, e non se ne accorge nessuno.*

### ⚡ Prestazioni

- **Connessioni SQLite persistenti per-thread in `archive-mcp`** (#197). I nove chiamanti di
  `_open()` aprivano una connessione per chiamata e per DB. Misurato su 300 iterazioni:
  **0,305 → 0,039 ms** sul DB in chiaro (7,7×) e **229 → 0,071 ms** su quello cifrato
  (3227×). *Il 7,7× da solo non giustificherebbe il diff: lo giustifica la cifratura* —
  è il prerequisito, non l'ottimizzazione.

### 📝 Quando è la PROSA a mentire

- **«La cura non è stata presa» era falsa alla nascita** (#199). L'unit dell'auto-update
  elencava due opzioni «non prese»: **la (A) era stata presa il 03/08**, nello stesso file,
  dodici giorni prima che la frase venisse scritta. Costo misurato: **due sessioni di fila**
  hanno concluso «il format non ripara l'auto-update», e la conclusione sbagliata è arrivata
  a @Neo come decisione da prendere — *quando la decisione era già stata presa*. La frase
  ora è **datata col commit che l'ha prodotta**; la tabella della misura resta, perché
  quella non scade.
- **L'avviso di collasso di `archive-mcp` nominava i caratteri sbagliati** (#201). Su `.NET`
  diceva «il tokenizer non indicizza `+` e `#`», ma a sparire è **il punto**: *giusto nel
  verdetto, sbagliato nella causa — e un avviso così manda a cercare il difetto dove non è.*
  I caratteri ora si **derivano dal termine**, come già faceva il meccanismo sotto:
  l'elenco a mano era l'unica parte che ne sapeva meno del meccanismo, e stava esattamente
  nel punto in cui qualcuno si fida.

### 📐 Disegno (proposta, non prodotto)

- **Il disegno della cifratura dell'archivio** (#195): cosa è misurato, cosa è stimato, e le
  tre domande ancora aperte. Dice per primo il limite che nessuna cifratura supera — *la VPS
  è affittata, e il provider vede la RAM di una VM accesa.*

## [0.42.0] — 2026-08-16

**Sessantatré commit in una settimana, e quasi nessuno aggiunge una funzione: quasi tutti
rendono ESEGUIBILE una garanzia che era già scritta.** La `0.41.2` chiudeva un difetto di
dipendenze; questa chiude una classe intera, ed è la stessa in quattro travestimenti —
`H65` «ogni action pinnata a SHA», `H66` sulle immagini di terzi, `H67` «il gateway non
tocca mai Docker», `H68` «secrets sempre file-mounted, mai in env var». Tutte e quattro
erano **vere**. Nessuna delle quattro era **tenuta da un test**.

> **Il filo:** *una garanzia scritta e non presidiata non è una garanzia — è una promessa
> che nessuno ha smesso di mantenere per caso.* E il suo gemello, che è peggio perché
> somiglia al successo: **un presidio che nessuno esegue non fallisce mai.** Tre test `.py`
> erano in git e non giravano in CI; il pre-commit con l'anti-leak non era versionato; il
> gate `contract` era diventato fail-open in una PR precedente e taceva invece di bloccare.

### 🛡️ Sicurezza — le garanzie che ora qualcuno tiene

- **Il gate dei segreti non vedeva i token Telegram VERI** (#185). Il pattern usava una
  lunghezza **esatta** (`{35}`) su un formato di terze parti, e l'esempio ufficiale della
  documentazione ne ha 34: rispondeva «pulito» sui token veri e sporco solo su quelli
  inventati per la prova. *Su una credenziale altrui la lunghezza non si promette.*
- **`H67` — «il gateway non tocca mai Docker» era presidiata su UN path** (#147), e il
  socket ha **due nomi per lo stesso inode**. Il perimetro ora è verificato su tutti i
  compose, non su un file (#131).
- **`H68` — «secrets sempre file-mounted, mai in env var»** (#153): vera, e nessun test la
  teneva. Ora sì.
- **`H65` e `H66`** (#143, #144, #145): action pinnate a SHA e immagini di terzi
  digest-pinnate, con i test che lo mantengono vero nel tempo.
- **Tetto assoluto sul body in Caddy** (#122), col margine misurato — 672 MiB, non 1 GB
  (#123) — e i due tetti che non possono più scavalcarsi.
- **`H15`/`H38`: i `chmod` dichiaravano riuscito ciò che sopprimevano** (#138), su sette
  punti e non tre.
- **Il download da NotebookLM non sceglie più dove scrivere** (#129, #130): era una
  scrittura arbitraria, ora passa da un endpoint interno e da un ponte admin.

### 🔍 I presìdi che non giravano — e il gate della classe

- **Tre test `.py` erano in git e NON in CI** (#136), più il gate che impedisce alla
  classe di ripetersi.
- **Ogni autoprova dichiarata dev'essere eseguita da un workflow** (#188): quattro presìdi
  autoprovanti erano agganciati *perché qualcuno se n'era ricordato quattro volte*.
- **`setup.sh` viene ESEGUITO, non solo letto** (#191). Cinque test lo nominavano e tutti e
  cinque lo leggevano come sorgente: **lo script che installa il prodotto era l'unico pezzo
  del prodotto che nessuno eseguiva**, e il primo a trovarlo rotto sarebbe stato chi installa
  da zero — cioè chi ha meno modo di capire cos'è andato storto. *La #165 aveva reso `setup.sh`
  pilotabile da variabili e nessuno era entrato dalla porta che aveva aperto: fra «adesso si
  può fare» e «adesso è fatto» non c'è nessun automatismo, e la distanza non la segnala niente.*
- **Il gate `contract` non può più tacere quando non ha potuto guardare** (#184): la #182
  l'aveva reso fail-open. *«Non ho potuto controllare» e «ho controllato ed è a posto» non
  sono lo stesso fatto.*
- **Il pre-commit con l'anti-leak non era in git** (#150) — e il suo unico ramo d'errore
  moriva invece di parlare.
- **Le nove prove empiriche entrano in CI senza il sistema sotto** (#187): un runner *è*
  una macchina nuda, quindi la fase (b) del collaudo FORMAT — *nessuna prova deve dichiarare
  un PASS quando non ha guardato niente* — si esegue a ogni PR, gratis.
- **La whitelist sudoers deve coprire i comandi che la CLI eleva** (#135), che erano due
  liste in tre file e nessuno le teneva allineate.

### 🛠️ Strumenti che dicono PERCHÉ, invece di un verdetto secco

- **`branch-verdetto`**: dice perché (#161), distingue una riga fuori da `main` che è il suo
  **passato** (#181), e non dà più il verdetto HA-LAVORO ai branch di sola prosa (#175, #177).
- **«Questo branch si può cancellare?»** — quattro strumenti che mentivano, sostituiti da uno
  che non lo fa (#159).
- **Le prove empiriche dicono perché una prova non è eseguibile** invece di lasciarlo
  indovinare (#186), e `--fase` tiene separate le tre foto del collaudo del format (#167).
- **L'indicizzazione distingue letti / scritti / deduplicati** (#180, chiude #55): prima un
  totale solo, che rispondeva a una domanda diversa da quella che sembrava.
- **`doc-riferimenti`**: i file che i documenti nominano esistono ancora? (#162, in CI).

### 💾 Backup, restore, aggiornamento

- **La ritenzione ha l'asse VERSIONI accanto a quello a tempo** (#169, #178), via sidecar in
  chiaro accanto all'archivio cifrato.
- **I volumi si CHIEDONO a `docker compose`** (#146): due del compose base non erano salvati.
- **`restore.sh` non esce più 2 su un restore RIUSCITO** quando manca `.env` (#163) — e
  l'auto-rollback ci si fidava.
- **La regola polkit per `daemon-reload`** (#125), l'anello mancante della via B.
- **`setup.sh` ha un contratto non-interattivo, e il primo test che lo ESEGUE** (#165).

### 📄 Documentazione — quando il testo diceva un'altra cosa del codice

- **L'URL del clone in `INSTALL.md` e `BACKUP-RESTORE.md` era un placeholder mai riempito**
  (#190): chi lo seguiva alla lettera falliva al primo comando.
- **La premessa del «segreto in chiaro» non descrive più il sistema** (#189, rif #61): era
  «una macchina piccola», e oggi il compose orchestra quattro servizi. *A scadere è la
  premessa, non la scelta.*
- **`«chiude la #N» non chiude la #N`** (#137): GitHub legge solo l'inglese, e tre issue
  erano rimaste aperte annunciando di essere chiuse.
- I secret sono **cinque**, `INSTALL.md` ne elencava quattro (#166); «`nlm-auth` lo monta
  SOLO `nb1777-mcp`» — a montarlo sono in quattro (#140); «byte» scritto per «caratteri»,
  che sovrastimava l'entropia dichiarata (#168).
- **`SECURITY.md`: la garanzia «solo la 443 via tunnel» ora nomina il fallback che la
  sospende** (#133, chiude #70), e `INGRESS.md` dice anche **chi** può raggiungere il
  servizio (#134, chiude #63).

### ⚠️ Noto e dichiarato

- **`systemd`: la riga della #101 NON ripara il guasto** (#155) — il commento prometteva il
  contrario. Resta come dichiarazione d'intento, e la cura è una scelta di progetto non
  ancora presa: togliere le direttive seccomp dalle unit che elevano, oppure non usare
  `sudo` nel self-update.
- **La cifratura at-rest dell'archivio non esiste**: il `.db` sta in chiaro sul disco, e
  `redazione.py` lo dichiara di sé. La redazione è in **uscita** — l'upload carica tutto,
  come richiesto. Decisione presa il 16/08, implementazione da fare.

## [0.41.2] — 2026-08-09

**Una patch tagliata per un motivo solo: la `0.41.1` non si avvia.** `archive-mcp` muore
all'import — `from mcp.server.fastmcp import FastMCP`, un path che in `mcp==2.0.0` non
esiste più — e il processo non arriva a toccare un dato: restart-loop → health-gate →
auto-rollback. Il vincolo era **identico** nella `0.40.14` (`mcp>=1.2.0`, senza tetto):
non è cambiato il vincolo, è cambiato **quando viene risolto**. Prima si risolveva a
build-time e la `2.0.0` non era ancora uscita; dalla `0.41.0` c'è il lock, generato
quando la `2.0.0` era già fuori — e ora viene riprodotto fedele.

> **Il filo:** *un lock garantisce riproducibilità, non correttezza — riproduce
> fedelmente anche una major sbagliata.* Prima era una lotteria, e finora aveva vinto.
> Le voci qui sotto sono la cura, più i presìdi che d'ora in poi guardano l'artefatto
> invece del suo sostituto.

### 🔴 Corretto — la dipendenza che impediva l'avvio

- **Tetto alla major di `mcp`: `>=1.28,<2`** (#112). Nei due servizi che lo importano
  (`archive-mcp`, `nb1777-mcp`) e nei lock. `archive-mcp` risale da `2.0.0` a `1.29.0`,
  e con lui escono `httpx2`, `httpcore2`, `mcp-types`, `opentelemetry-api`, `truststore`.
- **Lo stesso tetto in `plugins/example-mcp`** (#113), che ne era rimasto fuori — cioè
  **il posto da cui si copia**. Non ha un lock, quindi risolve a build-time: oggi
  avrebbe preso la `2.0.0` e sarebbe stato rotto per chiunque lo usi come punto di
  partenza. Il primo censimento iterava una lista di nomi scritta a mano e aveva curato
  due su tre; *un insieme enumerato a mano non fallisce quando è incompleto — risponde,
  e sembra una risposta.*

- **Il tetto sul body conta i byte veri, non quelli dichiarati** (#119). `admin.py`
  guardava il `Content-Length` — che lo dichiara il client: chi vuole riempire il disco lo
  omette (chunked) o ci scrive un numero piccolo. Il taglio che contava i byte veri partiva
  quando `upload.file` era **già pieno**: proteggeva la destinazione, non l'arrivo.
- **Tetto a `httpx`: `>=0.28,<1`** (#118), su `gateway` e `nb1777-bot` — le sole due che lo
  dichiarano. Oggi non c'è deriva (lock `0.28.1`, che è l'ultima stabile), ma su PyPI ci
  sono già le `1.0.dev*`: senza tetto, la prima rigenerazione di lock dopo il rilascio se la
  porterebbe dentro senza che nessuno lo decida.

### 🛡️ Presìdi — la CI ora guarda l'artefatto, non un suo sostituto

- **La build avvia ciò che costruisce** (#114). Il job `build` costruiva l'immagine e
  non la eseguiva mai; i test giravano con `uvx pytest`, in un ambiente effimero che non
  è quello dell'immagine (che installa dal lock, con `--frozen`). CI e artefatto
  guardavano due mondi diversi, e il verde certificava il primo. Ora un container che non
  parte rompe la CI.
- **Il gate importa il punto di ingresso, non il luogo dell'ultimo incidente** (#115).
  La prima versione importava `app.server` — il modulo dove il difetto si era
  manifestato — ma l'entrypoint delle quattro immagini è `python -m app`: il modulo che
  il container **esegue** è `app.__main__`, e nessuno lo importava. Restava scoperto
  `import uvicorn`, che esiste in un solo posto in tutto il repo.
- **La garanzia «IP client non spoofabile» ora la misura la CI** (#117), non più solo la
  documentazione: sei test, incluso il caso in cui l'header arriva già riscritto a monte.
- **Il verificatore delle regole non installa più «l'ultima versione» di ciò che le
  legge** (#111). `verify-features.yml` ancorava `actions/checkout` a uno SHA e due righe
  sotto faceva `pip install pyyaml` senza versione né hash — cioè l'unica dipendenza del
  programma che valida il ledger delle feature. Ora `--require-hashes`.
- **Il gate locale esegue gli step della CI leggendoli dal workflow** (#93), invece di
  riscriverli: due copie di una procedura sono una cache, e una cache scade in silenzio.

- **Un tetto committato senza rigenerare il lock non è più verde** (#118). `uv sync
  --frozen` fa quel che promette — usa il lock com'è — e **non** verifica la coerenza col
  `pyproject`: si poteva committare un vincolo puramente cosmetico e vederlo passare. Ora
  `uv lock --check` gira su tutti i servizi, e la lista dei servizi **la dà `git ls-files`**,
  non un elenco scritto a mano (un quinto servizio, in quel caso, sarebbe stato silenzio).
  Il gate **dichiara il proprio limite**: verifica l'accordo lock↔pyproject *dentro* un
  servizio, quindi due gemelli con lo stesso `pyproject` e lock diversi restano entrambi
  verdi. *Un limite scritto è un limite che il prossimo non deve riscoprire.*

### 📚 Documentazione

- **Gli `-f` dell'overlay ingress non sono facoltativi** (#116). In nove punti la
  documentazione scriveva `docker compose --profile ingress.<x> up -d` senza `-f`: misurato
  col diff delle due config, senza gli `-f` il gateway resta **senza porte pubblicate** e
  fuori dalla rete `funnel`. Chi seguiva la riga alla lettera otteneva un ingress che non
  ingressa.

### ⚠️ Note per chi aggiorna

- Se sei sulla `0.41.0` o `0.41.1` e l'aggiornamento è tornato indietro da solo, **è
  questo il motivo**: l'auto-rollback ha funzionato: non hai perso dati, il servizio è
  rimasto sulla versione precedente.
- I lock dei due gemelli restano su versioni `mcp` diverse (`archive-mcp` 1.29.0,
  `nb1777-mcp` 1.28.1): **entrambe dentro il tetto**, nessuna delle due rotta. È il
  risultato meccanico della cura — `uv lock` non muove ciò che è già conforme — e
  l'allineamento è un atto separato, da fare guardando il diff.

## [0.41.1] — 2026-08-03

**Una patch tagliata per un motivo solo: la `0.41.0` non poteva installarsi da sola.**
Il canale di auto-update era rotto — le unit `update` e `auto-update` giravano con `User=`
non-root e sei direttive di sandboxing, e systemd in quella combinazione accende
`NoNewPrivileges` **implicitamente**: `sudo -n install` falliva, e l'aggiornamento moriva
prima di installarsi. La `0.41.0` conteneva il guasto; questa lo toglie e aggiunge il
controllo che impedisce a un bundle futuro di rimetterlo.

> **Il filo:** *un presidio che parla si elude — quello che blocca protegge.* Quasi ogni
> voce qui sotto è un controllo che diceva la cosa giusta con la scala sbagliata.

### 🔴 Corretto — il canale di aggiornamento

- **`update.service` e `auto-update.service` non portano più sandboxing** (#104). Con
  `User=` non-root basta **una** direttiva seccomp perché systemd accenda `NoNewPrivs`:
  misurato sulla macchina, non dedotto. Costo dichiarato nella voce `H43`
  (`systemd-analyze security` 8.0 → 9.2 su ciascuna) — la rinuncia è scritta, non taciuta.
- **Un bundle non può più annullare una cura già sul disco** (#109). Prima del
  self-update, `vps1777 update` confronta le unit in arrivo con quelle installate e si
  ferma se il pacchetto **rimetterebbe** il sandboxing su una unit che dichiara di elevare.
  *Serviva perché la cura è entrata in `main` dopo che la `0.41.0` era già tagliata: senza
  questo controllo, premere «aggiorna» avrebbe cancellato la riparazione in silenzio.*
- **Se una unit fallisce, ora si sa** (#100, #99): `OnFailure=` + `avvisa-fallimento`, e un
  comando che esce ≠ 0 lo dice invece di tacere. *L'auto-update era fallito alle 04:32 del
  03/08 e nessuno se n'era accorto fino a sera.*

### 🛡️ Presìdi che prima guardavano la riga sbagliata

- **Le unit che elevano non possono portare sandboxing** (#105) — il test precedente
  chiedeva che `NoNewPrivileges` fosse *dichiarato*, e dava verde sulla unit con cui la
  macchina è morta. Ora la regola è sulla **combinazione**, con allowlist vuota (fail-closed).
- **I tre installer abilitano le stesse unit** (#106) — la lista si **esegue** estraendola
  dai tre file, non si confronta come testo. Chiude la divergenza che nel fix #13 aveva
  lasciato `secrets-check.timer` scoperto su un percorso d'installazione su tre.
- **Tutti i test bash girano** (#91) — via l'elenco a mano, che dimenticava tre file su cinque.
- **Le dipendenze Python dei quattro servizi sono sorvegliate** (#95) e i lock entrano
  nella build (#96).

### 🧹 Altro

- Spazio disco verificato **prima** di scrivere l'upload (#88) e tetto controllato prima di
  leggere il body (#94); journal caldo visibile in `archive-mcp` (#89); cadenza dichiarata
  per `unattended-upgrades` (#90) e per `secrets-check` (#92); default vuoto dichiarato in
  `settings` (#98); il 404 dal proxy documentato come scelta (#83, già in 0.41.0).

### ⚠️ Se aggiorni una macchina installata con la `0.41.0` o precedente

L'auto-update **non può portarti qui da solo**: è il guasto che questa versione ripara. Serve
un aggiornamento manuale una volta sola — da terminale, non dal pulsante del pannello.

## [0.41.0] — 2026-08-03

**Tutto quello che è entrato dopo la `0.40.14` (27/07), e quasi tutto ha la stessa forma:
un controllo che non guardava, e un verde che lo copriva.** Non è un tema scelto — è quello che è emerso
auditando, ed è il motivo per cui questa è una `minor` e non una `patch`.

> **Il filo, in una riga:** *l'assenza di un segnale non è un segnale di assenza.* Un gate
> che esamina zero file e dice «tutto bene»; una prova che non trova l'oggetto da misurare
> ed esce `0`; un `if <dato> and <condizione>` dove il dato può mancare — e allora il ramo
> di rifiuto non viene mai preso. In tutti questi casi non c'è niente di rotto da vedere:
> il risultato è *pieno*, plausibile, e dice il contrario del vero.

### ⚠️ Se aggiorni una macchina già installata con `caddy` o `cloudflared`

**Il pannello smette di rispondere su `http://<IP>:8080`.** La porta si sposta sul loopback
(vedi sotto), e l'overlay di onboarding si riapplica a **ogni** deploy, non solo al primo:
quindi il cambio ti arriva col primo aggiornamento, non con una nuova installazione.

```
  la strada che resta, ed è quella giusta:   https://<il tuo dominio>/admin/setup
  se ti serve la porta com'era:              ONBOARDING_BIND=0.0.0.0  (col tradeoff sotto)
  se il pannello non risponde da nessuna
  delle due:                                 ssh -L 8080:127.0.0.1:8080 <utente>@<vps>
                                             poi http://127.0.0.1:8080/admin/setup
```

*Con il profilo `tailscale` non cambia niente: quell'overlay era già escluso, e la porta era
già sul loopback.*

🔑 **Lo scriviamo qui perché un fail-closed corretto può chiudere fuori chi stava entrando
dalla porta giusta di ieri.** Il difetto non è la cura: è scoprirla dal sintomo.

### Sicurezza — controlli che non scattavano

- **Il proxy MCP accettava qualunque token quando l'owner non era configurato.**
  `_check_bearer` era `if allowed and <sub> not in allowed`: con `OAUTH_ALLOWED_EMAILS`
  vuota la condizione è sempre falsa, il ramo di rifiuto non veniva mai preso e **ogni
  access token valido attraversava il proxy**. Ora è fail-closed, con `owner_not_configured`
  distinto da `subject_not_allowed` — due casi che si curano in modo opposto e nell'audit
  devono contarsi separatamente. Il precedente era già in casa: `miniapp_core.is_owner`
  ritorna `False` quando l'owner non c'è (*«se non sappiamo chi è l'owner, nessuno lo è»*).
- **L'anti-downgrade dell'update si spegneva se la nota di versione spariva.** `consume_intent`
  leggeva `update_status.json` e trattava «file assente», «illeggibile» e «campo vuoto» come
  un solo stato muto. Ora sono tre e ognuno rifiuta. E **c'era un percorso, dentro il
  gateway, che quel file se lo cancellava da solo**: `admin_update_check` scriveva
  `latest: ""` sopra la nota buona quando la risposta di GitHub non portava il `tag_name`.
- **Un intent senza nonce era riusabile all'infinito.** Non solo il replay non veniva
  rilevato: `if nonce:` saltava anche la registrazione, quindi non lasciava traccia.
- **La porta del pannello di setup restava aperta in chiaro, per sempre, su due profili
  d'ingresso su tre.** Il criterio che includeva l'override di onboarding non era «il setup
  è finito» ma «quale ingress hai scelto»: con `caddy` o `cloudflared` la `:8080` in HTTP
  restava su `0.0.0.0` a tempo indeterminato. Ora sta sul **loopback** (`ONBOARDING_BIND`
  per riaprirla, col tradeoff scritto) — e la porta non serviva ai due proxy, che
  raggiungono il gateway dalla rete Docker.
- **L'audit log accetta solo chiavi dichiarate** (allowlist, non rilevamento), e
  l'anagrafica non esce più verbatim verso un modello terzo (`H64`).
- **Chiusi**: `H53` (il perimetro del gate non è più un elenco scritto a mano) · `H55` (le
  unit systemd non si rendono più come root, su entrambi i percorsi) · `H58` · `H62` · `H63`
  · `H64`.
- **Avanzati, e restano `partial` — il registro lo dice e questa riga non lo contraddice**:
  `H5` (il push off-site resta all'owner: è una **scelta**, non un arretrato — ma «chiuso»
  direbbe che non c'è più niente da sapere) · `H52` (le garanzie di hardening sono
  certificate **per stringa e non per comportamento**: il gate cerca il testo nel file) ·
  `H54` (esiste lo **strumento** della migrazione alla chiave derivata; la migrazione no).
  🔑 *Questa distinzione è la stessa cosa di cui parla la release: `partial` scritto «chiuso»
  è un verde che non ha guardato — su un registro di sicurezza, e nel documento che qualcuno
  legge per decidere se fidarsi.*

### Presìdi che dicevano «verde» senza aver guardato

- Il **gate anti-leak** rispondeva «tutto bene» dopo aver esaminato **zero file**; e conosceva
  le credenziali altrui, non le nostre.
- **`/health?deep=1`** rispondeva `200` avendo sondato **zero** backend.
- **`trivy`**: uno scan *saltato* lasciava il workflow verde — e gira schedulato.
- **`secrets-status`**: verde su zero secret osservati.
- **Nove prove empiriche non eseguite** uscivano `0`, cioè «tutto a posto»: *il testo era
  onesto, il codice no*. Ora una corsa parziale non distrugge il quadro delle nove, e
  `prova-4` senza l'ancoraggio esterno esce `2` (non-eseguita) invece di `0`.
- **«Funnel HTTPS attivo»** veniva dichiarato senza aver toccato il Funnel — e la porta di
  fallback si chiudeva su quella dichiarazione.

### Contabilità dell'ingest e del registro

- **L'estrattore HTML di Telegram era l'unico a scartare in silenzio**: un messaggio senza
  id spariva col suo testo, e nessuno lo contava. Ora emette `_Skip` come gli altri, con
  gli scarti che non collassano fra loro.
- **Il ledger**: il matcher era una regex che passava su codice *commentato* (47 voci); il
  verso reale→dichiarato non guardava `tools/` (20 script su 24 invisibili); le verifiche
  `def X` ora leggono l'albero invece di cercare una stringa.
- **`SECURITY.md` dichiarava 56 voci e il registro ne aveva 63** — e il gate era verde.

### Aggiunto

- **voice-tagging**: separa *chi ha scritto* da *di chi è la voce*, e lo rende interrogabile.
  Quattro stati distinti (`''` non classificato · `unknown` · classificato · `ignoto`
  pre-migrazione), migrazioni idempotenti, FTS *external content* — nessun rebuild
  distruttivo sugli archivi vivi.
- **Presìdi nuovi**: il fail-closed dell'update (`prova-9`), un aggancio di collaudo che
  *può solo dire no* (health-gate), e i test sulla trust-list dell'`X-Forwarded-For`.

### Dichiarato, non risolto

- **La garanzia sull'`X-Forwarded-For` ha due gambe, e una non è nostra.** *«L'IP client non
  è più spoofabile»* poggia sul comportamento di `ProxyHeadersMiddleware` di uvicorn
  («cammina da destra»), che **è storicamente cambiato** — le versioni più vecchie leggevano
  da sinistra, cioè la parte che un client inietta. Il vincolo è `>=`, e uvicorn è `0.x`.
  La gamba nostra è presidiata da test; l'altra è **scritta in `docs/ARCHITECTURE.md`**, con
  la strada da cui ripartire se un giorno l'IP tornasse spoofabile senza che nessuno abbia
  toccato la configurazione.
- **L'installer non poteva distinguere «non c'è nessuna release» da «non ho potuto
  chiedere»**: ora sì, in tutti e tre gli installer, e un errore di rete **ferma**
  l'installazione invece di degradarla in silenzio a build locale — che non passa dalla
  verifica della firma.

## [0.40.14] — 2026-07-27

Il rilascio che chiude il **residuo dichiarato** del giro precedente: la copia di sicurezza
si scrive su un nome provvisorio e prende il nome definitivo solo quando è finita.

> **Perché non era stato fatto subito, ed è la parte che vale**: la modifica precedente
> toccava la *conservazione* delle copie, e volevo che andasse in produzione **da sola e
> misurabile**. Ci è andata, è stata misurata sulla macchina, e solo allora si è toccato
> il secondo pezzo. *Due cambiamenti insieme sullo stesso file avrebbero reso illeggibile
> quale dei due produceva quale effetto.*

### Corretto

- **Una copia interrotta non lascia più un file col nome giusto.** Prima si scriveva
  direttamente sul nome definitivo: un processo ucciso o uno spegnimento lasciavano un
  file **col nome buono e il contenuto a metà**, che la rotazione contava come la copia di
  quel giorno. Ora si scrive accanto, con un nome provvisorio, e si rinomina alla fine —
  la rinomina è **istantanea e indivisibile**, quindi il nome definitivo o non esiste o è
  un file completo. *Sparisce l'istante in cui poteva esistere una copia a metà.*
- **E i resti delle scritture morte vengono rimossi dicendolo.** Un resto pesa 2,5 GB, e
  non è spazzatura: è **la traccia di una copia mai completata**, cioè di una notte
  scoperta. Il messaggio lo dice invece di ripulire in silenzio.

*Residuo che resta, più stretto del precedente: i byte vengono spinti su disco prima della
rinomina, ma se lo strumento di sistema non accetta quel modo si prosegue senza — una copia
scritta vale più di una garanzia in più non ottenuta. In quel caso una mancanza di corrente
lascerebbe un file provvisorio, non una copia monca: il danno peggiora nel modo giusto.*

> ⚠️ **La 0.40.13 esiste come etichetta e non è mai stata pubblicata.** L'avevo marcata su
> un commit i cui controlli erano rossi — un controllo del registro che avevo lanciato in
> modo da non vederne l'esito. Il rilascio **si è fermato da solo**: il primo passo del
> processo verifica che i controlli del commit etichettato siano verdi, e ha rifiutato di
> pubblicare. Nessun pacchetto rotto è uscito. L'etichetta resta dov'è perché una regola
> del repository, giustamente, vieta di cancellarla — *questo contenuto è qui, sotto il
> numero successivo.*

## [0.40.12] — 2026-07-27

Il rilascio in cui **un controllo nato ieri impara a dire «non lo so»**. Una riga sola di
sostanza, e viene da una rilettura fatta lo stesso giorno in cui quel controllo è nato.

> **La cosa che vale più del fix**: il difetto colpiva esattamente il criterio che quel
> controllo si era dato da sé. *Un allarme che grida al lupo brucia la fiducia prima della
> volta in cui è vero* — e gridare «le tue copie di sicurezza sono sparite» per un
> problema di permessi fa quel danno per un'altra strada.

### Corretto

- **«Non riesco a leggere» non è «non c'è niente».** Il controllo sulla copertura delle
  copie, se la cartella non era leggibile, otteneva zero e lo trattava come una perdita:
  avrebbe mandato l'avviso più allarmante che sappia produrre — *«la finestra di
  ripristino si è accorciata: zero giorni»* — per un problema di permessi. *Su questa
  macchina non è un caso di scuola: la stessa forma, permessi fra utente e
  amministratore, ha fermato un aggiornamento vero la mattina del 27 luglio.*
  Ora distingue **tre** stati: non misurato, misurato e vuoto, N giorni. Sul non misurato
  non allarma e non tocca la memoria di quanto copriva prima — **dichiara di essere
  cieco**, che è un'altra cosa e va saputa lo stesso.

## [0.40.11] — 2026-07-27

Il rilascio in cui **due regole scritte diventano controlli**. Nessuna funzione nuova per
chi usa il servizio: due cose che il progetto prometteva a parole e che nessun controllo
faceva rispettare.

> **La cosa che vale più dei due fix**: entrambi i controlli, la prima volta che sono
> stati eseguiti, hanno trovato un difetto **in sé stessi**. Uno era verde per costruzione
> — non poteva diventare rosso nemmeno volendo. *Un controllo che non si è mai visto
> fallire non è un controllo: è una riga di log con la faccia seria.*

### Corretto

- **La finestra di ripristino si accorciava in silenzio.** Lo script dei backup chiudeva
  dicendo «copie totali mantenute: 7» — un **conteggio**, mentre la promessa che quello
  script mantiene è in **giorni**. Il 27 luglio ha detto «7» quando i giorni erano tre, e
  poi ancora «7» quando erano due: non ha mai mentito e non ha mai detto niente. Ora dice
  **quanti giorni distinti** copre e da quando a quando, e avvisa se sono meno di sette
  spiegando come leggerlo.
- **E quel numero adesso lo guarda qualcuno.** Anche scritta giusta, quella riga finisce
  in un file di log dentro un container che nessuno apre. Il controllo giornaliero — lo
  stesso che già ogni giorno verifica se il servizio risponde — ora guarda anche la
  copertura e **avvisa su Telegram**. 🔑 Avvisa di una **regressione**, non di una finestra
  non ancora piena: dopo un'installazione nuova la copertura è 1, poi 2, poi 3, ed è
  normale — *un allarme che suona quando va tutto bene viene messo a tacere prima di
  servire davvero*. Quello che non è mai normale è che scenda sotto il massimo già
  raggiunto, perché a regime le copie si sostituiscono, non si perdono.
- **Un indirizzo pubblico nel repo, e nessun controllo che lo impedisse.** La regola era
  scritta — nessun indirizzo o nome della macchina, in nessuna forma, nemmeno in un
  esempio — e la applicavamo a mano. Un indirizzo è entrato dentro una nota che
  documentava una misura ed è rimasto visibile per otto ore. *Non è la macchina né la sua
  rete privata: è un ingresso pubblico e condiviso, e non dà accesso a niente.* Ora
  indirizzi pubblici e nomi di rete reali **fanno fallire la build**, con le esclusioni
  giuste: reti private, indirizzi nati apposta per la documentazione, e i bersagli di test
  dichiarati **uno per uno col perché** — *un controllo che grida al lupo viene spento.*

### Aggiunto

- **Il controllo sui backup ora si può provare**: `bash tools/backup.sh --prune-only`
  applica la rotazione senza scrivere 2,5 GB. Nove casi a risposta nota, e i tre nuovi
  presidiano il rendiconto — compreso quello che inganna il conteggio: sette file di un
  solo giorno.
- **Undici casi per il controllo sugli indirizzi**, metà dei quali contro i *falsi* rossi:
  un numero di sezione di una specifica (`§4.1.2.1`) somiglia a un indirizzo, e la
  dimensione di un file scritta all'italiana pure.

### Verificato

- Il controllo sugli indirizzi ora guarda anche i file **nuovi**, non solo quelli già
  registrati: prima rispondeva sul repo com'è invece che su come sta per diventare.
- Le esenzioni sono **per regola** e non più per file: un file esentato perché parla dei
  segreti non è più esentato anche dal resto. *Era esattamente il motivo per cui
  l'indirizzo è potuto restare dov'era.*

## [0.40.10] — 2026-07-27

Il rilascio in cui **le copie di sicurezza smettono di perdere giorni**. Nessuna
funzione nuova per chi usa il servizio: la macchina teneva sette copie e copriva tre
giorni, e nessuno poteva accorgersene perché il conteggio tornava.

> **La cosa che vale più del fix**: la finestra di ripristino si accorciava proprio nel
> giorno in cui qualcosa si rompeva. Ogni aggiornamento fa la sua copia; il 27 luglio la
> macchina è stata aggiornata quattro volte in una mattina perché c'era un guasto, e
> quelle quattro copie hanno occupato quattro dei sette posti, cancellando le notti dal
> 20 al 24. *L'evento che consuma i posti è lo stesso che rende quelle copie necessarie.*

### Corretto

- **Sette copie non erano sette giorni.** La rotazione teneva gli ultimi sette *file* e
  la riga accanto prometteva «7 giornalieri»: due unità di misura con lo stesso nome, che
  coincidono finché arriva una copia per notte — cioè sempre, tranne nel giorno storto.
  Ora se ne tiene **una per giorno, la più recente, per sette giorni distinti**. Per il
  giorno in corso la più recente è quella fatta subito prima dell'ultimo aggiornamento,
  che è esattamente ciò che serve per tornare indietro. *Il secondo livello — una copia a
  settimana — non poteva rimediare: ha la stessa larghezza del primo, sette giorni,
  quindi non lo estende, lo ricopre.*
  **Il disco non cresce di un byte**: stessi sette posti, stessi ~18 GB. Tenerne di più
  non era la strada — su quella macchina le copie sono già il 69% del disco occupato.

- **Una copia interrotta restava lì e sembrava buona.** Se la scrittura si fermava a metà
  — disco pieno, processo ucciso — rimaneva un file col nome giusto e il contenuto
  troncato, e la rotazione lo contava come la copia di quel giorno. Ora viene rimosso se
  la scrittura non arriva in fondo. *Residuo dichiarato: contro uno spegnimento brutale
  servirebbe scrivere su un nome provvisorio e rinominare alla fine.*

- **Una guardia fissa a difesa di dati che crescono.** Prima di aggiornare si controllava
  di avere 5 GB liberi, e le due copie che quell'aggiornamento scrive ne occupano circa 5.
  Il difetto non era la cifra: era che fosse **una costante**. Il giorno in cui una copia
  peserà il doppio, quella soglia direbbe di sì a un'operazione che non ci sta — e
  sembrerebbe verde fino a quel giorno. Ora si calcola dalla copia più grande presente e
  cresce da sola. Il vecchio valore resta come minimo assoluto.

- **Il backup notturno non aveva nessuna guardia di spazio.** Ora la stima dalla copia
  precedente e, se non ci sta, **rifiuta di scrivere invece di fallire a metà**. Al primo
  giro non c'è nulla da cui stimare e lo dichiara, invece di inventare una soglia.

### Aggiunto

- **Il primo controllo automatico sulla rotazione**, su sei casi costruiti di cui la
  risposta si conosce prima di eseguirli — compresi quelli che deve *lasciar passare*.
  Due dei sei hanno trovato difetti che nessuno cercava: su cartella vuota lo script
  usciva con un codice d'errore *dopo* aver finito il lavoro, e un nome di file
  illeggibile rubava davvero un posto alle copie vere. La rotazione è l'unico pezzo di
  vps1777 che cancella dati non rigenerabili, e fino a oggi non aveva una sola prova.
- `bash tools/backup.sh --prune-only` — applica la rotazione senza fare una copia nuova.
  È ciò che rende la rotazione provabile senza cifrare 2,5 GB.

### Verificato

- Due controlli non guardavano dove serviva: l'analizzatore degli script di shell non
  copriva la cartella dei test, e il lanciatore dei test Python non vede i file di shell —
  il nuovo controllo sulla rotazione sarebbe rimasto fermo sul disco con la build verde.
  Entrambi estesi.

## [0.40.9] — 2026-07-27

Il rilascio in cui **i controlli hanno controllato sé stessi**. Nessuna funzione nuova
per chi usa il servizio: quattro difetti nei controlli, e uno dei quattro nascondeva un
errore vero nella conservazione dei backup.

> **La cosa che vale più dei fix**: lo stesso controllo, eseguito in due posti, dava due
> verdetti diversi sullo stesso identico codice — verde qui, rosso nella build — perché
> «lo strumento X» non identifica uno strumento: identifica *una copia* di quello
> strumento, in *quel* posto, a *quella* versione. Ora è fissato per impronta, come tutto
> il resto.

### Corretto

- **Un controllo che approvava senza sapere.** Il passo che impedisce di modificare le
  migrazioni già pubblicate catturava il confronto con un «va bene comunque» in coda: se
  il confronto fosse fallito per un motivo vero, il risultato sarebbe stato vuoto e il
  passo avrebbe **approvato la modifica**. Ora, se non riesce a confrontare, si ferma e
  lo dice: *«non so dire se le migrazioni siano intatte, e "non lo so" non è "vanno
  bene"»*.
- **La soglia dell'analisi degli script abbassata al minimo** invece che alzata. Prima
  ignorava una categoria di segnalazioni *senza dire quali*; ora non tollera niente in
  silenzio, e le sette eccezioni che restano sono scritte nel codice una per una **col
  perché accanto**. *Una soglia alzata nasconde N cose e non dice quali; un'eccezione
  dichiarata è una cosa sola, con un nome e una ragione che il prossimo può contestare.*
  Fra queste, una era un difetto vero: una forma che *sembra* un se-allora-altrimenti e
  non lo è, nell'installer.
- **Lo strumento di analisi fissato per impronta.** Nella build era una versione, in
  locale un'altra, e le due davano verdetti diversi. Nessuna delle due sbagliava: erano
  due strumenti diversi con lo stesso nome, e niente lo diceva.
- **Il registro non si fida più di un commento.** Le sue prove cercano un testo dentro i
  file: se quel testo sopravviveva *solo in un commento*, la prova restava verde mentre
  il codice che doveva sorvegliare non c'era più — guardava la spiegazione, non la cosa.
  Verificato sul caso peggiore: cancellando una riga che protegge i cookie di Google e
  lasciandone il commento, prima passava, ora si ferma. Le prove che devono *davvero*
  vivere in un commento — quelle che tengono in vita una **ragione** — ora si dichiarano
  come tali.
- **Il ledger delle funzioni si accorgeva di ciò che nasce, non di ciò che cambia.**
  Quattro funzioni entrate oggi vivono dentro comandi e timer che esistevano già: non
  creando nulla di nuovo, erano invisibili al controllo automatico — ed è esattamente ciò
  per cui quel ledger esiste. Aggiunte; il buco resta scritto accanto a loro.

## [0.40.8] — 2026-07-27

Il rilascio che **porta gli strumenti dove servono**. Tre correzioni nate tutte dallo
stesso gesto — aggiornare davvero la macchina e guardare cosa succede, invece di
leggere il codice.

> La più istruttiva non è un fix ma una **cosa data per impossibile e misurata lo
> stesso**: il controllo che esce su Internet e rientra sembrava non potersi fare dalla
> macchina, perché la richiesta avrebbe girato su sé stessa. Misurata, esce davvero.
> *Un limite dedotto invece che misurato è un numero senza misura travestito da
> vincolo tecnico.*

### Dichiarato

- **La seconda metà di un rilievo che risultava chiuso** (`H56`). Prima di ogni
  aggiornamento la macchina prende una copia di sicurezza locale per poter tornare
  indietro. Una voce chiusa raccontava che da quella copia erano stati esclusi i cookie
  di Google: vero, ma era **un archivio su due**, e quello che resta è dodicimila volte
  più grande — circa 2,58 GB **in chiaro**, mentre gli stessi dati per l'altra strada
  viaggiano cifrati. *Il chiaro non è il difetto: quella copia serve al ripristino
  automatico, e cifrarla la renderebbe illeggibile proprio a chi deve usarla.* **Il
  difetto è che chi leggeva il registro concludeva che il problema fosse chiuso.**
  Misurato sulla macchina viva, non dedotto. La cura possibile — cifrare il disco — si
  fa sul disco e non nel codice: è una decisione di chi possiede la macchina.

### Aggiunto

- **Il controllo giornaliero esce su Internet e rientra** (`H51` c). Fino a ieri
  guardava la porta *sulla macchina*: con la porta viva e il tunnel pubblico caduto,
  per chi apre l'indirizzo il servizio è giù e nessun controllo lo direbbe. Ora la
  richiesta parte, esce davvero verso l'esterno e rientra dall'indirizzo pubblico.
  *Era stata data per impossibile — sembrava che dalla macchina la richiesta girasse
  su sé stessa: misurata, esce; la stessa richiesta all'indirizzo interno non
  risponde.* Provata sui tre esiti sulla macchina in produzione. **Non** entra nel
  cancello dell'aggiornamento, di proposito: quel cancello giudica ciò che
  l'aggiornamento può rompere, e un singhiozzo del tunnel farebbe tornare indietro
  una versione sana.

- **Le prove empiriche viaggiano col pacchetto** (`H51` d). Sono l'unico strumento che
  misura sul **sistema vivo** ciò che gli altri controlli verificano leggendo file — e
  restavano nel repo di sviluppo: sulla macchina andavano copiate a mano, quindi non
  c'erano. *Un controllo che per essere usato richiede un gesto manuale, nel giorno del
  guasto non esiste.* Settantadue kilobyte di script, nessuna dipendenza: il costo non
  era l'argomento.

### Corretto

- **Un aggiornamento non viene più abortito dal file che serve a raccontarlo**
  (`H55`). Il comando `vps1777 update` — quello che la documentazione consiglia —
  moriva a metà strada con un errore di programma se non riusciva a scrivere il file
  che i pannelli leggono per **disegnare la barra di avanzamento**. Trovato
  aggiornando davvero la macchina, non leggendo il codice: l'aggiornamento automatico
  gira con privilegi diversi da chi lancia il comando a mano, e lascia dietro un file
  che l'altro non può più riscrivere. **Rifiutarsi di installare qualcosa la cui firma
  non torna è giusto; rifiutarsi di riparare perché non si riesce a scriverne il
  resoconto non lo è.** Ora avvisa e prosegue — una volta sola, non a ogni passo — e
  quando può rimette il file nella disponibilità di chi userà il comando dopo.

## [0.40.7] — 2026-07-27

Il rilascio dei **controlli che non controllavano**. La `0.40.6` ha rimesso in piedi
il servizio; questa guarda i presìdi stessi e trova che alcuni non potevano vedere
ciò per cui esistevano — uno era verde per costruzione e nascondeva un difetto vero
nella conservazione dei backup.

> **La cosa più utile della giornata non è un fix, è una misura**: uno dei difetti
> che l'analisi esterna ha segnalato era **già scritto nel registro dal 4 luglio**,
> esatto, dentro un file che una pipeline controlla a ogni commit — e non era
> diventato codice per ventitré giorni, perché *nulla falliva se restava prosa*.
> Un audit che ri-scopre una tua nota «da fare» non ti dice una cosa nuova: ti
> misura quanto è vecchia.

### Aggiunto

- **Il servizio è controllato anche quando non si sta aggiornando nulla** (`H51` b).
  Il controllo che guarda la porta *da fuori* del container esisteva dalla `0.40.6`,
  ma girava solo durante un aggiornamento: un guasto arrivato in altro modo restava
  invisibile finché non apriva l'indirizzo una persona — che è precisamente com'è
  andata il 27 luglio, per un'ora e mezza. Ora la stessa domanda si fa **una volta al
  giorno**, dentro il controllo che già gira, e arriva un avviso quando il servizio
  smette di rispondere e un altro quando torna, **con la durata misurata fra i due
  istanti** — il numero che quel giorno nessuno aveva. Notifica i cambi di stato, non
  lo stato: un avviso che si ripete ogni giorno uguale si impara a ignorare.
- **La via d'emergenza `cosign` non si dimentica più da sola** (`H49` ③). Mettere
  `VPS1777_REQUIRE_COSIGN=0` nel `.env` sblocca una crisi ed è giusto che si possa
  fare — ma finora restava lì per sempre, riletta a ogni aggiornamento compreso
  quello automatico settimanale, e nessuno lo diceva. Ora il promemoria settimanale
  che già segnala i segreti da rinnovare segnala anche questa, con da quanti giorni
  è aperta, e la voce sparisce da sola appena la si toglie. **Non forza il ripristino
  della verifica**: la crisi che ti ha fatto aprire la via d'emergenza può durare più
  di un giorno, e richiuderla da soli ti chiuderebbe fuori mentre stai riparando.
  Era dichiarato nel registro dal 4 luglio come «da fare, non ancora implementato»:
  ventitré giorni di prosa esatta che non diventava codice perché nulla falliva se
  restava prosa.

### Corretto

- **Un difetto vero nella conservazione dei backup** (`H53`). Un file di backup col
  nome fuori formato non veniva scartato come previsto: si prendeva uno dei quattro
  posti riservati ai backup settimanali, buttandone fuori uno buono. Presente da
  sempre, e **segnalato dal primo giorno** dallo strumento di analisi degli script —
  che però in build girava con un pezzo in coda che ne buttava via il risultato.
- **Due controlli che non potevano fallire** (`H53`). Il passo che analizza gli script
  di shell era verde per costruzione; ora può diventare rosso, verificato rimettendo
  il difetto apposta. Il controllo di stile del Python guardava due percorsi su
  quattro: esteso a tutti, e fuori non c'era nulla di rotto — che è il motivo per cui
  la lacuna poteva durare tanto.
- **Il registro non poteva più dire di venire da una versione che non esiste.** Il
  campo che dichiara da quale versione vale ogni voce era l'unico che nessun
  controllo leggeva, e conteneva una versione mai rilasciata. Ora è verificato contro
  questo file. E ogni residuo dev'essere **nominato** in `SECURITY.md`, non solo
  contato: la tabella diceva dieci, il testo ne raccontava nove, e i conti tornavano.
- **Il file di test della CLI eseguiva 32 test su 39 quando lo si lanciava a mano**,
  uscendo `0`. I sette invisibili erano i più recenti. Corretto, e chiuso con un
  controllo che rilegge il file: se qualcuno ne aggiunge uno nel punto sbagliato,
  la build lo dice invece di tacere.
- **Il contratto dell'indicizzatore d'archivio copre i messaggi con contenuto
  dichiarato e vuoto**, la classe da cui veniva un divario di quasi settemila record.
  Il codice era già giusto: mancava il controllo che lo tiene giusto — e la fixture
  di prima passava verde sulla stessa regressione.
- **Il documento di sicurezza diceva una cosa non più vera** su sé stesso: sosteneva
  che il controllo della raggiungibilità «qualcuno deve lanciarlo» e che «lo stesso
  guasto passerebbe di nuovo». Falso dalla `0.40.6`. Il registro lo sapeva, il
  documento no, e nessun controllo poteva accorgersene — verifica che un rilievo sia
  *nominato*, non che la frase dica il vero.

### Dichiarato

- **Un rischio che il registro copriva solo di sponda** (`H54`). Il gateway monta
  cinque credenziali, e c'era una voce **chiusa** su questo terreno — ma chiudeva una
  lacuna *nella documentazione*, non il rischio: chi cercava cosa resta scoperto non
  trovava nulla. Misurato, il numero giusto è **uno, non cinque**: quattro di quelle
  credenziali sono del gateway stesso, e chi prende il gateway le ha già. Il token del
  bot no — quello serve a **parlare come il bot**, anche fuori da qui. Non è risolto:
  è scritto con lo stato che lo dice, perché la difesa possibile costa un pezzo in più
  da mantenere ed è un baratto che decide chi possiede la macchina.

## [0.40.6] — 2026-07-27

Rilascio di riparazione, e la parte che conta non è la riparazione. La `0.40.5`
chiudeva un buco reale e **ha reso il servizio irraggiungibile da Internet per
un'ora e ventotto minuti** — mentre tre controlli indipendenti davano verde.

> **Rettifica interna al rilascio**: la prima stesura di questa voce diceva «un'ora
> e quaranta». Il numero era **dedotto**, non misurato — preso dall'ora di partenza
> dell'aggiornamento e dall'ora in cui stavamo scrivendo, che non sono gli estremi
> del guasto. Gli istanti reali (`05:56:13Z` → `07:24:03Z`) danno **1h27m50s**.
> Corretto perché un numero senza la sua misura è esattamente il difetto che questa
> versione documenta.

### Corretto

- **Il servizio torna raggiungibile, senza riaprire il buco che la `0.40.5`
  aveva chiuso.** Tolta al gateway l'ultima rete non-interna che aveva, era
  rimasto solo su una rete `internal: true` — e **da una rete interna una porta
  non si può pubblicare**: Docker accetta l'istruzione `ports:` e non la applica,
  senza dirlo. Il tunnel bussava a una porta dove non c'era nessun processo in
  ascolto. Ora il profilo Tailscale usa una rete propria in cui **il traffico in
  ingresso passa e quello in uscita no** (il `masquerade` è spento: i pacchetti
  verso Internet partono con un indirizzo privato e non tornano indietro).
  Misurato sui due esiti, su due versioni di Docker, e poi sul sistema vivo dopo
  l'applicazione: porta pubblicata, risposta dall'host, risposta da fuori
  attraverso il tunnel, uscita verso Internet in timeout — e la controprova che
  da un altro container la stessa uscita riesce, senza la quale un timeout non
  distingue un blocco mirato da una rete guasta.
- **Il controllo di salute dell'aggiornamento guarda anche da fuori.** È il
  motivo per cui il guasto è passato: tutte le sonde interrogavano il gateway
  **dall'interno del suo container**, dove la porta risponde sempre — anche
  quando dall'esterno non esiste. Il container risultava sano, il comando che
  mostra la configurazione mostrava la porta (dice cosa è *dichiarato*, non cosa
  Docker riesce ad applicare), e il cancello dell'aggiornamento ha dato via
  libera: **per questo non è scattata la marcia indietro automatica**. Ora c'è
  anche una sonda che guarda la porta dall'host. Fallisce solo con una prova
  positiva del guasto — «non ho misurato» non è «è rotto», perché qui un falso
  allarme provocherebbe un ritorno indietro non necessario — e con Caddy o
  Cloudflared, dove a ricevere il traffico è il proxy, si dichiara non
  applicabile invece di accusare.

### Aggiunto

- **Una prova che misura la porta dal lato da cui il guasto si vede**
  (`tools/prove-empiriche/prova-7`): verifica dall'host che la porta sia
  pubblicata **e** che risponda, e distingue «non applicabile» da «passata»
  uscendo con un codice diverso. È stata provata sui due esiti prima di essere
  dichiarata utile: verde sul servizio vero, **rossa su un container rotto
  apposta**. Delle sette prove è per ora l'unica di cui si sappia che sa
  diventare rossa.
- **Il registro dei rilievi ha una voce nuova, `H51`**, che non nasce da una
  lettura ma da un guasto: *i controlli di salute sondano dal lato in cui il
  problema non si vede*. Resta dichiarata parziale, con i tre residui scritti:
  nessun controllo periodico, la sonda non attraversa il tunnel, e le prove
  empiriche non entrano ancora nel pacchetto di aggiornamento.

### Nota per chi aggiorna

Nessuna migrazione, nessun segreto nuovo. Chi usa il profilo Tailscale ottiene
una rete Docker nuova (`funnel`) e il gateway ricreato una volta. Chi usa Caddy
o Cloudflared non cambia nulla — **e su quei due profili il gateway ha ancora
l'uscita verso Internet**: `H50` resta parziale per loro, ed è scritto invece che
taciuto, perché la rete che userebbe la stessa cura è quella su cui Cloudflared
deve poter uscire per funzionare.

### Rettifica alla nota della `0.40.5`

Quella voce diceva: «Verificato eseguendo `docker compose config` su tutti e tre
i profili». Era vero e **non bastava**: quel comando riporta ciò che è
dichiarato, non ciò che Docker riesce ad applicare, e infatti mostrava la porta
mentre il servizio era giù. Aver eseguito uno strumento non è aver misurato un
effetto.

## [0.40.5] — 2026-07-26

Chiude il secondo dei due difetti che il ciclo di audit aveva **misurato** sul
sistema vivo invece di dedurlo dai documenti: il gateway — il solo servizio
esposto su Internet, e quello che monta i cinque secret — aveva un'uscita
verso qualunque host. Ora non ce l'ha.

### Corretto

- **Il gateway non esce più su Internet.** Stava sulla rete `ingress`, che è un
  bridge non-`internal`: aveva quindi una via d'uscita NAT verso qualsiasi
  destinazione — verificato con un socket aperto dall'interno del container, non
  dedotto da una lettura. La rete non è più dichiarata nel compose di base: la
  ri-mette il profilo che ne ha bisogno (Caddy e Cloudflared lo facevano già da
  sé; col profilo Tailscale il gateway è raggiunto da una porta pubblicata su
  loopback e non le serve). Verificato eseguendo `docker compose config` su
  tutti e tre i profili: col profilo Tailscale la rete `ingress` non viene
  nemmeno creata, perché nessun servizio la usa.
- **Il pannello non chiama più «guasto» una cosa che è una scelta.** Il pulsante
  «Ricontrolla adesso» interrogava GitHub dal gateway e ora non può più: senza
  un rimedio, avrebbe mostrato un errore di rete indistinguibile da un
  malfunzionamento. Il messaggio dice che non è un guasto e che l'avviso di
  aggiornamento continua ad aggiornarsi da solo — senza affermare quale delle
  due cause sia, perché il gateway non può distinguere «non ho rete» da «GitHub
  non risponde», e sceglierne una sarebbe inventare una diagnosi.
- **Il verdetto sugli aggiornamenti porta la propria età.** Diceva «Sei alla
  versione più recente» al presente, con la data dell'ultimo controllo stampata
  sotto in grigio: le due righe insieme dicevano il vero, la prima da sola no —
  ed è quella che si legge. Il controllo gira una volta al giorno, quindi quel
  verdetto poteva avere fino a un giorno. Ora l'età è dentro la frase, e oltre
  le 26 ore cambia significato: non «dato vecchio» ma «il controllo automatico
  potrebbe non essere attivo», col comando per verificarlo. Sono due condizioni
  diverse e finora erano lo stesso verde.

### Aggiunto

- **La logica che decide cosa legge l'amministratore ora ha dei test.** Nessuno
  dei test del gateway importava `admin.py` — non può, tira dentro starlette e
  pydantic mentre la CI gira i test senza dipendenze pesanti: tutta quella
  logica viveva dove nessun controllo la guardava. La decisione è stata estratta
  nel modulo puro accanto (`admin_core`, che esiste per questo e lo dichiara),
  con dieci test nuovi e le rispettive controprove — mutando la soglia e il
  confronto di versione, i test falliscono.

### Nota per chi aggiorna

Nessuna migrazione, nessun segreto nuovo. **Dopo questo aggiornamento il
pulsante «Ricontrolla adesso» del pannello smette di funzionare**: è
intenzionale, ed è il prezzo di un gateway che non parla con Internet.
L'avviso di aggiornamento resta e si rinfresca da sé una volta al giorno dal
controllo che gira sull'host, che la rete ce l'ha; la pagina ora dice
esplicitamente quanto è vecchio quel controllo.

## [0.40.4] — 2026-07-26

Rilascio di allineamento: la `0.40.3` è stata taggata su uno stato la cui CI
non era mai passata al verde, e i tre commit che l'hanno riportata verde sono
finiti **dopo** il tag, fuori dalla release. Nessun servizio ne era toccato —
il bundle runtime non contiene nessuno dei file corretti, quindi l'artefatto
installabile della `0.40.3` è identico a quello che sarebbe uscito dallo stato
verde — ma il sorgente al tag `v0.40.3` fallisce il proprio controllo del
registro, e per un progetto il cui valore dichiarato è «il registro presidia
le garanzie» quella incoerenza vale un rilascio.

### Corretto

- **`SECURITY.md` combacia col registro** (50 rilievi, 41 chiusi, 2 accettati:
  i numeri erano fermi al dossier originario di 43 mentre il ciclo di audit ne
  ha aggiunti 7 legittimi). Il gate `check_findings.py` è verde di nuovo, e la
  sua àncora ora **dichiara la propria provenienza** invece di portare numeri
  nudi: chi la sposta deve nominare le voci che aggiunge.
- **`ruff` è pinnato** (`0.15.22`). Era l'unico strumento non pinnato di un
  repo che pinna le action per sha e le immagini per digest: si è aggiornato
  da solo a `0.16.0` e ha bocciato con 181 rilievi codice identico a quello
  verde di sei giorni prima. Un linter che cambia versione da sé è un gate che
  cambia contratto senza un commit.

### Aggiunto

- **La release non parte più da uno stato che non passa i propri controlli.**
  Il job `guard` di `release.yml` verifica che la CI del commit taggato sia
  conclusa in `success` prima di costruire e firmare: fallita → release
  fermata con un messaggio che dice cosa fare; ancora in corso → attende fino
  a 15 minuti (il caso legittimo di tag e branch pushati insieme). Chiude la
  seconda metà di `H24`: la firma cosign certifica **da quale workflow** viene
  un artefatto, non che quello stato fosse in regola — e finora niente lo
  verificava. Questo rilascio è la sua prima esecuzione reale.

### Nota per chi aggiorna

Nessuna migrazione, nessun segreto, nessun cambiamento di comportamento nei
servizi: chi è già sulla `0.40.3` non ha nulla di rotto da riparare. Restano
valide la nota sulla potatura degli snapshot e il residuo dichiarato in `H50`
(l'uscita Internet del gateway) della `0.40.3` qui sotto.

## [0.40.3] — 2026-07-26

Prima release nata da un ciclo di audit con misure sulla macchina viva (cinque
tornate: lettura del codice → verifica indipendente → prova empirica → fix →
gate incrociato, tre sessioni che si controllano a vicenda). I due difetti che
corregge non sono stati trovati leggendo: sono stati **misurati** su una
installazione di produzione, e uno dei due esisteva da sempre senza che nessun
documento mentisse.

### Corretto

- **La retention degli snapshot pre-update ora scatta davvero.** La potatura a
  72h viveva solo nello step finale di un update *riuscito*: con update più
  rari della finestra, non scattava mai — misurato sul vivo: 8 snapshot non
  cifrati, ~14,5 GB, fermi da 6 giorni. Ora `cmd_check` pota **a ogni giro del
  timer giornaliero**, prima del fetch da GitHub (funziona anche a rete rotta),
  e protegge **sempre** lo snapshot più recente (`keep=snapshot_latest`, non
  `keep=None`): il punto di ripristino della versione in esecuzione sopravvive
  a qualunque età. Senza quella protezione — trovato al quinto giro di audit,
  sul diff del fix stesso — il primo check dopo questo rilascio avrebbe potato
  *tutti* gli snapshot, incluso quello a cui tornare se la versione corrente
  si rivelasse rotta. Anche la rollback-routine ora passa `keep=snap`: il
  ripristino non cancella lo snapshot che gli serve.
- **Il fail-open della firma cosign non è più silenzioso.** Con
  `VPS1777_REQUIRE_COSIGN=0` e una release senza `.sig`/`.pem`, il bundle
  veniva installato senza verifica **e senza dirlo**. La scelta resta possibile
  (è l'ultima spiaggia dichiarata, non un bypass), ma ora produce un avviso
  esplicito nel log — e la nota va detta intera: quell'interruttore in `.env` è
  **persistente**, vale per tutti gli update futuri finché non lo si rimuove.
- **`setup.sh` allinea l'hardening host agli altri due installer.** Installava
  lo stack senza `unattended-upgrades` né `fail2ban`, che `deploy.sh` e
  l'installer web applicano da sempre: terza incarnazione dello stesso blocco,
  ora presente in tutti e tre i percorsi. E abilita `auto-update.timer` dalla
  feature dichiarata (`VPS1777_FEATURES`), come gli altri.

### Aggiunto

- **`tools/prove-empiriche/` — sei prove eseguibili sul sistema vivo**, con
  exit code a tre stati (0 regge · 1 non regge · 2 non misurabile, mai
  confuso con un verde). Nate dal ciclo di audit e già temprate sul campo: le
  prime tre hanno prodotto un falso PASS (script troncato via stdin di
  `docker exec`) e un falso FAIL (`expose` scambiato per `ports`), corretti
  misurando di nuovo. La prova-4 (snapshot) confronta ciò che il codice
  proteggerebbe con la **versione in esecuzione** letta da una fonte esterna
  ai dati giudicati: sa dire di no anche al codice che presidia.
- **`CODEOWNERS`**: le modifiche a `security/` chiedono la review del
  proprietario. Da solo non impone nulla — lo impone una branch protection, e
  il registro (`H24`) dichiara esattamente questo limite invece di tacerlo.

### Nota per chi aggiorna

Nessun segreto nuovo, nessuna migrazione. **Al primo check giornaliero dopo
questo aggiornamento, gli snapshot pre-update più vecchi di 72h vengono potati
— tranne il più recente, che resta come punto di ripristino.** Sulla macchina
di riferimento: 7 su 8 rimossi, ~12 GB liberati, **non recuperabili** (erano
copie di update riusciti del 20/07). Chi vuole conservarne uno come campione
lo copi fuori da `backups/pre-update/` prima del primo check.

Resta aperto, misurato e dichiarato nel registro (`H50`): il gateway ha
un'uscita reale verso Internet, che serve al solo «Ricontrolla adesso» del
pannello (l'avviso di aggiornamento vero lo scrive il timer dell'host, e
chiudere l'uscita non lo toccherebbe — il costo reale è un refresh manuale
che smette di funzionare e un avviso che può invecchiare fino a 24h). La
scelta del proprietario è tenerla aperta **per ora**; le tre soluzioni
candidate — rete, intent per il bottone col pattern collect→apply già in
casa, allowlist — sono documentate nella voce di registro, in attesa del
prossimo round di audit.

## [0.40.2] — 2026-07-21

Due difetti trovati **dopo** aver taggato la 0.40.1, entrambi da chi non aveva
scritto il codice, entrambi registrati prima di essere corretti.

### Corretto

- **«Manca» e «c'è ma non si legge» non sono più la stessa cosa.** Un segreto
  integro ma illeggibile (permessi, ACL, mount, symlink rotto) veniva segnalato
  come «manca o è VUOTO», e il rimedio suggerito — un comando con `>` — lo
  avrebbe **troncato**: la riparazione distruggeva il segreto che doveva
  salvare. Ora i casi sono tre (assente / vuoto / non leggibile) con tre rimedi
  distinti, e per l'illeggibile il messaggio indica `ls -l` e `chmod`, mai una
  ridirezione. La distinzione usa il dato che il codice aveva già, invece di
  enumerare le cause: una lista di cause sarebbe stata incompleta dal primo
  giorno.
- **Lo `stage-check` valida gli stessi file compose che lo stack monta.** Ne
  leggeva due (base + ingress) mentre il comando reale ne monta anche uno per
  ogni feature attiva, e `backup` lo è di default: un controllo verde su un
  sottoinsieme non dice nulla sull'insieme che verrà usato. Non è un refactor —
  **cambia cosa viene validato**: un overlay di feature con un errore di
  sintassi, che prima passava e faceva fallire l'avvio dopo il punto di non
  ritorno, adesso ferma l'aggiornamento mentre è ancora annullabile.

### Nota per chi aggiorna

Nessuna azione richiesta, nessun segreto nuovo, nessuna migrazione.

**Questo aggiornamento è stato la prima prova reale del pre-flight introdotto
nella 0.40.1 — ed è avvenuta: 21/07, verde.** Fallimento controllato su una
macchina viva, lanciando il servizio di aggiornamento automatico (non il comando
da terminale, che gira in un ambiente diverso da quello reale). Il registro di
sistema mostra la sequenza nell'ordine che il fix prometteva: l'avviso sulla
configurazione attuale *prima* del download, il blocco sulla release in arrivo
*dopo* — e la cartella degli snapshot rimasta a zero, cioè il backup non è mai
partito. Lo stack è rimasto in salute per tutta la prova e i dati non si sono
mossi di una riga.

Il testo qui sotto è come era stato scritto prima della prova, e si lascia:
prometteva una verifica e la verifica c'è stata.

**Questo aggiornamento è la prima prova reale del pre-flight introdotto nella
0.40.1.** Non lo era la 0.40.1: là a orchestrare era ancora la CLI precedente,
col controllo vecchio, che si ferma prima di arrivare al nuovo. È solo
aggiornando *da* una 0.40.1 già installata che il codice nuovo decide davvero —
e si vede la differenza di severità fra il controllo sulla configurazione
attuale (avviso) e quello sulla release in arrivo (fatale).

## [0.40.1] — 2026-07-20

Patch, e una sola cosa: **il pre-flight dei segreti guardava la configurazione
sbagliata**. Il primo aggiornamento alla 0.40.0 è fallito per questo — lo stack
non è partito, l'health-gate è andato rosso, il rollback automatico ha
funzionato e nessun dato è stato toccato.

### ⚠️ Rettifica di quanto dichiarato nella 0.40.0

Là sotto si legge: «*l'update ora ha un pre-flight che si ferma se manca*».
**Non era vero**, ed è il caso più istruttivo di questa release: il controllo
esisteva, girava, era verde — e leggeva il compose **installato**, mentre quello
della release arriva col bundle uno step dopo. Quando girava, il file che
avrebbe dovuto controllare non era ancora sul disco. Ogni parola di quella frase
era vera della riga di codice; la protezione promessa non esisteva. Il difetto
non era nella logica ma nella **posizione**, ed è per questo che, letta da sola,
la funzione sembrava corretta a tutti.

### Cambiato

- **Il controllo fatale ora sta dopo il fetch e dopo il self-update della CLI**
  (step 6-bis) e legge i compose **del bundle**, cercando i file in `secrets/`
  del repo. La posizione non è dopo il self-update per comodità: prima, sarebbe
  il parser della release *N* a leggere il compose della *N+1*, e un cambio di
  formato del blocco `secrets:` impedirebbe di installare proprio la release che
  contiene il parser capace di leggerlo. Fallendo dopo, invece, si resta con CLI
  nuova e stack vecchio — uno stato che si ripara **rilanciando l'update**, e
  che è comunque l'esito normale di ogni rollback riuscito.
- **Il controllo sulla configurazione attuale resta, come avviso**: dice che la
  rete di *rollback* è bucata, e non ferma l'aggiornamento. Se lo fermasse, una
  release che rimuove un segreto già cancellato sarebbe l'unica installabile.
- **Il rimedio suggerito non può più fabbricare un guasto peggiore.** Prima
  consigliava `bash setup.sh`, che su una macchina viva è l'installatore
  completo. Ma toglierlo non bastava: i segreti non hanno tutti la stessa natura,
  e un `openssl rand` applicato a un token Telegram o all'hash bcrypt della
  password admin produce un file **pieno e sbagliato** — il controllo tornerebbe
  verde, lo stack partirebbe, e il guasto si vedrebbe solo all'uso. Ora il
  comando compare **solo sotto il segreto a cui si applica**.
- **Guarda tutti i compose che lo stack monta**, non solo quello base: l'overlay
  di ingress (`cloudflared` dichiara un segreto) e quelli delle feature attive.
- **Un file con solo spazi o un a capo conta come vuoto** (prima `st_size == 0`
  lo lasciava passare: 1 byte è "pieno" per il codice e vuoto per chiunque).
- **Un bundle senza `compose.yaml` si ferma** invece di rispondere "tutto a
  posto": «non ho trovato il file» non è «non c'è niente da segnalare».
- **«Mancano tutti i segreti» viene riconosciuto per quello che quasi sempre è**:
  non un guasto, ma una radice sbagliata — e lo dice.

### Aggiunto

- La suite `tools/tests/` **gira in CI**. Era l'unica del repo che nessun
  workflow lanciava: dieci test verdi sul componente che esegue gli
  aggiornamenti in produzione, che non avevano mai protetto nulla.

### Nota per chi aggiorna

Nessuna azione richiesta, nessun segreto nuovo, nessuna migrazione. Se
l'aggiornamento alla 0.40.0 era stato completato a mano creando
`archive_desc_secret`, resta valido.

**Fin dove è stato verificato, e fin dove no.** Questo fix è provato sulla
funzione (banchi in directory temporanee, tre banchi indipendenti) e in CI —
**mai su una macchina vera**. Nessuno ha ancora osservato l'ordine reale degli
step durante un aggiornamento vero, né il fatto che al primo aggiornamento il
controllo nuovo può scattare solo dopo il riavvio della CLI. Quindi:
**l'aggiornamento a questa versione è anche la sua prima prova end-to-end.** Se
fallisce, la rete è il rollback automatico — la stessa che ha funzionato il
20/07 senza toccare un dato. Lo diciamo perché è precisamente la distanza — fra
«i test passano» e «la macchina si aggiorna» — in cui era caduta la 0.40.0: una
release che tace su cosa non ha provato si legge come se avesse provato tutto.

**Difetto noto e non corretto**: lo `stage-check` (step 8) legge due file
compose, mentre lo stack ne monta anche uno per ogni feature attiva (`backup`
lo è di default). Stessa forma del difetto riparato qui, superficie diversa;
sistemarlo avrebbe voluto dire due cose in una release. Registrato con data di
revisione nel ledger delle funzioni.

## [0.40.0] — 2026-07-20

Minor e non patch: l'indexer cambia *cosa* legge, i DB cambiano *schema*, e nasce
un canale di scrittura fra due servizi. Chi legge questa storia fra sei mesi deve
vederlo dal numero.

### ⚠️ Chi aggiorna deve sapere queste quattro cose

1. **Nuovo segreto `archive_desc_secret`.** Il canale `set_description` non riusa
   `gateway_secret` di proposito: quello apre anche `/internal/nlm/*` (stato e
   installazione dei profili NotebookLM), e una funzione che scrive un campo di
   testo non deve portarsi dietro quel potere. `setup.sh` lo genera; l'update ora
   ha un **pre-flight** che si ferma se manca, invece di lasciar fallire lo stack
   con un sintomo che sembra una release rotta. Un file **vuoto** conta come
   mancante: con un segreto vuoto lo stack parte e il canale resta muto, cioè un
   difetto di provisioning travestito da bug della feature.
2. **Migrazione di schema al primo ingest** su ogni DB esistente: colonna
   `ts_source` su `messages` e tabella `revisions`. Trasparente e verificata sul
   dato preesistente; `ts_source` non è indicizzata in FTS, quindi non comporta un
   rebuild dell'indice.
   I valori sono **tre**: `messaggio` (istante reale), `data-export` (data della
   *fotografia*, non del contenuto) e **`ignoto`** — che riceve tutto ciò che
   esisteva prima della 0.40.0, perché su un DB precedente **il regime non è
   ricostruibile a posteriori**. Dichiararlo `messaggio` sarebbe stata
   un'asserzione mai verificata: misurato sul bundle di riferimento, **140.476
   righe su 221.514 con `ts` pieno non sono conversazioni** — sono log e documenti,
   il cui `ts` è il timestamp del file. È anche il motivo del punto 3: gli
   `ignoto` devono passare il filtro.
3. **Il `newest` si calcola in NEGATIVO**: `MAX(ts) WHERE ts_source <> 'data-export'`,
   **non** `= 'messaggio'`. La forma positiva escluderebbe le righe migrate
   (marcate `ignoto`, perché il loro regime non è ricostruibile a posteriori) e
   restituirebbe una data troppo vecchia. Chi tocca `db_info` non riscriva la
   forma positiva: è dimostrata rotta, e c'è un test che lo prova.
4. **Lo sniff cambia i conteggi dei prossimi ingest** — 826 file promossi da
   "non-testo" a documenti sul bundle di riferimento. Chi confronta i numeri
   prima/dopo deve sapere perché ballano: non è una regressione, è che prima non
   li leggevamo.

### Aggiunto
- **Sniff del contenuto nell'ingest.** La classificazione dei file era per
  *estensione*: un'etichetta, non una misura. Sul bundle reale, 826 dei 2.633
  censiti «non-testo» sono testo pieno — appunti senza estensione, todo, script,
  Dockerfile, `.cjs/.proto/.service/.xsd/.ndjson`. Ora si guardano i primi 4 KB,
  con criterio conservativo (un byte NUL chiude la questione, serve UTF-8 valido e
  ≥90% di caratteri stampabili): meglio una lapide di troppo che spazzatura binaria
  nell'indice full-text. I promossi sono marcati `[testo-sniffato]`.
- **Tabella `revisions`.** `messages` ha chiave primaria su `uuid` e si scrive con
  `INSERT OR REPLACE`: se lo stesso identificatore tornava con contenuto diverso,
  l'ultimo vinceva e il primo spariva **senza traccia**. Non è teorico — le voci
  `memory:*` sono slot riscrivibili. Finora le versioni sopravvivevano solo perché
  stavano in DB separati: la comparabilità degli snapshot era un *accidente della
  topologia*, non una proprietà. Ora è struttura. La ricerca continua a vedere
  l'ultima versione: nessuna API cambia.
- **`POST /internal/archive/description`** — il tool MCP `set_description`
  inoltra qui invece di aprire il DB. Rete interna, segreto dedicato
  constant-time, nome del DB in whitelist col percorso composto dal gateway, cap
  di lunghezza, rifiuto dei caratteri di controllo, audit di ogni scrittura. Ogni
  rifiuto risponde **404 e mai 403**: un 403 confermerebbe l'esistenza della rotta.
- **Pre-flight dei segreti nell'update**, che legge l'elenco *dal compose* e non da
  una lista nel codice — una lista andrebbe aggiornata a ogni segreto nuovo, ed è
  esattamente la dimenticanza che il controllo previene.

### Corretto
- **`set_description` non falliva più silenziosamente.** Il tool si dichiarava
  «l'unica scrittura ammessa da questo layer» mentre il suo container monta il
  volume in sola lettura per scelta deliberata: due dichiarazioni entrambe vere,
  ognuna nel suo file, che insieme mentivano. Chi lo chiamava riceveva
  `attempt to write a readonly database`.
- **Le voci senza `ts` erano invisibili ai filtri temporali** — un intero namespace
  saltato in silenzio da `since=`. `ts_source` distingue un istante *reale* da una
  *data di fotografia*, così chiudere quel buco non ne apre uno opposto: una
  memoria di maggio fotografata a luglio non «è successa a luglio».

## [0.39.4] — 2026-07-20

### Il volume dello spool nasce con l'owner giusto

Terzo e ultimo anello del caso «upload 2,6 GB»: `TMPDIR=/var/lib/uploads` c'era
(v0.39.3) ma il volume nuovo, creato da Docker, era `root:root` — e `tempfile`
scarta IN SILENZIO una tempdir non scrivibile, ripiegando sulla tmpfs `/tmp`
(che l'upload saturava: stesso 500 di prima, altra causa). Un volume vuoto al
primo mount eredita owner/permessi dal path dell'IMMAGINE: ora il Dockerfile
crea `/var/lib/uploads` chown-ato ad `app`, come già `/var/lib/gateway`. Sulle
installazioni esistenti l'owner è già stato corretto a mano sul volume (persiste);
questa release rende giusto ogni deploy futuro.

## [0.39.3] — 2026-07-20

### La pagina Archive regge gli upload giganti

L'upload del bundle da 2,6 GB moriva con un 500: `/tmp` del gateway è una tmpfs
in RAM (rootfs immutabile, H43) e Starlette vi spoola i multipart — 92 MB
passavano, 2,6 GB la saturavano («No space left on device»). Nuovo volume
`gateway-uploads` montato su `/var/lib/uploads` + `TMPDIR` puntato lì: lo spool
va su disco, la tmpfs resta per il resto. Il volume è usa-e-getta e resta fuori
dal backup. Il tetto applicativo (4 GB, v0.39.0) ora è raggiungibile davvero.

## [0.39.2] — 2026-07-20

### Il container backup non dipende più da DOVE lanci l'update

`compose.ops.backup.yaml` montava `${PWD}:/vps1777` — un'espansione d'ambiente,
cioè la cwd del CHIAMANTE, non il repo. `vps1777 update` lanciato da `/root`
montava `/root` sul container: «backup-container-setup.sh: no such file», compose
up fallito, e l'auto-rollback rifalliva allo stesso modo (visto dal vivo, oggi).
`--project-directory` non salva le espansioni d'ambiente; salva i path RELATIVI:
il mount ora è `.:/vps1777` e si risolve sempre rispetto al repo.
Workaround per chi è su ≤0.39.1: `cd /home/vps1777/vps1777 && vps1777 update`.

## [0.39.1] — 2026-07-20

### La pagina Update sa ricontrollare

Caso vero: release v0.39.0 pubblicata alle 08:36Z, ultimo check del timer alle 05:43Z
→ la pagina diceva «sei alla versione più recente» per ore, senza modo di forzare il
refresh (il timer gira una volta al giorno). Nuovo bottone **«↻ Ricontrolla adesso»**
(`POST /admin/update/check`): il gateway fa il GET a GitHub e rinfresca
`update_status.json` — con la stessa guardia anti-regressione della CLI (la «latest
nota» non regredisce mai su una risposta stantia della cache). Il check è innocuo
(niente Docker, niente privilegi): l'update vero resta collect→apply della CLI host.
Suite gateway: **155 passed**.

## [0.39.0] — 2026-07-20

### Archive ingerisce il bundle di Recupero Sessioni — e i doppioni raccontano dove sono stati

Il difetto scoperto (upload reale di Neo, 2,6 GB): il bundle «scarica tutto» dell'app
locale di recupero sessioni moriva sul tetto upload da 1 GB — e anche sotto il tetto
NON era un formato riconosciuto: cadeva nel fallback zip-di-documenti che indicizza
solo i `.md/.txt`, ignorando **in silenzio** 1.476 sessioni e 17.851 log MCP.

**Estrattore dedicato** (`_iter_bundle_zip`, riconoscimento `MANIFEST.json`+`sessions/`):
sessioni → conversazioni; log MCP → documenti chunked (`mcp-log:<server>`); workfiles-testo
→ documenti col path cercabile; i `.jsonl` dentro workfiles → sniff sul contenuto
(sessione CC / log / dati). Whitelist `_DOC_ZIP_EXTS` allargata al **codice** (py/sh/js/
dart/… markup, config) — vale anche per il fallback zip generico.

**Tabella `sightings(uuid, source)`** — i doppioni collassano in `messages` (la ricerca
non deve restituire dieci copie) ma ogni copia registra DOVE è stata vista: «questo file
prima era in una cartella, poi in un'altra» diventa un `GROUP BY`, non un ricordo.
I **binari** dei workfiles (zip/db/dill/so/immagini) non entrano nell'FTS ma lasciano
una lapide ciascuno in `skipped` (reason=`non-testo`, detail=path): l'inventario del
materiale non-indicizzato resta interrogabile. Tetti: archivio decompresso 2→16 GB,
upload 1→4 GB.

Verificato (locale): suite **48 passed**; bundle 254 MB → 111.137 record in 31 s,
91.461 in tabella (73.612 = previsione esatta del MANIFEST); bundle 2,6 GB con
workfiles → **376.706 record in 79 s, 61.100 uuid avvistati in 2+ path, 2.633 binari
censiti, zero crash**; tokenizer sul DB nuovo: `count(C++)=769 ≠ count(C)=7.807`.

## [0.38.0] — 2026-07-17

### L'installer allestisce TUTTO — niente più feature perse in silenzio

Il difetto scoperto: un reinstall (o un update) lasciava cadere gli opt-in `ops.*`
**in silenzio** — l'auto-install (Watchtower) e persino il backup notturno sparivano
senza un errore, perché lo "stato voluto" viveva solo nei `--profile` digitati a mano,
effimeri, mai catturati. Radice: nessun posto che l'installer legge *dichiarava* cosa
deve girare; il divario fra dichiarato e reale non aveva un guardiano.

**Stato feature dichiarato** (`VPS1777_FEATURES` in `.env`, default `backup,autoupdate`),
letto dove si costruisce OGNI comando compose (`vps1777.py:compose_cmd`): install, update
e rollback riproducono SEMPRE le stesse feature. Un update non spegne più il backup; un
reinstall lo riaccende senza doverlo ricordare. Stato autoritativo: una feature tolta si
spegne.

**Auto-update SICURO** — le unit `systemd/vps1777-auto-update.{service,timer}` lanciano
`vps1777 update --yes` (backup + firma cosign + migrazioni + health-gate 180s + auto-rollback),
timer settimanale. È il rimpiazzo *automatico e gestito* che al declassamento di Watchtower
(giugno) non fu mai costruito — Watchtower (`ops.autoupdate`) resta opt-in e in conflitto,
mai il default.

**L'installer fa tutto** (`deploy.sh` + `installer/engine.py`): al primo install accende
backup + timer, imposta la chiave age del backup (genera la coppia SUL PC, manda alla VPS
solo il recipient pubblico; oppure `AGE_RECIPIENT=…`), e stampa un **referto post-install**
(`backup ON · auto-update ON · portainer OFF · age OK/manca`) — l'assenza *parla*, non si
scopre dopo mesi. Corretta anche una divergenza: `unattended-upgrades`+`fail2ban` erano solo
nel web-installer, ora anche in `deploy.sh`.

Fix di regressione (preso dai test): `watchtower` ha file (`compose.ops.watchtower.yaml`)
≠ profilo (`ops.autoupdate`) — derivare il file dal profilo referenziava un file inesistente.

Verificato: `test_vps1777` **10 passed** (+2: stato dichiarato, fix watchtower); `deploy.sh`
`bash -n` ok; `engine.py`/`vps1777.py` compilano.

## [0.37.4] — 2026-07-17

### Il tokenizer che collassava — `C++` cercava `C` (la causa dell'11/07)

`unicode61` tratta `+ #` da **separatori**: `C++`, `C#`, `g++` perdono il suffisso
e diventano il token `C`/`g`, comunissimo (coordinate SVG, copyright, gradi della
caldaia). `count("C++")` non tornava vuoto — tornava **migliaia di falsi positivi
silenziosi** (7.051 su 13.797, il 51% dell'archivio). È così che nacque il falso
ricordo «Neo programmatore C++»: la ricerca non ha mentito, **ha risposto a una
domanda diversa**. Gemello a verso opposto dell'FTS5 muto (PR #20): lì lista vuota,
qui lista piena della cosa sbagliata — entrambi silenziosi. Trovato dalle tre
sessioni durante una compattazione, misurato al singolo risultato (`C++`==`C#`==`C`).

Fix su **due strati**, perché l'indice e la query sono piani diversi:

- **indice** (`archive_indexer`) — l'FTS si crea con `tokenize='unicode61
  tokenchars ''+#'''`: `C++`/`C#`/`g++` diventano token veri e distinti. Vale sui DB
  costruiti **da qui in poi**; il `tokenize` è cotto nella CREATE (un `rebuild` non
  lo cambia) → i DB già vivi vanno **re-ingeriti**. Il `.` resta separatore di
  proposito (romperebbe `node.js`, `github.com`, `0.7.9`).
- **query** (`fts.collapse_warnings_conn`, `count` → `warnings`, tool `check_term`)
  — un **canary** che chiede all'INDICE: se `count(term)==count(prefisso)` il termine
  è collassato e lo **dice**. Vale **subito** sui DB già vivi senza re-ingest, e si
  auto-tara: su un DB ricostruito i conteggi divergono e l'avviso non scatta.

### Crash `n_riga` sui titoli Claude Code senza `sessionId`

Il ramo `ai-title` di `_iter_claude_code` referenziava `n_riga`, variabile rimossa
in 0.37.3: un titolo **senza** `sessionId` sollevava `NameError` → moriva l'ingest
dell'intero file. Invisibile ai test (il loro titolo il sessionId ce l'ha). L'uid
ora ripiega sul testo del titolo.

### Contratto dei bucket — legare l'indexer al preflight della app senza memoria

`classify_cc()` + CLI `--classify` danno il verdetto per riga (`keep:<sender>` /
`skip:<reason>`) **eseguendo** `_iter_claude_code`, non re-implementandolo. È
l'interfaccia con cui la corsia app (standalone) verifica che il suo `_preflight`
non si sia staccato in silenzio dalla mia logica: due classificatori vivi sulla
stessa fixture, i verdetti devono combaciare.

Verificato: gateway **48 passed**, archive-mcp **30 passed**; canary provato sul
`.db` reale (`C++`/`C#`/`g++`/`.NET`/`F#` collassati → catturati, `node.js`/`flutter`
zero falsi positivi).

## [0.37.3] — 2026-07-16

### Il contatore della perdita non perde più

Tre scarti gemelli (stesso tipo, senza timestamp) collassavano in **una** lapide
del libro-mastro `skipped`: l'uid è `sha1(source·reason·detail·ts)`, il detail
era il solo tipo e il ts è vuoto *per definizione* su quel bucket → l'`INSERT
OR IGNORE` li fondeva. Lo strumento nato per la #56 — trasformare i «271 persi»
da inferenza in aritmetica — **contava i tipi di scarto, non gli scarti**.
Trovato eseguendo `write_rows` su un db di prova (6 scarti → 4 registrati),
**prima** del re-ingest che l'avrebbe usato come metro di collaudo.

Il `detail` ora porta la **posizione** (riga nel file per claude-code; nome
conversazione + indice per claude.ai): unica per scarto, **stabile fra
re-ingest** — la proprietà da non perdere: dedup fra ingest sì, collasso dentro
l'ingest no. Una PK è un'opinione su cosa rende due cose «la stessa cosa»: se
quell'opinione è sbagliata, il conteggio mente e nessun test lo vede.

Verificato: +1 test (3 gemelli → 3 lapidi uniche + idempotenza al re-ingest);
suite gateway **45 passed**.

## [0.37.2] — 2026-07-16

### Release pulita post-bonifica (la v0.37.1 spediva ancora il file)

La v0.37.1 è stata taggata **prima** della bonifica del leak (5528267): il suo
albero sorgente — quindi i tarball che GitHub genera dal tag e il bundle runtime
allegato — contengono ancora l'export di sessione rimosso da main (verificato
scaricandolo, non presunto). I tag `v*` sono immutabili (ruleset H24): questa
release riparte dal main bonificato. **La release v0.37.1 è stata rimossa**
(asset compresi); il suo tag resta orfano, come lo 0.37.0 — la coppia racconta
la stessa lezione: ciò che un tag ha spedito non si disfa, si supera con una
release più nuova. Nessun'altra modifica al codice rispetto alla 0.37.1.

## [0.37.1] — 2026-07-16

> Il numero salta lo 0.37.0: quel tag è nato bruciato (puntava al merge senza il
> bump — la guard `VERSION == tag` l'ha respinto in 8s, e i tag `v*` sono
> immutabili per ruleset H24). Nessuna release pubblicata con quel numero:
> resta un tag orfano innocuo. La guard ha fatto esattamente il suo mestiere.

### archive: il thread, il browse, gli scarti, la scheda — le decisioni del tavolo a 4

L'archivio smette di essere un solo-grep: sa leggere una chat intera, dire cosa
contiene, contare ciò che scarta, e portare una scheda per ogni DB. Sono le
decisioni D1–D5 del tavolo a 4 (le 3 sessioni + Neo), implementate e mergiate.

- **Thread vero (D1, #57)** — nuovo tool **`get_conversation`**: il thread intero
  che contiene un uuid, camminando l'albero `parent_uuid` (antenati + discendenti,
  due CTE ricorsive; indice `idx_parent` creato all'ingest). E **`get_context`
  riparato**: i vicini vengono dallo *stesso thread* quando l'arco c'è — prima
  approssimava con `(project, ts)` e poteva mischiare conversazioni interlacciate
  («stesso thread» era un over-claim). Sulle fonti senza arco (documenti chunked,
  DB v1) entrambi ripiegano sul comportamento storico: nessuna regressione.
- **Browse (D2)** — **`list_projects`** (le etichette con i conteggi) e
  **`archive_stats`** (istogramma per anno): navigare l'archivio, non solo
  cercarlo. La ricostruzione fedele dell'ordine dei chunk sulla coda-documenti è
  dichiarata fuori scope: passo evolutivo.
- **Il libro-mastro degli scarti (D3, #55/#56)** — ogni record che l'ingest non
  indicizza (senza uuid, vuoto, malformato) lascia una lapide nella tabella
  **`skipped`** (motivo, dettaglio, data) invece di sparire in un `continue`
  muto. Conteggio in `db_info()["skipped"]` / `count_skipped()`; i dati raw
  restano raggiungibili; il re-ingest non duplica le lapidi.
- **Le summary non si perdono più (D4)** — l'estrattore legge il campo `summary`
  delle conversazioni claude.ai (mancava il codice, non lo schema): righe
  attribuite `sender='summary'`, cercabili (~396k char su un export reale).
- **La scheda dell'archivio (D5)** — campo **descrizione** all'upload
  (`/admin/archive`), colonna nella pagina, tabella `meta` nel DB; esposta da
  `describe_databases` e aggiornabile col nuovo tool **`set_description`** —
  l'unica scrittura ammessa via MCP (tocca la scheda, mai i messaggi).
- **Zip di documenti** — uno zip che non è un export riconosciuto ma contiene
  `.md`/`.txt` ora si indicizza doc-per-doc (budget anti-zip-bomb condiviso,
  idempotente, resource-fork macOS saltate) invece di essere rifiutato.
- **Doc allineata** — `ARCHIVE.md` riflette lo schema v2 reale, gli 8 tool e le
  tabelle nuove; primo giro dell'audit doc: **`NB1777.md` nuovo** (37 tool
  verificati dal codice, #30/#42 documentate) + fix di freschezza su
  ARCHITECTURE/README/INSTALL/SECRETS/ONBOARDING/OPS/UPDATE.

Verificato: suite gateway **151 passed** (nuovi: summary, idx_parent,
skip-ledger, meta/descrizione, zip-di-documenti) + archive-mcp **26 passed**
(thread-walk, fallback lineare, context-nel-thread, projects, stats, meta).

## [0.36.0] — 2026-07-14

### nb1777: il verdetto e la notifica — chiude la #30 (②③)

Completa la #30: dopo ① (nb1777 *dichiara* il canonico), ora c'è il verdetto e la rete che avvisa Neo.

- **② `memoria_check(versione_portata)`** — il *verdetto*: confronta la versione del blocco che una sessione porta col canonico e ritorna `{canonico, data, stale, delta}`. L'effetto collaterale è il punto: se la sessione è vecchia, mette in coda **un ping Telegram per Neo** — così anche se la sessione ignora il verdetto, Neo lo sa. `app/memoria.py`, stato persistito su `/var/lib/nlm` (il bot ha rootfs read-only → tutto lo stato sta nel server).
- **③.1 ping drift** — «una sessione gira con memoria v2.2, il canonico è v2.4». Rate-limit **1 per coppia versione/giorno** (persistito), niente spam.
- **③.2 promemoria cloud** — periodico: «il canonico è cambiato, aggiorna a mano le superfici cloud». L'ack è un **bottone Telegram «✓ Fatto»** *oppure* una fonte `cloud-ack vX.Y` nel notebook (l'automatismo file-simile). Il **poll del bot è il tick** — niente scheduler (sul VPS non c'è cron).
- **Trasporto** — il bot resta senza stato e senza token verso il server: preleva le notifiche da `/internal/notifications` (secret condiviso, come `/internal/nlm/status`) e le manda; rimanda l'ack del bottone a `/internal/canonico/ack`. Nessuna modifica al compose.

Verificato: `tests/test_memoria.py` (verdetto stale/allineato/assente, rate-limit drift, ack bottone+fonte col max, promemoria dovuto/spento/rate-limitato, drain) + `test_canonical.py` esteso (parser `cloud-ack`). Suite piena nb1777-mcp **70 passed**.

**Il buco resta dichiarato:** un Project claude.ai **senza connettore MCP** non è raggiungibile da nessun canale. La #30 fa il massimo ottenibile: dove l'MCP c'è, la sessione lo sa e Neo viene avvisato; dove non c'è, nessun meccanismo può arrivare.

## [0.35.0] — 2026-07-14

### nb1777 dichiara il canonico del blocco di memoria (#30, parte ①)

Prima, una sessione che partiva con un blocco di memoria vecchio **non aveva modo di accorgersene**: nessuno le diceva qual è il canonico. La regola client v2.4 («se nb1777 dichiara il canonico, confrontalo») presupponeva una dichiarazione che non esisteva. Questa è quella dichiarazione.

- **`canonical.py`** — nb1777 legge il canonico dal notebook `claudemd1777`: le fonti hanno titolo `canonico vX.Y — <data> — <cosa cambia>`, la versione corrente è la `vX.Y` più alta (confronto **numerico**, v2.10 > v2.9). **Cache** 15 min, **fail-open** (se il notebook non risponde, nb1777 funziona e non dichiara nulla — la sessione fa il fallback con `notebook_query`).
- **Veicolo A** — `FastMCP(instructions=…)`: la risposta di `initialize` dice alla sessione che nb1777 conosce il canonico e come confrontarsi. Testo statico (non dipende dall'auth nlm al boot).
- **Veicolo B** — nuovo tool **`canonico`**: dichiara la versione canonica viva (`{version, date, note}`), fail-open con `available:false`. Il campo `canonico` è aggiunto anche a **`doctor`** (la chiamata tipica d'avvio sessione), così atterra senza un tool dedicato. Il Veicolo C (campo su ogni risposta) è **scartato**: costoso su 35 tool.

Verificato: `tests/test_canonical.py` (9 casi: versione più alta dai titoli reali, ordinamento numerico, rumore ignorato, titolo senza data, malformati, cache, fail-open).

**Cosa resta (dichiarato, non nascosto):**
- **②** il tool `memoria_check(versione_portata)` che fa il *verdetto* (stale sì/no + delta) e **③** la notifica Telegram del bot quando una sessione gira vecchia (+ scheduler per il promemoria superfici cloud) — passi successivi.
- **Il buco che resta aperto:** una chat in un Project claude.ai **senza connettore MCP** non è raggiungibile da nessun canale (l'MCP non c'è). Nessun meccanismo può toccarla — es. il Project del libro col `CLAUDE.md` caricato come file. ③ non lo risolverà: glielo *dirà*. È il massimo ottenibile.

## [0.34.0] — 2026-07-14

### nb1777 studio — id corretto e lista compatta (#42)

Due bug emersi usando davvero il server (6 audio + 1 video in una mattina), che si moltiplicavano a vicenda:

- **`studio_create_*` ritornava l'id sbagliato.** L'id dell'artefatto appena creato veniva preso per posizione in lista (`[-1]`, «assume ordine cronologico») — falso: sei create consecutivi tornavano tutti l'id del *primo*. Ora si ricava per **differenza di snapshot** (id prima/dopo il create), la stessa cura già in repo per le fonti (`_add_and_resolve_id`). Limite di concorrenza dichiarato: se un'altra sessione crea sullo stesso account nella finestra fra i due snapshot, si disambigua col tipo atteso o si ripiega best-effort — senza indovinare in silenzio.
- **`studio_list` restituiva i focus interi** (`custom_instructions`, 4-6 KB per un podcast): ~85:1 di rumore, e il risultato di un tool MCP entra inline nel contesto, non paginabile. Ora il default è **compatto** (id/type/status/label a 80 char); `verbose=true` per il JSON pieno. Stesso trattamento per `studio_status`.

Regola che li lega: **la proiezione la sceglie chi consuma, non chi produce** — la lista dà poco per default e tutto a richiesta, e il default non è mai irreversibile. Verificato da `tests/test_studio_id.py` (6 casi: compatto/verbose, id per differenza non per ordine, ripiego a 0 id nuovi, disambiguazione col tipo su concorrenza). Chiude #42.

## [0.33.0] — 2026-07-14

### Chiusura del dossier — zero rilievi aperti (35 chiusi · 7 parziali · 1 accettato · 0 aperti)

L'ultima ondata sui residui, dopo le decisioni di Neo sui bivi. Nessun rilievo della review difensiva resta aperto: i 7 parziali sono scelte deliberate o rinvii dichiarati, l'unico accettato è il no-2FA (motivato). Tutto verificato dal gate in CI.

**Costruiti (decisioni di Neo):**
- **H8** — **pagina di consenso OAuth** vera: `/authorize` da loggato mostra "autorizzi <client>?" con [Autorizza]/[Rifiuta], POST dietro CSRF, valori client html-escaped, Rifiuta → `access_denied`. Chiude anche uno scostamento: `ARCHITECTURE.md` la disegnava già.
- **H25** — **rete `egress` separata**: `nb1777-mcp` e il bot escono su Internet da una rete dedicata, tolti da `ingress` (dove restano solo gateway + proxy). Bridge senza porte pubblicate → solo uscita. Verificato sul VPS: da `egress` NotebookLM/Telegram = 302, da una rete `internal` = 000.

**Chiusi:**
- **H9** — `deploy.sh --apply` **valida** la forma dei valori di `pending.json` prima di scriverli (rifiuta le injection: `$(rm)`, `; cat /etc/shadow`, `http://`).
- **H10** — banner "sessione NON cifrata" nel pannello quando il gateway non è dietro HTTPS + flag `insecure` nell'audit del login.
- **H31/H33/H34/H36** — CORS scoped ai soli OAuth+/app (non `/admin`); `/health` con body minimo `{"ok":true}` e `?deep` riservato ai chiamanti interni; CSP di default globale (`default-src 'none'`); `pending.json` con TTL 24h + auto-wipe, intent file a `0640` (non più world-readable — porta un nonce che autorizza l'apply).
- **H32** — confronto PKCE constant-time (`hmac.compare_digest`).
- **H40** — cleanup OCR con retry + `cleanup_ok` + sweep dei notebook `_ingest_*` + `ingest_orphans` in `doctor`.
- **H42** — `archive-data` montato `:ro` (verificato: DB in `journal_mode=delete`, non WAL).
- **H43** — rootfs `read_only` su gateway/archive-mcp/bot con tmpfs `/tmp` (nb1777-mcp escluso: Chromium).
- **H18** — sezione «Dati a riposo» in `SECURITY.md` (onestà su cosa non è cifrato). **H29** — token bot riclassificato fascia massima, soglia 365→90. **H37** — rotazione chiave age documentata. **H21** — riconciliazione doc↔codice completata (il codice ha raggiunto la doc) + il gate `check_findings.py` in CI.

**Stato `accepted` nel registro** (nuovo): un rischio *deciso di non chiudere* non è né `open` (dimenticato) né `closed` (fatto). Il gate pretende che ogni `accepted` porti la sua motivazione. Primo: **H28** (no 2FA).

**Postilla dichiarata** (`SECURITY.md`): l'approvazione manuale dei rilasci (`H24`), il rootfs read-only su `nb1777-mcp` (`H43`) e il pinning digest delle immagini nostre (`H22`) sono **rinviati di proposito** — li faremo al 100% quando il ritmo dei rilasci sarà più regolare.

## [0.32.0] — 2026-07-14

### Chiusura del dossier residuo — 12 interventi, con la disciplina che li verifica

Dopo il registro dei rilievi (v0.31.0), la campagna che lo svuota. Sei lotti in parallelo, ognuno con quattro regole nel prompt — verifica alla fonte, nessun claim senza coordinata, «un fix è finito quando hai cercato chi hai rotto», ri-verifica anche il già-fatto. Da **8 chiusi** a inizio giornata a **20 chiusi · 16 parziali · 7 aperti** su 43, ogni transizione con l'evidenza che il gate in CI verifica.

**Chiusi in questa release** (con il dettaglio in `security/findings.yml`):
- **H20** — revoca reale della sessione admin: `jti` su ogni token + revoke-list persistente; il logout ora passa da CSRF e revoca davvero (prima cancellava solo il cookie). *Bonus trovato*: i form di logout erano annidati nei form di upload → il logout era già rotto.
- **H14** — i cookie Google **fuori** dallo snapshot pre-update (erodeva H6), coi `.tar` in chiaro già scritti da CLI vecchie **cancellati**, non solo evitati d'ora in poi.
- **H39** — tetti sul **decompresso** anche lato archivio (nlm era già in v0.30.2): byte contati mentre si leggono, non la dimensione dichiarata. *«Un limite su un input compresso non è un limite.»*
- **H26/H27/H11** — Mini App: il `gateway_secret` non entra più nel DOM (mascherato, reveal esplicito); finestra `initData` 24h→12h + re-check dell'owner sul Bearer; l'IP negli eventi di fallimento.
- **H17** — audit: lettura dalla coda (non più tutto il file in RAM) e contatore dei fallimenti **mostrato a schermo** (un elenco vuoto per errore di scrittura non è più una bugia per omissione).
- **H41** — testo delle fonti fuori dall'`argv` (via file temporaneo) e command line troncata negli errori.
- **H42** — `archive-data` montato `:ro` (verificato che i DB sono `journal_mode=delete`, non WAL).
- **H38/H15** — `secrets/`·`backups/`·`onboarding/` a `700`; `TS_AUTHKEY` monouso azzerata da `.env` dopo l'uso, `.env` a `600`, file orfano rimosso.
- **H13** — versioni `apk` pinnate nel container di backup.

**Ri-verifica del già-fatto — la regola ha pagato:**
- **H30** (open-redirect, dato per chiuso in v0.21.0) aveva un **bypass reale**: `startswith(base)` è un match di *prefisso*, non di *origine* — `https://host.evil.com/` superava il gate. La logica è ora in un modulo puro con 12 test d'attacco.
- **H24** — i tag `v*` sono **immutabili** (ruleset GitHub `deletion + update`, in `security/rulesets/`). Provato sul campo: spostare o cancellare un tag è rifiutato, crearne uno nuovo no. *La regola `non_fast_forward` non bastava*: spostare un tag in avanti è un fast-forward.

**Portati avanti in parziale, onestamente** (H12 sudo whitelist ma docker resta root-equiv; H16 password nasce sul PC ma il chiaro passa se manca bcrypt; H37, H43, H35, H8, H9, H18, H22, H31, H32, H34): il *cosa manca* di ognuno è nel registro, che la CI verifica sia dichiarato.

Nessun claim senza coordinata: `security/check_findings.py` è verde e i conteggi in `SECURITY.md` combaciano col registro per costruzione.

## [0.31.0] — 2026-07-14

### Il registro dei rilievi — «dichiarato fatto ma assente» ora è una build rossa

La campagna di hardening ha prodotto, oltre ai fix, **tre patologie** che vale la pena nominare perché non sono di questo progetto soltanto: *dichiarato fatto ma assente*, *soluzione scritta ma non applicata*, *fix che introduce un bug altrove*. Sotto le tre c'è **una** causa sola, e viene dall'angolo della provenienza: **una dichiarazione di sicurezza non ha coordinate**. Quando `SECURITY.md` ha scritto «il dossier è applicato per intero», quella frase non puntava a *nulla* — nessun file, nessuna riga, nessun test. Un claim infalsificabile non può marcire rumorosamente: marcisce in silenzio.

- **`security/findings.yml`** — i 43 rilievi del dossier, ciascuno con stato (`closed`/`partial`/`open`) e, se chiuso, l'**evidenza puntuale**: i pattern che devono esistere (o non esistere più) nei file. L'evidenza è ancorata al *contenuto*, non al numero di riga, così regge mentre il codice si muove.
- **`security/check_findings.py`**, in CI a ogni PR. Fallisce se: una voce `closed` non porta evidenza o la sua evidenza **è sparita dal codice**; un residuo non dichiara **cosa manca**; oppure i conteggi in `SECURITY.md` **non combaciano col registro**. Quest'ultimo controllo chiude il cerchio: il documento di sicurezza non può più dichiarare più di quanto il codice faccia — è lo scostamento doc↔codice che il dossier stesso denuncia in `H21`.

Il gate ha ripagato **prima di entrare in CI**: alla prima esecuzione ha trovato un errore di conteggio introdotto venti minuti prima in `SECURITY.md` (8/17/18 invece di 8/16/19). Il numero corretto è ristabilito.

Stato reale, ora verificato dalla macchina: **8 chiusi · 16 parziali · 19 aperti** su 43. Chiusi entrambi i critici.

## [0.30.2] — 2026-07-14

### Correzione — il dossier NON era applicato per intero (e una tar-bomb che avevo lasciato aperta)

Una verifica voce-per-voce dei 43 interventi del dossier **contro il codice** (non contro il ricordo) ha smentito una dichiarazione fatta nella v0.30.0 e ripetuta in `SECURITY.md`.

- **`SECURITY.md` diceva il falso in pubblico**: *«Nessuno dei rilievi della review è rimasto aperto»*. Il conteggio vero è **8 chiusi, 16 parziali, 19 aperti** su 43. Chiusi sono **entrambi i critici** (owner-gating fail-closed, cosign obbligatorio) e la sostanza della fascia alta — il resto no. La sezione *Residui noti* ora elenca i residui che pesano davvero, con il loro codice: cookie Google in chiaro nello snapshot pre-update (`H14`), tag `v*` non protetti (`H24`), sessione admin non revocabile (`H20`), operator con `sudo NOPASSWD: ALL` (`H12`), nessun 2FA (`H28`). È lo stesso scostamento doc↔codice che il dossier denuncia in `H21`: dichiararlo è l'unico modo di non ripeterlo.
- **Tetti sul decompresso nell'upload del profilo NotebookLM** (`H39`): il cap di 5 MB imposto dal gateway è sul tar **compresso**, e non dice nulla su quanto quel tar si espande. `nlm_profile.py` estraeva senza guardare né la dimensione dichiarata dei membri né i byte cumulativi: **una tar-bomb da meno di 5 MB compressi poteva riempire il volume**. Ora c'è un tetto per-file (16 MB) e cumulativo (64 MB), la lettura è a blocchi, e il rifiuto non lascia residui né tocca il profilo buono (un profilo `nlm` vero pesa qualche decina di KB). Due test nuovi lo dimostrano.

## [0.30.1] — 2026-07-14

### Fix — ruotare `gateway_secret` non rompe più il canale interno

Regressione introdotta dalla v0.30.0 e trovata rileggendo i piani di lavoro futuri, prima che mordesse. Con H6 il `gateway_secret` ha smesso di essere *solo* il namespace dell'URL: è **anche** il segreto con cui gateway e bot si autenticano verso gli endpoint interni di `nb1777-mcp`. Ma `rotate-secret.sh` riavviava **solo il gateway** — lasciando `nb1777-mcp` e il bot col segreto **vecchio**: il canale interno avrebbe risposto **403**, `/admin/nlm` avrebbe detto "nb1777-mcp non raggiungibile" e il bot avrebbe creduto l'auth NotebookLM mancante.

- `tools/rotate-secret.sh`: la rotazione di `gateway_secret` riavvia **tutti i consumatori** (`gateway nb1777-mcp nb1777-bot`).
- `docs/SECRETS.md`: la tabella dei secret dice ora chi legge davvero il `gateway_secret` (tre servizi, non uno), e lo snippet di rotazione manuale riavvia tutti e tre, col perché.

Verificato sul campo che il riavvio basta: i Docker secret con sorgente `file:` sono **bind mount** (non copie), quindi il container vede subito il contenuto nuovo e il restart lo fa rileggere.

## [0.30.0] — 2026-07-14

### Hardening H6 — il gateway non tocca più i cookie Google (l'ultimo finding aperto)

Era l'unico rilievo del dossier rimasto non applicato. Il gateway — **l'unico servizio esposto su Internet** — montava in **scrittura** il volume `nlm-auth`, cioè i cookie di sessione Google di NotebookLM, perché `/admin/nlm` ci estraeva dentro il profilo caricato. Un gateway compromesso poteva leggerli **e** riscriverli. Finding: area 04 (H6, alto).

Ora vale un invariante semplice: **il volume dei cookie lo monta SOLO `nb1777-mcp`**, che è il servizio che quei cookie li usa davvero. Gateway e bot hanno **accesso zero** — né lettura né scrittura — e chiedono a lui su rete interna.

- **Endpoint interni su `nb1777-mcp`** (`/internal/nlm/status`, `/internal/nlm/profile`): il primo dice solo *se* c'è un profilo valido (`{ok, has_cookies, pending}`) senza esporne il contenuto; il secondo riceve il tar.gz, lo valida e lo installa. Protetti da un **segreto condiviso** (`X-Vps1777-Internal`, confronto constant-time) e **fail-closed**: senza segreto configurato negano tutti. Si riusa il `gateway_secret` — che esiste su ogni installazione — invece di introdurre un secret nuovo, che mancherebbe agli update esistenti (compose non parte se il file del secret non c'è).
- **Il proxy non attraversa `internal/`**: il reverse proxy MCP è un catch-all su `{path:path}`, quindi senza un blocco esplicito un client esterno avrebbe raggiunto quegli endpoint via `/<SECRET>/<service>/internal/…` — creando proprio la via di scrittura che H6 chiude. Ora ogni sotto-path `internal/` è rifiutato con 404 **prima di ogni altro controllo**, per **tutti** gli upstream: chi scrive un plugin ha un prefisso riservato di cui fidarsi.
- **Upload non distruttivo**: il profilo si estrae in una staging, si **valida**, e solo allora sostituisce quello buono (con rollback se lo swap fallisce). Un tar sbagliato non ti scollega più da NotebookLM. Restano le difese sull'archivio non fidato (solo file regolari → niente symlink; niente path assoluti né `..`; solo sotto `profiles/`; file a 600).
- Il **bot** non monta più il volume: per sapere se l'auth manca chiede lo stato (fail-safe: se `nb1777-mcp` non risponde, assume auth pendente e mostra la guida).

Verificato: 12 test nuovi sul modulo che possiede il profilo (traversal, symlink, tar corrotto, non-distruttività) e prova end-to-end del servizio — 403 senza segreto e col segreto sbagliato, upload valido → `{"files":2}`, upload invalido → 400 **col profilo buono intatto**, cookie a 600.

**Con questo sono chiusi entrambi i finding CRITICI e la sostanza della fascia alta.**

> **Correzione (v0.30.2).** Questa riga, in origine, diceva *«il dossier è applicato per intero»*. **Era falsa** e va corretta invece che nascosta: il dossier ha 43 interventi, e una verifica voce-per-voce contro il codice ne conta **8 chiusi, 16 parziali, 19 aperti**. Chiusi sono i due critici e il grosso della fascia alta; restano aperte voci reali (i cookie nello snapshot pre-update, la protezione dei tag, la revoca della sessione admin, i sudoers dell'operator). L'elenco onesto sta in [SECURITY.md](SECURITY.md#residui-noti--cosa-non-è-ancora-chiuso).

### `vps1777 update` — la proprietà degli artefatti non deriva più

`vps1777 update` è pensato per girare come **operator** (che ha sudo NOPASSWD), ma capita di lanciarlo da una shell root. In quel caso le cartelle create — `releases/vX.Y.Z/` — restavano di **root**, e l'update successivo, lanciato dall'operator com'è giusto, non riusciva più a creare la cartella di rollback lì dentro: moriva con un `PermissionError` grezzo a metà strada (dopo il pull, prima del punto di non ritorno).

- Nuova `reclaim_ownership()`: ciò che l'update crea sotto il repo resta dell'operator. Riallinea nei due versi — da root chowna a chi possiede il repo; da operator si riprende con `sudo` ciò che trova altrui. **Nessun intervento manuale.**
- Se nonostante tutto la scrittura fallisce, ora si muore con un messaggio che dice cosa fare, non con un traceback.

## [0.29.0] — 2026-07-14

### Hardening segreti/host — segreti fuori dall'argv (deploy) e docker.sock fuori dal backup

Due finding dell'area 04 chiusi; il terzo (H6) è documentato come residuo che richiede una sessione con l'owner (vedi sotto).

**H7 — segreti nell'argv dei comandi remoti (`deploy.sh`), alto.** Durante il deploy i segreti (tailscale authkey, bot token, password admin) finivano nell'argv di comandi remoti, visibili via `ps` a ogni utente locale della VPS:

- Lo script di setup, prima passato come argomento di `bash -lc` (l'intero testo coi segreti in argv), ora viaggia nello **STDIN di `bash -s`** (canale SSH cifrato) — sia nel deploy iniziale sia in `--apply`.
- `set_kv` riscritto con soli **builtin** (`printf`-redirect): il valore non finisce più nell'argv di `sed`/`echo`.
- L'hash bcrypt della password legge il valore da **stdin**, non da `sys.argv`.
- `tailscale up` usa **`--authkey=file:`** (chiave via stdin → file temporaneo 600 → letta dal file, poi rimossa) invece di `--authkey=<segreto>` in argv.
- Verificato: le tecniche (bash -s, set_kv builtin idempotente, bcrypt-da-stdin, authkey stdin→file 600) testate in isolamento sulla VPS. Il flusso completo `deploy.sh --apply` non è stato eseguito contro la produzione (riconfigura l'intero stack) — verificato per lettura + test delle tecniche.

**H13 — `docker.sock` nel container di backup, medio-alto.** Il container `ops.backup` montava `/var/run/docker.sock:rw` (controllo root-equivalente dell'host) per dumpare i volumi via `docker run`:

- Rimosso il mount di `docker.sock` **e** l'installazione di `docker-cli`. I volumi dati sono ora montati **direttamente in sola lettura** (`/volumes/<nome>`) e `backup.sh` li tara da lì (`BACKUP_VOLUMES_DIR`). `backup.sh` resta dual-context: sull'host usa `docker run` come prima; nel container usa i mount diretti.
- Verificato: un backup one-shot contro i volumi reali di produzione, **senza docker.sock**, ha prodotto un `.tar.age` valido (95,8 MB coi 3 volumi + config + secrets).

**H6 — il gateway monta rw i cookie Google (`nlm-auth`), alto — RESIDUO documentato.** `/admin/nlm` scrive il profilo NotebookLM caricato direttamente nel volume, quindi il gateway (l'unico servizio esposto) ha accesso in scrittura ai cookie di sessione Google. Il fix corretto — un endpoint interno su `nb1777-mcp` che riceve l'upload e possiede lui i cookie, con il gateway ad accesso-zero — è un cambio d'architettura su un flusso core (il login NotebookLM) che non è verificabile end-to-end senza la sessione Google dell'owner. Rinviato a una sessione con l'owner per non spedire non verificato. Nota: rendere il mount `:ro` non basterebbe (il gateway deve comunque *leggere* la dir per lo stato → la lettura già espone i cookie); serve l'accesso-zero.

## [0.28.0] — 2026-07-14

### Hardening rete — `forwarded_allow_ips` ristretto (IP client non più spoofabile)

Il gateway girava con `forwarded_allow_ips="*"`: uvicorn si fidava dell'header `X-Forwarded-For` da **qualunque** peer, quindi `request.client.host` era falsificabile via header. Conseguenza: il rate-limit e il lockout del login per-IP erano evadibili (un IP finto diverso a ogni richiesta → contatore sempre fresco) e l'audit avvelenabile. Finding: area 03 (H4, alto).

- **`GATEWAY_FORWARDED_ALLOW_IPS`** (nuovo, default `127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16`): ci si fida dell'XFF **solo** dai range privati + loopback, **mai** da un IP pubblico. Il reverse-proxy (tailscale sull'host, o caddy/cloudflared in container) arriva sempre dalla bridge Docker privata; un client pubblico che colpisse la porta direttamente non è fidato e il suo XFF è ignorato. Il default copre le subnet Docker dinamiche (172.16–172.31) senza configurazione.
- **Verificato sul path di produzione live** (Funnel): con la trust-list ≠ `*` uvicorn cammina l'XFF **da destra** e prende il primo host non fidato. `tailscale serve` sanifica l'XFF — un `X-Forwarded-For: 6.6.6.6` iniettato dal client viene **scartato** e resta il vero IP (195.x). Richiesta pulita e richiesta spoofata loggano entrambe l'IP client reale, non quello iniettato.
- **Contatore globale valutato e scartato**: una volta chiuso lo spoofing, il rate-limit per-IP torna a mordere sull'IP reale dell'attaccante; un limite globale sugli endpoint auth aggiungerebbe rischio di auto-lockout dell'owner per beneficio marginale su un sistema mono-utente. `semplificare è ok`.

## [0.27.0] — 2026-07-14

### Hardening CI/supply-chain — action pinnate a SHA, Dependabot, least-privilege

La catena di fornitura della CI non può più iniettare codice tramite un tag ripuntato a monte, e il token di release non concede più del necessario. Findings: area 05 (H22/H23/H24).

- **SHA-pin di tutte le GitHub Action** (H23): da tag major mobile a **commit SHA pieno**, con la versione umana nel commento. Caso peggiore risolto: `aquasecurity/trivy-action@master` (branch mobile) → tag rilasciato `v0.36.0` pinnato. Coperti `ci.yml`, `release.yml`, `trivy.yml` (10 riferimenti).
- **Dependabot** (`.github/dependabot.yml`): perché il pin non invecchi. Ecosystem `github-actions` settimanale (bumpa SHA + commento versione, raggruppato); `docker` (base image dei Dockerfile, un servizio a directory); `docker-compose` (immagini di terzi). Le immagini vps1777 su ghcr sono ignorate: le versiona il release-flow.
- **Permessi least-privilege per-job** in `release.yml` (H24): prima un blocco unico al workflow dava a `guard` — che legge soltanto — `packages:write` + `id-token:write` inutilizzati. Ora `guard` = `contents:read`; `release` = `packages:write` + `id-token:write` (push GHCR + firma keyless); `bundle` = `contents:write` + `packages:read` + `id-token:write`. `ci.yml` floored a `contents:read`.
- **Digest-pin immagini di terzi nei compose** (H22): `tag@sha256` (tag tenuto come commento) per `alpine:3.20`, `caddy:2.8-alpine`, `cloudflare/cloudflared:2024.12.0`, `portainer/portainer-ce` (era il tag mobile `:lts`), `containrrr/watchtower:1.7.1`. Le 4 immagini vps1777 restano parametrizzate `${VPS1777_TAG}` e verificate contro `images.lock` da `vps1777 update`.

## [0.26.0] — 2026-07-13

### Hardening lotto 5 — la chiave di backup fuori dalla VPS (`age`)

Il backup cifrato resta (scelta dell'owner: mantenerlo, semplificato), ma la chiave privata torna a proteggere davvero. Prima `backup.sh` generava la coppia **sulla VPS** se il recipient mancava, mettendo la chiave privata **sullo stesso disco dei backup**: chi ruba o perde il disco ha (o perde) entrambi, e la cifratura non protegge da nulla (finding 2.4).

- **Niente auto-keygen sulla VPS**: `backup.sh` senza recipient si ferma e istruisce a generare la coppia **sul PC**, dove resta la privata.
- **Container backup senza chiave privata**: rimosso il mount di `keys.txt` — il backup cifra con la sola chiave **pubblica** (recipient); la privata serve solo al restore, dal PC.
- **`docs/BACKUP-RESTORE.md` riscritta**: dove sta cosa (privata sul PC, recipient sulla VPS), perché conta, la **migrazione** per chi ha già una chiave sulla VPS (copiala sul PC, poi rimuovila), e il fatto che l'off-site dei `.tar.age` è una **scelta dell'owner** (la cartella `backups/` la porti tu su NAS/cloud) — vps1777 non trasferisce nulla in automatico.

Findings: area 04 (2.4 media-alta). Resta separato il container backup con `docker.sock` (2.8/H13).

## [0.25.0] — 2026-07-13

### Hardening lotto 4 — rate-limit sugli endpoint auth + audience del proxy

- **Rate-limit per-IP** sugli endpoint di autenticazione pubblici, che finora avevano solo il lockout del login admin: `/register` (10 ogni 5 min), `/token` (60 al minuto), `/app/auth` (20 ogni 5 min). Nuovo modulo `RateLimiter` (stdlib, 4 test). Ferma la raffica da singola sorgente; difesa best-effort in-memory (si azzera al restart).
- **Audience del proxy MCP**: il reverse-proxy accettava **qualunque** access token valido senza verificare a chi appartenesse. Ora il token è legato al **proprietario** — il `sub` dev'essere un'email ammessa (`oauth_allowed_emails`). vps1777 è single-owner: un token il cui soggetto non è l'owner non passa il proxy.

Findings: aree 03 (R5 media), 01 (R1 parte). Lotti sicuri in autonomia; restano rete e segreti (con l'owner).

## [0.24.0] — 2026-07-13

### Hardening lotto 3 — privacy & logging

- **`gateway_secret` fuori dai log**: il secret vive nel path del proxy MCP (`/<secret>/<service>/…`), quindi finiva nella request-line dell'access-log in chiaro — un leak continuo, una riga per ogni chiamata MCP. Nuovo filtro `RedactSecrets` (stdlib, testato) lo sostituisce con `***` in ogni record. Difesa a valle: non sostituisce la rotazione del secret, ma smette di produrne di nuovi in chiaro.
- **Comandi RAG del bot disattivabili** (`BOT_RAG_COMMANDS=0`): `/lista` e `/chiedi` fanno transitare titoli e risposte dai server **Telegram** (Bot API non è E2E). Chi vuole la massima privacy li spegne e usa la **Mini App**, che parla solo col gateway. Default: attivi.
- **Retention dell'audit** (`AUDIT_RETENTION_DAYS`, default **90**, personalizzabile): le righe più vecchie vengono potate quando il file supera 5 MB — niente più crescita illimitata di un log che contiene IP, email e user_id.
- **`SECURITY.md`**: corretto il claim "zero telemetria" (vero per vps1777, ma i dati **funzionali** escono verso Google/Telegram) + nuova tabella **"Flussi di dati verso terzi"** (cosa esce verso chi) + email di contatto reale per le segnalazioni (era `[da configurare]`).

Findings: aree 03 (R1 alta), 06 (2.3, 2.8), 02 (2.10), 05 (R6).

## [0.23.0] — 2026-07-13

### Hardening lotto 2b — verifica firma `cosign` obbligatoria (il 2° dei due CRITICI)

Le release sono sempre firmate (`cosign` keyless in `release.yml`) e il CLI aveva già la logica di verifica — ma era **saltata in silenzio** quando `cosign` non era installato (default `require_cosign=False`). Su un'installazione senza `cosign` il self-update faceva `sudo install` ed eseguiva codice dal bundle **senza verificarne la firma**.

- **Verifica `cosign` obbligatoria di default** (fail-closed): se la firma non è verificabile, l'update si ferma invece di procedere.
- **Auto-installazione di `cosign`**: se manca, il CLI lo installa da sé (binario pinnato `v2.4.1`) invece di dipendere dal deploy iniziale — copre anche le installazioni esistenti. Se l'installazione non riesce → fail-closed (non salta la verifica).
- **Via d'emergenza consapevole**: `VPS1777_REQUIRE_COSIGN=0` nel `.env` o `--no-require-cosign`, propagata anche al re-exec del self-update.
- **Prima di attivare il default**, verificato sul VPS che `cosign` valida la firma di una release reale (v0.22.0 → *Verified OK*), così il canale update non si blocca.

Findings: area 05 (R1 CRITICO). Con questo, **entrambi i critici della review sono chiusi**.

## [0.22.0] — 2026-07-13

### Hardening lotto 2 — owner-gating fail-closed (il 1° dei due CRITICI)

`is_owner` con `owner_id` non configurato (`0`, o coerzione silenziosa di un valore malformato nel `.env`) ritornava **True** ("nessun filtro"): un `TELEGRAM_OWNER_ID` vuoto o storto in produzione avrebbe aperto **bot e Mini App a QUALUNQUE utente Telegram** con `initData` valida — accesso al pannello completo (URL MCP col gateway secret, RAG, archivio, audit, trigger update).

- **`is_owner` ora fail-closed**: `owner_id==0` → nessuno è owner. Se non sappiamo chi è l'owner, non lo è nessuno.
- **Mini App `/app/auth`**: `503 owner_not_configured` quando l'owner manca — errore chiaro invece di aprirsi a tutti.
- **Bot `owner_only` fail-closed**: `if owner_id and …` corto-circuitava su `0` e rispondeva a chiunque; ora senza owner nega a tutti.
- **Menu button della Mini App per-chat** (`chat_id=owner`): era impostato globale → visibile a ogni utente del bot.
- **Warning all'avvio** del gateway se l'owner è assente; messaggio di `setup.sh` corretto (bot **e** Mini App negati finché non impostato).

Findings: area 02 (2.1 CRITICO, 2.2). Verificato che `TELEGRAM_OWNER_ID` è impostato in produzione → **zero impatto sull'accesso dell'owner**.

## [0.21.0] — 2026-07-13

### Hardening lotto 1 — quick-wins auth/gateway (dalla review difensiva)

Primo lotto dell'applicazione della review difensiva, ri-verificata sul codice attuale prima di agire (6 agenti paralleli, un'area ciascuno). Sei fix chirurgici, testabili, **zero rischio di lockout**:

- **Open redirect** sul parametro `next` del login: `//host` e `/\host` iniziano con `/` ma sono protocol-relative (redirect esterno) — ora rifiutati.
- **`state` OAuth url-encoded** nella redirect finale: un `&`/`#` nello `state` scelto dal client non spezza più la query di redirect.
- **`code_challenge` vuoto rifiutato** in `/authorize`: senza challenge la PKCE non protegge il code — meglio 400 che un code scambiabile.
- **CORS senza fallback wildcard**: origine non configurata → CORS **spento** (fail-closed), niente più `["*"]` accoppiato ai cookie con `allow_credentials`.
- **Header di sicurezza globali**: `Permissions-Policy` (nega camera/microfono/geolocalizzazione/usb) e `Cross-Origin-Opener-Policy: same-origin` su ogni risposta.
- **Login fallito non logga più l'email digitata**: chi sbaglia campo può averci scritto la password — ora l'audit registra solo se l'utente esiste (booleano), utile al triage senza conservare un segreto.

Findings: aree 01 (R3, R6, R8, R9), 03 (R6, R9), 06 (2.4). Primo di 7 lotti.

## [0.20.0] — 2026-07-13

### L'archivio indicizza il contenuto pieno — le azioni non sono rumore

L'indexer scartava **il 62% di quello che gli veniva dato**, e non era rumore: erano **le azioni**. Un archivio di sole dichiarazioni non può contraddire una frase con un fatto — una ricerca su un tratto identitario premia la dichiarazione più esplicita, chiunque l'abbia pronunciata, perché non esiste nessuna azione che la smentisca.

- **`extract_blocks()`** scompone il `content` in `(text, tools, thinking, attachments)` invece di buttarlo (`extract_text()` resta come wrapper retrocompatibile). Prima, per l'export claude.ai il campo `content` non veniva letto **nemmeno una volta** (il ramo `text or extract_text(content)` cadeva sempre a sinistra), e i messaggi di soli `tool_use` sparivano in silenzio.
- **Schema v2** (`+sender +tools +thinking +attachments +parent_uuid`). `tools` e `attachments` **vanno nell'FTS** (sono ciò che si cerca); `thinking` si **conserva ma non si indicizza** (~9.400 blocchi di ragionamento che inquinerebbero ogni `MATCH`/`bm25` — chi li vuole cercabili usa il column filter `col:` già supportato da `fts.py`). Migrazione `migrate_v1_to_v2()` idempotente, che non perde righe; le righe a 4 campi restano accettate (un estrattore esterno non si rompe).
- **L'upload non filtra più a monte**: anche `users.json` (che era scartato) viene indicizzato. Il filtro sta a valle, non all'ingest.
- Sull'export reale: da 42,4 M a **128,5 M** di caratteri indicizzati (**3,03×**); **1.440** messaggi con allegati che prima non c'erano. Chiude **#22**.

### Privacy — dichiarato cosa contiene l'archivio e come è protetto (#24)

Indicizzare il contenuto pieno rende **cercabili** anche i segreti incollati durante il lavoro (password, chiavi, IP). Scelta consapevole (opzione D): l'archivio è un contenitore di dati personali, la protezione è l'**accesso** (gateway OAuth 2.1 + path-secret, owner-only), non la redazione. Nuova sezione **"Dati sensibili e privacy"** in [docs/ARCHIVE.md](docs/ARCHIVE.md): cosa contiene, che chiunque abbia accesso lo trova con una query, e che una strategia di redazione/cifratura va decisa **prima** di condividere o esporre l'archivio. Chiude **#24**.

## [0.19.1] — 2026-07-13

### Fix — `studio_rename` ora funziona (nb1777-mcp)

Affrontando la issue #21 (che segnalava 4 comandi disallineati alla CLI `nlm`): verificando alla fonte, **tre erano già a posto** — la *source family* era stata allineata a `nlm` 0.7.x in un commit precedente, con i relativi contract test. L'unico ancora rotto era **`studio_rename`**, sfuggito perché il contract test copriva `source` ma non `studio`.

- **`studio_rename`** passava `notebook_id` come argomento posizionale, ma `nlm studio rename` vuole `ARTIFACT_ID NEW_TITLE` (l'artifact id è globale, niente notebook — a differenza di `studio delete`, che invece lo richiede). L'id di troppo faceva slittare gli argomenti → *"unexpected extra argument"*, comando **inutilizzabile**. Ora `nb_id` resta nella firma MCP ma **non** si inoltra alla CLI.
- **Contract test esteso a `studio`** (`rename`/`delete`): blocca proprio l'asimmetria che aveva ingannato il wrapper (rename senza notebook, delete con).
- Validato con `nlm` reale sul VPS: 3 posizionali → errore di parsing; 2 posizionali → comando ben formato.

Chiude #21.

## [0.19.0] — 2026-07-11

### archive-mcp: ricerca onesta, leggibile e potente

Emerso da un collaudo sperimentale della ricerca (paper con 4 subagent, ~130 chiamate): l'FTS5 era potente ma con un difetto capitale, e mancavano strumenti per leggere e misurare. Riscrittura della logica di ricerca, retrocompatibile.

- **Bug capitale — falsi negativi silenziosi (fix).** Un errore di sintassi FTS5 è un `sqlite3.OperationalError`: prima veniva **inghiottito** (`db.py`) e `search` restituiva lista vuota, indistinguibile da "nessun risultato" — lo strumento nato per non dimenticare produceva l'illusione opposta ("non ne abbiamo mai parlato" per un trattino non quotato). Ora una query malformata **solleva un errore parlante** che spiega come correggerla; i 0-risultati veri restano 0.
- **Auto-quoting difensivo (smart mode, default).** I termini con caratteri speciali (`flutter-elinux`, `0.7.9`, `github.com`) vengono quotati dal server prima della `MATCH` — la trappola numero uno sparisce senza che il chiamante debba saperlo. Conservativo sulle query avanzate (NEAR, parentesi, `col:term`): le lascia intatte, con fallback all'originale. `raw=true` per passare la query così com'è.
- **Docstring-cookbook.** La docstring di `search` — ciò che ogni Claude client legge *prima* di cercare — ora contiene le regole dure (operatori MAIUSCOLI, doppia lingua, prefissi, quoting, protocollo dello zero): previene l'errore a monte, lato client.
- **Nuovi tool.** `count(query)` (frequenze/prevalenze, prima impossibili); `get_context(uuid, before, after)` (i messaggi attorno a un risultato col **contenuto pieno**, supera il troncamento dello snippet); `describe_databases()` (righe, intervallo date, etichette, **snapshot** di freschezza per DB). `list_databases` invariato per compatibilità col connettore.
- **Ricerca più espressiva su `search`** (parametri opzionali, retrocompatibili): `sort` (`rank`/`newest`/`oldest`), `since`/`until`, `project`, `snippet_tokens`; su più DB il **`limit` è globale** e i risultati sono **fusi e ri-ordinati per rilevanza**, non più concatenati per DB. Ogni riga porta `snapshot` (freschezza del DB) — cura il "paradosso della memoria che invecchia".
- **Primi test del servizio.** `archive-mcp` non aveva alcun test: nuovo modulo `fts.py` (stdlib-only, come `archive_indexer`) con 20 test, in CI via `uvx pytest`.

Fuori da questa release, segnalati dal collaudo ma appartenenti ad altri strati: sync automatico del catalogo `masterIndex1777` (bibliotecario1777/NotebookLM, non vps1777) e le skill "Registro delle Promesse"/"Verificatore di Memorie" (pattern per `create1777`).

## [0.18.1] — 2026-07-10

### Fix — la pagina admin non propone più downgrade (e il checker non ci casca)

Caso reale: 2 minuti dopo la publish della v0.18.0, `/releases/latest` di GitHub ha servito dalla cache **v0.16.1** (più vecchia perfino della v0.17.0 di 4 ore prima) — l'endpoint non è monotono. La pagina `/admin/update` mostrava «Aggiornamento disponibile: v0.16.1 (sei alla 0.18.0)» col pulsante **"Aggiorna a v0.16.1"**. Il danno reale era già impossibile (la CLI host rifiuta i downgrade dal canale intent — la difesa in profondità ha retto), ma la UI mentiva. Tre livelli sistemati:

- **Checker host (`vps1777 check`)**: `latest` significa "la più nuova NOTA" — se GitHub risponde con una release più vecchia di quella già registrata, la risposta stantia si logga e si scarta (si aggiorna solo `checked_at`). La notifica Telegram parte solo per un **vero** upgrade (prima un downgrade stantio avrebbe notificato "v0.16.1 disponibile (sei alla 0.18.0)").
- **CLI (`vps1777 update`)**: una `latest` naturale più vecchia della versione in esecuzione è un **no-op** con messaggio chiaro, mai un prompt di downgrade. Il downgrade intenzionale resta possibile solo con `--version` esplicito.
- **Pagina `/admin/update`**: banner e pulsante ora usano `version_gt` (stesso gate della Mini App, che era già a posto), il confronto con la versione **in esecuzione** (env, non solo file di stato); check stantio → messaggio esplicativo, niente pulsante; il POST rifiuta comunque un non-upgrade (audit `admin_update_rejected`). Bonus: la conferma del pulsante era un `onsubmit` inline **silenziosamente bloccato dalla CSP** — ora è uno `<script>` con nonce e funziona davvero.

## [0.18.0] — 2026-07-10

### L'export HTML di Telegram si indicizza direttamente

Il formato **HTML è il default** di "Esporta cronologia chat" in Telegram Desktop, e il selettore JSON non è ovvio da trovare: chiedere all'utente di riesportare (come faceva la 0.16.1) era scaricare su di lui un problema del tool. Ora lo zip della cartella `ChatExport_*` si carica **così com'è**, in entrambi i formati.

- Nuovo estrattore `_iter_telegram_html_zip` + `_TgHtmlParser` (**stdlib**, `html.parser`): `div.message[id]` → data completa dal `title` (convertita in ISO ordinabile), `from_name`, `div.text` (entità decodificate, `<br>` → newline, testo dei link preservato); i messaggi **joined** ereditano il mittente precedente; service message e media senza testo saltati; `messages2.html`, `messages3.html`… letti in ordine numerico.
- Se lo zip contiene sia `result.json` sia `messages*.html` vince il **JSON** (più fedele). Avvertenza documentata: non mischiare HTML e JSON della stessa chat nello stesso DB (chiavi di dedup diverse → doppioni).
- Validato su **due export reali** (908 e 964 messaggi): estrazione 1:1 coi `div.text`, zero mittenti orfani, timestamp ISO col fuso, FTS ok.
- 5 test nuovi (50 totali gateway); aggiornati l'help di `/admin/archive` e [docs/ARCHIVE.md](docs/ARCHIVE.md).

## [0.17.0] — 2026-07-10

### Gestione dei DB archivio — lista completa ed eliminazione (admin + Mini App)

Prima i DB caricati erano solo un elenco nome+righe, e per toglierne uno serviva la shell. Ora:

- **Scheda per ogni DB** su `/admin/archive` e nella Mini App (tab Archivio): messaggi, **etichette distinte** e le principali (titoli chat, `project:*`, `design:*`…), dimensione su disco, ultimo aggiornamento. Il tutto da una nuova `db_info()` in `archive_indexer` (stdlib-only, testata).
- **Elimina con conferma** (bottone su entrambe le superfici): rimuove il `.db`, archive-mcp se ne accorge da solo (scan-mode), evento in audit (`admin_archive_delete` / `miniapp_archive_delete`). Irreversibile; il *reset* è elimina + ricarica la fonte con lo stesso nome (il dedup fa il resto).
- **Sicurezza**: il nome da eliminare è risolto **contro il listato reale** della dir (`find_db`, niente path costruiti dall'input → niente traversal); admin dietro CSRF (già centralizzato in `_require_admin`), Mini App dietro Bearer `typ=miniapp`; conferma via `showConfirm` Telegram (fallback `confirm`).
- `/app/api/archive/dbs` ora legge il volume condiviso direttamente (stessa fonte di `/admin/archive`) e ritorna la scheda completa, non più il semplice elenco nomi via MCP.
- CSS admin: stili tabella (prima erano i default del browser) e bottone `danger`.
- 3 test nuovi (47 totali gateway); aggiornati [docs/ARCHIVE.md](docs/ARCHIVE.md) e [docs/MINIAPP.md](docs/MINIAPP.md).

## [0.16.1] — 2026-07-10

### Fix — l'ingest archive non mente più sugli zip

Trovato collaudando `/admin/archive` con dati reali (export claude.ai da 325 MB + export Telegram):

- **Design chats indicizzate.** Nell'export claude.ai i messaggi delle design chats hanno il `content` **annidato** (`{"role", "content"}`), che `extract_text` non gestiva → 0 righe in silenzio. Ora si scende nel dict (ricorsivo) e le design chats entrano, etichettate **`design:<progetto>`** (il loro `title` è sempre il generico "Chat"; l'etichetta utile è il progetto di appartenenza).
- **Zip Telegram Desktop JSON supportato.** Prima ogni `.zip` era assunto export claude.ai; ora il dispatch guarda il **contenuto**: `result.json` (anche in sottocartella `ChatExport_*/`) → estrattore Telegram. Si carica direttamente lo zip della cartella esportata.
- **Mai più "ok, 0 record".** Uno zip **HTML** di Telegram (`messages.html`) viene rifiutato spiegando di riesportare in JSON; uno zip **non riconosciuto** viene rifiutato dicendo cosa ci si aspetta; uno zip riconosciuto ma **senza messaggi estraibili** è un errore (e non lascia un DB vuoto; un DB già popolato resta intatto). Stesso principio del rifiuto dei PDF-immagine.
- 7 test nuovi (44 totali gateway); aggiornati l'help di `/admin/archive` e [docs/ARCHIVE.md](docs/ARCHIVE.md).

## [0.16.0] — 2026-07-09

### Mini App Telegram completa — la plancia mobile di vps1777

Da placeholder a pannello production-ready, aperto dal bot (bottone **Pannello** / `/pannello`), **senza password**: l'identità arriva da Telegram e la verifica il server.

- **4 tab**: *Stato* (gateway, versione con badge release, connettori MCP con URL copiabile, riassunto secret) · *Notebook* (lista NotebookLM + **domanda RAG dal telefono**, con indicatore del tempo per le query lunghe) · *Archivio* (ricerca FTS5, tutti i DB o uno, snippet evidenziati) · *Sistema* (scadenze secret, **update a un tap** con conferma + progress in tempo reale — stesso meccanismo intent+CLI del pulsante admin — e ultimi eventi audit).
- **Backend `/app/api/*`** (10 endpoint JSON, tutti dietro Bearer `typ=miniapp`): il gateway chiama gli upstream MCP direttamente sulla rete backend (`mcp_client.py`); parsing SSE/JSON e initData in `miniapp_core.py` (stdlib-only, 21 test). Frontend *thin*: riusa gli stessi file di stato di `/admin`, zero logica duplicata.
- **Sicurezza**:
  - `initData` verificata **server-side** (HMAC col token bot, scadenza 24h) + **owner-only** (`TELEGRAM_OWNER_ID`, ora passato anche al gateway): un altro utente Telegram riceve 403 anche con initData valida — il bottone del bot non è il gate, il server sì.
  - **`/app/plugins` non è più pubblico**: era raggiungibile senza auth e restituiva gli URL MCP **col gateway secret** (leak). Ora è `/app/api/plugins`, dietro Bearer.
  - CSP con nonce per-risposta sulla pagina; `Cache-Control: no-store` su `/app/auth` e `/app/api/*` (middleware, path-based); niente CSRF necessario (Bearer header, mai cookie).
  - **Anti-downgrade alla fonte**: `available` usa un confronto di versione vero (`version_gt`), non `latest != running` — con un check giornaliero stantio la UI non propone più un downgrade, e il POST update lo rifiuta con 409 (trovato col collaudo E2E live).
- **Bot**: nuovo comando `/pannello` + **menu button** impostato automaticamente all'avvio (`set_chat_menu_button` → `PUBLIC_BASE/app`, solo se https).
- Validato **E2E sul VPS reale**: 29 check (auth positiva/negativa/manomessa, 401 su tutti gli endpoint senza Bearer, RAG reale su NotebookLM, anti-downgrade, CSP) — tutti verdi.
- Doc: nuovo **[docs/MINIAPP.md](docs/MINIAPP.md)**; aggiornati README, SECURITY.md, INSTALL.md, TROUBLESHOOTING.md (launcher BotFather stantio, not-owner), `.env.example`.

## [0.15.2] — 2026-07-09

### Fix/hardening — le pagine admin non vengono più servite dalla cache del browser

- **`Cache-Control: no-store` su tutte le risposte sotto `/admin`.** Le pagine di controllo devono dire *sempre* la verità: prima, una scheda admin già aperta poteva continuare a mostrare un render vecchio (es. la versione nel footer, ferma alla precedente dopo un update) finché non la si ricaricava a mano. Ora ogni navigazione rifetcha. Applicato **path-based nel middleware ASGI** → vale anche per ogni endpoint admin futuro, senza doverlo ricordare handler per handler (stessa logica "difesa a prescindere" del token CSRF). Le risposte non-admin (mini-app `/app`, `/health`, proxy MCP) restano invariate — nessun impatto sullo streaming.
- **Refactor testabile**: il middleware `SecurityHeadersASGI` è stato estratto in `app/asgi_security.py` (puro stdlib) e coperto da `tests/test_asgi_security.py` — la CI gira i test del gateway con `uvx pytest` senza deps pesanti, quindi il modulo dev'essere stdlib-only (come `archive_indexer`). Prima era inline in `__main__.py`, non testato.

## [0.15.1] — 2026-07-09

### Fix — l'installazione ora abilita il timer di check dei secret

- **`vps1777-secrets-check.timer` non veniva abilitato da nessun percorso d'installazione.** `deploy.sh` e `installer/engine.py` *copiavano* la unit in `/etc/systemd/system/` ma la riga `systemctl enable --now` elencava solo `vps1777-check-update.timer` + `vps1777-update.path`, dimenticando il timer dei secret. Risultato: su ogni **nuova installazione** il check settimanale delle scadenze secret (introdotto in 0.15.0) restava **spento** — la notifica Telegram di un secret scaduto non sarebbe mai partita. Scoperto col collaudo di una fresh install reale. Fix: aggiunto `vps1777-secrets-check.timer` alla riga di enable in entrambi i file. (`install_systemd_units` in `tools/vps1777.py` lo abilitava già; le installazioni esistenti vanno allineate a mano con `systemctl enable --now vps1777-secrets-check.timer`.)

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
