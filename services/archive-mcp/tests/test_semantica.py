"""Test della ricerca ibrida (#281).

Due livelli, deliberatamente separati:

① **La fusione e le degradazioni** — stdlib-only, sempre in CI. Qui vive la
   prova che conta di più: la RRF pesata NON deve far uscire dai top-10 un
   risultato che FTS5 metteva primo. È la regressione misurata nel POC con i
   parametri di default della letteratura, e un test che non la riproduce non
   sta collaudando niente.

② **Il banco sui bersagli veri** — richiede indice + modello (artefatti sul
   volume, non nel repo): gira dove ci sono, si SALTA dichiarando il perché
   dove non ci sono. Un test che finge di passare senza i suoi dati sarebbe
   verde per cortesia.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import semantica  # noqa: E402


# ── ① fusione RRF ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("overlap", [0, 4, 10])
def test_chi_sta_in_entrambe_batte_il_rank1_di_una_sola_qualunque_parametro(overlap):
    """⚠️ COMPORTAMENTO REALE DI RRF, misurato qui il 07/09 e scritto perché è
    contro-intuitivo: **i parametri non proteggono il rank-1 contro la
    sovrapposizione**. Un risultato presente in ENTRAMBE le liste batte sempre
    uno presente in una sola, con qualunque k e qualunque peso ragionevole — e la
    posizione del solo-FTS scende esattamente col numero di condivisi (overlap N
    → posizione N+1), identica con k=60/peso 1 e con k=30/peso 1.5.

    Serve saperlo per due ragioni: chi taglia a top-10 sappia che con 10+
    risultati condivisi il rank-1 esce a prescindere; e chi in futuro cerca di
    curare una regressione ritoccando k o il peso sappia, prima di provarci, che
    di lì non passa. (La regressione E4 del POC fu curata su dati veri, dove le
    liste hanno strutture diverse da questo caso limite.)"""
    fts = ["esatto"] + [f"f{i}" for i in range(1, 20)]
    vec = [f"v{i}" for i in range(1, 10)] + [f"f{i}" for i in range(1, overlap + 1)]
    pos = lambda **kw: semantica.fondi_rrf(fts, vec, **kw).index("esatto") + 1  # noqa: E731
    assert pos() == overlap + 1
    assert pos() == pos(k=60, peso_fts=1.0), "k e peso non cambiano questo caso: non fingere che lo facciano"


def test_primo_di_fts_resta_nei_top10_con_sovrapposizione_realistica():
    """Il caso vero (E4/E5 del banco): le due liste condividono pochi risultati.
    Lì il rank-1 di FTS5 deve restare in testa — e resta."""
    fts = ["esatto"] + [f"f{i}" for i in range(1, 20)]
    vec = [f"v{i}" for i in range(1, 8)] + ["f1", "f2", "f3"]
    fusi = semantica.fondi_rrf(fts, vec)
    assert "esatto" in fusi[:10], "il primo di FTS5 è uscito dai top-10: fusione che peggiora"


def test_fusione_promuove_chi_sta_in_entrambe():
    """Il guadagno atteso: un risultato mediocre in entrambe batte un buono in una sola."""
    fts = ["solo_fts", "x", "condiviso"]
    vec = ["solo_vec", "y", "condiviso"]
    fusi = semantica.fondi_rrf(fts, vec, k=10, peso_fts=1.0)
    assert fusi[0] == "condiviso"


def test_fusione_con_una_lista_vuota_non_perde_l_altra():
    """Metà fusione resta una ricerca: se un ramo tace, l'altro passa intero."""
    assert semantica.fondi_rrf([], ["a", "b"]) == ["a", "b"]
    assert semantica.fondi_rrf(["a", "b"], []) == ["a", "b"]


def test_peso_fts_sposta_l_ordine_nella_direzione_dichiarata():
    """Il peso fa quello che dice: alzarlo avvicina il risultato full-text."""
    fts, vec = ["F"], ["V"]
    assert semantica.fondi_rrf(fts, vec, k=10, peso_fts=3.0)[0] == "F"
    assert semantica.fondi_rrf(fts, vec, k=10, peso_fts=0.3)[0] == "V"


# ── ① degradazione: cosa manca e come si rimedia ─────────────────────────────

def test_modello_assente_dice_cosa_manca_e_dove(tmp_path):
    """L'errore deve nominare il file mancante, la cartella attesa e il rimedio —
    e dichiarare che `search` continua a funzionare: chi legge deve sapere se è
    rotto tutto o solo un pezzo."""
    with pytest.raises(semantica.SemanticaNonPronta) as e:
        semantica.embed_query("prova", tmp_path / "non-esiste")
    msg = str(e.value)
    assert "model.onnx" in msg and "tokenizer.json" in msg
    assert str(tmp_path) in msg
    assert "search" in msg and "FTS5" in msg


def test_percorso_indice_e_accanto_al_db():
    assert semantica.percorso_indice(Path("/var/lib/archive/db/recupero.db")) == \
        Path("/var/lib/archive/db/recupero.vec.db")


def test_meta_indice_non_esplode_su_indice_senza_metadati():
    """Un indice generato prima dei metadati non deve far fallire la ricerca:
    degrada a 'non dichiarato', che è un'informazione onesta."""
    import sqlite3
    conn = sqlite3.connect(":memory:")
    assert semantica.meta_indice(conn) == {}


# ── ② il banco: solo dove ci sono indice e modello ───────────────────────────

_DB = Path("/var/lib/archive/db/recupero-20260905.db")
_MODELLO = Path("/var/lib/archive/models/e5-small")
_ha_tutto = _DB.is_file() and semantica.percorso_indice(_DB).is_file() and \
    (_MODELLO / "model.onnx").is_file()

# I bersagli del banco del POC: uuid dei messaggi che DEVONO uscire nei top-10
# per la query in linguaggio naturale. Fissati prima di misurare (banco.py).
_BERSAGLI = [
    ("l'articolo dove raccontavo quanto ho speso con perplexity e quanto sarebbe "
     "costato coi consulenti", "C3 articolo Medium"),
]


@pytest.mark.skipif(not _ha_tutto,
                    reason="indice o modello assenti (artefatti di volume, non del repo): "
                           "il banco gira dove i dati esistono, qui si dichiara saltato")
@pytest.mark.parametrize("query,nome", _BERSAGLI)
def test_banco_bersagli_semantici(query, nome):
    import sqlite3

    import sqlite_vec

    conn = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("ATTACH DATABASE ? AS vec", (f"file:{semantica.percorso_indice(_DB)}?mode=ro",))
    blob = semantica.embed_query(query, _MODELLO)
    rowids = semantica.knn_dedup(conn, blob, topn=10)
    assert rowids, f"{nome}: il knn non ha restituito nulla"
