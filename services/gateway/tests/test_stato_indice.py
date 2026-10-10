"""P13 (11/10/2026): /admin/archive dice, per ogni DB, com'è il suo indice per senso.

Prima la pagina non lo diceva: un DB senza indice, o cresciuto dopo l'ultima costruzione,
spariva in silenzio dalla ricerca per senso (il perimetro dichiarato lo dice solo a chi
chiama search_ibrida). Il timer notturno aggiorna solo i DB che un indice LO HANNO; la prima
costruzione si fa sul PC. Qui: lo stato, i numeri e il comando giusto per ogni caso.
Stdlib-only (sqlite3 puro: le tabelle lette sono tabelle normali, non vec0).
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import archive_indexer as ai  # noqa: E402


def _db(cartella: Path, nome: str, righe: int) -> Path:
    p = cartella / f"{nome}.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE messages (uuid TEXT, content TEXT)")
    c.executemany("INSERT INTO messages VALUES (?, ?)", [(f"u{i}", "x") for i in range(righe)])
    c.commit()
    c.close()
    return p


def _indice(db: Path, fino_a_rowid: int | None, *, registro: bool = True, meta: dict | None = None) -> Path:
    v = db.with_suffix(".vec.db")
    c = sqlite3.connect(v)
    c.execute("CREATE TABLE indice_meta (chiave TEXT, valore TEXT)")
    c.executemany("INSERT INTO indice_meta VALUES (?, ?)", list((meta or {
        "generato": "2026-10-06T01:46:51Z", "messaggi": str(fino_a_rowid or 0),
        "modello_impronta": "12abb31156ffd84174466f4757f99f08"}).items()))
    if registro:
        c.execute("CREATE TABLE indice_righe (msg_rowid INTEGER, uuid TEXT, impronta TEXT, "
                  "primo_chunk INTEGER, n_chunk INTEGER)")
        c.executemany("INSERT INTO indice_righe VALUES (?, ?, '', 0, 1)",
                      [(i, f"u{i}") for i in range(1, (fino_a_rowid or 0) + 1)])
    c.commit()
    c.close()
    return v


def _invecchia(p: Path, secondi: int) -> None:
    t = p.stat().st_mtime - secondi
    os.utime(p, (t, t))


def test_senza_indice(tmp_path):
    s = ai.stato_indice(_db(tmp_path, "a", 3), cache=False)
    assert s["stato"] == "assente" and "PC" in s["cura"]


def test_allineato(tmp_path):
    db = _db(tmp_path, "a", 3)
    _invecchia(db, 100)
    _indice(db, 3)
    s = ai.stato_indice(db, cache=False)
    assert (s["stato"], s["messaggi"], s["dopo"]) == ("allineato", 3, 0)
    assert s["generato"] == "2026-10-06T01:46:51Z"


def test_da_aggiornare_conta_le_righe_arrivate_dopo(tmp_path):
    db = _db(tmp_path, "a", 5)
    v = _indice(db, 3)
    _invecchia(v, 100)
    s = ai.stato_indice(db, cache=False)
    assert s["stato"] == "da_aggiornare" and s["dopo"] == 2
    assert "vps1777 indice-notturno --db a" in s["cura"]


def test_senza_registro_va_ricostruito(tmp_path):
    db = _db(tmp_path, "vecchio", 3)
    _indice(db, 3, registro=False)
    s = ai.stato_indice(db, cache=False)
    assert s["stato"] == "senza_registro" and "ricostruito" in s["cura"]


def test_un_indice_illeggibile_non_rompe_la_pagina(tmp_path):
    db = _db(tmp_path, "a", 1)
    db.with_suffix(".vec.db").write_bytes(b"non sono sqlite")
    s = ai.stato_indice(db, cache=False)
    assert s["stato"] == "illeggibile"


def test_db_toccato_senza_righe_nuove_resta_allineato(tmp_path):
    """Misurato sulla VPS l'11/10: tre DB «da aggiornare» con 0 righe dopo. Il file era
    cambiato per una scrittura di metadati (ruolo, descrizione), non per messaggi nuovi."""
    db = _db(tmp_path, "a", 3)
    v = _indice(db, 3)
    _invecchia(v, 100)
    s = ai.stato_indice(db, cache=False)
    assert s["stato"] == "allineato" and s["dopo"] == 0
    assert "metadati" in s["nota"]
