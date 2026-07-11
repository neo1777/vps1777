# Skill da costruire sopra archive1777 — roadmap (non prodotto)

> **Cos'è questo documento.** Un catalogo di **skill 1777** (voci per
> `~/.claude/skills`, non componenti del prodotto vps1777) che sfruttano i tool
> di `archive-mcp`. vps1777 le contiene **come istruzioni per costruirle**, non
> come codice del server. La fabbrica naturale è **`create1777`** (avvolge
> `skill-creator` con lo strato-stile 1777).
>
> **Stato:** bozza da studiare e completare. Nasce dal *paper sperimentale su
> archive1777* (2026-07-11, §6.4 "usi emergenti" e §12 "future work") + dalle
> migliorie di **archive-mcp v0.19.0**. Non è un piano esecutivo: è la base su
> cui, in una sessione dedicata, si fa l'approfondimento con ricerca reale su
> `archive1777` e poi si passa a `create1777`.
>
> **Disciplina di provenienza (1777):** [paper] = dal paper con riferimento di
> sezione · [tool] = capacità reale di archive-mcp v0.19.0 · [inferenza] =
> ragionamento oltre l'evidenza, da validare in sessione.

## Perché queste skill sono possibili solo ora

Il paper ha dimostrato che il valore emergente dell'archivio nasce dalla
**combinazione verbatim × timestamp × cross-DB** — proprietà non pianificate
insieme. La release **archive-mcp v0.19.0** ha aggiunto proprio gli strumenti
che queste skill richiedono [tool]:

- `count(query)` → frequenze e prevalenze (abilita *Cronotopo*, *Estrattore di Gotcha*).
- `get_context(uuid, before, after)` → il testo **pieno** attorno a un hit, non
  lo snippet troncato (indispensabile per *Verificatore di Memorie* e *Registro
  delle Promesse*, che devono leggere l'impegno per intero).
- `sort=newest|oldest` + `since`/`until` → l'asse temporale esplicito (*Cronotopo*,
  *Genealogia dei Nomi*).
- `describe_databases()` con `snapshot` → freschezza per DB (ogni skill sa quanto
  è vecchio ciò che legge).
- superficie d'errore **parlante** → niente più falsi negativi silenziosi: una
  skill che conclude "non c'è" ora può fidarsi (dopo il *protocollo dello zero*).

> Vincolo di costruzione ricorrente: la logica pura di ogni skill che potrebbe
> finire lato-server va tenuta **stdlib-only e testabile** (pattern vps1777:
> `archive_indexer`, `fts.py`, `miniapp_core`). Per le skill pure-prompt non
> serve, ma la disciplina fatti/inferenze del metodo 1777 sì.

---

## A1 — Registro delle Promesse

**Cosa fa.** Traccia gli **impegni presi con persone reali** (nel gruppo
Telegram, nelle chat) e ne verifica la **chiusura**: distingue ciò che è stato
mantenuto da ciò che è rimasto in sospeso. [paper §6.4 #1]

**Il problema che risolve.** Neo prende impegni sparsi ("appena finisco ti passo
l'MCP", "vi mando la versione libera") in canali diversi e li perde di vista. Una
sessione isolata non può sapere quali sono aperti. Il paper l'ha usato come primo
uso emergente e ne ha mostrato un ciclo end-to-end: **promessa dell'MCP agli amici
→ repo pubblicato il 24-25 giu** (mantenuta), a fronte della *"versione libera di
marzio1777 promessa a Lorenzo il 1 giu"* che **non risulta ancora uscita** (aperta).
[paper §6.2, §6.4]

**Come funziona (pattern abilitante).** [paper §6.4 #1]
- Ricerca degli impegni: `"vi passo" OR "ti passo" OR "appena" OR "prometto" OR "ti mando"`
  sul DB `stirati-coding-group` e su `claude-ai`.
- Per ogni impegno trovato: `get_context` per leggere l'oggetto preciso, poi
  follow-up sull'oggetto per cercarne la chiusura (es. il nome del deliverable
  promesso → esiste un messaggio successivo che lo consegna?).
- Output: due liste datate — **mantenute** / **aperte** — ciascuna con
  uuid+ts di apertura e (se presente) di chiusura.

**Come costruirla.** `create1777` → skill pure-prompt che orchestra query su
`archive1777`, con la disciplina "aperto/chiuso" già usata da `setaccio` e
`dossier1777` (fatto vs inferenza). Interlocutore umano nel loop per confermare
le chiusure ambigue.

**Da decidere in sessione.** Confini di privacy (il DB Telegram contiene persone
reali); se produce un artefatto persistente (una nota di plancia aggiornabile) o
solo un report on-demand; se integra le persone via *A3/Indice delle Persone*.

**Stato:** definita, ROI alto, candidata apripista. [paper §12: "create1777 è la
fabbrica naturale"]

---

## A2 — Verificatore di Memorie

**Cosa fa.** Fa **fact-checking dei "ricordi"** — le memorie di sessione
(`userMemories`, `CLAUDE.md`, `MEMORY.md`, le note di plancia) — **contro
l'archivio** con uuid+timestamp: scova le assunzioni invecchiate prima che
finiscano in un deliverable. [paper §6.4 #3]

**Il problema che risolve.** È la contro-parte operativa della scoperta centrale
del paper: *«un'assunzione sbagliata in meno vale più di dieci ricordi in più»*,
perché gli errori di premessa si propagano a valle. Il paper ha **corretto 5
assunzioni** che una sessione isolata avrebbe fatto con fiducia (es. "Neo è un
hobbista autodidatta" → in realtà programmatore C++; "il libro è il cantiere
attivo" → in pausa volontaria; "l'archivio è stabile a 3 DB / 37.590 msg" → è uno
snapshot datato). [paper §5.2] Un uso embrionale è già comparso il 21 giu e il
6 lug (fact-checking del CV). [paper §6.1]

**Come funziona (pattern abilitante).** [inferenza dai §5, §7 del paper]
- Prende un "ricordo" (una riga di memoria, un claim in un CLAUDE.md).
- Ne estrae il claim verificabile e lo cerca in `archive1777` con `sort=newest`:
  qual è l'**evidenza più recente** su quel fatto?
- Confronta la data del ricordo con lo `snapshot` del DB e con il ts dell'ultima
  evidenza → verdetto **CONFERMATO / ESTESO / CORRETTO / NON TROVATO** (la stessa
  rubrica del paper §5).
- `get_context` per leggere l'evidenza per intero prima di sentenziare.

**Come costruirla.** `create1777` → skill che incrocia lo strato-memoria con
l'archivio. Va coordinata con la disciplina **live/arch/mem/cieco** già codificata
in plancia [paper §9] e con la regola "datare ogni ricordo citato".

**Da decidere in sessione.** Su quali file di memoria opera (solo i propri, o
anche i CLAUDE.md di progetto); se propone patch alle memorie o solo il verdetto;
come tratta il "delta tra strati" come segnale (paper §7: il masterIndex fermo di
un mese è esso stesso diagnostico → vedi doc B).

**Stato:** definita, alto valore, seconda apripista naturale dopo A1.

---

## A3 — Interrogatore dell'Archivio (contenitore, da valutare)

**Cosa fa.** Raccoglie gli **altri cinque usi emergenti** del paper come *lenti*
di un'unica skill (o come query-pattern documentati, da decidere). Sono tutti
già dimostrati nel paper ma meno "prodotto-izzabili" singolarmente. [paper §6.4]

| Lente | Cosa estrae | Pattern [paper §6.4] |
|---|---|---|
| **Genealogia dei Nomi** | quando e perché nasce un nome | `<nome> AND (nome OR "la mia" OR battezz*)` cross-DB; ricostruisce l'arco di un nome-progetto (prima menzione → battesimo → manifesto) dai messaggi datati |
| **Estrattore di Gotcha** | runbook auto-generato delle regole dure | `SEQUENZIALI OR droppano OR "verifica alla fonte"` — restituisce ciò che fu ricopiato a mano molte volte |
| **Cronotopo** | ritmi di lavoro dai timestamp | `count` + `sort` sui ts: come cambiano gli orari di lavoro nel tempo |
| **Indice delle Persone** | ruoli e relazioni dai soli nomi | poche query ricostruiscono ruoli e legami di un gruppo chat dai nomi ricorrenti |
| **Lente biografica** ⚠️ | marcatori datati per una eventuale autobiografia | *uso delicato*: tocca materiale personale; **solo con consenso esplicito, query non invasive — probabilmente da NON automatizzare** |

**Da decidere in sessione.** Se è **una** skill con più modalità, cinque skill
piccole, o semplicemente una pagina di **query-pattern** nella doc di archive1777.
La *Lente biografica* ha implicazioni etiche/di privacy che vanno trattate a parte
e probabilmente **non** vanno automatizzate.

**Stato:** contenitore opzionale; da triare con `create1777` (check anti-doppione,
"ricorre / non banale / non già coperto") prima di decidere la forma.

---

## Fonti

- *Paper sperimentale su archive1777* (2026-07-11), §3, §5.2, §6, §7, §9, §12 e
  Appendice A. File di baseline: `baseline_memoria_isolata.md`.
- Migliorie abilitanti: `CHANGELOG.md` [0.19.0]; tool in `docs/ARCHIVE.md`.
- Memoria di progetto: `vps1777-archive-mcp-search`, `vps1777-archive-ingest`.
- Fabbrica: skill `create1777` (`~/.claude/skills/create1777`).
