# Ricerca ibrida — trovare per senso, non per lessico

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

## I tre pezzi

| pezzo | dove vive | perché lì |
|---|---|---|
| il **codice** (embedding query + knn + fusione) | immagine `archive-mcp` | ~35 MB di dipendenze: onnxruntime, tokenizers, sqlite-vec, numpy |
| il **modello** (`model.onnx` + `tokenizer.json`) | volume, `/var/lib/archive/models/e5-small/` | 449 MB: nell'immagine peserebbero su ogni pull, e si aggiornano senza rilasciare una versione |
| l'**indice** (`<nome-db>.vec.db`) | volume, accanto al suo DB | indicizzare il corpus costa ~60 h di CPU: si fa **fuori** e l'indice viaggia come artefatto |

Tre conseguenze volute:
- il **DB dell'archivio non viene toccato**: la sua firma non cambia, i backup
  non si gonfiano, e un archivio senza indice funziona come prima;
- l'indice si **rigenera senza rifare il DB** (e viceversa);
- la ricerca ibrida **degrada dichiarando**: senza modello o senza indice non
  ricade in silenzio su FTS5 — solleva un errore che dice cosa manca e come
  rimediare. *Un risultato dimezzato che sembra intero è peggio di un errore.*

## Perché ONNX e non torch

Il modello serve a una cosa sola: trasformare **la query** in un vettore. Con
torch + sentence-transformers sarebbero ~1 GB di immagine e ~1,5 GB di RAM: su
una VPS da 3 GB con sei container è una tassa che non ripaga. L'export ONNX
dello stesso modello dà vettori **identici** — misurato: `cosine = 1.000000`
contro sentence-transformers, quindi il verdetto del banco resta valido — in
~25 ms per query.

La quantizzazione int8 (113 MB invece di 449) è stata misurata e **scartata**:
`cosine 0.985–0.990`, cioè vettori diversi da quelli con cui l'indice è stato
costruito. Risparmiare 336 MB cambiando il metro a metà esperimento non è
un'ottimizzazione.

## Generare gli artefatti (sul PC, non sulla VPS)

```bash
# 1. modello: export ONNX con pooling e normalizzazione DENTRO il grafo
#    (così il runtime non li replica e non può sbagliarli in modo diverso)
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

### L'indice: `services/archive-mcp/tools/costruisci_indice.py`

Il costruttore sta nel repo, accanto al server che legge ciò che scrive, e gira
**nell'ambiente del lock di archive-mcp**: le stesse versioni di onnxruntime,
tokenizers e sqlite-vec del server, nessuna dipendenza in più. Non entra
nell'immagine (il Dockerfile copia solo `app/`).

```bash
cd services/archive-mcp
uv sync --frozen
uv run python tools/costruisci_indice.py \
    --db /percorso/copia-archivio.db --modello /percorso/e5-small \
    --dal 2026-05 --al 2026-07 --senza-ts escludi
```

Il DB si apre in **sola lettura**; l'indice esce accanto al DB
(`<nome-db>.vec.db`, o `--out`). Cosa entra in ciascun vettore: content +
attachments + tools **spogliati** dei payload binari, a pezzi di 1400 caratteri
con overlap 200, al più 12 per messaggio, sotto i 40 caratteri niente.
⚠️ Il testo utile vive anche nei tool-call: un indice sul solo `content` è
cieco proprio dove la scoperta proattiva serve (misurato nel POC).

**Il metro è quello del server, importato e non ricopiato.** Il modello si apre
con `semantica.apri_modello` e si interroga con `semantica.codifica`, le stesse
funzioni di `embed_query`; il prefisso dei testi è `semantica.PREFISSO_PASSAGGIO`
(`passage: `), gemello di `PREFISSO_QUERY` (`query: `). Misurato contro l'indice
del POC, costruito con sentence-transformers: 60 messaggi, 127 pezzi, coseno
**1.000000** su tutti.

**Il perimetro si dichiara sempre**, in uno di tre modi:

| parametro | cosa entra |
|---|---|
| `--tutto` | tutto il DB |
| `--dal X --al Y` | `ts >= X AND ts < Y` (stringhe ISO, `al` escluso) |
| `--project ETICHETTA` | etichetta esatta, o prefisso se finisce in `*` (`recupero:*`); ripetibile, in OR |

Finestra ed etichette si combinano (in AND). Se la finestra lascerebbe fuori
righe **senza ts**, il costruttore si ferma, dice quante sono e chiede di
scegliere: `--senza-ts includi` oppure `--senza-ts escludi`. Il prototipo le
escludeva sempre, senza dirlo. Senza parametri di perimetro, un indice
esistente si aggiorna col perimetro che dichiara lui.

**`indice_meta` la scrive il costruttore**, a ogni passaggio. Il server
restituisce `perimetro`, `messaggi`, `modello` e `generato` a ogni ricerca: senza
il perimetro, un indice parziale produce zeri che sembrano assenze.

| chiave | cosa dice |
|---|---|
| `perimetro`, `perimetro_json` | il perimetro, leggibile e ripetibile |
| `modello`, `modello_impronta` | il nome e lo sha256 di `model.onnx` + `tokenizer.json` |
| `dim`, `tabella`, `chunk`, `prefisso` | il metro |
| `messaggi`, `vettori`, `messaggi_perimetro`, `messaggi_corti`, `righe_senza_ts` | i conteggi |
| `db_sorgente`, `db_righe`, `db_max_rowid` | il DB da cui è nato |
| `generato`, `costruttore`, `ultimo_passaggio`, `stato` | quando, con cosa, cosa ha fatto |

### Aggiornare l'indice: l'incrementale e il rowid

L'indice lavora sul `rowid` di `messages`, e l'indexer fa `INSERT OR REPLACE`
sull'uuid: un re-ingest dà **rowid nuovi** alle righe rimpiazzate. Un indice
vecchio ha allora vettori appesi a rowid che non esistono più (il server li
scarta e il risultato sparisce senza errori) o a rowid **riusati** da un altro
messaggio (il server restituisce il messaggio sbagliato).

Per questo accanto alla tabella vec0 c'è un registro, `indice_righe`: per ogni
messaggio il rowid, l'uuid, l'impronta del testo indicizzato e l'intervallo dei
suoi vettori. Il server non lo legge: per lui l'indice è identico. Rilanciare il
costruttore su un indice esistente lo confronta col DB e dice, coi numeri:

| categoria | cosa è successo | cosa fa |
|---|---|---|
| invariati | stesso rowid, uuid e testo | niente |
| nuovi | nel perimetro, non ancora indicizzati | li indicizza |
| testo cambiato | stesso rowid e uuid, testo diverso | toglie e ricalcola |
| rowid riassegnato | allo stesso rowid ora c'è un altro uuid | toglie e, se nel perimetro, ricalcola |
| orfani | il rowid non esiste più nel DB | toglie |
| usciti dal perimetro | ancora nel DB, ma fuori dal perimetro (o ora troppo corti) | toglie |

Prima di pubblicare, il numero di vettori nella tabella vec0 deve essere uguale a
quello del registro. Se non lo è, l'indice non viene pubblicato: nessun vettore
orfano viene servito senza che nessuno lo sappia.

- **`--controlla`** fa lo stesso confronto **senza scrivere niente** ed esce 1 se
  l'indice non è in pari. Serve dopo un re-ingest e prima di caricare un indice
  sulla VPS.
- **Un cambio di metro** (un altro export del modello, per l'impronta; un altro
  chunking) rifiuta l'incrementale e chiede `--ricostruisci`: vettori di due
  metri nello stesso indice danno vicini insensati senza errori.
- **Un indice del POC** non ha registro: l'incrementale lo rifiuta e chiede una
  ricostruzione, una volta sola. `--controlla` su di lui dice solo gli orfani e
  dichiara che il resto non è verificabile (esce 2 se non ne trova).
- **Il lavoro passa da `<indice>.parziale`**, un lotto per transazione: se si
  interrompe, rilanciando lo stesso comando si riprende. L'indice servito viene
  sostituito solo alla fine, a conti quadrati.

Esito: 0 fatto (o in pari), 1 non in pari (solo `--controlla`), 2 rifiutato o
non misurabile, 130 interrotto. `--json` stampa l'esito per le macchine.

Quanto costa, misurato il 24/09/2026 su un PC a 8 core: ~2,3 vettori al secondo,
1,9 GB di RAM al massimo. Su una finestra di due giorni lo stesso perimetro del
prototipo ha dato gli stessi messaggi e lo stesso numero di vettori per
messaggio. I testi di un lotto vanno al modello ordinati per lunghezza, a
gruppi di 16 (`EmbedderOnnx`): mandarli tutti insieme, 96 alla volta, aveva
portato la RAM a ~12 GB.

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

Nessun riavvio: la registry dei DB si ricarica da sola quando la dir cambia, e
il modello si carica alla prima ricerca ibrida.

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
per il primo aggiornamento incrementale serve una ricostruzione (`--ricostruisci`).
