"""P19 (11/10/2026): cosa è cambiato fra due fotografie dello stesso archivio.

Due export claude.ai di date diverse dicono cosa l'account ha perso, guadagnato o
riscritto. Il collaudo vero sta nel 07/09: `bot1777` e `How to use Claude` c'erano nel
080726 ed erano spariti nel 290826. Qui lo stesso caso in piccolo, più il segnale degli
uuid instabili e il budget. Stdlib.
"""
from __future__ import annotations

import sqlite3
import sys
import types
from pathlib import Path

import pytest

_SERVIZIO = Path(__file__).resolve().parents[1]
_SCHEMA = """
CREATE TABLE messages(uuid TEXT PRIMARY KEY, project, ts, content);
CREATE VIRTUAL TABLE messages_fts USING fts5(
    uuid, project, ts, content, content='messages', content_rowid='rowid');
"""

VECCHIO = [
    ("u1", "bot1777", "2026-07-01T10:00:00Z", "la chat del bot"),
    ("u2", "bot1777", "2026-07-02T10:00:00Z", "ancora il bot"),
    ("u3", "How to use Claude", "2026-06-01T10:00:00Z", "come si usa"),
    ("u4", "resta", "2026-07-03T10:00:00Z", "uguale"),
    ("u5", "resta", "2026-07-04T10:00:00Z", "prima versione"),
]
NUOVO = [
    ("u4", "resta", "2026-07-03T10:00:00Z", "uguale"),
    ("u5", "resta", "2026-07-04T10:00:00Z", "seconda versione"),
    ("u6", "nuova chat", "2026-08-20T10:00:00Z", "arrivata dopo"),
]


def _crea(p: Path, righe) -> None:
    c = sqlite3.connect(p)
    c.executescript(_SCHEMA)
    c.executemany("INSERT INTO messages VALUES (?,?,?,?)", righe)
    c.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
    c.commit()
    c.close()


class _SettingsFinte:
    def __init__(self, d: Path) -> None:
        self.archive_db_dir = str(d)
        self.archive_db_paths: dict[str, Path] = {}
        self.archive_model_dir = str(d / "modello")


@pytest.fixture()
def db(tmp_path, monkeypatch):
    _crea(tmp_path / "claude-ai-080726.db", VECCHIO)
    _crea(tmp_path / "claude-ai-290826.db", NUOVO)
    _crea(tmp_path / "altra-fonte.db", [(f"x{i}", "resta", "2026-07-03", "uguale")
                                        for i in range(5)])
    sys.path.insert(0, str(_SERVIZIO))
    for mod in [m for m in list(sys.modules) if m == "app" or m.startswith("app.")]:
        del sys.modules[mod]
    finte = types.ModuleType("app.settings")
    finte.get_settings = lambda: _SettingsFinte(tmp_path)   # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.settings", finte)
    from app import db as modulo
    modulo.reload_registry()
    return modulo


def test_i_canarini_risultano_spariti(db):
    d = db.delta("claude-ai-080726", "claude-ai-290826")
    assert (d["spariti"], d["nuovi"], d["cambiati"], d["in_comune"]) == (3, 1, 1, 2)
    per = {g["project"]: g for g in d["progetti"]}
    assert per["bot1777"]["spariti"] == 2 and per["How to use Claude"]["spariti"] == 1
    assert per["nuova chat"]["nuovi"] == 1 and per["resta"]["cambiati"] == 1
    assert d["vecchio"]["righe"] == 5 and d["nuovo"]["righe"] == 3
    assert "nota" not in d and "parziale" not in d


def test_gli_esempi_sono_i_piu_recenti_e_hanno_lo_snippet(db):
    d = db.delta("claude-ai-080726", "claude-ai-290826", limit=2)
    assert [e["uuid"] for e in d["esempi"]["spariti"]] == ["u2", "u1"]
    assert d["esempi"]["cambiati"][0]["snippet"] == "seconda versione"
    assert len(d["progetti"]) == 2 and d["progetti_totali"] == 4


def test_il_filtro_per_progetto(db):
    d = db.delta("claude-ai-080726", "claude-ai-290826", project="bot1777")
    assert (d["spariti"], d["nuovi"], d["cambiati"]) == (2, 0, 0)
    assert d["project"] == "bot1777"


def test_uuid_instabili_lo_dice(db):
    d = db.delta("claude-ai-290826", "altra-fonte")
    assert d["in_comune"] == 0 and d["uuid_condivisi"] == 0.0
    assert "non sono stabili" in d["nota"]


def test_lo_stesso_db_due_volte_e_un_errore(db):
    with pytest.raises(ValueError):
        db.delta("claude-ai-290826", "claude-ai-290826")


def test_un_db_che_non_c_e(db):
    with pytest.raises(KeyError):
        db.delta("claude-ai-080726", "manca")


def test_a_budget_finito_e_parziale(db, monkeypatch):
    monkeypatch.setattr(db, "BUDGET_S", 0.0)
    monkeypatch.setattr(db, "_PASSI_HANDLER", 1)
    d = db.delta("claude-ai-080726", "claude-ai-290826")
    assert d["parziale"] is True and "Budget" in d["nota"]
