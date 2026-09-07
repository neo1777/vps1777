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

# 2. indice: chunking (1400 char, overlap 200, max 12 per messaggio) su
#    content + attachments + tools SPOGLIATI dei payload binari, poi
#    tabella vec0 in un file separato con la sua scheda `indice_meta`.
#    ⚠️ Il testo utile vive anche nei tool-call: un indice sul solo `content`
#    è cieco proprio dove la scoperta proattiva serve (misurato nel POC).
```

L'indice **deve** dichiarare in `indice_meta`: `modello`, `dim`, `tabella`,
`chunk`, `perimetro`, `db_sorgente`, `generato`. Il tool li restituisce a ogni
ricerca: senza il perimetro, un indice parziale produce zeri che sembrano
assenze.

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

## Perimetro attuale

L'indice del primario copre **maggio–giugno 2026** (58.322 messaggi, 139.011
vettori): il resto del corpus si indicizza a scaglioni. Fuori dal perimetro la
ricerca ibrida non ha vettori da fondere — `indici[].perimetro` nella risposta
lo dichiara a ogni chiamata, ed è la prima cosa da leggere prima di concludere
«non c'è».
