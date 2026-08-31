# La CLI `vps1777` — tutti i comandi

> Questa pagina è la guida con gli esempi; l'aiuto sintetico è `vps1777 help`
> (o `--help`), e `vps1777 help <comando>` mostra le opzioni di un comando.
> **Un test tiene questa pagina allineata al codice** (`tools/tests/test_cli_doc.py`):
> un comando nuovo senza la sua sezione qui fa fallire la CI.

Dove si lancia: **sull'host della VPS**, come utente operatore (mai da root nudo:
se sei root, `sudo -u <operatore> vps1777 …`). Le parole del glossario:
[GLOSSARIO.md](GLOSSARIO.md).

## vps1777 help

L'aiuto, per esteso o per singolo comando. Riusa il parser vero: quello che
stampa è per costruzione ciò che il codice accetta.

```bash
vps1777 help              # elenco dei comandi
vps1777 help memoria      # opzioni e sotto-comandi di `memoria`
```

## vps1777 check

Controlla se esiste una release più nuova di quella installata (chiede a GitHub,
non tocca nulla).

```bash
vps1777 check             # stampa: installata vs ultima release
vps1777 check --notify    # in più: messaggio Telegram all'owner se c'è una nuova
```

## vps1777 update

Aggiorna alla release più recente (o a una versione esplicita): backup,
snapshot dei volumi, download del bundle **firmato** (verifica cosign), pull
delle immagini per digest, riavvio, health-gate — e rollback automatico se
qualcosa non torna. È il comando che la unit `vps1777-auto-update.service`
esegue: dall'host di solito si avvia **quella**, non questo a mano.

```bash
sudo systemctl start vps1777-auto-update.service   # la via normale
vps1777 update --version v0.44.0 --yes             # target esplicito (es. una rc)
```

## vps1777 rollback

Torna alla versione precedente (immagini + file gestiti). Con `--with-data`
ripristina anche i volumi dallo snapshot pre-update — è l'opzione invasiva,
chiede conferma.

```bash
vps1777 rollback
vps1777 rollback --with-data --yes
```

## vps1777 status

Lo stato del canale di aggiornamento: versione installata, ultima release nota,
snapshot, esito dell'ultimo update.

```bash
vps1777 status
vps1777 status --probe    # interroga anche i container
vps1777 status --json     # per gli script
```

## vps1777 version

Le versioni deployate: tag del repo e versione dentro ogni container.

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
Si usa una volta sola, seguendo [INSTALL.md](INSTALL.md).

```bash
vps1777 bootstrap --yes
```

## vps1777 archive-ingest

Indicizza un file nell'archivio di ricerca **passando da NotebookLM** (lettura
multimodale/OCR): è la via per il documento pregiato che l'ingest normale non sa
leggere — PDF-scansione, foto di documenti. ⚠️ Il file viene mandato a Google.
Per i formati normali (zip/jsonl/md/pdf-con-testo) usa la pagina
`/admin/archive` del gateway ([ARCHIVE.md](ARCHIVE.md)).

```bash
vps1777 archive-ingest scansione.pdf --db documenti --verify
```

## vps1777 archive-retag

Ri-classifica la colonna `voice` (di chi è la voce nel contenuto) sui DB
dell'archivio, con l'euristica corrente. **A secco di default**: stampa il delta
e non tocca nulla; scrive solo con `--scrivi`.

```bash
vps1777 archive-retag                     # anteprima su tutti i DB
vps1777 archive-retag --db cc --scrivi    # applica su un DB solo
```

## vps1777 secrets-status

Età e scadenze dei secret (chiavi, token, cookie NotebookLM): elenca cosa è da
ruotare. Con `--notify` avvisa su Telegram gli scaduti. Il risultato compare
anche in `/admin/secrets`.

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
