# La CLI `vps1777` — tutti i comandi

> Questa pagina è la guida con gli esempi; l'aiuto sintetico è `vps1777 help`
> (o `--help`), e `vps1777 help <comando>` mostra le opzioni di un comando.
> **Un test tiene questa pagina allineata al codice** (`tools/tests/test_cli_doc.py`):
> un comando nuovo senza la sua sezione qui fa fallire la CI.

Dove si lancia: **sull'host della VPS**, come utente operatore (mai da root nudo:
se sei root, `sudo -u <operatore> vps1777 …`). Le parole del glossario:
[GLOSSARIO.md](GLOSSARIO.md).

Un'opzione vale per tutti i comandi e va **prima** del comando: `--home CARTELLA`, la
radice del repo sulla VPS. Senza, la CLI usa `$VPS1777_HOME` e, se manca anche quella,
`/home/vps1777/vps1777`.

```bash
vps1777 --home /srv/vps1777 status
```

## vps1777 help

L'aiuto, per esteso o per singolo comando. Riusa il parser vero: quello che
stampa è per costruzione ciò che il codice accetta.

```bash
vps1777 help              # elenco dei comandi
vps1777 help memoria      # opzioni e sotto-comandi di `memoria`
```

## vps1777 check

Controlla se esiste una release più nuova di quella installata (chiede a GitHub). È il
comando del timer giornaliero `vps1777-check-update.timer`, e **non è di sola lettura**:
prima di chiedere a GitHub fa anche la manutenzione e le sorveglianze che stanno sul suo
giro.

- **Pota gli snapshot pre-update** (`backups/pre-update/`): restano l'ultimo di ciascuna
  delle versioni n e n-1, più il più recente in assoluto — il punto di ritorno della
  versione in esecuzione ([BACKUP-RESTORE.md](BACKUP-RESTORE.md)).
- **Tre sorveglianze**, sempre, con l'esito nel log: la raggiungibilità del servizio da
  fuori (la porta sull'host, poi l'indirizzo pubblico — il Funnel o `PUBLIC_BASE`;
  l'esito va anche in `onboarding/raggiungibilita.json`,
  letto da `/admin/setup`), la **copertura** dei backup (giorni distinti, avvisa se scende
  sotto il massimo già raggiunto) e l'**età** dell'ultimo backup archivio (avvisa oltre i
  14 giorni; se l'archivio non esiste ancora, tace).
- **Scrive lo stato**: `onboarding/update_status.json` (la card admin e la Mini App lo
  leggono) e `last_check` in `var/state.json`.

Con GitHub irraggiungibile esce comunque 0: l'errore finisce in `update_status.json`,
non in una notifica.

```bash
vps1777 check             # stampa: installata vs ultima release
vps1777 check --notify    # in più: messaggio Telegram all'owner se c'è una nuova
```

`--notify` manda su Telegram la release nuova (una volta per versione) e i **cambi di
stato** delle tre sorveglianze — la caduta e il ritorno, non lo stato ogni giorno. Senza
`--notify` le sorveglianze girano lo stesso e scrivono solo nel log.

## vps1777 update

Aggiorna alla release più recente (o a una versione esplicita): backup,
snapshot dei volumi, download del bundle **firmato** (verifica cosign), pull
delle immagini per digest, riavvio, health-gate — e rollback automatico se
qualcosa non torna. È il comando che la unit `vps1777-auto-update.service`
esegue: dall'host di solito si avvia **quella**, non questo a mano.

**La quarantena scatta solo con `--eta-minima ORE`**, ed è la unit a passarla
(`--eta-minima 48`): installa l'ultima release solo se è stata pubblicata da almeno 48 ore,
altrimenti non fa niente e riprova al giro dopo (vedi [UPDATE.md](UPDATE.md)). Un
`vps1777 update` lanciato a mano **senza opzioni non ha quarantena**: installa subito
l'ultima release, dopo aver chiesto conferma. Con `--version` la quarantena è ignorata
anche se passi `--eta-minima`, e il target esplicito può essere anche **più vecchio** di
quello installato (è l'unica via di downgrade; dal pulsante admin è rifiutato).

Le opzioni:

- `--version vX.Y.Z` — target esplicito (es. una rc).
- `--yes` — nessuna conferma.
- `--eta-minima ORE` — la quarantena, sul solo percorso senza `--version`.
- `--from-intent FILE` — il file d'intento scritto dal pulsante admin: lo usa la unit
  `vps1777-update.service`, non si lancia a mano. Con questo non chiede conferma.
- `--no-require-cosign` — **via d'emergenza**: salta la verifica della firma del bundle
  (come `VPS1777_REQUIRE_COSIGN=0` nel `.env`). `secrets-status` la segnala finché resta
  aperta.
- `--require-cosign` — ridondante: la verifica è già obbligatoria di default.

Cosa lascia sul disco: nel `.env` il tag (`VPS1777_TAG`) e un digest per servizio
(`VPS1777_DIGEST_<SERVIZIO>`, es. `VPS1777_DIGEST_ARCHIVE_MCP`), scritti insieme allo
step 10; in `onboarding/update_progress.json` l'ultimo step (la barra dei pannelli) e in
`onboarding/update_journal.ndjson` **una riga per step**, anche per un update riuscito —
è da lì che si legge la mattina dopo cosa ha fatto l'auto-update della notte.

Se un altro update (o un rollback) è già in corso esce con **75** («riprova più tardi»),
che le unit contano come successo: non è un guasto e non manda l'avviso di fallimento.

```bash
sudo systemctl start vps1777-auto-update.service   # la via normale (con la quarantena)
vps1777 update                                     # a mano: l'ultima release, subito (chiede conferma)
vps1777 update --version v0.44.0 --yes             # target esplicito, subito (es. una rc)
```

## vps1777 rollback

Torna alla versione precedente (immagini + file gestiti, e nel `.env` tag e digest della
versione precedente). Con `--with-data` ripristina anche i volumi dallo snapshot
pre-update — è l'opzione invasiva. **Chiede sempre conferma**, con o senza `--with-data`:
la salta solo `--yes`.

Esce **75** se un update o un altro rollback è in corso (lo stesso lock di `update`), e
**2** se il rollback è applicato ma l'health-gate non torna verde (avviso su Telegram).

```bash
vps1777 rollback
vps1777 rollback --with-data --yes
```

## vps1777 status

Lo stato del canale di aggiornamento: versione corrente, precedente, ultima release nota
(`latest_known`), ora dell'ultimo check, l'eventuale errore del check e l'update in corso
(`update_in_progress`: c'è dallo step 10 in poi, e resta se un update muore dopo quel
punto di non ritorno). Con
`--json` c'è anche il canale delle release (`channel`); con `--probe` lo stato di ogni
container e il deep health. Snapshot ed esito dell'ultimo update non li mostra: stanno in
`backups/pre-update/` e in `onboarding/update_journal.ndjson`.

```bash
vps1777 status
vps1777 status --probe    # interroga anche i container
vps1777 status --json     # per gli script
```

## vps1777 version

Le versioni deployate: tag del repo e versione dentro ogni container dello stack. Un'immagine
opzionale che lo stack non usa (`caddy-dns01` a feature spenta) compare come «non attivo».

```bash
vps1777 version
```

## vps1777 migrate

Il runner delle migrazioni dati (cartella `migrations/`): elenca o applica
quelle non ancora eseguite. `vps1777 update` le applica da sé; questo serve
per guardarle o per recuperare a mano.

```bash
vps1777 migrate --pending   # cosa manca
vps1777 migrate --run       # applica
```

## vps1777 bootstrap

Cutover one-shot da un'installazione legacy (pre-canale-update) al canale
gestito: importa lo stato, fa il primo backup completo, aggancia le unit.
Si usa una volta sola, seguendo [INSTALL.md](INSTALL.md). Il bundle lo cerca da sé
quando la CLI gira dal bundle estratto; altrimenti gli si indica con `--bundle`.

```bash
vps1777 bootstrap --yes
vps1777 bootstrap --bundle /tmp/vps1777-bundle --yes   # bundle estratto altrove
```

## vps1777 archive-ingest

Indicizza un file nell'archivio di ricerca. La strada la sceglie l'estensione:

- **file di testo** (`.md` `.txt` `.markdown` `.rst` `.log` `.csv` `.json` `.jsonl`) →
  **diretti all'indexer** del gateway, senza NotebookLM;
- **tutto il resto** (PDF-scansione, foto di documenti…) → **passando da NotebookLM**
  (lettura multimodale/OCR). ⚠️ Il file viene mandato a Google.

Per i formati normali caricati dal browser (zip/jsonl/md/pdf-con-testo) c'è anche la pagina
`/admin/archive` del gateway ([ARCHIVE.md](ARCHIVE.md)).

Le opzioni: `--db NOME` (il DB di destinazione; default dal nome del file), `--project
ETICHETTA` (l'etichetta progetto; default il nome del DB), `--verify` (chiede a NotebookLM
di verificare la trascrizione), `--nlm` (forza il giro NotebookLM anche su un file di
testo — per esempio un `.txt` che è il dump di una scansione).

```bash
vps1777 archive-ingest scansione.pdf --db documenti --verify
vps1777 archive-ingest note.md --db documenti --project studio   # testo: diretto
```

## vps1777 archive-retag

Ri-classifica la colonna `voice` (di chi è la voce nel contenuto) sui DB
dell'archivio, con l'euristica corrente. **A secco di default**: stampa il delta
e non tocca nulla; scrive solo con `--scrivi`.

```bash
vps1777 archive-retag                     # anteprima su tutti i DB
vps1777 archive-retag --db cc --scrivi    # applica su un DB solo
```

## vps1777 indice-modello

Scarica il modello della ricerca per senso (`intfloat/multilingual-e5-small`,
l'ONNX ufficiale) **a revisione fissa**, verifica byte e sha256 di ogni file e lo
mette nel volume dell'archivio, dove lo legge archive-mcp. Idempotente: se il
modello giusto c'è già, non scarica niente. Un modello **diverso** già presente (un
export fatto a mano) non lo sostituisce senza `--sostituisci`, perché l'indice
costruito con quello è legato alla sua impronta. Con `--dest CARTELLA` scarica solo
lì: è il modo di averlo sul PC per il costruttore dell'indice
([RICERCA-IBRIDA.md](RICERCA-IBRIDA.md)).

```bash
vps1777 indice-modello                                         # sulla VPS, nel volume
python3 tools/vps1777.py indice-modello --dest ~/e5-small      # sul PC, dal checkout
```

## vps1777 indice-notturno

Aggiorna in modo incrementale gli indici della ricerca per senso che **esistono già**,
solo per i DB più recenti del loro indice. Lo lancia il timer notturno; a mano serve a
provarlo o ad accenderlo e spegnerlo. Il costruttore gira nel servizio compose
`indice-notturno` (limite di memoria 1300m, una CPU, nessuna rete). Non fa mai una prima
costruzione. Dettagli e costi: [RICERCA-IBRIDA.md](RICERCA-IBRIDA.md).

```bash
vps1777 indice-notturno --abilita          # accende il timer (opt-in)
vps1777 indice-notturno --disabilita       # lo spegne
vps1777 indice-notturno                    # un giro adesso
vps1777 indice-notturno --db X --tutti     # un DB solo, anche se già allineato
```

## vps1777 archive-migra

Porta ai DB **già caricati** le migrazioni delle colonne derivate, senza ingest:
oggi gli output degli strumenti di Claude Code scritti `human` da un indexer
precedente alla 0.52.0 diventano `speaker='tool'`, e i turni del programma
(notifiche, output di comandi locali, compattazioni) scritti `human` prima della
0.53.0 diventano `speaker='system'` ([ARCHIVE.md](ARCHIVE.md)). Crea anche, dove
manca, l'indice per etichetta di progetto (`idx_project`). Il
testo non cambia: FTS e indice semantico restano validi. **A secco di default**:
misura il delta su una transazione vera, la annulla e non tocca i dati; scrive solo
con `--scrivi`. I `.vec.db` (indici semantici) non sono archivi e vengono saltati.

```bash
vps1777 archive-migra                                  # anteprima su tutti i DB
vps1777 archive-migra --db recupero-20260924 --scrivi  # applica su un DB solo
```

Con `--telegram` (e `--db`, obbligatorio) dà lo `speaker` ai messaggi di un **gruppo
Telegram** già caricato: il proprietario `human`, gli altri membri `other`. Il
proprietario lo dicono i suoi nomi Telegram in `ARCHIVE_TELEGRAM_PROPRIETARIO` nel `.env`
(senza, esce 2); si lancia solo sui DB che sono export Telegram
([ARCHIVE.md](ARCHIVE.md)).

```bash
vps1777 archive-migra --db gruppo-telegram --telegram           # anteprima
vps1777 archive-migra --db gruppo-telegram --telegram --scrivi  # applica
```

## vps1777 secrets-status

Età e scadenze dei secret (chiavi, token, cookie NotebookLM): elenca cosa è da
ruotare. Nella stessa lista compare la **via d'emergenza cosign** se è aperta
(`VPS1777_REQUIRE_COSIGN=0` nel `.env`), con una soglia di un giorno. Elenca a parte i
**secret attesi e non trovati** in `secrets/` — `cloudflared_token` solo col profilo
Cloudflare (fino alla 0.62.2 compariva fra i mancanti su ogni installazione), `cf_api_token`
solo con la feature `caddy-dns01`. Con `--notify` avvisa su Telegram gli scaduti. Il
risultato compare anche in `/admin/secrets` (dal file `onboarding/secrets_status.json`).

Se non trova **nessun** secret da misurare esce **2**: non è «tutto a posto», è «non ho
potuto guardare» (percorso sbagliato o permessi), e con `--notify` lo dice su Telegram.

```bash
vps1777 secrets-status
vps1777 secrets-status --notify
```

## vps1777 memoria

Gli **strati locali della memoria 1777** ([MEMORIA-1777.md](MEMORIA-1777.md)):
la disciplina (le regole, dentro il prodotto) più i due file dell'installazione,
`fatti.md` (chi è l'utente) ed `errata.md` (falsi corretti). Tre sotto-comandi:

```bash
vps1777 memoria stato                      # versione della disciplina, strati presenti, ack cloud
vps1777 memoria mostra disciplina          # stampa il canonico servito dal tool
vps1777 memoria mostra fatti               # stampa uno strato locale (o: errata)
vps1777 memoria importa fatti mio-file.md  # carica (SOSTITUISCE) uno strato (o: errata)
```

`importa` scrive dentro il container di nb1777-mcp come l'utente giusto, in modo
atomico, e verifica i byte scritti; un file vuoto viene rifiutato (cancellerebbe
lo strato buono in silenzio).

## vps1777 avvisa-fallimento

Manda su Telegram «la unit X è fallita» con le ultime righe di journal. Non si
lancia a mano: lo usano le unit systemd via `OnFailure=`.

```bash
vps1777 avvisa-fallimento --unit vps1777-auto-update.service --righe 12
```

## vps1777 campanello

Manda a Neo su Telegram il conto delle «cose da fare» (pagine e decisioni sulla frontiera,
posti rossi) con il link alla pagina. Un messaggio per giro: lo stesso conto non suona due
volte. Accetta solo numeri e un link `https://claude.ai/…`. Lo chiama il PC dopo ogni
cottura della pagina, via SSH; `--prova` stampa il messaggio senza mandarlo.

```bash
vps1777 campanello --pagine 3 --decisioni 114 --rossi 0 --url https://claude.ai/artifact/… --prova
```
