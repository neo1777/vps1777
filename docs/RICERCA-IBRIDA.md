# Ricerca ibrida — trovare per senso, non per lessico

> 🇬🇧 English: [docs/en/RICERCA-IBRIDA.md](en/RICERCA-IBRIDA.md)

`search` (FTS5) risponde benissimo a chi **sa come si chiama** ciò che cerca.
Ma il caso d'uso che ha fatto nascere l'archivio è l'opposto: *ricordo il senso
e non la parola*. «L'articolo dove raccontavo quanto avevo speso», «la dashboard
dove i file erano pianeti»: lì il full-text tace, perché la parola che useresti
tu non è quella scritta nel testo.

`search_ibrida` cerca **anche** per significato: fonde i risultati di FTS5 con
quelli di una ricerca vettoriale e restituisce una lista sola.

## Quanto vale — misurato, non promesso

Banco del POC (issue #281): 9 bersagli scelti **prima** di misurare, ciascuno
con la query in linguaggio naturale di chi non ricorda e la sua controparte FTS5
col lessico giusto. Posizione del bersaglio nei primi 10 risultati:

| | FTS5 | solo vettori | **ibrido** |
|---|---|---|---|
| bersagli trovati | 5/9 | 4/9 | **6/9** |

I due motori sbagliano in modi diversi: la fusione tiene il meglio di entrambi.
Sulle query **esatte** l'ibrido non batte `search` — è tarato per non
peggiorarle, non per vincerle. Se cerchi un termine preciso, usa `search`.

## I quattro pezzi

| pezzo | dove vive | perché lì |
|---|---|---|
| il **codice di ricerca** (embedding della query + knn + fusione) | immagine `archive-mcp` | ~35 MB di dipendenze: onnxruntime, tokenizers, sqlite-vec, numpy |
| il **modello** (`model.onnx` + `tokenizer.json`) | volume, `/var/lib/archive/models/e5-small/` | 449 MB: nell'immagine peserebbero su ogni pull, e si aggiornano senza rilasciare una versione |
| l'**indice** (`<nome-db>.vec.db`) | volume, accanto al suo DB | indicizzare il corpus costa decine di ore di CPU: si fa **fuori** e l'indice viaggia come artefatto |
| il **costruttore** dell'indice | repo, `services/archive-mcp/tools/costruisci_indice.py` | gira sul PC, nell'ambiente del lock di archive-mcp; non entra nell'immagine |

Tre conseguenze volute:
- il **DB dell'archivio non viene toccato**: la sua firma non cambia, i backup
  non si gonfiano, e un archivio senza indice funziona come prima;
- l'indice si **rigenera senza rifare il DB** (e viceversa);
- la ricerca ibrida **degrada dichiarando**: senza modello o senza indice non
  ricade in silenzio su FTS5 — solleva un errore che dice cosa manca e come
  rimediare. *Un risultato dimezzato che sembra intero è peggio di un errore.*

## Perché ONNX e non torch

Il modello serve al server per una cosa sola: trasformare **la query** in un
vettore. Con torch + sentence-transformers sarebbero ~1 GB di immagine e ~1,5 GB
di RAM: su una VPS da 3 GB con sei container è una tassa che non ripaga.
L'export ONNX dello stesso modello dà vettori **identici** — misurato:
`cosine = 1.000000` contro sentence-transformers, quindi il verdetto del banco
resta valido — in ~25 ms per query.

Il costruttore usa lo **stesso** export ONNX anche per i testi indicizzati. Il
POC li aveva calcolati con sentence-transformers: confrontati col costruttore il
24/09/2026 (80 messaggi, 195 pezzi) danno ancora `cosine = 1.000000`. Un indice
del POC e uno del costruttore parlano lo stesso spazio.

La quantizzazione int8 (113 MB invece di 449) è stata misurata e **scartata**:
`cosine 0.985–0.990`, cioè vettori diversi da quelli con cui l'indice è stato
costruito. Risparmiare 336 MB cambiando il metro a metà esperimento non è
un'ottimizzazione.

## Il modello: l'export (sul PC, una volta)

```bash
# export ONNX con pooling e normalizzazione DENTRO il grafo
# (così il runtime non li replica e non può sbagliarli in modo diverso)
python - <<'PY'
import torch, torch.nn as nn
from transformers import AutoTokenizer, AutoModel
NOME, OUT = "intfloat/multilingual-e5-small", "e5-small"
tok = AutoTokenizer.from_pretrained(NOME); base = AutoModel.from_pretrained(NOME).eval()
tok.save_pretrained(OUT)
class E5(nn.Module):
    def __init__(s, m): super().__init__(); s.m = m
    def forward(s, input_ids, attention_mask):
        h = s.m(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
        w = attention_mask.unsqueeze(-1).float()
        e = (h * w).sum(1) / w.sum(1).clamp(min=1e-9)
        return e / e.norm(dim=1, keepdim=True).clamp(min=1e-12)
enc = tok(["query: x"], return_tensors="pt")
torch.onnx.export(E5(base).eval(), (enc["input_ids"], enc["attention_mask"]),
    f"{OUT}/model.onnx", input_names=["input_ids", "attention_mask"],
    output_names=["embedding"], opset_version=17, dynamo=False,
    dynamic_axes={"input_ids": {0:"b",1:"s"}, "attention_mask": {0:"b",1:"s"}, "embedding": {0:"b"}})
PY
```

La stessa cartella (`model.onnx` + `tokenizer.json`) serve due volte: al
costruttore sul PC (`--modello`) e al server sul volume.

## L'indice: il costruttore

### Dove gira e come si lancia

`services/archive-mcp/tools/costruisci_indice.py` sta nel repo, accanto al
server che legge ciò che scrive. Fino al 24/09/2026 l'indice lo scriveva un
prototipo del POC tenuto fuori dal repo: aveva il DB sorgente scritto nel
codice, selezionava solo per finestra di ts (le righe senza ts non entravano
mai, e nessuno lo diceva) e non scriveva `indice_meta`, che fu aggiunta a mano.

Gira **sul PC**, **nell'ambiente del lock di archive-mcp**: onnxruntime,
tokenizers e sqlite-vec hanno le stesse versioni del server, e non c'è nessuna
dipendenza in più. Non entra nell'immagine: il Dockerfile copia solo `app/`.

```bash
cd services/archive-mcp
uv sync --frozen
uv run python tools/costruisci_indice.py \
    --db /percorso/copia-archivio.db --modello /percorso/e5-small \
    --dal 2026-05 --al 2026-07 --senza-ts escludi
```

Il DB si apre in **sola lettura** (`mode=ro`): il costruttore non può scriverci.
Lavoralo comunque su una **copia**: il costruttore legge il DB con più query in
sequenza, e un DB che un ingest sta scrivendo potrebbe mostrargli due stati
diversi. L'indice esce accanto al DB (`<nome-db>.vec.db`) o dove dice `--out`,
che deve finire in `.vec.db`: è così che il server lo trova, ed è così che lo
scan dei DB non lo scambia per un archivio.

### Cosa entra in un vettore

- **Il testo** di un messaggio è `content` + `attachments` + `tools`. Dai campi
  JSON si tengono solo le stringhe e si scartano i payload binari (data-URI, PNG
  in base64). ⚠️ Il testo utile vive anche nei tool-call: un indice sul solo
  `content` è cieco proprio dove la scoperta proattiva serve (misurato nel POC).
- **I pezzi**: finestre di 1400 caratteri con 200 di sovrapposizione, al più 12
  per messaggio. 1400 caratteri sono ~400-460 token e5, dentro il limite di 512.
  Sotto i 40 caratteri un messaggio non si indicizza, ma si conta («troppo
  corti»). È il chunking che nel POC ha raddoppiato il recall sui messaggi lunghi.
- **Il prefisso**: ogni pezzo va al modello come `passage: <testo>`, gemello del
  `query: <domanda>` del server. È il contratto di e5: senza, la qualità cala.

### Il metro è quello del server, importato e non ricopiato

Un indice costruito con un metro diverso da quello della query produce vicini
insensati **senza errori**. Per questo il costruttore non ricopia niente da
`services/archive-mcp/app/semantica.py`, lo importa:

| cosa | da dove |
|---|---|
| apertura del modello (tokenizer, troncatura a 512) | `semantica.apri_modello`, la stessa funzione del server |
| codifica di un lotto di testi | `semantica.codifica`, da cui passa anche `embed_query` |
| prefissi | `semantica.PREFISSO_PASSAGGIO` (`passage: `) accanto a `PREFISSO_QUERY` (`query: `) |
| tabella e dimensione | `semantica.TABELLA` (`vec_chunk_small`), `semantica.DIM` (384) |

Quando queste funzioni sono state estratte dal server (24/09/2026), i vettori
della query sono rimasti identici byte per byte a quelli di prima.

In più il costruttore controlla ogni lotto: ogni vettore deve avere 384
dimensioni, e il primo vettore di ogni lotto deve avere norma 1. Un export senza
normalizzazione L2 nel grafo, o un altro modello, viene rifiutato.

### Il perimetro: si dichiara sempre

| parametro | cosa entra |
|---|---|
| `--tutto` | tutto il DB |
| `--dal X --al Y` | `ts >= X AND ts < Y` (stringhe ISO, `al` escluso; si può dare solo uno dei due) |
| `--project ETICHETTA` | etichetta esatta, o prefisso se finisce in `*` (`recupero:*`); ripetibile, le etichette vanno in OR |
| `--senza-ts includi` / `--senza-ts escludi` | solo con una finestra: le righe senza ts entrano o restano fuori |

- **Finestra ed etichette si combinano** in AND. `--tutto` non si combina.
- **Nel prefisso `_` e `%` sono lettere, non jolly**: `rec_x:*` non prende `recAx:1`.
- **Le righe senza ts.** Se la finestra lascerebbe fuori righe senza ts, il
  costruttore **si ferma**, dice quante sono e chiede di scegliere. La scelta
  finisce nel perimetro dichiarato («righe senza ts: escluse (1147)»). Senza
  finestra non c'è niente da scegliere: nessun filtro le esclude. Esempio
  reale: sulla copia del primario del 08/09/2026 le righe senza ts erano
  **1.147**, e il prototipo le escludeva tutte.
- **Senza parametri di perimetro**, un indice esistente si aggiorna col
  perimetro che dichiara lui (`perimetro_json`). Un indice nuovo senza perimetro
  viene rifiutato, con l'elenco delle scelte.
- **Un perimetro vuoto** (0 messaggi), o senza nessun messaggio indicizzabile,
  viene rifiutato senza scrivere niente: un indice vuoto sembrerebbe un indice.

### Cosa c'è nel file `<nome-db>.vec.db`

| tabella | cosa contiene | chi la legge |
|---|---|---|
| `vec_chunk_small` | `vec0(embedding float[384], +msg_rowid integer)`: un vettore per pezzo, col rowid del messaggio | il server (knn) |
| `indice_meta` | `(chiave, valore)`: la scheda dell'indice, sotto | il server (4 chiavi) e il costruttore |
| `indice_righe` | `(msg_rowid, uuid, impronta, primo_chunk, n_chunk)`: il **registro**, un messaggio per riga | il costruttore (l'incrementale) e il server (la verifica) |

I vettori di un messaggio hanno rowid contigui (`primo_chunk` … `primo_chunk +
n_chunk - 1`), assegnati dal costruttore: toglierli non richiede di scorrere la
tabella. `impronta` è lo sha256 (32 cifre esadecimali) del testo indicizzato.

### `indice_meta`: la scheda dell'indice

La scrive il costruttore, a ogni passaggio. Il server restituisce `perimetro`,
`messaggi`, `modello` e `generato` a ogni ricerca: senza il perimetro, un indice
parziale produce zeri che sembrano assenze.

| chiave | cosa dice |
|---|---|
| `perimetro` | il perimetro in chiaro, come lo mostra il server (`ts >= 2026-05 AND ts < 2026-07 · righe senza ts: escluse (1147)`) |
| `perimetro_json` | lo stesso, in forma ripetibile: lo rilegge l'incrementale |
| `modello` | il nome del modello (`intfloat/multilingual-e5-small`) |
| `modello_impronta` | sha256 di `model.onnx` + `tokenizer.json` (32 cifre): due export diversi dello «stesso» modello hanno impronte diverse |
| `dim`, `tabella`, `chunk`, `prefisso` | il metro: 384, `vec_chunk_small`, `1400/overlap 200/cap 12`, `passage: ` |
| `messaggi`, `vettori` | i messaggi con almeno un vettore e i vettori in tabella |
| `messaggi_perimetro`, `messaggi_corti`, `righe_senza_ts` | i messaggi nel perimetro, quelli sotto i 40 caratteri, le righe senza ts nel resto del filtro |
| `db_sorgente`, `db_righe`, `db_max_rowid` | il nome del DB (senza percorso), le sue righe e il suo rowid massimo alla generazione |
| `generato` | data e ora UTC della generazione |
| `costruttore` | `costruisci_indice 1.0` |
| `ultimo_passaggio` | JSON: modo e numeri dell'ultimo passaggio (invariati, nuovi, cambiati, riassegnati, orfani, usciti, vettori tolti e aggiunti) |
| `stato` | `completo`; `in costruzione` solo nel `.parziale` |

### Tutte le opzioni

| opzione | cosa fa |
|---|---|
| `--db PERCORSO` | il DB dell'archivio (obbligatorio; aperto in sola lettura) |
| `--modello CARTELLA` | `model.onnx` + `tokenizer.json`; obbligatorio per costruire, non per `--controlla` |
| `--out PERCORSO` | l'indice da scrivere (default: `<nome-db>.vec.db` accanto al DB) |
| `--tutto`, `--dal`, `--al`, `--project`, `--senza-ts` | il perimetro, sopra |
| `--ricostruisci` | riparte da zero invece di aggiornare; senza perimetro ricostruisce quello dichiarato dall'indice |
| `--controlla` | confronta indice e DB senza scrivere niente |
| `--lotto N` | pezzi per lotto e per transazione (default 96) |
| `--thread N` | thread di onnxruntime (default: tutti i core) |
| `--json` | l'esito in JSON su stdout, per le macchine |

### Cosa stampa, e come esce

Una costruzione su un DB sintetico di 6 messaggi (uno senza ts, uno troppo corto):

```
indice: sintetico.vec.db  (ricostruzione)
perimetro: ts >= 2026-05 AND ts < 2026-07 · righe senza ts: incluse (1)
messaggi nel perimetro: 6 · con testo indicizzabile: 5 · troppo corti: 1
righe senza ts nel resto del filtro: 1
registro prima: 0 messaggi
  invariati: 0
  nuovi: 5
  testo cambiato (stesso uuid): 0
  rowid riassegnato a un altro uuid: 0
  orfani (rowid sparito dal DB): 0
  usciti dal perimetro: 0
vettori tolti: 0 · aggiunti: 5
dopo: 5 messaggi · 5 vettori (registro e tabella vec0 quadrano)
```

L'avanzamento va su stderr (`1079/1203 messaggi · 3274 vettori · 2.3 vett/s`).

| esito | significato |
|---|---|
| 0 | indice scritto; con `--controlla`, indice in pari col DB |
| 1 | solo con `--controlla`: l'indice non è in pari (i numeri dicono perché) |
| 2 | rifiutato o non misurabile: il messaggio dice cosa manca e come rimediare |
| 130 | interrotto (Ctrl-C): il lavoro fatto resta nel `.parziale` |

## Aggiornare l'indice: l'incrementale e il rowid

L'indice lavora sul `rowid` di `messages`, e l'indexer fa `INSERT OR REPLACE`
sull'uuid: un re-ingest dà **rowid nuovi** alle righe rimpiazzate. Un indice
vecchio ha allora vettori appesi a rowid che non esistono più (il risultato
sparisce senza errori) o a rowid **riusati** da un altro messaggio (il messaggio
sbagliato, restituito per il senso di un altro).

Il registro `indice_righe` serve a vederlo. Rilanciare il costruttore su un
indice esistente lo confronta col DB e dice, coi numeri:

| categoria | cosa è successo | cosa fa |
|---|---|---|
| invariati | stesso rowid, uuid e testo | niente |
| nuovi | nel perimetro, non ancora indicizzati | li indicizza |
| testo cambiato | stesso rowid e uuid, testo diverso | toglie e ricalcola |
| rowid riassegnato | allo stesso rowid ora c'è un altro uuid | toglie e, se nel perimetro, ricalcola |
| orfani | il rowid non esiste più nel DB | toglie |
| usciti dal perimetro | ancora nel DB, ma fuori dal perimetro (o ora troppo corti) | toglie |

Lo stesso meccanismo fa crescere l'indice **a scaglioni**: allargare la finestra
aggiunge solo i messaggi nuovi, restringerla toglie quelli usciti.

Prima di pubblicare, il numero di vettori nella tabella vec0 deve essere uguale
alla somma di `n_chunk` nel registro. Se non lo è, l'indice non viene
pubblicato: un vettore che il registro non spiega è un orfano che il server
servirebbe.

- **`--controlla`** fa lo stesso confronto **senza scrivere niente** ed esce 1 se
  l'indice non è in pari. Serve dopo un re-ingest e prima di caricare un indice
  sulla VPS.
- **Un cambio di metro** (un altro export del modello, riconosciuto
  dall'impronta; un altro chunking o prefisso) rifiuta l'incrementale e chiede
  `--ricostruisci`: vettori di due metri nello stesso indice danno vicini
  insensati senza errori.
- **Un indice del POC** non ha registro: l'incrementale lo rifiuta e chiede una
  ricostruzione, una volta sola. `--controlla` su di lui dice solo gli orfani
  (rowid spariti dal DB), dichiara che il resto non è verificabile, ed esce 2 se
  non ne trova, 1 se ne trova.
- **Il lavoro passa da `<nome-db>.vec.db.parziale`**, un lotto per transazione:
  registro e vettori di un messaggio entrano insieme. Se si interrompe,
  rilanciando lo stesso comando si riprende senza rifare ciò che è fatto (modo
  «ripresa»). Per l'incrementale l'indice esistente si copia prima in un file a
  parte, rinominato in `.parziale` solo a copia finita. L'indice servito viene
  sostituito solo alla fine, a conti quadrati.

## La verifica nel server: `indici[].verifica`

Il costruttore rende l'indice coerente col DB **nel momento in cui lo
costruisce**. Ma il DB sulla VPS può essere re-ingerito dopo, e allora l'indice
caricato torna disallineato. Per questo anche `search_ibrida` verifica, a ogni
ricerca.

Se l'indice ha il registro, per ogni risultato vettoriale il server confronta
l'uuid registrato per quel rowid con l'uuid della riga in `messages`. Chi non
combacia **si scarta**: non viene mai restituito come se fosse giusto. La
risposta lo dichiara in un campo **in più** di ogni voce di `indici[]`; i campi
di prima non cambiano forma.

| campo | cosa dice |
|---|---|
| `registro` | `true` se l'indice ha il registro, `false` se è un indice vecchio non verificabile |
| `candidati` | quanti vicini del knn sono stati esaminati (non l'intero indice) |
| `scartati` | quanti sono stati tolti dai risultati: `rowid_assenti` + `uuid_diversi` |
| `rowid_assenti` | vicini il cui rowid non esiste più nel DB |
| `uuid_diversi` | vicini il cui rowid ora appartiene a un altro messaggio |
| `stato` | la frase per chi legge, con la cura |

I tre stati possibili:

- `verificato: ogni risultato vettoriale combacia col DB (uuid per rowid)`;
- `indice disallineato col DB: N risultati vettoriali scartati (A rowid spariti,
  B rowid ora di un altro messaggio) — lancia …costruisci_indice.py --controlla
  su una copia del DB e aggiorna l'indice`;
- `indice senza registro: l'uuid dei risultati vettoriali non è verificabile …`:
  l'indice del POC. Si comporta come prima; i rowid spariti dal DB, che prima si
  scartavano in silenzio, ora si contano.

Il server scrive anche un avviso nel log quando scarta qualcosa.

⚠️ Cosa la verifica **non** vede:
- conta solo sui candidati di quella ricerca: zero scarti non certificano
  l'intero indice. Quello lo fa `--controlla`;
- un messaggio con lo **stesso** uuid e lo stesso rowid ma testo cambiato è il
  messaggio giusto con un vettore vecchio: il server non lo scarta, il
  costruttore lo vede («testo cambiato») e lo ricalcola.

## Quanto costa — misurato

Misurato il 24/09/2026 su un PC a 8 core, sulla copia del primario, per una
finestra di due giorni (1.618 messaggi, 4.366 vettori):

| | |
|---|---|
| velocità | ~2,3 vettori al secondo (il prototipo con torch, 6 thread: ~3,0) |
| RAM | 1,9 GB al massimo |
| CPU | ~550% |
| risultato | gli stessi messaggi e lo stesso numero di vettori per messaggio del prototipo sulla stessa finestra |

Il costruttore manda al modello i testi di un lotto **ordinati per lunghezza, a
gruppi di 16** (`EmbedderOnnx`). La prima stesura li mandava tutti insieme, 96
alla volta: il padding portava ogni lotto alla lunghezza del più lungo, e l'arena
di onnxruntime era arrivata a **~12 GB** di RAM. Il risultato non cambia: il
pooling nel grafo pesa con `attention_mask`, quindi il padding non entra nel
vettore (riverificato: coseno 1.000000).

Stime, dalla velocità misurata (sono stime, non misure):

| perimetro | vettori | tempo a ~2,3 v/s |
|---|---|---|
| maggio–giugno 2026 (l'indice di oggi) | ~139.000 | **~17 h** |
| luglio–settembre 2026 (pezzi contati dal prototipo sulla copia del 08/09) | ~282.000 | ~34 h |

## La prima volta sulla VPS

L'indice che oggi sta sulla VPS è quello del prototipo: senza registro. La
ricerca funziona, ma `indici[].verifica` dirà `registro: false`, e il primo
aggiornamento chiede una ricostruzione. I passi, una volta:

1. **Una copia del DB sul PC**, presa mentre non c'è un ingest in corso:

   ```bash
   ssh vps1777 'docker cp vps1777-gateway-1:/var/lib/archive/db/recupero-20260905.db /tmp/'
   scp vps1777:/tmp/recupero-20260905.db ./ && ssh vps1777 'rm /tmp/recupero-20260905.db'
   ```

2. **La ricostruzione** col perimetro di oggi (maggio–giugno). Sono **~17 ore**:
   si può interrompere e riprendere rilanciando lo stesso comando.

   ```bash
   cd services/archive-mcp
   uv run python tools/costruisci_indice.py --db /percorso/recupero-20260905.db \
       --modello /percorso/e5-small --dal 2026-05 --al 2026-07 \
       --senza-ts escludi --ricostruisci
   ```

   `--senza-ts escludi` tiene il perimetro del prototipo; `includi` fa entrare
   anche le righe senza ts (1.147 sulla copia del 08/09/2026).

3. **Il controllo**: `--controlla` deve uscire 0 («in pari col DB»).

   ```bash
   uv run python tools/costruisci_indice.py --db /percorso/recupero-20260905.db --controlla
   ```

4. **Il caricamento**, come sotto.
5. **La prova**: una `search_ibrida` qualunque deve rispondere con
   `indici[].verifica.registro: true` e `scartati: 0`.

**Dopo ogni re-ingest** di quel DB: una copia nuova sul PC, il costruttore
**senza parametri di perimetro** (aggiorna in modo incrementale col perimetro
che l'indice dichiara), `--controlla`, caricamento. Se `search_ibrida` dichiara
scarti, è questo il segnale che il giro va rifatto.

## Caricare gli artefatti sulla VPS

Il volume `archive-data` è montato **read-only** su `archive-mcp` (che legge) e
**read-write** sul gateway (che scrive): gli artefatti passano da lì.

```bash
scp recupero-20260905.vec.db vps1777:/tmp/
ssh vps1777 'docker cp /tmp/recupero-20260905.vec.db \
    vps1777-gateway-1:/var/lib/archive/db/ && rm /tmp/recupero-20260905.vec.db'

# il modello (una volta sola)
ssh vps1777 'docker exec vps1777-gateway-1 mkdir -p /var/lib/archive/models/e5-small'
ssh vps1777 'docker cp /tmp/model.onnx vps1777-gateway-1:/var/lib/archive/models/e5-small/'
```

Nessun riavvio: la registry dei DB si ricarica da sola quando la dir cambia (un
`.vec.db` nuovo cambia la firma della dir, quindi anche le connessioni con
l'indice agganciato si riaprono), e il modello si carica alla prima ricerca
ibrida.

⚠️ L'indice vale per il DB da cui è nato. Se sulla VPS il DB è stato
re-ingerito dopo, prima di caricarlo lancia `--controlla` su una copia di quel
DB: se non è in pari, aggiornalo lì e carica quello.

## Perimetro attuale

L'indice del primario copre **maggio–giugno 2026** (58.322 messaggi, 139.011
vettori): il resto del corpus si indicizza a scaglioni. Fuori dal perimetro la
ricerca ibrida non ha vettori da fondere — `indici[].perimetro` nella risposta
lo dichiara a ogni chiamata, ed è la prima cosa da leggere prima di concludere
«non c'è».

📌 Quell'indice (generato il 07/09/2026) viene dal prototipo del POC: il suo
`indice_meta` è stato scritto a mano e non ha il registro `indice_righe`. I
vettori sono gli stessi che scrive il costruttore (coseno 1.000000, sopra), ma
per il primo aggiornamento incrementale serve una ricostruzione (`--ricostruisci`,
vedi «La prima volta sulla VPS»).

## Limiti noti

- **Lettura su copia.** Il costruttore legge il DB con più query in sequenza,
  senza una lettura unica: su un DB che un ingest sta scrivendo potrebbe vedere
  due stati. Si lavora su una copia.
- **La verifica del server guarda i candidati**, non l'intero indice; e non vede
  un testo cambiato con lo stesso uuid (vedi sopra). Il controllo completo è
  `--controlla`.
- **Velocità.** ~2,3 vettori/s contro i ~3,0 del prototipo: `--thread` e la
  dimensione dei gruppi non sono ancora stati tarati.
- **Etichette `recupero:*`.** Il filtro per prefisso è provato su dati
  sintetici; le etichette vere arrivano da un altro ramo dell'indexer.
