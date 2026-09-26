# Archivio di ricerca (archive1777)

`archive1777` è un motore di ricerca full-text (SQLite FTS5 + BM25) sui tuoi
corpora: chat, sessioni, note, documenti. **Nasce vuoto**: lo popoli tu, dal
pannello admin o da riga di comando. I DB caricati sono cercabili **subito**,
senza riavvii, attraverso i **15 tool MCP** di `archive-mcp` (vedi
[Cercare — i tool MCP](#cercare--i-tool-mcp)): dalla ricerca (`search`,
`search_ibrida`, `count`) alla lettura (`get_context`, `get_conversation`) fino
alle schede di sessione e alle stirpi (`get_session`, `get_stirpe`).

> **Traduzione.** Questa pagina ha una traduzione inglese completa in
> [docs/en/ARCHIVE.md](en/ARCHIVE.md), tenuta allineata da un test della CI: chi
> modifica l'italiano deve aggiornare anche l'inglese.

## Dati sensibili e privacy — leggi prima di caricare

L'archivio indicizza **tutto ciò che carichi, verbatim** (il filtro sta a valle,
non all'ingest: un ingestore che scarta metà del file mente su cosa contiene).
Le tue chat e sessioni contengono, di fatto, **dati personali e segreti**: email,
numeri di telefono, e — capita — **credenziali, chiavi SSH, IP e token incollati
durante il lavoro**. Dalla v0.20.0 viene indicizzato anche il **contenuto pieno**
dei messaggi (le *azioni*: comandi lanciati, file aperti, output di tool), quindi
anche quei segreti diventano **cercabili**. È corretto — li hai caricati tu — ma
va saputo.

**La protezione principale è l'ACCESSO.** L'archivio è raggiungibile solo
attraverso il gateway (**OAuth 2.1 + path-secret**) ed è **owner-only**: chi non ha
i token MCP non entra. Il DB su disco è **in chiaro**: non c'è cifratura del
contenuto.

**In uscita c'è una redazione parziale, e va detta della dimensione giusta**
(dal 02/08/2026, attiva di default; si spegne solo con `ARCHIVE_REDACT=0` sul
servizio `archive-mcp`). Ogni risposta di ogni tool passa da un mascheramento che
copre:

- gli **identificatori in formato riconoscibile** — email e numeri di telefono —
  ovunque compaiano, transcript compresi;
- i **valori dell'anagrafica dell'account** (le righe `account:user` dell'export
  claude.ai), anche quando sono scritti a mano dentro un messaggio.

**Non copre**: token, chiavi, password, IP, indirizzi postali, nomi di terzi mai
comparsi nell'anagrafica. *Chiunque abbia accesso all'archivio trova quei segreti
con una query.* Il pattern dei telefoni **non** si applica dentro un uuid canonico
(8-4-4-4-12 esadecimali) e lascia intatte le date ISO valide con l'ora
(`2026-09-05 13:10`) e la sagoma `AAAAMMGG-HHMMSS` dei nomi di bundle: tre esenzioni
strette, dalla 0.51.1 (prima un uuid coi gruppi di sole cifre e una data con l'ora
uscivano come «[telefono redatto]»; misurato il 24/09/2026 dal vivo). Dalla 0.51.4 la
data con l'ora vale anche con minuti e secondi scritti coi trattini o coi punti, come nei
nomi degli screenshot (`Schermata del 2026-09-24 18-41-38.png` usciva
«Schermata del [telefono redatto]-38.png»); minuti e secondi devono essere 00-59.

**Un valore dell'anagrafica che è pubblico per tua scelta** si esenta per nome, con
`ARCHIVE_REDACT_ESENTI` nel `.env` (valori separati da virgola, senza maiuscole; dalla
0.51.4). Il caso che l'ha fatto nascere: il `full_name` dell'account claude.ai era
l'handle pubblico dell'autore, lo stesso nome dei suoi repository, e la redazione lo
toglieva da ogni percorso e da ogni etichetta (`corpus-<handle>/…` usciva
«corpus-[dato personale redatto]/…»). Vuota per default: la politica non cambia finché non
la scrivi. Vale solo per i valori noti: un'email o un telefono in formato riconoscibile
restano redatti anche se li esenti.

**La regola pratica** (finché l'archivio resta tuo e dei modelli a cui dai *tu* il
connettore, questa è una scelta difendibile):

- Non caricare nell'archivio materiale che non vuoi ritrovare cercabile in chiaro.
- Se prepari un export **da condividere o pubblicare**, ripuliscilo *prima* di
  caricarlo — l'archivio non lo farà per te.
- Il giorno in cui l'archivio dovesse essere **condiviso, esposto o dato in pasto
  a un modello di terzi**, servirà prima una strategia di redazione completa o di
  cifratura (mascheramento dei segreti, o marcatura `sensitive` con esclusione di
  default): **è una decisione da prendere prima di crescere l'archivio in quella
  direzione, non dopo.**

## Popolare dall'admin — `/admin/archive`

Pannello admin → tab **Archive**. Carichi una fonte, viene indicizzata in un DB
FTS5 e diventa cercabile. Dispatch automatico per estensione:

| Formato | Cosa indicizza |
|---|---|
| `.zip` | riconosciuto dal **contenuto**, non dal nome. Nell'ordine: il **bundle di Recupero Sessioni 1777** (se ha `MANIFEST.json` **e** almeno un membro `sessions/…` — vedi [il bundle](#il-bundle-di-recupero-sessioni)); l'export account **claude.ai** (`conversations.json` + `design_chats/` + `projects/docs` + `memories` + `users.json`/`login_history.json` — **unico** oppure **spezzato in 5 zip per categoria**, il formato consegnato da claude.ai dal 29/08/2026: ogni zip è riconosciuto da solo, si caricano tutti sullo stesso *nome DB*, vedi sotto); l'export chat **Telegram Desktop** — `result.json` *o* `messages*.html`, anche zippato come cartella `ChatExport_*/`. **Fallback**: uno zip che non è niente di questo ma contiene documenti `.md`/`.txt` (e codice, config, testo leggibile) viene indicizzato doc-per-doc, come i file sciolti |
| `.jsonl` | sessione **Claude Code** (`~/.claude/projects/<progetto>/<id>.jsonl`) |
| `.json` | export **Telegram Desktop** (formato *Machine-readable JSON*) |
| `.pdf` | documento **con testo** (estratto via `pypdf`) |
| `.md` / `.txt` | testo/markdown generico (ponte per l'output di altri tool) |
| `.db` | drop-in di un archivio SQLite già indicizzato (schema validato) |

> **Export claude.ai a 5 zip (dal 29/08/2026).** L'account non consegna più
> un file unico: dà un `manifest-<id>-<ts>.json` con 5 link **one-shot** e i 5 zip
> per categoria — `conversations-000.zip`, `projects-000.zip`,
> `design_chats-000.zip`, `memories-000.zip` (memoria persistente: `conversations_memory`,
> `project_memories` e i `memory_files` `/areas/*.md`), `light_metadata-000.zip`
> (`users.json` + `login_history.json`, gli accessi: una riga per evento,
> `account:login`). Il suffisso `-NNN` è la **parte**: una categoria grande può
> arrivare in più zip. Il manifest **non** si carica (contiene solo i link).
> Dall'admin: seleziona i 5 zip insieme (il campo *fonte* accetta più file) con lo
> stesso *nome DB* — es. `claude-ai-<ggmmaa>`, un DB per export, come da convenzione;
> dalla CLI: `for z in *-000.zip; do python3 services/gateway/app/archive_indexer.py "$z" claude-ai-<ggmmaa>.db; done`.
> L'ordine non conta e ricaricare non duplica (idempotente per uuid). Misurato sul
> primo export di questo formato: 13.920 record in 15 s, 1,2 GB di RAM di picco.
> ⚠️ `conversations.json` decompresso è al 58% del tetto per membro (297 MB su 512):
> quando lo supera l'ingest **si ferma parlante** (`MAX_MEMBER_BYTES`), non tronca.

> L'export chat di Telegram Desktop funziona **così com'è**: comprimi la
> cartella `ChatExport_*` in zip e caricala — sia il formato **HTML** (il
> default, `messages.html`) sia il **JSON** (`result.json`) vengono
> indicizzati. Se ci sono entrambi, vince il JSON (più fedele). Unica
> avvertenza: non mischiare HTML e JSON della *stessa* chat nello stesso DB —
> le chiavi di dedup sono diverse e i messaggi si duplicherebbero. Uno zip non
> riconosciuto, o senza messaggi estraibili, viene **rifiutato con un errore
> chiaro** — mai un "ok, 0 record".

Campi del form: **nome DB** (vuoto = dal nome file), **progetto** (etichetta;
vuoto = dedotta dalla fonte) e **descrizione** (facoltativa: a cosa serve / cosa
contiene l'archivio — compare nella scheda e in `describe_databases`, ed è
aggiornabile dopo col tool MCP `set_description`). Ricaricare lo stesso nome DB
non duplica (dedup per id); fonti diverse sullo stesso nome si accumulano.

> ⚠️ **Il gateway cancella lo zip dopo l'ingest**: sulla VPS resta solo ciò che è
> entrato nel DB (righe, tabelle, lapidi). Ciò che l'indexer non legge non si
> recupera dopo — per questo ogni membro scartato lascia una lapide che dice perché.

## Il bundle di Recupero Sessioni

Il bundle è lo zip che l'app locale **Recupero Sessioni 1777** produce con «scarica
tutto»: le sessioni Claude Code di un disco, deduplicate, con tutto ciò che serve a
ritrovarle. L'app vive fuori da questo repo; qui c'è il lato che lo **legge**.
L'indexer lo riconosce da `MANIFEST.json` **più** almeno un membro `sessions/…`, e
lo controlla prima degli altri formati (contiene `.md` che il fallback «zip di
documenti» mangerebbe, ignorando sessioni e log).

### Cosa c'è nello zip, e cosa diventa

| membro | cosa diventa | etichetta `project` |
|---|---|---|
| `sessions/<sessionId>.jsonl` (e `<sessionId>__fN.jsonl` per i filoni) | conversazioni: una riga per messaggio user/assistant, uuid nativi, `parent_uuid` nativo; più i titoli (`sender='title'`) e gli allegati (`sender='attachment'`) | ultima cartella della cwd della sessione |
| `subagents/<sessionId>/agent-<hash>.jsonl` (dal 16/09/2026) | conversazioni dei sub-agenti; le righe user di un sub-agente sono `sender='mandato'` (le ha scritte la macchina) | `subagent:<etichetta-cwd>` |
| `mcp-logs/<sessionId>/<server>/…` | log dei server MCP, a pezzi da 4000 caratteri | `mcp-log:<server>` |
| `workfiles/<cwd-codificata>/…` | artefatti delle cartelle di lavoro: testo e codice a pezzi, PDF con testo, immagini via OCR, zip annidati (un livello); un backup di sessione (`.jsonl` di Claude Code) diventa conversazione; i binari lasciano una lapide `non-testo` | `workfile:<cwd-codificata>/<prima sottocartella>` |
| `documents/…` (dal 25/09/2026) | i **documenti** che l'`export` dell'app consegna accanto alle sessioni (non conversazioni): la stessa trafila di `workfiles/` — testo e codice a pezzi, PDF, immagini via OCR, zip annidati, sniff del contenuto; i binari lasciano una lapide `non-testo` con `source` `bundle-documents`. Uno zip della cartella dell'export ha `MANIFEST.json` e `sessions/`, quindi è un bundle: prima ogni documento finiva in `membro-sconosciuto` | `document:<prima sottocartella>`, o `document` per un file nella radice di `documents/`. L'app (dal 25/09/2026) scrive `documents/<famiglia>/<md5-corto-del-path>__<nome>`: l'etichetta è la famiglia — `document:testo`, `document:codice`, `document:config`… —, mai il percorso d'origine |
| `recupero/…` (dal 24/09/2026) — o il ponte `workfiles/_recupero-1777/…` | schede di sessione, di stirpe e di memoria come righe; tre `.tsv` come tabelle — vedi [il prefisso `recupero/`](#il-prefisso-recupero--contratto-r1) | `recupero:sessioni` · `recupero:stirpi` · `recupero:memorie` |
| `inventario/inventario-sessioni.tsv` | l'indice delle sessioni come testo, a pezzi da 4000 | `inventario` |
| `inventario/inventario-sessioni.json` | **non** si indicizza: lapide che dice se i suoi dati sono entrati da un'altra parte — vedi [le lapidi](#lapidi-cosa-non-entra-e-perché) | — |
| `MANIFEST.md` | la prosa del manifest, a pezzi | `manifest` |
| `MANIFEST.json` | **non** diventa testo: tre chiavi vanno nella scheda `meta` — vedi [il manifest](#il-manifest-nella-scheda-meta) | — |
| qualunque altro membro | lapide `membro-sconosciuto`: il bundle è cresciuto più dell'indexer | — |

Le righe di conversazione (da `sessions/`, `subagents/` e dai backup di sessione
trovati in `workfiles/`) e le righe delle schede di `recupero/` lasciano un
**avvistamento** (tabella `sightings`: uuid + percorso del membro). È l'unico legame
fra un uuid e il file da cui è arrivato — per esempio fra un messaggio e il
sessionId della sua sessione (`sessions/<sessionId>.jsonl`), o fra un sub-agente e
la sessione madre. I pezzi di log MCP, documenti, inventario e `MANIFEST.md` non ne
lasciano: il loro percorso sta nella chiave dell'uuid e, per i documenti, nella
prima riga del testo.

### Il prefisso `recupero/` — contratto R1

Fino al 24/09/2026 lo **stato** di ogni sessione, le **stirpi** (le sessioni che si
continuano l'una nell'altra: clone, `/clear`, compact…), gli **archi** fra sessioni
e le **memorie** scritte durante il lavoro viaggiavano solo dentro
`inventario/inventario-sessioni.json`, che l'indexer scartava come «ridondante». Con
lo zip cancellato dopo l'ingest, **arrivavano sulla VPS e sparivano**. E il sessionId
non era una colonna: nell'archivio non esisteva un'entità «sessione».

Il prefisso `recupero/` li porta in una forma che l'indexer legge, secondo un
contratto versionato (**R1**) scritto dalla parte che li produce (il file
CONTRATTO-RECUPERO.md dell'app). Solo `.md` e `.tsv`, mai json:

```
recupero/sessioni/<sessionId>.md          una scheda per ogni sessione consegnata nel bundle
recupero/stirpi/<id-stirpe>.md            una scheda per ogni stirpe che tocca il bundle
recupero/memorie/<k10>__<nome>.md         il contenuto di una memoria (k10 = md5 del PERCORSO d'origine)
recupero/sessioni.tsv                     una riga per sessione consegnata
recupero/archi.tsv                        una riga per arco che tocca una sessione consegnata
recupero/memorie.tsv                      una riga per memoria consegnata
```

**Le schede `.md`** cominciano con un front-matter fra due righe `---`, fatto di
righe `chiave: valore` (un valore per riga, niente YAML annidato), poi il corpo in
markdown, che è il testo da indicizzare. Tre chiavi sono obbligatorie: `contratto`
(deve valere `R1`), `tipo` (`sessione` · `stirpe` · `memoria`, coerente con la
cartella) e il campo che identifica la scheda (`sessionId` · `id` · `path`). Un
esempio di scheda di sessione (dati inventati):

```
---
contratto: R1
tipo: sessione
sessionId: 0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0
titolo: sessione di prova
cwd: /percorso/del/progetto
first_ts: 2026-09-10T10:00:00.000Z
last_ts: 2026-09-10T10:05:00.000Z
last_uuid: <uuid dell'ultimo messaggio user/assistant>
file: sessions/0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0.jsonl
stato: turno-chiuso
stato_fonte: transcript
stirpe: <id della stirpe>
stirpe_pos: 1
n_commit: 2
n_fili: 1
---
# sessione di prova

## Stato
…
## Ultime parole
…
```

Il corpo di una scheda di sessione porta **Stato**, **Ultime parole** (le ultime
dell'utente e dell'assistente, marcate `[verbatim]`), **Fili aperti**, **Commit**,
**Memorie scritte** e **Stirpe**. Quello di una stirpe porta una riga per membro e
una per arco, con i sessionId **interi** (così un sid, o i suoi primi 8 caratteri,
trova l'arco con FTS). Quello di una memoria è il testo della memoria così com'è.

**I `.tsv`**: prima riga = intestazione, campi separati da TAB, nessun TAB né
a-capo nei valori. Le colonne si leggono **per nome**.

**Versioni.** Un campo in più nel front-matter, o una colonna in più in coda a un
`.tsv`, non cambia la versione: l'indexer li ignora. Un campo tolto, rinominato o di
significato diverso è un contratto **R2**, e questo indexer lo rifiuta con una
lapide che lo dice (non lo legge a metà).

### Il ponte `workfiles/_recupero-1777/`

L'app sceglie la radice leggendo `BUNDLE_PREFISSI_INDICIZZATI` dalla **sua** copia
dell'indexer: se quella copia non conosce ancora `recupero`, mette gli stessi file
sotto `workfiles/_recupero-1777/` (il «ponte», livello 0 del contratto), che anche un
indexer vecchio legge — come testo. Il `MANIFEST.json` dice quale radice è stata
usata e perché.

**Per questo indexer il ponte è un alias di `recupero/`**: stessa lettura, tabelle
comprese. Le righe escono **identiche** da una radice o dall'altra: etichette
`recupero:*`, uuid, testo e avvistamenti usano la forma canonica `recupero/…`, così
lo stesso contenuto arrivato dalle due strade non raddoppia (verificato: lo stesso
bundle dalle due radici dà lo stesso DB, date d'ingest a parte). Le **lapidi**,
invece, citano il nome vero nello zip, che è quello che chi le legge cerca.

### Le schede diventano righe

| scheda | `project` | `sender` | `uuid` | `ts` | `parent_uuid` |
|---|---|---|---|---|---|
| sessione | `recupero:sessioni` | `recupero` | `_uid("recupero", membro, idx)` per ogni pezzo | `last_ts` **+ (idx+1) ms** | pezzo 0: **`last_uuid`** (l'ultimo messaggio della sessione); gli altri: il pezzo precedente |
| stirpe | `recupero:stirpi` | `recupero` | `_uid("recupero", membro, idx)` | `last_ts` se c'è, altrimenti la data del membro nello zip; + (idx+1) ms | pezzo 0: nessuno; gli altri: il pezzo precedente |
| memoria | `recupero:memorie` | `memory` | `_uid("recupero-memoria", path)` — **una** riga | `mtime` | nessuno |

`_uid(...)` è lo sha1 delle parti (l'uuid deterministico dell'indexer), e `membro`
è sempre la forma canonica `recupero/…`. Ne seguono quattro proprietà:

- **La scheda è una foglia del thread.** Il pezzo 0 di una scheda di sessione pende
  dall'ultimo messaggio della conversazione. `get_conversation` però la trova **per
  nome del membro** (`recupero/sessioni/<sid>.md`), non risalendo `parent_uuid`: i
  cloni condividono gli uuid, e la scheda di un clone appesa a un messaggio comune
  finiva in coda alla chat sbagliata (misurato il 26/09/2026). Da qualunque messaggio
  della sessione si arriva alla scheda, e dalla scheda a tutta la chat.
- **La scheda viene dopo l'ultimo messaggio.** `get_conversation` ordina per
  `(ts, uuid)`: con lo stesso ts dell'ultimo messaggio, l'ordine lo deciderebbe lo
  sha1. Per questo il pezzo `idx` ha `last_ts` + (idx+1) millisecondi, scritto in ISO
  con `Z` e i millesimi (`2026-09-10T10:05:00.000Z` → `…00.001Z`, `…00.002Z`). Se
  `last_ts` non ha i millesimi si parte dal **secondo dopo** (`…05:00Z` →
  `…05:01.000Z`), perché come stringa `…00.001Z` ordinerebbe *prima* di `…00Z`. Un
  formato che l'indexer non riconosce resta com'è: non si inventa un tempo.
- **Pezzi da 8000 caratteri.** Una scheda di sessione (~4 KB per contratto, 4,5 KB
  misurati su una vera) resta in una riga sola; una stirpe lunga si spezza.
- **Il testo indicizzato comincia con `[<membro>]`**, come i documenti del bundle:
  il membro porta il sessionId, che così si trova con FTS anche quando il corpo non
  lo ripete.

Tutte le righe delle schede hanno **`ts_source='data-export'`**: una scheda è una
**fotografia** (cambia fra un bundle e l'altro, e la versione uscente va in
`revisions`), non un evento detto una volta. Chi calcola il «più recente» di un
archivio filtra in negativo (`WHERE ts_source <> 'data-export'`), quindi le schede
non lo spostano. **`speaker` è `unknown`** (una scheda non ha un mittente) e
**`voice` è `unknown` con la bandiera `scheda_recupero`**: la scheda cita parola per
parola le ultime frasi dell'utente, e classificarla come testo incollato (i suoi
titoli e grassetti la farebbero uscire `pasted_ai`) sarebbe il falso positivo più
caro. Le memorie restano all'euristica, come le memorie di claude.ai. Ogni riga
lascia un **avvistamento** col membro canonico.

**Una scheda riscritta con meno pezzi non lascia orfani.** Se la versione nuova di
una scheda (o di una memoria) ha meno pezzi di quella già nel DB, le righe in più
**dello stesso membro** (trovate dai suoi avvistamenti, e solo con la stessa
etichetta) escono da `messages`, dall'FTS e dagli avvistamenti; la loro ultima
versione resta in `revisions`, come per ogni riga riscritta. Una memoria cambiata
fra due bundle è la stessa riga con testo nuovo: la versione vecchia va in
`revisions`, niente doppione.

### Le tabelle `sessioni`, `archi`, `memorie`

I tre `.tsv` **non** diventano testo: riempiono tre tabelle, una riga per riga del
file (`INSERT OR REPLACE` sulla chiave, con la data d'ingest). Le colonne sono quelle
del contratto, nello stesso ordine:

**`sessioni`** — chiave `(sessionId, file)`. Una riga per **file** consegnato: una
sessione in collisione ha più **filoni** con lo stesso `sessionId`
(`sessions/<sid>.jsonl`, `sessions/<sid>__f2.jsonl`…), e ciascuno ha la sua riga. Fino
alla 0.51.1 la chiave era il solo `sessionId` e ne restava uno (misurato sul primo
bundle vero: 1.300 righe per 1.303 schede). Una riga con `file` vuoto lascia la lapide
`recupero-tsv-fuori-contratto`, come una con `sessionId` vuoto.

| colonna | cosa contiene |
|---|---|
| `sessionId` | l'uuid intero della sessione |
| `titolo` | il titolo (custom-title o primo messaggio, una riga) |
| `cwd` | la cartella di lavoro principale |
| `first_ts` · `last_ts` | primo e ultimo timestamp di conversazione (ISO UTC, `Z`) |
| `last_uuid` | l'uuid dell'ultimo record user/assistant della copia consegnata — il padre della scheda |
| `file` | il membro dello zip con la conversazione (`sessions/<sid>.jsonl`, `__fN` per i filoni) |
| `stato` · `stato_fonte` | dove si è fermata la sessione, e da quale fonte lo si sa (processo / job / transcript) |
| `stirpe` · `stirpe_pos` | l'id della stirpe e la posizione della sessione (vuoti se è sola) |
| `n_commit` · `n_fili` | quanti commit e quanti fili aperti porta |
| `ingest_date` | quando è entrata (o è stata riscritta) |

**`archi`** — chiave `(da, a, relazione, via)`, la stessa della tabella `archi`
dell'inventario dell'app: lo stesso arco visto da due bundle è UNA riga.

| colonna | cosa contiene |
|---|---|
| `da` · `a` | i due sessionId |
| `relazione` | che legame è (per esempio `clone`, `continua`) |
| `via` | da quale segnale è stato ricostruito |
| `livello` · `prova` · `voce` | quanto è forte, la prova, chi lo afferma |
| `peso` | un numero (REAL) |
| `chiusura` | `1` se l'arco conta per la stirpe (INTEGER: `chiusura=1` trova le righe) |
| `bundle_scan` · `ingest_date` | quando l'app l'ha calcolato, quando è entrato |

**`memorie`** — chiave `path`.

| colonna | cosa contiene |
|---|---|
| `path` | il percorso d'**origine** della memoria (non il membro) |
| `sistema` · `livello` | quale sistema di memoria, e come è stata riconosciuta (strutturale · per-nome) |
| `md5` · `mtime` | impronta e data di modifica (ISO UTC, `Z`) |
| `scritta_da` | i sessionId che l'hanno scritta, separati da virgola |
| `membro` | il membro `recupero/memorie/…` che porta il testo (la riga in `messages`) |
| `ingest_date` | quando è entrata |

Le tre tabelle sono `CREATE TABLE IF NOT EXISTS`: **ogni** DB le riceve, vuote, al
primo ingest fatto con un indexer di questa versione (anche un export claude.ai),
e resta leggibile dalle versioni precedenti. Un DB mai re-ingerito da allora non le
ha: è la differenza che i tool `get_session` e `get_stirpe` dichiarano.

### Il manifest nella scheda `meta`

`MANIFEST.json` non diventa testo (la sua prosa la porta già `MANIFEST.md`), ma tre
sue chiavi vanno nella scheda `meta` del DB, in json:

| chiave in `meta` | dal manifest | a cosa serve |
|---|---|---|
| `bundle_generated` | `generated` | quando è stato fatto il bundle: data gli altri due valori |
| `bundle_previsione_ingest` | `previsione_ingest` | quante righe l'app si aspetta in tabella (anche per prefisso): il metro del collaudo, ora confrontabile dentro il DB |
| `bundle_recupero` | `recupero` | versione del contratto, radice usata (`recupero/` o il ponte) e perché, quante schede e righe `.tsv` |

La scheda parla dell'**ultimo** bundle letto: una di queste chiavi che il manifest
nuovo non porta viene **tolta**, perché resterebbe a parlare per un bundle che non
l'ha detta. Il membro lascia la lapide `manifest-in-meta`, che dice dov'è finito; un
json illeggibile lascia `manifest-illeggibile`, e l'ingest delle sessioni prosegue.

### Lapidi: cosa non entra e perché

Un membro che non entra **non sparisce**: lascia una lapide nella tabella `skipped`,
con un motivo (`reason`) e un dettaglio (`detail`) che comincia col nome del membro e
dice il perché.

| `source` | `reason` | quando |
|---|---|---|
| `bundle` | `membro-sconosciuto` | un membro (anche dentro `recupero/`) che l'indexer non sa leggere: un `count(*)` su questo motivo dice se il bundle è cresciuto più dell'indexer |
| `bundle` | `manifest-in-meta` | `MANIFEST.json` letto: tre chiavi in `meta`, il resto non indicizzato |
| `bundle` | `manifest-illeggibile` | `MANIFEST.json` non è json, o non è un oggetto |
| `bundle` | `non-indicizzato-ridondante` | l'inventario json, quando il bundle ha `recupero/` (o il ponte): i suoi dati sono entrati da lì |
| `bundle` | `non-indicizzato-senza-recupero` | l'inventario json, quando il bundle NON ha `recupero/` né il ponte: stirpi, archi e memorie di quel bundle **non** sono nell'archivio (e lo zip è stato cancellato) |
| `bundle-recupero` | `recupero-senza-front-matter` | una scheda senza il primo `---`, o con un front-matter che non si chiude |
| `bundle-recupero` | `recupero-front-matter-malformato` | una riga del front-matter senza `:` — il formato è rigido apposta |
| `bundle-recupero` | `recupero-contratto-ignoto` | `contratto` assente o diverso da `R1` (per esempio un `R2` che questo indexer non legge ancora): la scheda non entra |
| `bundle-recupero` | `recupero-fuori-contratto` | `tipo` incoerente con la cartella, o manca il campo che identifica la scheda |
| `bundle-recupero` | `recupero-tsv-fuori-contratto` | un `.tsv` la cui intestazione non ha una colonna del contratto (il file intero non entra: niente tabelle riempite a metà), oppure una sua riga con un numero di campi sbagliato o con la chiave vuota (salta solo quella riga, col numero di riga) |
| `bundle-workfiles` | `non-testo`, `pdf-*`, `ocr-*`, `zip-*`, `membro-oltre-tetto`, … | un file di lavoro che non ha testo da leggere, o che l'OCR / l'apertura non ha potuto leggere |
| `bundle-documents` | gli stessi di `bundle-workfiles` | lo stesso, per un membro di `documents/` |
| `claude-code` | `non-message`, `no-uuid-o-ts`, `empty` | un record di una sessione che non è un messaggio, non ha uuid o ts, o è vuoto |

```sql
-- che cosa non è entrato da questo DB, per motivo
SELECT source, reason, count(*) FROM skipped GROUP BY 1, 2 ORDER BY 3 DESC;
```

## Gestire i DB — lista ed eliminazione

La pagina mostra per ogni DB la **scheda completa**: descrizione, messaggi,
etichette distinte (le "provenienze": titoli chat, `project:<nome>`,
`design:<nome>`…), le etichette principali, la dimensione su disco e l'ultimo
aggiornamento.

Il bottone **Elimina** (con conferma) rimuove il DB: la ricerca su quell'archivio
smette subito (archive-mcp se ne accorge da solo, scan-mode) e l'azione finisce
nell'audit. È **irreversibile** — per *resettare* un archivio (es. ricaricarlo
da zero dopo che la fonte è cambiata): elimina e ricarica la fonte con lo
stesso nome DB. Lista ed eliminazione sono disponibili anche dalla **Mini App**
(tab Archivio).

## Cercare — i tool MCP

`archive-mcp` espone **15 tool** via MCP (usabili dal connettore claude.ai e
dalla Mini App). Tutti passano dalla redazione in uscita descritta sopra.

| Tool | Cosa fa |
|---|---|
| `search(query, db_name, limit, …)` | ricerca FTS5; ritorna `{db, uuid, project, ts, rank, snippet, snapshot}`. Sulla ricerca in **tutti** i DB lo stesso uuid arriva **una volta**, con `anche_in` per gli altri archivi che lo contengono (niente limit sprecato in fotocopie). Filtri `since`/`until`, `project`, `speaker`, `voice`, `campi` (sotto) |
| `search_ibrida(query, db_name, limit, query_fts, …)` | ricerca **per senso**: FTS5 + vettori fusi (RRF). Serve quando ricordi il senso e non il lessico; richiede il modello di embedding e un indice `<db>.vec.db` sul volume, e se mancano **lo dice** invece di ricadere su FTS5. Accetta `campi` come `search`. Vedi [RICERCA-IBRIDA.md](RICERCA-IBRIDA.md) |
| `count(query, db_name, …)` | quanti messaggi corrispondono (non limitato): `{total, per_db}`; se un termine **collassa** aggiunge `warnings`. Stessi filtri di `search`, `campi` compreso |
| `check_term(term, db_name)` | diagnostica se un termine con `+`/`#` (`C++`, `C#`, `g++`) è ricercabile o **collassa** sul prefisso — chiede all'indice, non alla doc |
| `get_context(uuid, db_name, before, after, max_chars)` | i messaggi **attorno** a un risultato, col **contenuto pieno**; sulle sessioni Claude Code i vicini vengono dal **file di sessione** (la riga cercata lo dice in `vicini_da`); altrove, se il messaggio è in un thread, dallo **stesso thread** (arco `parent_uuid`), non dalla sola vicinanza temporale. `max_chars` (0 = intero) tronca ogni riga **dichiarandolo nel testo** — sui messaggi-hub giganti il payload pieno uccideva la connessione. Una riga **senza testo** (un tool_use, l'output di un comando) porta anche **`tools`**, le azioni che sono il suo contenuto (dalla 0.52.0: prima arrivava vuota), troncato da `max_chars` come il testo |
| `get_conversation(uuid, db_name, limit, max_chars)` | il **thread intero** che contiene l'uuid (albero `parent_uuid`, antenati + discendenti, in ordine `(ts, uuid)`) — per **leggere una chat** dall'inizio alla fine, non solo la finestra ±N; `max_chars` e `tools` come in `get_context`. Sulle sessioni Claude Code è il **file di sessione** intero (`conversazione_da`), e coi bundle con `recupero/` la scheda della sessione esce **in coda** |
| `get_session(sessionId, db_name, limit, max_chars)` | tutto ciò che l'archivio sa di **una sessione** Claude Code: la riga di `sessioni`, la **scheda**, i messaggi della conversazione, gli archi, la stirpe — vedi [Sessioni e stirpi](#sessioni-e-stirpi--get_session-e-get_stirpe) |
| `get_stirpe(sessionId, db_name, limit, max_chars)` | la **stirpe** di una sessione: la chiusura sugli archi con `chiusura=1`, coi dati di ogni membro — vedi [Sessioni e stirpi](#sessioni-e-stirpi--get_session-e-get_stirpe) |
| `list_projects(db_name, top)` | le etichette `project` con i conteggi — per **navigare** l'archivio, non solo cercarlo |
| `archive_stats(db_name)` | istogramma dei messaggi per **anno** — *quando* l'archivio è fitto, da sapere prima di cercare. La **prima** chiamata su un DB scandisce tutto (decine di secondi su archivi grandi); le successive sono **memoizzate per snapshot** |
| `list_databases(schede)` | i nomi dei DB caricati; con `schede=true` ogni voce porta la sua carta d'identità (**ruolo**, righe, intervallo date, descrizione) — la scelta del DB è il primo bivio di ogni ricerca |
| `describe_databases()` | scheda per DB: righe, intervallo date, etichette, **snapshot** (freschezza), **description**, **ruolo** |
| `check_integrity(db_name)` | integrità degli archivi: `ok` · `sporco` (journal caldo: lo scrittore è morto a metà) · `corrotto` · `non_misurabile`. Costa una scansione per DB: da chiamare quando un risultato sembra strano, non a ogni ricerca |
| `set_description(db_name, description)` | scrive/aggiorna la **descrizione** dell'archivio (tocca la scheda, mai i messaggi) |
| `set_ruolo(db_name, ruolo)` | dichiara il **ruolo** dell'archivio a vocabolario chiuso — vedi sotto |

**`campi` — cercare nelle parole o anche nelle azioni (dalla 0.54.0, #273).** Per
default `search`, `count` e `search_ibrida` cercano **ovunque**: nel testo, nelle azioni
(`tools`: il comando lanciato, il file scritto da un Edit, l'output di un Read) e negli
allegati. È voluto, perché le azioni sono contenuto: è lì che si trova il file toccato o
il comando dato. Ma con `sort='newest'` il codice diventa rumore in prima posizione. Il
05/09 una ricerca sul «libro» restituiva per prima una fixture di test dell'indexer («il
libro è al capitolo 81»): un dato finto e plausibile. Misurato il 26/09 sul primario: su
14 righe con quella frase, 12 hanno il testo vuoto e la frase nelle azioni. Con
**`campi='testo'`** la ricerca guarda solo le parole (la colonna `content`): è il filtro
per il «più recente» e per «chi ha detto cosa». In `search_ibrida` il ramo vettoriale
tiene allora solo le righe che hanno parole, perché un vettore non dice se ha colpito il
testo o le azioni. Un valore diverso da `tutto`/`testo` è un errore, non un ritorno
silenzioso al default.

### Il `ruolo` di un archivio — instradare senza leggere la prosa

Con molti DB caricati, «quale archivio interrogare» è la prima domanda di ogni
ricerca. Finché la risposta vive solo dentro la `description` — «★ primario»,
«⚠️ superato, usare quell'altro» — è scritta in una lingua che un umano legge e
un client no: **una regola per la macchina scritta in prosa riesce a metà, e in
silenzio.** Il campo `ruolo` la rende leggibile.

| valore | vuol dire |
|---|---|
| `primario` | la fonte **corrente** di quel versante: se non scegli, è lei che deve rispondere |
| `fotografia` | versione più **vecchia** dello stesso versante, tenuta per la storia: si cerca qui quando interessa com'*era* |
| `riscontro` | non si interroga per **trovare** ma per **verificare**: ridondanza voluta, gemelli re-ingeriti con un indexer diverso, DB-sonda con un caso-noto-che-deve-riuscire |
| `riservato` | materiale personale: fuori dai compiti tecnici senza richiesta esplicita. È una **dichiarazione, non un lucchetto** — nessun tool lo esclude da solo |
| `non dichiarato` | **nessuno si è pronunciato** su quel DB. Non è «poco importante», e non va indovinato dal nome: è il valore che si legge quando `set_ruolo` non è mai stata chiamata (o quando la dichiarazione è stata ritirata passando `""`) |

> **Additivo, e per ora solo informativo.** `search` e `count` senza `db_name`
> toccano **tutti** i DB come prima, `riservato` compreso: chi vuole restringere
> ai primari legge il campo e passa `db_name`. Far pescare il default dai soli
> primari è un **cambio di contratto** — cambierebbe il significato di uno zero
> («0 sui primari» ≠ «0 ovunque») — e vive in una sua issue.

> **Concorrenza.** Il server serve **2 ricerche alla volta** (`search`,
> `search_ibrida`, `count`, `archive_stats`, `get_session`, `get_stirpe`): le
> richieste in più si mettono in coda da sole invece di morire in timeout. Chi
> orchestra più chiamate le raggruppi a coppie.

> **Fonti senza thread.** Sui documenti chunked (pdf/telegram/memory) e sui DB
> storici `parent_uuid` è vuoto: lì `get_conversation` ripiega sull'ordine
> lineare dell'archivio e `get_context` sull'adiacenza temporale. La
> ricostruzione fedele dell'ordine dei chunk (colonna `seq`) è un passo
> **evolutivo dichiarato**, fuori scope oggi.

> **Sessioni Claude Code: il file, non la catena.** Nei transcript di Claude Code
> ogni record punta al precedente, anche quando il precedente è un record che
> l'indexer non tiene (la durata di un turno, un allegato vuoto, un messaggio di
> soli metadati). Nel DB quel genitore manca: sul primario del 24/09/2026 mancava
> per **82.876 righe su 260.072 (32%)**, e il thread di un messaggio si riduceva
> spesso al messaggio stesso — `get_context` restituiva solo lui. Dal 26/09 i due
> tool, per le righe viste in un file `sessions/` o `subagents/` (tabella
> `sightings`), usano **quel file**: la conversazione vera, senza buchi e senza le
> altre sessioni parallele dello stesso project. Più copie dello stesso uuid (i
> filoni `__fN`): vince il file principale. Riallacciare la catena all'ingest
> (saltando i record non tenuti) resta un passo **dichiarato**, non fatto.

**Sintassi della query FTS5** (le stesse regole sono nella docstring che il
modello legge prima di cercare):

- Operatori **in MAIUSCOLO**: `AND`, `OR`, `NOT`, `NEAR(a b, 5)` — in minuscolo
  diventano termini.
- Nessuno stemming, quindi **doppia lingua**: `errore OR error`.
- Famiglie di nomi col **prefisso**: `palant*` (i numeri attaccati non si
  separano: `1777` non trova `N1777`).
- Termini con caratteri speciali (`- . / @ : # '`) **tra virgolette**:
  `"flutter-elinux"`, `"0.7.9"`. In modalità *smart* (default) il server li quota
  da sé; con `raw=true` la query passa intatta (per NEAR/parentesi complesse).
  **Ma il quoting non basta per il suffisso** — vedi il riquadro sotto.
- `sort`: `rank` (rilevanza, default), `newest`, `oldest`. Filtri `since`/`until`
  (ISO) e `project` (etichetta esatta). Su più DB il `limit` è **globale**.

> **Superficie d'errore parlante.** Una query malformata **non** restituisce
> lista vuota (che sarebbe indistinguibile da "nessun match" — un falso negativo
> silenzioso): solleva un errore che spiega come correggerla. Resta valido il
> *protocollo dello zero*: 0 risultati non prova assenza — riprova quotando il
> termine prima di concludere che "non c'è".

> **Termini che COLLASSANO (`C++`, `C#`, `g++`) — il difetto dell'11/07.** Il
> tokenizer `unicode61` tratta `+ #` da **separatori**: un termine come `C++`
> perde il suffisso e diventa il token `C`, comunissimo (coordinate SVG,
> copyright, gradi). `count("C++")` non torna vuoto — torna **migliaia di falsi
> positivi silenziosi**: è così che nacque il falso ricordo «Neo programmatore
> C++». È il gemello a verso opposto dell'errore parlante: lì lista vuota, qui
> lista piena della cosa sbagliata. **Il quoting non protegge** — non è la
> sintassi, è l'indice: nessun apice cerca un carattere che il tokenizer ha
> buttato. Il difetto morde solo i caratteri **in coda** (`C++`); **in mezzo**
> (`node.js`) il quoting tiene i due token come frase e funziona.
>
> Il fix è su **due strati**, perché indice e query sono piani diversi:
> - **indice** — l'FTS si crea con `tokenize='unicode61 tokenchars ''+#'''`, così
>   `C++`/`C#`/`g++` sono token veri e distinti. Vale sui DB **costruiti da qui in
>   poi**; i DB già caricati vanno ricostruiti (re-ingest): il `tokenize` è
>   fissato alla creazione, un `rebuild` non lo cambia. Il `.` resta separatore di
>   proposito (romperebbe `node.js`, `github.com`, `0.7.9`).
> - **query** — `count` e `check_term` fanno da **canary**: confrontano
>   `count(term)` con `count(prefisso)`; se coincidono, il termine è collassato e
>   lo **dicono** (campo `warnings`). Vale **subito** sui DB già vivi senza
>   re-ingest, e si auto-tara: su un DB ricostruito i conteggi divergono e
>   l'avviso non scatta. Chiedi `check_term("C++")` quando un conteggio ti sembra
>   assurdo.

## Sessioni e stirpi — `get_session` e `get_stirpe`

Dal contratto `recupero/` R1 l'archivio ha un'entità «sessione». Due tool la
leggono, in **sola lettura**, dalle tabelle `sessioni` e `archi` e dalle schede.

### Come si chiede una sessione

`sessionId` è l'**uuid intero** oppure un **prefisso di almeno 8 caratteri** — la
forma breve in uso (`0f1e2d3c`) — purché univoco. La sessione si cerca fra le righe
di `sessioni` **e** fra gli estremi degli `archi` (una sessione può essere nota solo
come estremo di un arco: la madre non consegnata di un clone). `%` e `_` nell'input
restano caratteri, non diventano jolly.

- **Prefisso ambiguo** → errore che elenca i candidati coi loro DB:
  `il prefisso '0f1e2d3c' è ambiguo: 2 sessioni. Candidati: 0f1e2d3c-4b5a-… (primario); 0f1e2d3c-ffff-… (primario). Passa più caratteri o l'id intero.`
- **Meno di 8 caratteri** → errore: serve l'id intero o un prefisso di almeno 8.
- **Più DB conoscono la stessa sessione** (un primario e una fotografia, per
  esempio) → risponde il DB col **`last_ts` più recente** per quella sessione (a
  parità, il primo per nome); gli altri sono elencati in **`anche_in`**, come per il
  dedup di `search`. Con `db_name` si sceglie un DB solo.

### `get_session(sessionId, db_name="", limit=200, max_chars=0)`

Risponde con un oggetto:

| campo | cosa contiene |
|---|---|
| `sessionId` | l'uuid intero (risolto dal prefisso) |
| `db` · `snapshot` | il DB che ha risposto e la data dell'ultima modifica del suo file |
| `sessione` | la riga di `sessioni` (tutte le colonne); `null` se la sessione è nota solo come estremo di un arco. Se la sessione ha più **filoni**, è la riga del **principale**: il file senza `__fN` (`sessions/<sid>.jsonl`), o, se manca, quello col N più basso |
| `filoni` | **tutte** le righe di `sessioni` per quel `sessionId`, il principale per primo: una sola per una sessione senza collisioni, `[]` se non c'è riga. Con più filoni lo dice anche `note` |
| `scheda` | il testo della scheda di sessione del principale (`recupero/sessioni/<sid>.md`, o `<sid>__fN.md` se il principale è un filone) (stato, ultime parole, fili aperti, commit, memorie scritte, stirpe), ricomposto dai suoi pezzi; `null` se non c'è. ⚠️ Le «ultime parole» sono **citazioni**: chi parla lo dice la scheda, non il fatto che siano lì |
| `conversazione` | `{messaggi, per_sender, primo_ts, ultimo_ts, fonti}`: le righe dell'archivio avvistate in `sessions/<sessionId>…` (tutti i filoni; titolo e allegati compresi, distinti in `per_sender`), il primo e l'ultimo ts, i file d'origine |
| `archi` · `archi_totali` | gli archi che toccano la sessione (da o a), fino a `limit`, e quanti sono in tutto |
| `stirpe` | `{id, posizione, scheda}` della stirpe dichiarata nella riga; `null` se la sessione è sola |
| `note` | ciò che manca, detto: archi troncati, scheda assente, conversazione non in questo DB… |
| `anche_in` | (solo se serve) gli altri DB che conoscono la sessione |

`max_chars` (0 = intero) tronca il testo delle schede **dichiarandolo nel testo**,
come in `get_context`. Per **leggere** la conversazione: `get_conversation` con
`sessione.last_uuid`.

Un esempio di risposta (dati inventati, testo accorciato):

```json
{
  "sessionId": "0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0",
  "db": "recupero-bundle",
  "snapshot": "2026-09-24T19:42:50Z",
  "sessione": {"sessionId": "0f1e2d3c-…", "titolo": "sessione di prova",
               "last_ts": "2026-09-10T10:05:00.000Z", "last_uuid": "…",
               "file": "sessions/0f1e2d3c-….jsonl",
               "stato": "turno-chiuso", "stirpe": "9a8b7c6d-…", "stirpe_pos": 1,
               "n_commit": 2, "n_fili": 1, "…": "…"},
  "filoni": [{"sessionId": "0f1e2d3c-…", "file": "sessions/0f1e2d3c-….jsonl", "…": "…"}],
  "scheda": "[recupero/sessioni/0f1e2d3c-….md]\n# sessione di prova\n\n## Stato\n…",
  "conversazione": {"messaggi": 3, "per_sender": {"user": 1, "assistant": 1, "title": 1},
                    "primo_ts": "2026-09-10T10:00:00.000Z",
                    "ultimo_ts": "2026-09-10T10:05:00.000Z",
                    "fonti": ["sessions/0f1e2d3c-….jsonl"]},
  "archi": [{"da": "0f1e2d3c-…", "a": "1a2b3c4d-…", "relazione": "clone",
             "via": "uuid-condivisi", "chiusura": 1, "…": "…"}],
  "archi_totali": 1,
  "stirpe": {"id": "9a8b7c6d-…", "posizione": 1, "scheda": "…"},
  "note": []
}
```

### `get_stirpe(sessionId, db_name="", limit=200, max_chars=0)`

La stirpe è la **chiusura sugli archi con `chiusura=1`**, presi senza verso (da↔a),
a partire dalla sessione chiesta: tutte le sessioni che si continuano l'una
nell'altra.

| campo | cosa contiene |
|---|---|
| `sessionId` · `db` · `snapshot` · `anche_in` | come in `get_session` |
| `membri` | ogni sessione della stirpe coi suoi dati da `sessioni`, in ordine di `first_ts`; ognuna con `in_sessioni: true/false` e `filoni` (le sue righe di `sessioni`, il principale per primo — i dati del membro sono i suoi; `[]` per un membro senza riga) |
| `senza_riga` | i membri **senza** riga in `sessioni` (noti solo come estremi di un arco): restano nell'elenco — incompleti, non spariti |
| `archi` | gli archi con `chiusura=1` fra i membri |
| `stirpi_dichiarate` · `schede_stirpe` | gli id di stirpe scritti nelle righe dei membri, e le loro schede |
| `note` | per esempio: stirpe troncata a `limit` membri, sessione sola (con quanti archi senza chiusura la toccano), membri che dichiarano stirpi diverse |

Oltre `limit` membri la visita si ferma, lo dice in `note`, e gli archi verso i
membri rimasti fuori non vengono dati.

### I DB nati prima del contratto R1

Un DB indicizzato prima del 24/09/2026 (e mai re-ingerito da allora) **non ha** le
tabelle `sessioni` e `archi`. Lì i due tool non rispondono con una scheda vuota — che
direbbe «la sessione non ha niente» — ma con un **errore parlante**:

```
questo DB ('cc-vecchio') non ha la tabella sessioni: è stato indicizzato prima del
contratto R1 (recupero/, 24/09/2026): re-ingerisci il bundle con un indexer che legge
recupero/. La CONVERSAZIONE però c'è, avvistata in sessions/0f1e2d3c… di:
cc-vecchio (412 righe) — leggila con search / get_conversation.
```

Senza `db_name`, se la sessione non si trova da nessuna parte l'errore distingue i DB
in cui è stata **cercata**, quelli con la tabella **vuota** (nessun bundle con
`recupero/` è mai entrato) e quelli **senza tabella**, dove non si poteva cercare.
«Non c'è» e «non potevo guardare» restano due risposte diverse.

### Come si interrogano sessioni e stirpi, in pratica

1. **Trovare la sessione.** Dal sessionId (o i suoi primi 8 caratteri):
   `get_session("0f1e2d3c")`. Dal contenuto: `search("parola", project="recupero:sessioni")`
   cerca solo fra le schede; l'uuid di una scheda porta a `get_conversation`, che
   risale a tutta la chat.
2. **Sapere dove si era fermata.** `get_session(...)`: `sessione.stato`, la
   `scheda` (ultime parole, fili aperti, commit).
3. **Leggerla.** `get_conversation(sessione.last_uuid)` — la chat intera, con la
   scheda in coda.
4. **Ricostruire la famiglia.** `get_stirpe(...)`: i membri in ordine, e per
   ciascuno di nuovo `get_session`.
5. **Le stirpi dal testo.** `search('"0f1e2d3c"', project="recupero:stirpi")`
   trova le schede di stirpe che nominano quella sessione.

Via SQL, sul file del DB (per esempio sulla VPS, o su una copia):

```sql
-- le sessioni di un bundle, dalla più recente
SELECT sessionId, titolo, stato, last_ts FROM sessioni ORDER BY last_ts DESC;

-- gli archi di una stirpe (chiusura = 1) che toccano una sessione
SELECT * FROM archi
 WHERE chiusura = 1 AND ('0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0' IN (da, a));

-- quale sessione ha scritto una memoria
SELECT path, scritta_da, mtime FROM memorie WHERE path LIKE '%nota%';

-- i messaggi di una sessione, dagli avvistamenti
SELECT m.ts, m.sender, substr(m.content, 1, 80)
  FROM sightings s JOIN messages m ON m.uuid = s.uuid
 WHERE s.source LIKE 'sessions/0f1e2d3c%' ORDER BY m.ts;
```

La tabella `memorie` non ha ancora un tool MCP: le memorie si cercano con `search`
(`project="recupero:memorie"`) e la tabella si legge via SQL.

## Documenti e immagini (PDF-scansione, screenshot) — via NotebookLM

Un PDF **senza testo** (scansione, screenshot) non ha nulla da estrarre con
`pypdf`. Ma **NotebookLM lo legge** (OCR multimodale). Dall'host:

```bash
vps1777 archive-ingest <file> --db <nome> --verify
```

Cosa fa: crea un notebook usa-e-getta, ci mette il file (NotebookLM lo processa),
chiede la **trascrizione integrale** via query, con `--verify` chiede a NotebookLM
di **verificare la fedeltà** della propria trascrizione (doer + checker), poi
indicizza il testo nell'archivio e pulisce il notebook. Funziona con PDF-immagine,
scansioni e qualunque file che NotebookLM sappia leggere.

> ⚠️ La trascrizione è generata da LLM, **non è OCR deterministico**: ottima per
> ritrovare contenuti, non garantita fedele al 100% su layout complessi. La query
> di verifica (`--verify`) segnala parti incerte/mancanti.

Richiede l'auth NotebookLM configurata (profilo nlm — vedi `/admin/nlm`).

Le **immagini dentro un bundle** (`workfiles/`) seguono un'altra strada: le legge
il servizio interno `ocr` (tesseract), senza mandare niente fuori; se il servizio
non c'è, ogni immagine lascia una lapide `ocr-non-disponibile`.

## Costruire un DB da riga di comando (locale)

L'indexer è stdlib-only e gira anche standalone (utile per batch grossi sul PC,
poi carichi il `.db` col drop-in):

```bash
python3 services/gateway/app/archive_indexer.py <input> out.db --project nome

# un bundle di Recupero Sessioni: stesso comando, lo zip si riconosce dal contenuto
python3 services/gateway/app/archive_indexer.py bundle.zip recupero-<ggmmaa>.db
```

L'indexer stampa **letti N → scritti M · deduplicati K** (la differenza è
deduplicazione per uuid, non perdita) e, se ci sono, quante lapidi ha lasciato. Le
righe delle tabelle `sessioni`/`archi`/`memorie` non entrano in quei numeri: si
contano con una query.

## Schema di un DB valido

Schema corrente:

```sql
messages(uuid PRIMARY KEY, project, ts, content,
         sender, tools, thinking, attachments, parent_uuid,
         ts_source,                                -- regime del ts (vedi sotto)
         speaker, voice, quoted_share, voice_conf, content_flags)  -- chi scrive / di chi è la voce
messages_fts USING fts5(uuid, project, ts, content, tools, attachments,
                        content='messages', ...,   -- external-content
                        tokenize="unicode61 tokenchars '+#'")  -- C++/C# non collassano
CREATE INDEX idx_parent ON messages(parent_uuid);   -- il thread-walking di get_conversation
revisions(uuid, ts, content, sender, project, ts_source, content_sha, superseded_date,
          PRIMARY KEY(uuid, content_sha))           -- le versioni uscenti di una riga riscritta
skipped(uid PRIMARY KEY, source, reason, detail, ts, ingest_date)  -- libro-mastro degli scarti
sightings(uuid, source, ingest_date, PRIMARY KEY(uuid, source))    -- dove ogni uuid è stato visto
meta(key PRIMARY KEY, value)                        -- scheda: description, ruolo, bundle_*
-- dal bundle di Recupero Sessioni (contratto recupero/ R1, 24/09/2026); vuote altrove
sessioni(sessionId, titolo, cwd, first_ts, last_ts, last_uuid, file,
         stato, stato_fonte, stirpe, stirpe_pos INTEGER, n_commit INTEGER,
         n_fili INTEGER, ingest_date, PRIMARY KEY(sessionId, file))  -- una riga per filone
archi(da, a, relazione, via, livello, prova, voce, peso REAL, chiusura INTEGER,
      bundle_scan, ingest_date, PRIMARY KEY(da, a, relazione, via))
memorie(path PRIMARY KEY, sistema, livello, md5, mtime, scritta_da, membro, ingest_date)
```

Le tabelle `revisions`, `sightings`, `meta` e le tre del bundle sono `CREATE TABLE
IF NOT EXISTS`: un DB esistente le riceve al primo ingest, e resta leggibile dalle
versioni precedenti.

**La chiave di `sessioni` è cambiata (dal 25/09/2026).** Un DB creato dalla 0.51.x ha
`sessioni` con la chiave `sessionId`. Al primo ingest l'indexer la porta alla chiave
`(sessionId, file)` (`_ensure_sessioni_filoni`): SQLite non cambia la chiave di una
tabella con un `ALTER`, quindi la tabella viene ricreata e le righe ricopiate tutte,
in un `SAVEPOINT` (o tutto o niente). Se fallisce, la tabella resta com'era e l'errore
esce. Una seconda volta non fa niente. Nessuna riga si perde: la chiave vecchia era
unica su `sessionId`, quindi lo è anche su `(sessionId, file)`. Un `file` NULL diventa
`''`. I filoni che la chiave vecchia aveva già schiacciato **non** tornano da soli:
**re-ingerisci il bundle**, e ora entrano tutti. archive-mcp legge anche la tabella
vecchia: su un DB non ancora migrato `filoni` ha una riga sola.

È quello che producono `archive_indexer` e `archive-ingest`. In FTS finiscono
`content`, `tools` (le azioni: `tool_use` + `tool_result`) e `attachments`;
`thinking` e `parent_uuid` si **conservano** nella tabella (leggibili via SQL /
`get_context`) ma **non** si indicizzano — vedi la nota sullo schema in
`archive_indexer.py`.

**`ts_source` — il regime del `ts`.** Dice che cosa è la data di una riga:

| valore | vuol dire |
|---|---|
| `messaggio` | il ts di un evento reale (un messaggio detto non cambia più). È il default |
| `data-export` | un ts della **fotografia**, non del contenuto: oggi lo dichiarano le schede e le memorie di `recupero/` (righe-stato, riscritte fra un ingest e l'altro) |
| `ignoto` | righe migrate da un DB nato prima della colonna: il regime non si ricostruisce a posteriori, e non si indovina |

Chi calcola il «più recente» di un archivio filtra **in negativo**:
`MAX(ts) WHERE ts_source <> 'data-export'`. Un estrattore dichiara il regime
passando a `write_rows` una **decima colonna** facoltativa (`messaggio` o
`data-export`; senza, resta `messaggio`; un altro valore ferma l'ingest).

**`speaker` e `voice`** — due assi che non vanno fusi. `speaker` è **chi ha inviato**
la riga, un fatto preso dalla fonte (`human` · `assistant` · `tool` · `system` · `unknown`:
allegati, titoli, memorie e schede sono `unknown`, perché non dicono chi le ha scritte).
`voice` è **di chi è la voce** nel contenuto, una stima euristica (`own` ·
`pasted_transcript` · `pasted_ai` · `character` · `mixed` · `unknown`), con la sua
confidenza e le bandiere che la spiegano. Escono **popolate** da ogni percorso
d'ingest.

**Gli output degli strumenti sono `tool`, non `human` (dalla 0.52.0).** In Claude Code
l'output di un comando (il `tool_result`) viaggia in un record di tipo `user`: fino alla
0.51.4 entrava come `sender='user'` → `speaker='human'`, e sul primario erano **74.818
delle 89.950** righe `human` (83%, misurato il 26/09/2026). Ora un record `user` fatto di
soli tool_result entra come `sender='strumento'` → `speaker='tool'`, e `speaker='human'`
torna a voler dire «parole di chi scrive». Due eccezioni restano `human`, perché sono
parole dell'utente consegnate dentro un tool_result: le **risposte alle domande a
opzioni** (il testo comincia con «Your questions have been answered» o «The user
answered»: la forma cambia con la versione di Claude Code) e i **rifiuti motivati**
(«The user doesn't want to proceed with this tool use… the user said:» seguito dalle sue
parole). Il riconoscimento è ancorato all'inizio del testo: la stessa frase dentro
l'output di un `grep` resta `tool`. Un tool_result dentro una sidechain resta
`mandato`, come prima.

I DB **già caricati** non vanno ri-ingeriti: la cura è una migrazione, perché il testo
non cambia (`sender` e `speaker` non stanno nell'FTS né nei vettori, e l'indice
semantico è legato ai rowid, che la migrazione non tocca). Parte da sola al primo
ingest in un DB vecchio; per i DB in cui non si scrive più c'è
[`vps1777 archive-migra`](CLI.md) (a secco di default, `--scrivi` per applicare), che
per ogni DB chiama nel gateway:

```bash
python -m app.archive_indexer /var/lib/archive/db/<nome>.db --migra [--scrivi]
```

e stampa `{"strumenti": N, "speaker_prima": {…}, "speaker_dopo": {…}, "scritto": …}`. Sul
primario: 74.818 righe, `human` da 89.950 a 15.132, 6 secondi (e con i turni del
programma, sotto, a 3.967). ⚠️ Anche a secco il file
può cambiare **sha** senza cambiare dati: SQLite non mette nel journal le pagine libere
che riusa, e dopo il ROLLBACK quelle restano libere ma con byte diversi (misurato: 638
pagine libere, dati e `integrity_check` identici). Chi confronta un DB per sha, come uno
script che carica l'indice solo se il DB non è cambiato, lo faccia prima del `--migra`.

**I turni del programma sono `system` (dalla 0.53.0, #293).** Dopo gli strumenti, sul
primario restavano 14.878 righe `human`, e il 75% non l'aveva scritto nessuno: 9.643
`<task-notification>` (un sotto-agente o un comando in background che ha finito), 1.115
output di comandi locali, 151 riassunti di compattazione, i testi delle skill, i messaggi
di altre sessioni. Li inietta Claude Code in un record di tipo `user`. Ora entrano come
`sender='sistema'` → `speaker='system'`. Come si decide:

1. **il fatto del record**, dove c'è: le versioni recenti scrivono `origin.kind`
   (`human` = chi scrive; `task-notification`, `peer`, `coordinator`… = il programma),
   `isMeta` e `isCompactSummary`. `origin.kind='human'` vince su tutto il resto;
2. **la forma del testo**, solo se il record non dice niente: le forme che solo il
   programma scrive (`<task-notification`, `<local-command-…`, «This session is being
   continued…», «Base directory for this skill:», «Another Claude session sent a
   message», `<system-reminder>`…; l'elenco è `_FORME_DEL_PROGRAMMA` nell'indexer),
   ancorate all'inizio del testo.

Restano `human` gli **slash command** (`<command-name>`) e i comandi lanciati con `!`
(`<bash-input>`): sono gesti di chi scrive. Restano `human` anche i prompt che uno
script manda a una sessione senza testa (un cron che chiama `claude -p`): il record non
lo distingue da un prompt scritto a mano, e il testo è quello dello script.

Sui DB già caricati `origin` e `isMeta` non sono stati conservati: `vps1777
archive-migra` decide solo con la forma del testo. Un turno che il programma marcava
solo col campo, con un testo senza forma riconoscibile, resta `human` finché un
re-ingest non lo rilegge dalla fonte. Sul primario: 11.165 righe a `system`, `human` da
15.132 a 3.967.

**`revisions`** conserva la versione **uscente** quando lo stesso uuid ritorna con un
contenuto diverso (una memoria riscritta, una scheda aggiornata, un pezzo tolto):
`messages` resta l'ultima versione, la storia si interroga per uuid.

Cose in più che l'ingest produce:

- le **`summary`** delle conversazioni claude.ai diventano righe attribuite
  `sender='summary'`, cercabili come tutto il resto;
- dalle **sessioni Claude Code** (`.jsonl`) l'ingest cattura anche i **titoli**
  (`ai-title` → riga `sender='title'`: trovi una chat dal suo nome) e gli
  **allegati** (`attachment` → riga `sender='attachment'` coi nomi-file), a
  parità col percorso claude.ai. I record che **non sono messaggi** (`mode`,
  `system`, `last-prompt`, `queue-operation`, …) non vengono indicizzati ma
  **non spariscono**: lasciano una lapide `reason='non-message'` (vedi sotto);
- ogni record **scartato** (senza uuid, vuoto, non-messaggio) lascia una
  **lapide** in `skipped` — con motivo e il record grezzo — invece di sparire in
  un `continue` muto: il conteggio è in `db_info()["skipped"]` / `count_skipped()`,
  e i dati raw restano raggiungibili. *(Nota sul contare: la tabella `skipped`
  deduplica per contenuto — due record identici sono una lapide, come il dedup
  per `uuid` dei messaggi. Un collaudo che vuole quadrare col numero di **righe
  lette** deve trattare i doppioni come categoria, non come perdita: vedi
  `tools/collaudo-quadratura.py`.)*
- la **descrizione** dell'archivio vive in `meta['description']` (scritta
  all'upload, aggiornabile via `set_description`); il **ruolo** vive accanto in
  `meta['ruolo']` (scritto da `set_ruolo`, chiave assente = `non dichiarato`); dai
  bundle arrivano `bundle_generated`, `bundle_previsione_ingest` e `bundle_recupero`.
  Tutti viaggiano **dentro il file**: un `.db` spostato o ripristinato da un
  backup si porta dietro la propria scheda, senza un registro esterno da tenere
  in sincrono.

> **Righe-evento vs righe-stato.** Le chat sono **eventi** (un `ts`, immutabili);
> `memory:*`, `account:user` e le schede `recupero:*` sono **stati** (riscritti fra
> un ingest e l'altro). `oldest` in `describe_databases` usa `min(NULLIF(ts,''))`
> così gli stati senza data non fanno vincere la stringa vuota sul minimo —
> l'archivio non dice più «non so da quando» sapendolo.

Un `.db` drop-in è accettato se è un SQLite con la tabella `messages_fts`
(controllo in `admin.py`). Anche un DB **v1** (le sole 4 colonne
`uuid, project, ts, content`) resta valido: `migrate_v1_to_v2()` gli aggiunge le
colonne nuove e ricostruisce l'FTS: le righe vecchie restano (con `tools`/`thinking`
vuoti finché non ri-esegui l'ingest sulla fonte, idempotente per `uuid`).

## Limiti noti

Dichiarati, non scoperti per caso:

- **Le tabelle si accumulano, non dimenticano.** Una sessione, un arco o una memoria
  che spariscono da un bundle nuovo **restano** in `sessioni`, `archi` e `memorie`:
  il contratto R1 non ha una semantica di rimozione. Allo stesso modo resta la
  scheda di una sessione che un bundle nuovo non consegna più (la potatura dei pezzi
  vale solo quando lo stesso membro ritorna).
- **`meta` dice l'ultimo bundle.** Se nello stesso DB entrano più bundle, le chiavi
  `bundle_*` descrivono solo l'ultimo; `bundle_generated` lo data.
- **La redazione in uscita guastava uuid e date — curato nella 0.51.1.** Fino alla 0.51.0
  il pattern dei telefoni prendeva i gruppi di sole cifre di un uuid
  (`12345678-1234-4123-8123-123456789012` usciva `[telefono redatto]-4123-8123-[telefono
  redatto]`) e le date con l'ora separata da uno spazio (`2026-09-05 13:10` usciva
  `[telefono redatto]:10`). Ora gli uuid canonici non si toccano e le date valide con l'ora
  restano; le esenzioni sono strette (un mese 13, un giorno 32, un'ora 24 restano telefono) e
  i telefoni veri continuano a sparire (test in `test_redazione.py`, nei due versi).
- **«MCP server connection lost» alla prima chiamata dopo una pausa — curato nella
  0.55.1.** Tre volte fra il 24 e il 26/09 la prima chiamata del connettore dopo un
  update, un ingest o il caricamento di un indice si interrompeva, e la seconda andava.
  Riprodotto il 26/09: dopo un riavvio di archive-mcp la prima `search_ibrida` rispondeva
  in **64,9 s**, oltre i 60 s di lettura del proxy del gateway (`httpx.ReadTimeout` nei
  log). La causa era la redazione in uscita: alla prima chiamata dopo un avvio o un
  cambio della dir raccoglie l'anagrafica (`project='account:user'`) da ogni DB, e senza
  un indice su `project` li leggeva per intero, **46,7 s** a cache fredda su 29 DB. Ora
  i DB hanno `idx_project`: lo crea l'ingest, e sui DB già caricati `vps1777
  archive-migra --scrivi` (4,6 s sul primario, +7 MB). Finché un DB non ce l'ha, la
  prima chiamata resta lenta.
- **Le righe vecchie del ponte non si tolgono da sole.** Un DB che aveva ingerito
  bundle col ponte `workfiles/_recupero-1777/` con un indexer **precedente**
  all'alias ha righe `workfile:_recupero-1777/…`; re-ingerire con questo indexer
  aggiunge le righe `recupero:*` ma non toglie quelle.
- **`memorie` senza tool.** Si legge via SQL o con `search`.
- **`documents/` dice di che specie è un documento, non da dove viene.** L'app (dal
  25/09/2026) scrive `documents/<famiglia>/…`: l'etichetta è la famiglia
  (`document:testo`, `document:codice`…). Il nome del file è cercabile, perché è la
  prima riga del testo; la cartella d'origine sta solo in `MANIFEST.json`
  (`documenti.consegnati[].src`), di proposito: un percorso nell'etichetta porterebbe
  la struttura del disco in ogni risposta.
- **`last_ts` e l'ultimo messaggio.** Su un bundle reale il `last_ts` della scheda è
  risultato più recente del ts del messaggio `last_uuid` (l'ultimo record con quel
  timestamp non era un messaggio). L'ordine regge — la scheda esce dopo — ma
  `last_ts` e `conversazione.ultimo_ts` di `get_session` possono non coincidere.

## Come funziona sotto (confine no-docker.sock)

Il gateway monta il volume `archive-data:rw` e scrive i `.db` in
`/var/lib/archive/db/`; `archive-mcp` lo monta **in sola lettura**, scansiona quella
dir (**scan-mode**) e scopre i DB nuovi senza riavvio. Le uniche due scritture che un
tool può chiedere — `set_description` e `set_ruolo`, che toccano solo la scheda
`meta` — passano dal gateway (`/internal/archive/description`,
`/internal/archive/ruolo`, sulla rete interna con un segreto condiviso). Per l'ingest
via NotebookLM, l'orchestrazione è sull'host (`vps1777 archive-ingest`): il gateway
non parla a Docker né a nlm — il CLI host copia il file in `nb1777-mcp` (che ha l'auth
nlm), ne ricava il testo, e lo passa al gateway per l'indicizzazione. Vedi
[ARCHITECTURE.md](ARCHITECTURE.md).
