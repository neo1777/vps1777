"""Il ruolo decide dove si cerca, quando non si sceglie un DB (#278 cura B, P1, 05/10/2026).

Fino alla 0.73 il `ruolo` era solo informazione: `search` e `count` senza `db_name`
toccavano TUTTI i DB, `voce-1777-personale` compreso, e i riscontri duplicavano i
primari. Ora, senza `db_name`, i quattro tool di ricerca guardano i **primari** e i **non
dichiarati** (un'installazione nuova, dove nessuno ha dichiarato niente, non perde nulla).
Fotografie e riscontri si riaprono con `ruoli`, e `count` dice quanti risultati ci sono
anche lì: «0 sui primari» non deve sembrare «0 ovunque». Il riservato non si interroga
mai di sua iniziativa: solo nominandolo.

Stdlib-only, come test_ruolo.py.
"""
from __future__ import annotations

import sqlite3
import sys
import types
from pathlib import Path

import pytest

_SCHEMA = """
CREATE TABLE messages(uuid TEXT PRIMARY KEY, project, ts, content);
CREATE VIRTUAL TABLE messages_fts USING fts5(
    uuid, project, ts, content, content='messages', content_rowid='rowid');
"""

_DB = {"prim": "primario", "foto": "fotografia", "risc": "riscontro",
       "pers": "riservato", "nuovo": None}


def _crea_db(percorso: Path, ruolo: str | None) -> None:
    conn = sqlite3.connect(percorso)
    conn.executescript(_SCHEMA)
    conn.execute("INSERT INTO messages(uuid, project, ts, content) VALUES (?,?,?,?)",
                 (f"u-{percorso.stem}", "chat", "2026-01-01T10:00:00Z", "parliamo di flutter"))
    conn.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
    if ruolo:
        conn.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO meta(key, value) VALUES ('ruolo', ?)", (ruolo,))
    conn.commit()
    conn.close()


class _SettingsFinte:
    def __init__(self, dir_db: Path) -> None:
        self.archive_db_dir = str(dir_db)
        self.archive_db_paths: dict[str, Path] = {}


@pytest.fixture()
def db(tmp_path, monkeypatch):
    for nome, ruolo in _DB.items():
        _crea_db(tmp_path / f"{nome}.db", ruolo)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    for mod in [m for m in list(sys.modules) if m == "app" or m.startswith("app.")]:
        del sys.modules[mod]
    finte = types.ModuleType("app.settings")
    finte.get_settings = lambda: _SettingsFinte(tmp_path)   # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.settings", finte)
    from app import db as modulo
    modulo.reload_registry()
    yield modulo


def _dbs(righe) -> set[str]:
    return {r["db"] for r in righe}


def test_senza_db_name_primari_e_non_dichiarati(db):
    assert _dbs(db.search("flutter")) == {"prim", "nuovo"}


def test_il_riservato_non_compare_mai_senza_nominarlo(db):
    assert "pers" not in _dbs(db.search("flutter"))
    assert "pers" not in db.count("flutter")["per_db"]
    assert "pers" not in db.count("flutter").get("anche_fuori", {})
    assert "pers" not in db.check_term("flutter")["per_db"]
    assert _dbs(db.search("flutter", "pers")) == {"pers"}


def test_tutti_riapre_ogni_db(db):
    assert _dbs(db.search("flutter", ruoli="tutti")) == set(_DB)


def test_un_ruolo_scelto_vale_da_solo(db):
    assert _dbs(db.search("flutter", ruoli="fotografia")) == {"foto"}
    assert _dbs(db.search("flutter", ruoli="fotografia, riscontro")) == {"foto", "risc"}


def test_count_avvisa_dei_risultati_fuori_dal_perimetro(db):
    out = db.count("flutter")
    assert out["per_db"] == {"prim": 1, "nuovo": 1}
    assert out["anche_fuori"] == {"foto": 1, "risc": 1}
    assert db.count("niente-di-simile")["anche_fuori"] == {}
    assert "anche_fuori" not in db.count("flutter", ruoli="tutti")
    assert "anche_fuori" not in db.count("flutter", "prim")


def test_check_term_rispetta_il_perimetro(db):
    assert set(db.check_term("flutter")["per_db"]) == {"prim", "nuovo"}


def test_un_ruolo_sbagliato_e_un_errore_parlante(db):
    with pytest.raises(ValueError, match="primario"):
        db.search("flutter", ruoli="primari")


def test_un_ruolo_cambiato_vale_subito(db, tmp_path):
    db.search("flutter")
    conn = sqlite3.connect(tmp_path / "foto.db")
    conn.execute("UPDATE meta SET value='primario' WHERE key='ruolo'")
    conn.commit()
    conn.close()
    import os
    os.utime(tmp_path / "foto.db", (2_000_000_000, 2_000_000_000))
    assert "foto" in _dbs(db.search("flutter"))
