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
| backup **di `vps1777`** che escono di casa | ✅ *(già oggi: `tools/backup.sh` cifra con `age`)* |
| backup **del canale `_chat`** sul disco esterno | 🔴 **NO — 14 file su 14 in chiaro**, misurati il 16/08 22:4x |
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

STIMATO ⚠️ — poi MISURATO, vedi sotto: la stima era alta e guardava la cosa sbagliata
  quante pagine tocca una query FTS5 reale → 3x / 10x / 36x
```

### 🔬 SQLCipher misurato davvero (16/08 22:4x) — e la stima sopra era sbagliata due volte

SQLCipher 4.5.6 installato, DB convertito con `sqlcipher_export`, **stesso motore
(`sqlcipher3`) per entrambi i lati** così l'unica variabile è la cifratura. Stesse 200
query, stessi 4.000 hit su entrambi:

```
  COSTO PER QUERY — stimato 3x-36x, misurato **1,75x**
    cache 2 MB     chiaro 0,204 ms  ·  cifrato 0,350 ms     1,72x
    cache 200 MB   chiaro 0,169 ms  ·  cifrato 0,303 ms     1,80x
    ⇒ 0,15 ms in più per ricerca: impercettibile.

  🔴 COSTO PER CONNESSIONE — non l'avevo considerato, ed è quello che decide
    apertura       chiaro   **0,5 ms**  ·  cifrato  **299 ms**   ⇒ **600x**
    ⚠️ la prima misura diceva «56 → 367»: era gonfiata da un `SELECT count(*)`
       che avevo messo per «forzare l'apertura vera» e che scansiona 60.000
       righe. Il DELTA reggeva, la BASE no — e la base è ciò che dice quanto
       il costo è fuori scala. Separati: il count costa 124 ms in chiaro e
       285 in cifrato (2,3x, coerente col per-query); l'apertura pura è quella
       sopra. *Una sonda che «forza» un'operazione ne misura due.*
    perché: PBKDF2-HMAC-SHA512, **256.000 iterazioni**. È lento apposta (contro il
    brute-force sulla passphrase) e non va abbassato: è la difesa, non un difetto.
```

⚠️ **`archive-mcp` apre una connessione PER OGNI RICHIESTA** (`db.py:161`, dentro
`search()`; sono 10 i punti che chiamano `_open()`). Con SQLCipher così com'è, una ricerca
passerebbe da 0,2 ms a **310 ms**: non 1,75x, **millecinquecento volte**.

🔑 **Il prerequisito è architetturale, non crittografico: la connessione va tenuta
aperta** (una cache per-DB in `_open()`, che oggi non esiste perché non serviva). Con una
connessione persistente si paga 310 ms **una volta all'avvio** e poi 0,35 ms a ricerca.
⇒ **Cifrare senza toccare questo trasformerebbe un costo trascurabile in uno insostenibile
— e sembrerebbe «colpa della cifratura».**

📌 *Anche la previsione «con una cache generosa paga poco sui cache-miss» è smentita dal
banco: 1,72x con 2 MB e 1,80x con 200 MB. La page-cache non c'entra — il costo per pagina
si paga comunque.*

## Le tre strade, e perché ne resta una

**(a) Cifratura per campo** — ❌ **esclusa, e va detto perché è la prima a cui si pensa.**
FTS5 indicizza le *parole*: su testo cifrato le parole non esistono. Non deteriora la
ricerca, la toglie.

**(b) File cifrato a riposo, aperto in RAM all'avvio** — costo per query **zero**
(misurato: 0,17 vs 0,18 ms), il pedaggio si paga una volta sola all'avvio (~5,4 s/GB).
🔴 **Ma richiede che il DB stia in RAM**, e l'owner stima «qualche GB»: su una VPS
affittata non regge.

**(c) SQLCipher — cifratura a pagine** — ✅ **la sola che regge con un archivio da
gigabyte**, perché decifra pagina per pagina su richiesta e non chiede che il DB stia in
RAM. **Costo per query misurato: 1,75x, cioè 0,15 ms in più a ricerca.**

⚠️ *La prima stesura di questa riga diceva «paga sui cache-miss: con una `cache_size`
generosa il costo si concentra all'inizio». **Il banco l'ha smentita**: 1,72x con 2 MB di
cache e 1,80x con 200 MB. La page-cache non sposta niente — il costo per pagina si paga
comunque.* La tengo scritta perché era il ragionamento che sembrava ovvio, e sapere che è
falso vale quanto il numero.

🔴 **Il vincolo di questa strada non è il costo per query: è il costo per CONNESSIONE**
(299 ms, §sopra). Va risolto **prima** di cifrare, e non è un problema di crittografia.

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
