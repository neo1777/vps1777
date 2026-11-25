"""`write_rows` scrive lo stesso DB qualunque sia la grandezza del lotto (25/11/2026, QUA-04).

Prima di spezzare `write_rows` (complessità 30) la copertura per rami diceva che le prove non
percorrevano mai un lotto PIENO a metà flusso per scarti, avvistamenti e record, né il caso in cui
la coda di una tabella è già stata svuotata quando lo stream finisce. Sono i rami che lavorano solo
sui carichi grossi, cioè quando servono. Qui lo stesso flusso misto si scrive con lotti da 1, 2 e 3
e con quello di default, e il contenuto del DB dev'essere identico, righe e ritorno compresi.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import archive_indexer as ai  # noqa: E402


def _flusso() -> list:
    return [
        ("u1", "p", "2026-01-01T00:00:00Z", "uno"),
        ai._Skip("f1", "vuoto", "d" * 10, "2026"),
        ai._Skip("f2", "rotto", "e" * 10, "2026"),
        ai._Sighting("u1", "membro-a"),
        ai._Sighting("u2", "membro-a"),
        ai._Record("sessioni", {"sessionId": "s1", "file": "a.jsonl", "titolo": "t"}),
        ai._Record("sessioni", {"sessionId": "s2", "file": "b.jsonl"}),
        ai._Record("meta", {"key": "bundle", "value": "1"}),
        ai._Record("archi", {"da": "s1", "a": "s2", "relazione": "segue"}),
        ("u2", "p", "2026-01-02T00:00:00Z", "due", "human", "", "", "", "u1"),
        ai._Skip("f3", "vuoto", "x", "2026"),
        ai._Sighting("u3", "membro-b"),
        ("u3", "p", "2026-01-03T00:00:00Z", "tre", "assistant", "", "", "", "u2", "data-export"),
    ]


def _contenuto(db: Path) -> dict:
    conn = sqlite3.connect(str(db))
    try:
        tabelle = ("messages", "skipped", "sightings", "sessioni", "archi", "meta", "revisions")
        return {t: sorted(conn.execute(f"SELECT * FROM {t}").fetchall(), key=repr) for t in tabelle}
    finally:
        conn.close()


@pytest.fixture
def ora_fissa(monkeypatch):
    monkeypatch.setattr(ai, "_now_iso", lambda: "2026-11-25T00:00:00Z")


def test_lo_stesso_flusso_con_lotti_diversi_da_lo_stesso_db(tmp_path, ora_fissa):
    atteso = None
    for lotto in (500, 1, 2, 3):
        db = tmp_path / f"lotto-{lotto}.db"
        assert ai.write_rows(db, iter(_flusso()), batch=lotto) == 3
        contenuto = _contenuto(db)
        if atteso is None:
            atteso = contenuto
            assert len(contenuto["skipped"]) == 3 and len(contenuto["sightings"]) == 3
            assert len(contenuto["sessioni"]) == 2 and len(contenuto["archi"]) == 1
        assert contenuto == atteso, f"il lotto da {lotto} scrive un DB diverso"


def test_un_secondo_ingest_a_lotti_piccoli_conserva_le_revisioni(tmp_path, ora_fissa):
    db = tmp_path / "a.db"
    ai.write_rows(db, iter([("u1", "p", "t", "prima"), ("u2", "p", "t", "uguale")]), batch=1)
    ai.write_rows(db, iter([("u1", "p", "t", "dopo"), ("u2", "p", "t", "uguale")]), batch=1)
    c = _contenuto(db)
    assert [r[0] for r in c["revisions"]] == ["u1"], "solo la riga che CAMBIA lascia una revisione"
    assert {r[0]: r[3] for r in c["messages"]} == {"u1": "dopo", "u2": "uguale"}
