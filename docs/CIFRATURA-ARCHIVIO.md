# Cifratura dell'archivio — disegno

> **Stato: PROPOSTA, non implementata.** Serve l'approvazione di chi possiede la macchina
> prima di scrivere una riga di prodotto. Scritto il 2026-08-16 da `71d540e6`, dopo la
> decisione dell'owner («cifriamo se è possibile e se non deteriora l'utilizzo»).

## Il problema, e da chi ci si difende

Il `.db` di `archive1777` sta **in chiaro** sul disco. La redazione esiste ma è in *uscita*
(`services/archive-mcp/app/redazione.py:1`), che è la scelta giusta e voluta: l'upload
carica tutto, il filtro sta nella ricerca. Quindi il contenuto è integralmente leggibile
da chiunque abbia il file.

**Il limite che va detto per primo, perché nessuna cifratura lo supera.** La macchina è una
VPS *affittata*: il provider controlla l'hypervisor e può leggere la RAM di una VM accesa.
Ogni cifratura, per funzionare, tiene la chiave in memoria mentre il servizio gira.

⇒ **L'obiettivo realistico non è «rendere impossibile», è «rendere costoso e coprire tutto
il resto»** — e «tutto il resto» è la maggioranza dei casi reali:

| scenario | coperto da questo disegno |
|---|---|
| snapshot del provider | ✅ |
| disco dismesso, riassegnato, rivenduto | ✅ |
| backup che escono di casa | ✅ *(già oggi: cifrati con `age`)* |
| accesso al pannello del provider senza console | ✅ |
| VM spenta e disco copiato | ✅ |
| **provider ostile con VM accesa** | ❌ **no, e non c'è difesa tecnica** |

## Perché non la cifratura del disco

L'owner ha chiesto se può farla l'installer. **No**, e il motivo indica il momento giusto:
`setup.sh` e `deploy.sh` non toccano il disco (`cryptsetup`, `mkfs`, `parted`, `dm-crypt`:
zero occorrenze) — sono installer *applicativi*, e quando partono il filesystem è già
montato in chiaro. La cifratura del disco si fa **al partizionamento**, cioè
nell'installazione del sistema, e su una VPS affittata spesso non è nemmeno disponibile
(serve ISO custom o rescue mode).

E anche dove c'è, resta il nodo della chiave: se il disco si sblocca da solo al boot, la
chiave è sulla macchina.

## Le misure, e cosa è misurato davvero

Banco eseguito il 16/08 su un DB FTS5 di 60.000 righe, 61,6 MB, 15.040 pagine da 4 KB:

```
MISURATO ✅
  query FTS5, disco in chiaro              0,18 ms
  query FTS5, stesso DB in RAM (tmpfs)     0,17 ms      ⇒ dentro il rumore
  AES-256-GCM sul file intero              291 ms cifra · 330 ms decifra  (~190 MB/s)
  AES-256-GCM su UNA pagina da 4 KB        31,6 µs      (130 MB/s)

STIMATO ⚠️ — NON misurato, e serve per decidere
  quante pagine tocca una query FTS5 reale
     10 pagine →  0,50 ms  (3x)
     50 pagine →  1,76 ms  (10x)
    200 pagine →  6,50 ms  (36x)
```

⚠️ **Il numero che manca si ottiene installando SQLCipher e misurando.** Finché non c'è,
qualunque affermazione sul costo per query è una stima — e va scritta come tale.

## Le tre strade, e perché ne resta una

**(a) Cifratura per campo** — ❌ **esclusa, e va detto perché è la prima a cui si pensa.**
FTS5 indicizza le *parole*: su testo cifrato le parole non esistono. Non deteriora la
ricerca, la toglie.

**(b) File cifrato a riposo, aperto in RAM all'avvio** — costo per query **zero**
(misurato: 0,17 vs 0,18 ms), il pedaggio si paga una volta sola all'avvio (~5,4 s/GB).
🔴 **Ma richiede che il DB stia in RAM**, e l'owner stima «qualche GB»: su una VPS
affittata non regge.

**(c) SQLCipher — cifratura a pagine** — non richiede il DB in RAM, perché decifra pagina
per pagina su richiesta. Paga su ogni *cache-miss*, non su ogni query: con una
`PRAGMA cache_size` generosa le pagine calde restano decifrate in memoria e il costo si
concentra all'inizio. **È la sola che regge con un archivio da gigabyte** — a patto che il
numero stimato sopra risulti nella fascia bassa.

## Il nodo vero: la chiave

L'owner ha scelto il livello massimo: **la chiave non sta sulla macchina**, arriva
dall'esterno all'avvio e vive solo in RAM. Da qui discendono tre domande di progetto che
**non sono ancora decise**:

### 1. Cosa fa un servizio che parte senza chiave

Tre comportamenti possibili, e due sono sbagliati:

- ❌ **muore** — con `restart: unless-stopped` (che è la policy attuale, `compose.yaml:36`)
  entra in un loop di riavvii che brucia CPU e riempie i log;
- ❌ **parte in chiaro** — fail-open: il difetto peggiore, perché la protezione sembra
  attiva e non lo è;
- ✅ **aspetta** — parte, dichiara «in attesa di chiave», e l'healthcheck deve
  **distinguere questo stato da un guasto**. Un servizio in attesa non è rotto, e un
  monitoraggio che li confonde insegna a ignorare gli allarmi.

### 2. Come arriva la chiave

Il gateway ha già un pannello admin autenticato. La strada che si innesta su ciò che esiste:
l'owner si collega, inserisce la passphrase, il gateway la tiene **in memoria** e la passa
ad `archive-mcp` sulla rete interna. Nessun file, nessun secret di compose — un secret di
compose *è un file*, e sarebbe il contrario di quel che si vuole ottenere.

⚠️ Da decidere: cosa succede se il gateway riparte e `archive-mcp` no (o viceversa).

### 3. Cosa succede se la chiave si perde

**L'archivio è perduto. Non c'è recupero: è il punto della faccenda.**

🔑 *Una cifratura fatta bene e una chiave persa producono lo stesso risultato di un disco
cancellato.* Prima di andare in produzione va deciso **dove la chiave viene custodita** e
**chi altro la conosce** — ed è una domanda di custodia, non di codice. Nessuna riga di
questo repo può rispondere al posto di chi possiede la macchina.

## Cosa serve per passare da questo documento al codice

1. ✅ approvazione del disegno;
2. ⚠️ **la misura mancante**: installare SQLCipher e contare le pagine per query;
3. ⚠️ la decisione sulla custodia della chiave (§3);
4. ⚠️ la scelta del comportamento in attesa (§1) e del canale di consegna (§2).

I punti 2–4 sono indipendenti fra loro e si possono chiudere in qualunque ordine.
