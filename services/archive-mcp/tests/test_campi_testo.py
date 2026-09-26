"""`campi='testo'`: cercare solo nelle parole, non nelle azioni — #273 (26/09/2026).

Il 05/09 una ricerca sul «libro» con `sort=newest` era dominata da una fixture di
test dell'indexer («il libro è al capitolo 81»): un dato finto, plausibile e in prima
posizione. Misurato il 26/09 sul primario: su 14 righe con quella frase, 12 hanno il
testo vuoto e la frase nelle AZIONI (`tools`: il codice scritto da un Edit, l'output
di un Read). La cura è un filtro per colonna dell'FTS, opt-in (scelta di Neo):
`campi='tutto'` resta il default, `campi='testo'` cerca solo in `content`.

Stessa meccanica stdlib-only di test_ricerca_igiene.py.
"""
from __future__ import annotations

import sqlite3
import sys
import types
from pathlib import Path

import pytest

_SCHEMA = """
CREATE TABLE messages(uuid TEXT PRIMARY KEY, project, ts, content,
                      sender TEXT DEFAULT '', tools TEXT DEFAULT '',
                      attachments TEXT DEFAULT '', speaker TEXT DEFAULT '',
                      voice TEXT DEFAULT '', quoted_share REAL DEFAULT 0);
CREATE VIRTUAL TABLE messages_fts USING fts5(
    uuid, project, ts, content, tools, attachments,
    content='messages', content_rowid='rowid');
"""


def _crea(percorso: Path) -> None:
    conn = sqlite3.connect(percorso)
    conn.executescript(_SCHEMA)
    conn.executemany(
        "INSERT INTO messages(uuid, project, ts, content, sender, tools, speaker)"
        " VALUES (?,?,?,?,?,?,?)", [
            ("vero", "chat", "2026-01-01T10:00:00Z",
             "il libro è al capitolo 12", "user", "", "human"),
            ("fixture", "chat", "2026-09-05T10:00:00Z", "", "assistant",
             'Edit {"new_string": "il libro è al capitolo 81"}', "assistant"),
        ])
    conn.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
    conn.commit()
    conn.close()


class _SettingsFinte:
    def __init__(self, dir_db: Path) -> None:
        self.archive_db_dir = str(dir_db)
        self.archive_db_paths: dict[str, Path] = {}


@pytest.fixture()
def db(tmp_path, monkeypatch):
    _crea(tmp_path / "archivio.db")
    monkeypatch.setenv("ARCHIVE_DB_DIR", str(tmp_path))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    for mod in [m for m in list(sys.modules) if m == "app" or m.startswith("app.")]:
        del sys.modules[mod]
    finte = types.ModuleType("app.settings")
    finte.get_settings = lambda: _SettingsFinte(tmp_path)   # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.settings", finte)
    from app import db as modulo
    modulo.reload_registry()
    yield modulo


def test_default_cerca_ovunque_come_prima(db) -> None:
    """Il default non cambia: le azioni restano cercabili (e il newest è la fixture)."""
    righe = db.search("libro capitolo", "archivio", sort="newest")
    assert [r["uuid"] for r in righe] == ["fixture", "vero"]


def test_campi_testo_esclude_le_azioni(db) -> None:
    righe = db.search("libro capitolo", "archivio", sort="newest", campi="testo")
    assert [r["uuid"] for r in righe] == ["vero"]


def test_count_segue_gli_stessi_campi(db) -> None:
    """count e search parlano della stessa popolazione (il patto di count_conn)."""
    assert db.count("libro", "archivio")["total"] == 2
    assert db.count("libro", "archivio", campi="testo")["total"] == 1


def test_campi_testo_con_query_raw_e_operatori(db) -> None:
    righe = db.search("libro OR capitolo", "archivio", raw=True, campi="testo")
    assert [r["uuid"] for r in righe] == ["vero"]


def test_campi_sconosciuto_e_un_errore_parlante(db) -> None:
    """Un valore sbagliato non ricade in silenzio sul default: lo dice."""
    with pytest.raises(ValueError, match="campi"):
        db.search("libro", "archivio", campi="parole")
