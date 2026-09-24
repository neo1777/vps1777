"""`search_ibrida` verifica che il rowid dell'indice sia ancora del messaggio giusto.

🔴 IL DIFETTO CHE QUESTI TEST FERMANO. L'indice vettoriale lavora sul `rowid` di
`messages`, e l'indexer fa `INSERT OR REPLACE` sull'uuid. Dopo un re-ingest:
  · un rowid dell'indice può NON esistere più → il risultato spariva in silenzio;
  · un rowid può essere stato RIUSATO da un altro messaggio → il server restituiva
    quel messaggio per il senso di un altro, con l'aria di un risultato giusto.
Se l'indice ha il registro del costruttore (`indice_righe`), ogni risultato si
confronta con l'uuid registrato; chi non combacia si scarta, e `indici[].verifica`
lo conta e dice la cura. Un indice senza registro (quello del POC) funziona come
prima, ma lo dichiara.

Due famiglie: ① stdlib (il verdetto e la lettura del registro, che è una tabella
normale) e ② con sqlite-vec (la ricerca vera: salta nello step stdlib-only, gira
nello step «deps del lock», dove il file è elencato). Dati sintetici.
"""
from __future__ import annotations

import sqlite3
import sys
import types
from pathlib import Path

import pytest

_SERVIZIO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVIZIO / "tools"))
sys.path.insert(0, str(_SERVIZIO))

from app import semantica  # noqa: E402


def _ha_vec() -> bool:
    try:
        import sqlite_vec
        c = sqlite3.connect(":memory:")
        c.enable_load_extension(True)
        sqlite_vec.load(c)
        c.close()
        return True
    except Exception:                                   # noqa: BLE001
        return False


vec = pytest.mark.skipif(
    not _ha_vec(),
    reason="sqlite-vec assente (step stdlib-only): questi test girano nello step "
           "«deps del lock» di archive-mcp, dove c'è")


# ── ① stdlib ─────────────────────────────────────────────────────────────────

def test_verdetto_indice_in_pari():
    v = semantica.verdetto_registro(True, candidati=12, assenti=0, uuid_diversi=0)
    assert v["registro"] is True and v["scartati"] == 0 and v["candidati"] == 12
    assert v["stato"].startswith("verificato")


def test_verdetto_indice_disallineato_conta_e_dice_la_cura():
    v = semantica.verdetto_registro(True, candidati=12, assenti=2, uuid_diversi=1)
    assert v["scartati"] == 3 and v["rowid_assenti"] == 2 and v["uuid_diversi"] == 1
    assert "disallineato" in v["stato"] and "--controlla" in v["stato"]


def test_verdetto_indice_senza_registro_si_dichiara():
    v = semantica.verdetto_registro(False, candidati=5, assenti=0, uuid_diversi=0)
    assert v["registro"] is False and v["scartati"] == 0
    assert "senza registro" in v["stato"] and "non è verificabile" in v["stato"]
    v = semantica.verdetto_registro(False, candidati=5, assenti=1, uuid_diversi=0)
    assert v["scartati"] == 1 and "rowid assenti" in v["stato"]


def test_uuid_registrati_legge_il_registro_o_dice_che_manca(tmp_path):
    idx = tmp_path / "x.vec.db"
    c = sqlite3.connect(idx)
    c.execute("CREATE TABLE indice_meta(chiave TEXT PRIMARY KEY, valore TEXT)")
    c.commit()
    c.close()
    # uri=True come in `db._open`: l'ATTACH con `file:…?mode=ro` lo richiede
    conn = sqlite3.connect("file::memory:", uri=True)
    conn.execute("ATTACH DATABASE ? AS vec", (f"file:{idx}?mode=ro",))
    assert semantica.uuid_registrati(conn, [1, 2]) is None, "senza registro: None, non {}"
    conn.execute("DETACH DATABASE vec")
    c = sqlite3.connect(idx)
    c.execute("CREATE TABLE indice_righe(msg_rowid INTEGER PRIMARY KEY, uuid TEXT, "
              "impronta TEXT, primo_chunk INTEGER, n_chunk INTEGER)")
    c.execute("INSERT INTO indice_righe VALUES (1, 'u1', 'h', 1, 1)")
    c.commit()
    c.close()
    conn.execute("ATTACH DATABASE ? AS vec", (f"file:{idx}?mode=ro",))
    assert semantica.uuid_registrati(conn, [1, 2]) == {1: "u1"}
    assert semantica.uuid_registrati(conn, []) == {}


# ── ② la ricerca vera ────────────────────────────────────────────────────────

FRASE = "Un messaggio sintetico abbastanza lungo da entrare nell'indice vettoriale"


class _SettingsFinte:
    def __init__(self, d: Path) -> None:
        self.archive_db_dir = str(d)
        self.archive_db_paths: dict[str, Path] = {}
        self.archive_model_dir = str(d / "modello")


@pytest.fixture()
def archivio(tmp_path, monkeypatch):
    """(modulo db, percorso del DB, embedder finto) — `app.db` importato da capo
    su una dir sua, con le settings stubbate (vedi test_db_conn.py per il perché)."""
    import test_costruisci_indice as tci

    db = tci.nuovo_db(tmp_path / "arch.db", [
        (f"u{i}", "claude-code", f"2026-05-{10 + i:02d}", f"{FRASE} numero {i}")
        for i in range(1, 7)])
    for mod in [m for m in list(sys.modules) if m == "app" or m.startswith("app.")]:
        del sys.modules[mod]
    finte = types.ModuleType("app.settings")
    finte.get_settings = lambda: _SettingsFinte(tmp_path)   # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.settings", finte)
    from app import db as modulo
    modulo.reload_registry()
    yield modulo, db, tci


def _cerca(modulo, tci, testo: str, monkeypatch) -> dict:
    """La query «vale» il vettore del passaggio: il finto è deterministico, quindi
    il vicino più prossimo è il messaggio con quel testo."""
    blob = tci.vettore(semantica.PREFISSO_PASSAGGIO + testo)
    monkeypatch.setattr(modulo.semantica, "embed_query", lambda q, d: blob)
    modulo._maybe_reload()
    return modulo.search_ibrida("x", db="arch", limit=3)


def _rw(db: Path, *sql: tuple) -> None:
    c = sqlite3.connect(db)
    for q in sql:
        c.execute(*q)
    c.commit()
    c.close()


@vec
def test_indice_in_pari_verificato(archivio, monkeypatch):
    modulo, db, tci = archivio
    import costruisci_indice as ci
    ci.costruisci(db, tci.Finto(), ci.Perimetro(tutto=True))
    r = _cerca(modulo, tci, f"{FRASE} numero 2", monkeypatch)
    assert r["righe"][0]["uuid"] == "u2"
    v = r["indici"][0]["verifica"]
    assert v["registro"] is True and v["scartati"] == 0 and v["candidati"] > 0
    # la forma dei campi di prima non cambia
    assert set(r["indici"][0]) >= {"db", "indice", "messaggi_indicizzati", "perimetro",
                                   "modello", "generato"}


@vec
def test_rowid_riusato_non_restituisce_il_messaggio_sbagliato(archivio, monkeypatch):
    """Il caso peggiore: il rowid di u6 ora è di u9. Prima della cura il server
    restituiva u9 per il senso di u6."""
    modulo, db, tci = archivio
    import costruisci_indice as ci
    ci.costruisci(db, tci.Finto(), ci.Perimetro(tutto=True))
    rid = tci.rowid_di(db, "u6")
    _rw(db, ("DELETE FROM messages WHERE uuid='u6'",),
        ("INSERT INTO messages(uuid, project, ts, content) VALUES (?,?,?,?)",
         ("u9", "claude-code", "2026-06-01", "tutt'altro argomento, niente a che vedere")))
    assert tci.rowid_di(db, "u9") == rid, "premessa: rowid riusato"
    r = _cerca(modulo, tci, f"{FRASE} numero 6", monkeypatch)
    assert "u9" not in [x["uuid"] for x in r["righe"]], \
        "il messaggio sbagliato è uscito come risultato vettoriale"
    v = r["indici"][0]["verifica"]
    assert v["uuid_diversi"] == 1 and v["scartati"] == 1
    assert "disallineato" in v["stato"]


@vec
def test_reingest_insert_or_replace_contato(archivio, monkeypatch):
    """Il rowid sparito si scartava già, ma in silenzio: ora si conta."""
    modulo, db, tci = archivio
    import costruisci_indice as ci
    ci.costruisci(db, tci.Finto(), ci.Perimetro(tutto=True))
    _rw(db, ("INSERT OR REPLACE INTO messages(uuid, project, ts, content) "
             "SELECT uuid, project, ts, content FROM messages WHERE uuid='u3'",))
    r = _cerca(modulo, tci, f"{FRASE} numero 3", monkeypatch)
    v = r["indici"][0]["verifica"]
    assert v["rowid_assenti"] == 1 and v["scartati"] == 1
    ci.costruisci(db, tci.Finto())                       # l'incrementale cura
    r = _cerca(modulo, tci, f"{FRASE} numero 3", monkeypatch)
    assert r["righe"][0]["uuid"] == "u3"
    assert r["indici"][0]["verifica"]["scartati"] == 0


@vec
def test_indice_senza_registro_dichiarato(archivio, monkeypatch):
    """L'indice del POC: si comporta come prima, ma dice che non è verificabile."""
    modulo, db, tci = archivio
    import costruisci_indice as ci
    ci.costruisci(db, tci.Finto(), ci.Perimetro(tutto=True))
    _rw(semantica.percorso_indice(db), ("DROP TABLE indice_righe",))
    r = _cerca(modulo, tci, f"{FRASE} numero 4", monkeypatch)
    assert r["righe"][0]["uuid"] == "u4"
    v = r["indici"][0]["verifica"]
    assert v["registro"] is False and "senza registro" in v["stato"]
