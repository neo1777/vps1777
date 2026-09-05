"""Le tre igiene della ricerca — issue #268 / #269 / #270 / #272 (05/09/2026).

Quattro comportamenti nuovi, ognuno nato da una misura sul vivo:
  ① dedup cross-DB per uuid (#272): lo stesso messaggio nei DB di riscontro
    consumava metà del limit in fotocopie — ora arriva una volta, con `anche_in`;
  ② max_chars su get_context (#268): il payload pieno dei messaggi-hub uccideva
    la connessione MCP — il troncamento è per-riga e DICHIARATO nel testo;
  ③ memo per-snapshot su archive_stats (#269): la scansione si paga una volta
    per versione del file (stesso patto di describe, misurato 74,6s a freddo);
  ④ semaforo a 2 sulla ricerca (#270): la terza richiesta concorrente ASPETTA
    invece di morire in timeout.

Stessa meccanica stdlib-only di test_db_conn.py (la CI esegue questa cartella
con `uvx pytest`: pydantic non c'è, si stubbano le settings e si gira davvero).
"""
from __future__ import annotations

import sqlite3
import sys
import threading
import types
from pathlib import Path

import pytest

_SCHEMA = """
CREATE TABLE messages(uuid TEXT PRIMARY KEY, project, ts, content);
CREATE VIRTUAL TABLE messages_fts USING fts5(
    uuid, project, ts, content, content='messages', content_rowid='rowid');
"""

_LUNGO = "flutter " + ("x" * 500)


def _crea_db(percorso: Path) -> None:
    conn = sqlite3.connect(percorso)
    conn.executescript(_SCHEMA)
    conn.execute("INSERT INTO messages VALUES (?,?,?,?)",
                 ("u1", "chatA", "2026-01-01T10:00:00Z", "parliamo di flutter"))
    conn.execute("INSERT INTO messages VALUES (?,?,?,?)",
                 ("lungo", "chatA", "2026-01-01T10:00:01Z", _LUNGO))
    conn.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
    conn.commit()
    conn.close()


class _SettingsFinte:
    def __init__(self, dir_db: Path) -> None:
        self.archive_db_dir = str(dir_db)
        self.archive_db_paths: dict[str, Path] = {}


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """Due DB con lo STESSO uuid `u1` — il caso che #272 esiste per curare."""
    for nome in ("uno", "due"):
        _crea_db(tmp_path / f"{nome}.db")
    monkeypatch.setenv("ARCHIVE_DB_DIR", str(tmp_path))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    for mod in [m for m in list(sys.modules) if m == "app" or m.startswith("app.")]:
        del sys.modules[mod]
    finte = types.ModuleType("app.settings")
    finte.get_settings = lambda: _SettingsFinte(tmp_path)   # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.settings", finte)
    from app import db as modulo
    modulo.reload_registry()
    assert modulo.available_dbs() == ["due", "uno"], "la fixture non ha caricato i DB"
    yield modulo


def test_dedup_cross_db_con_anche_in(db) -> None:
    """① Lo stesso uuid in due DB arriva UNA volta, e dice dove altro vive."""
    righe = db.search("flutter", "", limit=10)
    per_uuid = [r for r in righe if r["uuid"] == "u1"]
    assert len(per_uuid) == 1, "u1 doveva arrivare una volta sola"
    assert per_uuid[0].get("anche_in") == (["uno"] if per_uuid[0]["db"] == "due" else ["due"])


def test_dedup_non_tocca_il_db_singolo(db) -> None:
    """① controprova: sul DB singolo niente dedup e niente `anche_in`."""
    righe = db.search("flutter", "uno", limit=10)
    assert righe and all("anche_in" not in r for r in righe)


def test_max_chars_tronca_e_lo_dichiara(db) -> None:
    """② La riga lunga arriva corta col marcatore; con 0 arriva intera."""
    corte = db.get_context("lungo", "uno", before=0, after=0, max_chars=50)
    assert corte and "‹troncato: 50 di" in corte[0]["content"]
    assert len(corte[0]["content"]) < len(_LUNGO)
    piene = db.get_context("lungo", "uno", before=0, after=0, max_chars=0)
    assert piene[0]["content"] == _LUNGO


def test_stats_memo_non_riapre_il_db(db, monkeypatch) -> None:
    """③ La seconda archive_stats sullo stesso snapshot apre ZERO connessioni.

    Contare le aperture e non «c'è un memo» — è la lezione di test_db_conn:
    un test sulla forma resta verde anche se ogni chiamata ignora la cache."""
    prima = db.archive_stats("")
    assert prima, "l'istogramma non può essere vuoto su DB pieni"
    n = {"aperture": 0}
    originale = sqlite3.connect

    def spia(*a, **k):
        n["aperture"] += 1
        return originale(*a, **k)

    monkeypatch.setattr(sqlite3, "connect", spia)
    seconda = db.archive_stats("")
    assert seconda == prima
    assert n["aperture"] == 0, "il memo non ha morso: il DB è stato riaperto"


def test_terza_ricerca_aspetta_il_turno(db) -> None:
    """④ Coi 2 permessi occupati la ricerca ASPETTA; liberati, completa."""
    db._RICERCHE.acquire()
    db._RICERCHE.acquire()
    esito: list = []
    t = threading.Thread(target=lambda: esito.append(db.count("flutter", "uno")))
    t.start()
    t.join(0.4)
    assert t.is_alive(), "doveva essere in coda, non fallita né già passata"
    db._RICERCHE.release()
    db._RICERCHE.release()
    t.join(5)
    assert not t.is_alive() and esito and esito[0]["total"] >= 1
