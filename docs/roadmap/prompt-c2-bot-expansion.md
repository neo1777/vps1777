# Prompt di onboarding — C2: Bot expansion (nb1777-bot)

> **Come usare questo file.** Prompt per una sessione dedicata (Claude Code, repo
> `vps1777`) che estende il bot Telegram. Copia il blocco sotto la riga come primo
> messaggio. Scritto per reggere il tempo: se lo lanci fra settimane, la sessione
> **prima verifica lo stato reale**. Nessun segreto: credenziali/URL li fornisci tu.
>
> **Rinfrescato il 2026-07-14** (base: v0.30.1). Il cambiamento che conta: **il
> nodo di scope del §3 si è parzialmente risposto da solo** — Neo ha spento i
> comandi RAG testuali in produzione. Leggi §3 prima di proporre comandi nuovi.

---

Sei incaricato di **estendere il bot Telegram `nb1777-bot`** di vps1777, oggi a 5
comandi, verso una copertura più ricca di NotebookLM. Ma il compito **non è
"clonare il vecchio bot"**: è **decidere insieme a Neo quale bot vogliamo** e
costruirlo bene. La ricognizione qui sotto smonta un mito e mette in luce una
tensione di design reale: leggila prima di scrivere codice.

## 0. Come lavorare (leggi prima di tutto)

- **Questa è una fotografia, non la verità corrente.** Prima di progettare, fai
  la **ricognizione dello stato reale** (§5): codice, memoria e archivio
  potrebbero essere cambiati, potrei aver già iniziato altrove. Se scopri che è
  già fatto o che le priorità sono cambiate, **fermati e dillo a Neo**.
- **Hai margine.** La direzione in §4 è una proposta motivata, non un binario.
  Il **nodo di scope** (§3) è una domanda aperta vera: portala a Neo, non
  deciderla di nascosto.
- **Metodo 1777:** italiano, tono da pari e asciutto; **fatti (file:riga)
  distinti dalle inferenze**; niente rassicurazione; verifica alla fonte, mai a
  memoria. (Questo prompt stesso corregge un "fatto a memoria" — vedi §2.)
- **Confini vps1777:** **owner-only** sul bot, ora **fail-closed** (senza
  `TELEGRAM_OWNER_ID` il bot non risponde a *nessuno*, v0.22.0); il bot parla
  **solo con `nb1777-mcp`** sulla rete `internal` — via MCP per i tool e, dalla
  v0.30.0, via un **endpoint interno HTTP** (`/internal/nlm/status`) per sapere se
  l'auth NotebookLM c'è; non ha docker.sock, **non monta più i cookie Google**
  (H6) e non tocca il sistema; azioni-sistema alla CLI host. Branch dedicato, mai
  `main`.

## 1. Cos'è vps1777 e dov'è il bot

Gateway MCP personale (Docker, HTTPS via Tailscale Funnel): OAuth + reverse proxy
MCP + `/admin/*` + Mini App `/app/*`; upstream su rete `internal`: `archive-mcp`,
**`nb1777-mcp`** (NotebookLM, ~35 tool), **`nb1777-bot`** (Telegram). Il bot è in
`services/nb1777-bot/app/bot.py`. Rilascio: branch → PR → CI (lint+contract+4
build) → tag `vX.Y.Z` → release GHCR → `vps1777 update` → E2E live. Versione in
`VERSION`.

## 2. Il mito da sfatare (verità tecnica)

La docstring del bot attuale dice: *"In F8 estendiamo a tutti i **~60** del
vecchio nb1777/bot.py"*. **È falso, verificato alla fonte.** Il bot legacy
(`~/Scrivania/mcp_dash/mcp1777/notebookllm1777/nb1777/nb1777/bot.py`, 742 righe;
copia identica in `.../workfiles/nb1777/nb1777/bot.py`) ha **19 CommandHandler**,
di cui ~17 user-facing. Non 60. Il numero giusto da cui partire è **~19**, e il
lavoro reale è ancora meno (vedi scope). Correggi quella docstring come prima cosa.

## 3. Il nodo di scope (la vera decisione — l'archivio lo rende esplicito)

C'è una **tensione documentata** su cosa deve essere il bot, che va risolta con
Neo prima di codificare:

- **Visione "granulare di tutto"** (originale, giu 2026): *«voglio che di base
  sia server mcp che collega bot telegram ↔ llm ↔ nbllm, con comandi granulari
  di tutto, bidirezionali per quanto possibile»* [archive1777 uuid 019ea1ca,
  2026-06-07]. Qui il bot espone CRUD completo di NotebookLM.
- **Visione "complementare"** (più recente): divisione delle superfici concordata
  — **bot = notifiche + launcher + comandi rapidi**, **Mini App = mobile, azioni
  frequenti**, **admin = desktop/pesante** (memoria `vps1777-miniapp`). E in altri
  contesti Neo stesso: *«comandi minimi /start /help … NON duplicare»* [uuid
  019e8a4b]. Qui il bot è snello e non ricopia la Mini App.

Le due visioni **confliggono**: la prima vuole ~tutti i comandi nel bot, la
seconda li tiene nella Mini App e lascia al bot solo l'essenziale + ciò che il
bot fa *meglio*. **Chiedi a Neo quale delle due (o quale sintesi) vuole ora.**
La mia raccomandazione — da discutere, non imporre — nel §4.

### ⚠️ Aggiornamento (v0.24.0 + prod, lug 2026): il nodo si è mosso da sé

Non è più una domanda del tutto aperta. Nel frattempo è successo un **fatto
datato** che pende netto verso il *complementare*:

- La v0.24.0 ha introdotto **`BOT_RAG_COMMANDS`**: `=0` **disattiva `/lista` e
  `/chiedi`**. Ragione: quei comandi fanno transitare titoli e risposte RAG dai
  **server Telegram**, e la **Bot API non è E2E**.
- **Neo l'ha impostato a `0` in produzione.** Cioè: sul bot reale, oggi, i comandi
  testuali RAG **sono spenti**, per privacy. La superficie che usa è la **Mini App**
  (che parla solo col suo gateway).

**Cosa ne segue per te (non ignorarlo):**
- Proporre *altri* comandi testuali che facciano passare **contenuto** da Telegram
  contraddirebbe una scelta esplicita dell'owner. Non farlo senza rimettere in
  discussione la scelta **con lui**.
- Il criterio di scope diventa più affilato: per ogni comando, chiedi **"che cosa
  esce da Telegram?"**. Un *segnale di controllo* ("crea l'artefatto", "è pronto")
  esce quasi a zero. Una *risposta RAG* o il *contenuto di una fonte* esce per
  intero. Sono due categorie diverse, e vanno trattate diversamente.
- Verifica alla fonte com'è oggi: `BOT_RAG_COMMANDS` in `.env` sulla VPS,
  `_rag_disabled()` in `bot.py`, e la tabella *Flussi di dati verso terzi* in
  `SECURITY.md` (dice esattamente cosa esce, verso chi).

## 4. Direzione tecnica proposta (non prescrittiva)

**Raccomandazione: non clonare il legacy, ma dare al bot ciò che è suo e che le
altre superfici non fanno bene.** Tre fasce:

1. **Ciò che il bot fa MEGLIO di tutti: notifiche push su operazioni lunghe.**
   Gli artefatti Studio (audio, video, mindmap, quiz, slides, report,
   infographic, data_table, flashcards) richiedono minuti (`studio_wait`).
   Lanciarli e **ricevere un ping quando sono pronti** è il vero superpotere del
   bot — la Mini App e l'admin non notificano. Qui il bot vince: `/artefatti`,
   creazione (uno o tutti e 9), `/scarica <tipo>`, con notifica async a fine job.
   → **Questa fascia esce rafforzata** dall'aggiornamento in §3: un "il tuo
   artefatto è pronto" è un *segnale*, non *contenuto* — leaka quasi nulla da
   Telegram, a differenza di una risposta RAG. È il pezzo più difendibile anche
   dal lato privacy. (Attenzione al **download**: se il bot spedisce il file
   dell'artefatto *dentro* Telegram, allora il contenuto esce davvero — decidi se
   mandare il file o solo un link alla Mini App, e dillo a Neo.)
2. **Comandi rapidi da tastiera** che in mobilità sono più veloci di aprire la
   Mini App: gestione notebook (`/nuovo`, `/rinomina`, `/cancella` con conferma
   inline), gestione fonti (`/fonti`, `/aggiungi <url>`, `/aggiungitesto`,
   `/cancellafonte`, upload file allegato → fonte), `/info <id>`, `/doctor`.
   Già presenti e da tenere: `/pannello` (=/app), `/start`, `/aiuto` — e
   `/lista`, `/chiedi`, che però **oggi sono spenti in produzione**
   (`BOT_RAG_COMMANDS=0`, §3).
   → **Passa ogni comando di questa fascia al filtro del §3**: quali fanno uscire
   *contenuto* da Telegram (una lista di titoli, il testo di una fonte) e quali
   sono solo *comandi* (crea, rinomina, cancella)? I secondi sono molto più
   difendibili dei primi. Se un comando utile leaka, valuta di farlo **agire** dal
   bot e **mostrare** dalla Mini App.
3. **Ciò che NON va nel bot** perché la Mini App lo fa meglio (UI ricca): la
   navigazione/lettura estesa, la ricerca archivio, il pannello di stato/update.
   Il bot le **lancia** (link alla Mini App), non le duplica.

**Nodi implementativi da affrontare:**
- **Operazioni lunghe async:** i comandi Studio non devono bloccare; serve un
  pattern job→notifica (task asyncio + `studio_wait` + messaggio a fine). È il
  pezzo di ingegneria più sostanzioso.
- **Flussi multi-step:** il legacy usava `ConversationHandler` per l'upload fonte
  (file → "a quale notebook?") e `/aggiungitesto`. Decidi se replicarli o
  semplificarli (es. argomenti in un solo messaggio con separatori).
- **`_mcp_call` attuale** (`bot.py`) è single-shot verso `nb1777_mcp_url` con
  `Accept` duale e timeout 300s: va bene per query brevi, ma per lo Studio async
  serve un pattern che non tenga aperta la richiesta per minuti.
- **Testabilità:** la logica pura (parsing argomenti dei comandi, formattazione
  delle risposte, dispatch) va isolata in un modulo **testabile** — la CI gira i
  test senza le deps pesanti (`python-telegram-bot`/`httpx`), quindi la logica
  parsabile dev'essere **stdlib-only** (pattern `miniapp_core`, `fts.py`). Oggi
  il bot **non ha test**: è l'occasione per i primi.

## 5. Ricognizione iniziale obbligatoria (prima di codice)

1. **Codice attuale:** `services/nb1777-bot/app/bot.py` per intero (5 comandi:
   start/aiuto/pannello/lista/chiedi; `owner_only` **fail-closed**; `_mcp_call`;
   `auth_pending()` — ora **async, via HTTP** verso l'endpoint interno di
   nb1777-mcp, non più leggendo il volume; `_rag_disabled()` — il gate di
   `BOT_RAG_COMMANDS`; heartbeat; `_install_menu_button`; error handler globale).
   `services/nb1777-bot/app/settings.py` (`nb1777_mcp_url`, `nlm_internal_base`,
   token, owner_id, `gateway_secret_file`, `bot_rag_commands`).
2. **Superficie nb1777-mcp** (~35 tool, ciò che il bot può esporre): `nb_list/
   create/delete/rename/describe/get`, `notebook_query`, `source_add_{url,file,
   text,youtube,drive}`, `source_{list,delete,rename,get_content}`,
   `studio_create_{audio,video,mindmap,quiz,slides,report,infographic,
   data_table,flashcards,all_9}`, `studio_{list,download,status,wait,rename,
   delete,export_to_docs,export_to_sheets}`, `doctor`. Verifica alla fonte in
   `services/nb1777-mcp/app/`.
3. **Legacy** (per riuso, non per copia): il file citato in §2 e il suo `cmd_help`
   (lista comandi per categoria: Notebook / Fonti / Chat / Studio / Mini App /
   Meta). Nota i pattern: `ConversationHandler`, `cb_delete_nb` (conferma inline),
   `on_document` (upload).
4. **Memoria:** `vps1777-miniapp` (divisione superfici), e ogni nota sul bot.
5. **Archivio `archive1777`:** cerca cosa Neo ha deciso sul bot e la divisione
   superfici — c'è materiale (il tema è più vecchio, indicizzato): parti dagli
   uuid 019ea1ca (visione "granulare di tutto") e 019e8a4b ("non duplicare"), poi
   `get_context` per leggerli interi. Usa il **protocollo dello zero** e la doppia
   lingua. Ricorda il **lag** dell'archivio (le decisioni recentissime potrebbero
   non esserci).
6. **Chiedi a Neo** il §3: quale bot vuole (granulare vs complementare), e se le
   notifiche push Studio sono la priorità.

## 6. Criteri di accettazione

- I comandi scelti (concordati con Neo) **funzionanti E2E sul bot reale**,
  owner-only (un non-owner riceve il rifiuto).
- Se includi lo Studio: **notifica push a fine job** dimostrata (lancio artefatto
  → ping quando pronto), senza bloccare il bot.
- Conferma inline sui comandi distruttivi (`/cancella`, `/cancellafonte`).
- Help (`/aiuto`) aggiornato e coerente coi comandi effettivi; docstring del bot
  corretta (il "~60" → il numero vero).
- **Primi test del bot** (logica pura stdlib-only, CI `uvx pytest`).
- Doc + CHANGELOG + VERSION; rilascio standard; verifica live a 4 container
  healthy; il menu button / Mini App restano funzionanti.

## 7. Libertà e limiti

Puoi: proporre uno scope diverso da §4 e motivarlo; dire quali comandi **non**
vanno nel bot; estendere (dillo prima) se scopri un tassello adiacente utile.
Non puoi: clonare il legacy per inerzia senza risolvere il nodo §3; far parlare il
bot con qualcosa che non sia `nb1777-mcp` (via MCP per i tool, via il suo endpoint
interno per lo stato auth); **aggiungere comandi che fanno uscire contenuto da
Telegram senza discuterlo con Neo** (ha spento i RAG apposta — §3); lavorare su
`main`; dichiarare fatto senza E2E sul bot reale; duplicare nel bot ciò che la
Mini App già fa meglio senza una ragione.

## 8. Riferimenti

- Codice: `services/nb1777-bot/app/{bot,settings}.py`, `services/nb1777-mcp/app/`,
  `compose.yaml`.
- Legacy: `~/Scrivania/mcp_dash/mcp1777/notebookllm1777/nb1777/nb1777/bot.py`.
- Doc: `docs/MINIAPP.md` (divisione superfici), `docs/ARCHITECTURE.md`.
- Memoria: `vps1777-miniapp`.
- MCP: `archive1777` (search/count/get_context; il server è v0.19.0, 5 tool).
