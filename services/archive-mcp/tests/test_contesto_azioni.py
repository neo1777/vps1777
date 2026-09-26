"""`get_context` e `get_conversation` mostrano le AZIONI quando il testo è vuoto (26/09/2026).

Una riga di sole azioni — un tool_use dell'assistente, l'output di un comando — ha
`content=''` e tutto il suo contenuto in `tools`. Le due funzioni restituivano solo
`content`: la riga arrivava vuota, e chi leggeva una sessione Claude Code vedeva buchi
proprio dove la sessione LAVORAVA (misurato il 26/09 ricostruendo il 24/09 dal
connettore). Ora, se il testo è vuoto, la riga porta anche `tools`, troncato da
`max_chars` come il testo.

Stessa meccanica stdlib-only di test_ricerca_igiene.py.
"""
from __future__ import annotations

import sqlite3
import sys
import types
from pathlib import Path

import pytest

_SCHEMA_V2 = """
CREATE TABLE messages(uuid TEXT PRIMARY KEY, project, ts, content,
                      sender TEXT DEFAULT '', tools TEXT DEFAULT '',
                      parent_uuid TEXT DEFAULT '');
CREATE VIRTUAL TABLE messages_fts USING fts5(
    uuid, project, ts, content, tools, content='messages', content_rowid='rowid');
"""
_SCHEMA_V1 = """
CREATE TABLE messages(uuid TEXT PRIMARY KEY, project, ts, content);
CREATE VIRTUAL TABLE messages_fts USING fts5(
    uuid, project, ts, content, content='messages', content_rowid='rowid');
"""
_OUTPUT = "total 8\n" + ("-rw-r--r-- 1 a a 10 file\n" * 40)


def _crea(percorso: Path, v2: bool) -> None:
    conn = sqlite3.connect(percorso)
    conn.executescript(_SCHEMA_V2 if v2 else _SCHEMA_V1)
    if v2:
        conn.executemany("INSERT INTO messages VALUES (?,?,?,?,?,?,?)", [
            ("d1", "chat", "2026-01-01T10:00:00Z", "guarda la cartella", "user", "", ""),
            ("a1", "chat", "2026-01-01T10:00:01Z", "", "assistant", 'Bash {"command": "ls -la"}', ""),
            ("t1", "chat", "2026-01-01T10:00:02Z", "", "strumento", _OUTPUT, ""),
            ("a2", "chat", "2026-01-01T10:00:03Z", "ci sono 40 file", "assistant", "", ""),
        ])
    else:
        conn.execute("INSERT INTO messages VALUES (?,?,?,?)",
                     ("v1", "chat", "2026-01-01T10:00:00Z", ""))
    conn.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
    conn.commit()
    conn.close()


class _SettingsFinte:
    def __init__(self, dir_db: Path) -> None:
        self.archive_db_dir = str(dir_db)
        self.archive_db_paths: dict[str, Path] = {}


@pytest.fixture()
def db(tmp_path, monkeypatch):
    _crea(tmp_path / "nuovo.db", v2=True)
    _crea(tmp_path / "vecchio.db", v2=False)
    monkeypatch.setenv("ARCHIVE_DB_DIR", str(tmp_path))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    for mod in [m for m in list(sys.modules) if m == "app" or m.startswith("app.")]:
        del sys.modules[mod]
    finte = types.ModuleType("app.settings")
    finte.get_settings = lambda: _SettingsFinte(tmp_path)   # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.settings", finte)
    from app import db as modulo
    modulo.reload_registry()
    assert modulo.available_dbs() == ["nuovo", "vecchio"]
    yield modulo


def test_contesto_mostra_le_azioni_delle_righe_senza_testo(db) -> None:
    righe = {r["uuid"]: r for r in db.get_context("a1", "nuovo", before=1, after=2)}
    assert righe["a1"]["tools"] == 'Bash {"command": "ls -la"}'
    assert righe["t1"]["tools"] == _OUTPUT
    # controprova: la riga col testo resta com'era, senza un campo in più
    assert "tools" not in righe["d1"] and "tools" not in righe["a2"]


def test_conversazione_mostra_le_azioni(db) -> None:
    righe = {r["uuid"]: r for r in db.get_conversation("d1", "nuovo")}
    assert righe["t1"]["tools"] == _OUTPUT and "tools" not in righe["d1"]


def test_max_chars_tronca_anche_le_azioni(db) -> None:
    riga = next(r for r in db.get_context("t1", "nuovo", before=0, after=0, max_chars=40)
                if r["uuid"] == "t1")
    assert riga["tools"].startswith(_OUTPUT[:40])
    assert "‹troncato: 40 di" in riga["tools"]


def test_db_senza_colonna_tools_non_si_rompe(db) -> None:
    """Un DB v1 non ha `tools`: la riga arriva come prima, senza errore."""
    righe = db.get_context("v1", "vecchio", before=0, after=0)
    assert righe and righe[0]["content"] == "" and "tools" not in righe[0]
