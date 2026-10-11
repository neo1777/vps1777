"""P3 (11/10/2026): le ricerche su più DB hanno un budget di tempo, e un parziale si dice.

Il proxy del gateway chiude la lettura a 60 s («MCP server connection lost»). Dall'audit del
10-11/10: `count` ha impiegato 41 s, due volte, a cache fredda (la stessa chiamata a cache
calda: 0,7 s su 25 DB). Con un DB lento in più la risposta non arrivava, e il client vedeva
un errore invece di un numero. Ora `count`, `check_term` e `search_ibrida` si fermano a
BUDGET_S secondi; un `progress_handler` di SQLite interrompe anche una sola query lunga; i DB
non guardati vanno in `saltati` con `ramo: "budget"`, e un totale incompleto porta
`parziale: true`. `search` non ha budget: misurata al massimo a 3,6 s, e la sua lista non ha
dove dirlo.

Stdlib. Il tempo è finto dove serve (`db._adesso`), vero nel test del progress handler.
"""
from __future__ import annotations

import sqlite3
import sys
import time
import types
from pathlib import Path

import pytest

_SERVIZIO = Path(__file__).resolve().parents[1]

_SCHEMA = """
CREATE TABLE messages(uuid TEXT PRIMARY KEY, project, ts, content);
CREATE VIRTUAL TABLE messages_fts USING fts5(
    uuid, project, ts, content, content='messages', content_rowid='rowid');
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
"""
_DB = {"a": "primario", "b": "primario", "c": "fotografia", "d": "riscontro"}


def _crea(percorso: Path, ruolo: str) -> None:
    c = sqlite3.connect(percorso)
    c.executescript(_SCHEMA)
    c.execute("INSERT INTO messages VALUES (?, 'p', '2026-01-01', 'parliamo di memoria')",
              (f"u-{percorso.stem}",))
    c.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
    c.execute("INSERT INTO meta VALUES ('ruolo', ?)", (ruolo,))
    c.commit()
    c.close()


class _SettingsFinte:
    def __init__(self, d: Path) -> None:
        self.archive_db_dir = str(d)
        self.archive_db_paths: dict[str, Path] = {}
        self.archive_model_dir = str(d / "modello")


@pytest.fixture()
def db(tmp_path, monkeypatch):
    for nome, ruolo in _DB.items():
        _crea(tmp_path / f"{nome}.db", ruolo)
    sys.path.insert(0, str(_SERVIZIO))
    for mod in [m for m in list(sys.modules) if m == "app" or m.startswith("app.")]:
        del sys.modules[mod]
    finte = types.ModuleType("app.settings")
    finte.get_settings = lambda: _SettingsFinte(tmp_path)   # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.settings", finte)
    from app import db as modulo
    modulo.reload_registry()
    yield modulo


def _orologio(monkeypatch, db, passo: float) -> None:
    """Ogni lettura dell'orologio va avanti di `passo` secondi."""
    stato = {"t": 1000.0}

    def adesso() -> float:
        stato["t"] += passo
        return stato["t"]
    monkeypatch.setattr(db, "_adesso", adesso)


def test_count_nel_budget_e_completo(db):
    r = db.count("memoria")
    assert r["total"] == 2 and "parziale" not in r and "saltati" not in r
    assert r["anche_fuori"] == {"c": 1, "d": 1}


def test_count_oltre_il_budget_si_dice_parziale(db, monkeypatch):
    monkeypatch.setattr(db, "BUDGET_S", 0.0)
    r = db.count("memoria")
    assert r["parziale"] is True and r["total"] == 0
    assert {s["db"] for s in r["saltati"]} == {"a", "b"}
    assert all(s["ramo"] == "budget" for s in r["saltati"])
    assert "rilancia" in r["saltati"][0]["motivo"]


def test_count_il_tempo_che_resta_va_ad_anche_fuori_e_chi_manca_si_dice(db, monkeypatch):
    # 4 letture dell'orologio da 15 s: i due primari stanno nei 40 s, i fuori no
    monkeypatch.setattr(db, "BUDGET_S", 40.0)
    _orologio(monkeypatch, db, 15.0)
    r = db.count("memoria")
    assert r["total"] == 2 and "parziale" not in r
    assert set(r.get("anche_fuori_non_contati", [])) >= {"d"}


def test_un_db_illeggibile_non_rompe_la_ricerca_e_non_e_uno_zero(db, tmp_path):
    """Un file .db rotto nella cartella: SQLite solleva DatabaseError (non OperationalError)
    alla prima query. Prima della 0.81 lo leggeva `_ruolo` per il perimetro, e ogni ricerca
    senza db_name falliva per tutti; ora quel DB si dice non letto, e gli altri rispondono."""
    (tmp_path / "c.db").write_bytes(b"non sono un db " * 100)
    db._maybe_reload()
    r = db.count("memoria")
    assert r["total"] == 2
    non_letti = {s["db"] for s in r.get("saltati", [])} | set(r.get("anche_fuori_non_contati", []))
    assert "c" in non_letti
    assert {x["db"] for x in db.search("memoria")} == {"a", "b"}
    assert set(db.check_term("memoria")["per_db"]) == {"a", "b"}


def test_check_term_oltre_il_budget(db, monkeypatch):
    monkeypatch.setattr(db, "BUDGET_S", 0.0)
    r = db.check_term("C++")
    assert r["per_db"] == {} and r["parziale"] is True
    assert {s["db"] for s in r["saltati"]} == {"a", "b"}


def test_search_ibrida_oltre_il_budget_dice_i_db_non_guardati(db, monkeypatch):
    monkeypatch.setattr(db, "BUDGET_IBRIDA_S", 0.0)
    monkeypatch.setattr(db, "_indici_disponibili",
                        lambda: {"a": Path("/x/a.vec.db"), "b": Path("/x/b.vec.db")})
    monkeypatch.setattr(db.semantica, "embed_query", lambda t, d: b"\x00" * 4)
    aperti = []
    monkeypatch.setattr(db, "_open_con_indice", lambda name, idx: aperti.append(name))
    r = db.search_ibrida("memoria", limit=5)
    assert aperti == [] and r["righe"] == []
    assert {(s["db"], s["ramo"]) for s in r["saltati"]} == {("a", "budget"), ("b", "budget")}
    assert r["parziale"] is True


def test_il_progress_handler_interrompe_una_query_lunga(db):
    """Il budget non aspetta la fine di una query: SQLite la interrompe."""
    conn = sqlite3.connect(":memory:")
    budget = db._Budget(0.05)
    t = time.monotonic()
    with pytest.raises(sqlite3.OperationalError, match="interrupt"):
        with budget.su(conn):
            conn.execute("WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i+1 FROM n "
                         "WHERE i < 100000000) SELECT count(*) FROM n").fetchone()
    assert time.monotonic() - t < 2.0
    assert budget.finito()
    # la connessione torna senza handler: una query dopo il budget non si interrompe
    assert conn.execute("SELECT 1").fetchone() == (1,)


def test_search_ibrida_ha_un_budget_suo_piu_corto():
    """La ricerca dei vicini di sqlite-vec è codice C in una tabella virtuale: il progress
    handler non la interrompe a metà (dal vivo, 11/10: 8 s per una sola ricerca su 452.000
    vettori, e una search_ibrida da 69 s con `parziale: true`). Il budget di search_ibrida
    lascia spazio a una ricerca che non si ferma e al lavoro dopo la fusione."""
    sys.path.insert(0, str(_SERVIZIO))
    from app import db as modulo
    assert modulo.BUDGET_IBRIDA_S <= 30.0 < modulo.BUDGET_S


def test_a_budget_finito_la_ricerca_dei_vicini_non_parte(db, monkeypatch):
    """Prima il controllo era solo fra un DB e l'altro: un FTS interrotto dal budget
    lasciava partire lo stesso la ricerca dei vicini, che non si interrompe."""
    monkeypatch.setattr(db, "BUDGET_IBRIDA_S", 40.0)
    _orologio(monkeypatch, db, 25.0)     # init 1025 → fine 1065; ogni lettura +25 s
    monkeypatch.setattr(db, "_indici_disponibili", lambda: {"a": Path("/x/a.vec.db")})
    monkeypatch.setattr(db.semantica, "embed_query", lambda t, d: b"\x00" * 4)

    class _Conn:
        def set_progress_handler(self, *a):
            pass

        def execute(self, *a, **k):
            raise sqlite3.OperationalError("niente tabelle qui")

        def close(self):
            pass
    monkeypatch.setattr(db, "_open_con_indice", lambda name, idx: _Conn())
    monkeypatch.setattr(db.fts, "search_conn", lambda *a, **k: [])
    vicini = []
    monkeypatch.setattr(db.semantica, "knn_pezzi", lambda *a, **k: vicini.append(1) or [])
    r = db.search_ibrida("memoria piano", "a", limit=5)
    assert vicini == [], "la ricerca dei vicini è partita a budget finito"
    assert ("a", "budget") in {(s["db"], s["ramo"]) for s in r["saltati"]}
    assert r["parziale"] is True
