"""
Ricerca semantica — embedding della query + knn su indice vettoriale sqlite-vec.

PERCHÉ ESISTE (issue #281, POC 06-07/09/2026)
─────────────────────────────────────────────
FTS5 risponde benissimo a chi sa già come si chiama ciò che cerca. Ma il caso
d'uso che ha fatto nascere l'archivio è l'inverso: **l'utente non ricorda il
lessico**, ricorda il senso («l'articolo dove raccontavo quanto ho speso…»).
Lì il full-text tace, e un archivio che tace su ciò che contiene è un archivio
che non serve.

Il POC ha misurato la differenza sul medesimo metro (9 bersagli fissati PRIMA,
banco con controllo): FTS5 da solo 5/9, vettori da soli 4/9, **ibrido 6/9** —
e i tre bersagli semantici che FTS5 non trova entrano solo grazie ai vettori.
Referto: `_chat/POC-semantica-esito.md` (fuori repo, è lavoro di sessione).

LE TRE SCELTE DI DESIGN, e perché
──────────────────────────────────
1. **ONNX, non torch.** Il modello serve per UNA cosa: embeddare la query (una
   frase). torch+sentence-transformers costano ~1 GB di immagine e ~1,5 GB di
   RAM: su una VPS con 3 GB e sei container è una tassa che non ripaga.
   L'export ONNX dello STESSO modello (multilingual-e5-small) dà vettori
   **identici** — misurato: cosine 1.000000 contro sentence-transformers, quindi
   il verdetto del banco resta valido senza asterischi — con 25 ms di latenza e
   ~35 MB di dipendenze. La quantizzazione int8 (113 MB invece di 449) è stata
   MISURATA e scartata: cosine 0.985-0.990, cioè vettori diversi da quelli con
   cui l'indice è stato costruito. Risparmiare 336 MB invalidando il metro non
   è un'ottimizzazione: è cambiare esperimento a metà.
2. **L'indice è un file separato** `<nome-db>.vec.db` accanto al DB, ATTACHato
   in sola lettura. Il DB dell'archivio NON viene toccato: la sua firma non
   cambia, i backup non si gonfiano, l'indice si rigenera senza rifare il DB, e
   un archivio senza indice continua a funzionare esattamente come prima.
3. **Il pesante si calcola altrove.** Indicizzare 276k messaggi costa ~60 h di
   CPU: si fa sul PC e l'indice viaggia come artefatto (come i DB). Qui gira
   solo l'embedding della query.

DEGRADAZIONE DICHIARATA: senza modello o senza indice questo modulo non ricade
in silenzio sul solo FTS5 — solleva un errore che dice cosa manca, dove va
messo e come si genera. Un risultato dimezzato che sembra intero è il difetto
che questo repo combatte da sempre.
"""
from __future__ import annotations

import logging
import struct
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Il modello con cui è stato costruito l'indice. Cambiarlo INVALIDA gli indici
# esistenti (vettori di un altro spazio): il metadato `modello` dentro ogni
# .vec.db serve a scoprirlo prima di servire risultati insensati.
MODELLO_ATTESO = "intfloat/multilingual-e5-small"
DIM = 384
PREFISSO_QUERY = "query: "          # e5 vuole il prefisso: senza, la qualità cala
MAX_TOKEN = 512

# Fusione RRF: i parametri VINCENTI del banco (plateau k=20-40, peso FTS 1.2-1.5:
# dentro quella finestra il risultato non cambia, quindi non è taratura fortunata).
RRF_K = 30
RRF_PESO_FTS = 1.5


class SemanticaNonPronta(RuntimeError):
    """Manca un pezzo (modello o indice) — con dentro cosa fare, non solo cosa manca."""


_LOCK = threading.Lock()
_SESSIONE: Any = None                # onnxruntime.InferenceSession (lazy, condivisa)
_TOKENIZER: Any = None


def _carica_modello(model_dir: Path) -> tuple[Any, Any]:
    """Sessione ONNX + tokenizer, una volta sola per processo.

    Thread-safe con lock: i tool MCP girano sul thread pool di FastMCP e due
    richieste in parallelo caricherebbero il modello due volte (900 MB di RAM
    invece di 450, per pura sfortuna di timing).
    """
    global _SESSIONE, _TOKENIZER
    if _SESSIONE is not None:
        return _SESSIONE, _TOKENIZER
    with _LOCK:
        if _SESSIONE is not None:                       # qualcuno l'ha caricato mentre aspettavo
            return _SESSIONE, _TOKENIZER
        onnx = model_dir / "model.onnx"
        tok = model_dir / "tokenizer.json"
        mancanti = [str(p) for p in (onnx, tok) if not p.is_file()]
        if mancanti:
            raise SemanticaNonPronta(
                f"Modello di embedding assente: mancano {', '.join(mancanti)}.\n"
                f"La ricerca ibrida ha bisogno di {MODELLO_ATTESO} esportato in ONNX "
                f"(model.onnx + tokenizer.json) in {model_dir}.\n"
                "Si genera sul PC e si copia sul volume dell'archivio "
                "(vedi docs/RICERCA-IBRIDA.md). Nel frattempo `search` (FTS5) "
                "funziona normalmente: nessun'altra capacità è compromessa."
            )
        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer
        except ImportError as exc:                      # pragma: no cover — dipendenza d'immagine
            raise SemanticaNonPronta(
                f"Runtime di embedding non installato nell'immagine ({exc}). "
                "Attese: onnxruntime, tokenizers."
            ) from exc
        opts = ort.SessionOptions()
        # 2 thread: la VPS ha 4 core e sei container. Un embedding da 25 ms non
        # vale la fame di CPU degli altri servizi.
        opts.intra_op_num_threads = 2
        opts.inter_op_num_threads = 1
        sess = ort.InferenceSession(str(onnx), opts, providers=["CPUExecutionProvider"])
        tk = Tokenizer.from_file(str(tok))
        tk.enable_truncation(MAX_TOKEN)
        tk.enable_padding()
        _SESSIONE, _TOKENIZER = sess, tk
        log.info("modello di embedding caricato da %s", model_dir)
        return _SESSIONE, _TOKENIZER


def embed_query(testo: str, model_dir: Path) -> bytes:
    """La query come vettore già impacchettato per sqlite-vec (float32 little-endian).

    Il pooling e la normalizzazione L2 sono DENTRO il grafo ONNX (esportati col
    modello): il runtime non li replica, quindi non può sbagliarli in modo
    diverso da chi ha costruito l'indice.
    """
    sess, tk = _carica_modello(model_dir)   # PRIMA il controllo: se manca il modello,
    import numpy as np                      # l'errore parlante non deve dipendere da un import
    enc = tk.encode_batch([PREFISSO_QUERY + (testo or "").strip()])
    ids = np.array([e.ids for e in enc], dtype=np.int64)
    mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
    vec = sess.run(None, {"input_ids": ids, "attention_mask": mask})[0][0]
    return struct.pack(f"{DIM}f", *vec.astype("float32"))


def percorso_indice(db_path: Path) -> Path:
    """`/…/archivio.db` → `/…/archivio.vec.db` (l'indice vive accanto al suo DB)."""
    return db_path.with_suffix(".vec.db")


def meta_indice(conn: Any, alias: str = "vec") -> dict[str, str]:
    """I metadati dell'indice ATTACHato: modello, perimetro, quando, quanto.

    Servono a rispondere alla domanda che un risultato semantico solleva sempre:
    *questo indice copre il periodo che sto cercando?* Un indice parziale che non
    dichiara il proprio perimetro produce zeri che sembrano assenze.
    """
    try:
        return {k: v for k, v in conn.execute(
            f"SELECT chiave, valore FROM {alias}.indice_meta")}
    except Exception:                                   # noqa: BLE001 — indice vecchio senza meta
        return {}


def knn_dedup(conn: Any, blob: bytes, *, topn: int, k_chunk: int = 400,
              alias: str = "vec", tabella: str = "vec_chunk_small") -> list[int]:
    """I `topn` MESSAGGI più vicini, dedotti dai chunk più vicini.

    L'indice è per CHUNK (un messaggio lungo produce più vettori: è la cura che
    ha raddoppiato il recall nel POC). Il rank di un messaggio è quello del suo
    chunk migliore — e la deduplica va fatta QUI, in Python: sqlite-vec vieta
    GROUP BY/ORDER BY diversi da `distance` nelle query knn (misurato: solleva
    «Only a single 'ORDER BY distance' clause is allowed»).
    """
    cur = conn.execute(
        f"SELECT msg_rowid FROM {alias}.{tabella} "
        "WHERE embedding MATCH ? AND k = ? ORDER BY distance", (blob, int(k_chunk)))
    visti: set[int] = set()
    ordine: list[int] = []
    for (rid,) in cur:
        if rid in visti:
            continue
        visti.add(rid)
        ordine.append(rid)
        if len(ordine) >= topn:
            break
    return ordine


# Parole che in una domanda parlata non portano segnale. Non è una lista di
# stopword «linguistica»: è la lista di ciò che rovina una query FTS5, misurata
# sul caso reale (sotto).
_VUOTE = {
    "a", "ad", "ai", "al", "alla", "alle", "allo", "anche", "che", "chi", "ci",
    "coi", "col", "come", "con", "cosa", "cui", "da", "dai", "dal", "dalla",
    "de", "dei", "del", "della", "delle", "dello", "di", "dove", "e", "ed",
    "era", "erano", "essere", "gia", "già", "gli", "ho", "i", "il", "in", "io",
    "la", "le", "lo", "ma", "mi", "mia", "mie", "miei", "mio", "ne", "nei",
    "nel", "nella", "nelle", "nello", "non", "o", "per", "piu", "più", "qual",
    "quale", "quando", "quanto", "quella", "quello", "questa", "questo", "sono",
    "su", "sul", "sulla", "te", "tu", "tuo", "un", "una", "uno", "and", "for",
    "from", "how", "of", "on", "or", "that", "the", "to", "was", "were", "what",
    "when", "where", "which", "with",
}


def query_fts_da_naturale(testo: str, *, minimo: int = 2) -> str:
    """Da una domanda parlata a un'espressione FTS5 utile — o stringa vuota.

    🔴 PERCHÉ ESISTE, misurato in produzione il 07/09 al primo collaudo dal vivo.
    FTS5 fa **AND implicito** fra tutti i termini: passargli «la dashboard dove i
    file erano pianeti nello spazio» significa chiedere i documenti che
    contengono *anche* «la», «dove», «i», «erano» — cioè solo testi lunghissimi
    dove quelle parole capitano tutte insieme. Il risultato non era zero (che si
    sarebbe notato): erano **quattro risultati plausibili e inutili**, che la
    fusione poi promuoveva sopra i veri. *Il rumore che passa il controllo è più
    dannoso del silenzio.*

    La cura: tenere i termini che portano segnale e unirli con OR, così bm25
    premia chi ne contiene di più e di più rari. Sotto `minimo` termini utili
    restituisce "" — e chi chiama salta il ramo full-text invece di inventarselo.
    """
    parole = [p.strip(".,;:!?()[]{}«»\"'`").lower()
              for p in (testo or "").split()]
    utili = [p for p in parole if len(p) > 2 and p not in _VUOTE and not p.isdigit()]
    # de-duplica conservando l'ordine: «memoria … memoria» non pesa doppio
    viste, tenuti = set(), []
    for p in utili:
        if p not in viste:
            viste.add(p)
            tenuti.append(p)
    if len(tenuti) < minimo:
        return ""
    return " OR ".join(f'"{p}"' for p in tenuti)


def fondi_rrf(fts: list, vec: list, *, k: int = RRF_K,
              peso_fts: float = RRF_PESO_FTS) -> list:
    """Reciprocal Rank Fusion PESATA delle due liste (identità qualsiasi hashable).

    ⚠️ Il peso NON è cosmesi. Con RRF di default (k=60, pesi pari) il POC ha
    misurato una REGRESSIONE: un risultato esatto primo in FTS5 usciva dai
    top-10 perché due mediocri-in-entrambe-le-liste lo superavano. Cioè la
    fusione peggiorava proprio il caso che funzionava. Con questi parametri la
    regressione sparisce e restano i guadagni: è il motivo per cui i default
    stanno scritti qui e non nella firma di chi chiama.
    """
    punti: dict[Any, float] = {}
    for lista, peso in ((fts, peso_fts), (vec, 1.0)):
        for i, ident in enumerate(lista, 1):
            punti[ident] = punti.get(ident, 0.0) + peso / (k + i)
    return [ident for ident, _ in sorted(punti.items(), key=lambda kv: -kv[1])]
