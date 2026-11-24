"""L'indicizzatore ucciso a metà (`kill -9`) non rovina il DB e non lo lascia illeggibile.

22/11/2026. Non è una lettura del codice: lancia l'ingest vero in un processo, lo uccide mentre
scrive, e guarda in che stato resta il file. Quello che deve reggere:
  1. niente righe a metà: il DB torna a com'era prima del lavoro ucciso;
  2. dopo `risana` si legge di nuovo in SOLA LETTURA (è così che lo apre archive-mcp);
  3. il controllo d'integrità è verde, e l'indice di ricerca combacia con le righe;
  4. rifare il lavoro arriva in fondo senza doppioni.
E la prova sa diventare rossa: senza `risana` la lettura in sola lettura fallisce (era il
difetto), e su un DB rovinato davvero `risana` non dice «risanato».
"""
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

GATEWAY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GATEWAY))
from app import archive_indexer, ingest_worker  # noqa: E402

RIGHE_PRIMA = 40
RIGHE_GRANDE = 60_000


def _sorgente(p: Path, n: int, prefisso: str) -> Path:
    with open(p, "w", encoding="utf-8") as fh:
        for i in range(n):
            fh.write(json.dumps({
                "type": "user" if i % 2 == 0 else "assistant", "uuid": f"{prefisso}{i:06d}",
                "timestamp": "2026-01-01T00:00:00Z", "cwd": "/x/proj", "sessionId": "s1",
                "message": {"content": f"riga {prefisso} numero {i} " + "parola " * 40},
            }) + "\n")
    return p


def _leggi_ro(db: Path) -> int:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return conn.execute("SELECT count(*) FROM messages").fetchone()[0]
    finally:
        conn.close()


def _uccidi_a_meta(sorgente: Path, db: Path) -> None:
    """Lancia l'ingest e lo uccide appena il journal della scrittura esiste e il DB è cresciuto."""
    journal = db.with_name(db.name + "-journal")
    partenza = db.stat().st_size
    proc = subprocess.Popen(
        [sys.executable, "-c",
         "import sys; from app import archive_indexer as a; a.index_file(sys.argv[1], sys.argv[2], project='p')",
         str(sorgente), str(db)], cwd=GATEWAY)
    scadenza = time.monotonic() + 60
    try:
        while time.monotonic() < scadenza:
            if proc.poll() is not None:
                pytest.fail("l'ingest è finito prima di poterlo uccidere: la prova non ha misurato niente")
            if journal.is_file() and journal.stat().st_size > 0 and db.stat().st_size > partenza + 1_000_000:
                break
            time.sleep(0.002)
        else:
            pytest.fail("in 60 s l'ingest non ha cominciato a scrivere")
        os.kill(proc.pid, signal.SIGKILL)
    finally:
        proc.wait(timeout=30)
    assert proc.returncode == -signal.SIGKILL
    assert journal.is_file() and journal.stat().st_size > 0, "nessun journal dopo l'uccisione: non era a metà"


@pytest.fixture()
def ucciso(tmp_path):
    db = tmp_path / "prova.db"
    assert archive_indexer.index_file(str(_sorgente(tmp_path / "prima.jsonl", RIGHE_PRIMA, "a")), str(db)) == RIGHE_PRIMA
    grande = _sorgente(tmp_path / "grande.jsonl", RIGHE_GRANDE, "b")
    _uccidi_a_meta(grande, db)
    return tmp_path, db, grande


def test_senza_risanare_il_db_non_si_legge_in_sola_lettura(ucciso):
    """Il difetto, tenuto fermo: è il motivo per cui `risana` esiste. Se un giorno SQLite o il
    codice cambiano e questa lettura riesce da sola, il test lo dice e `risana` si ripensa."""
    _, db, _ = ucciso
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        _leggi_ro(db)


def test_dopo_risana_il_db_e_quello_di_prima_ed_e_sano(ucciso):
    cartella, db, _ = ucciso
    cura = ingest_worker.risana(str(cartella))
    assert cura == {"risanati": ["prova"], "falliti": {}}
    assert not db.with_name(db.name + "-journal").exists()
    assert _leggi_ro(db) == RIGHE_PRIMA, "devono esserci le righe di prima, e nessuna del lavoro ucciso"
    conn = sqlite3.connect(str(db))
    try:
        assert [r[0] for r in conn.execute("PRAGMA integrity_check").fetchall()] == ["ok"]
        conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('integrity-check')")  # solleva se non combacia
        assert conn.execute("SELECT count(*) FROM messages_fts").fetchone()[0] == RIGHE_PRIMA
    finally:
        conn.close()
    assert ingest_worker.risana(str(cartella)) == {"risanati": [], "falliti": {}}, "la seconda volta non c'è niente da fare"


def test_rifare_il_lavoro_ucciso_arriva_in_fondo_senza_doppioni(ucciso):
    cartella, db, grande = ucciso
    ingest_worker.risana(str(cartella))
    assert archive_indexer.index_file(str(grande), str(db)) == RIGHE_GRANDE
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        tot, distinti = conn.execute("SELECT count(*), count(DISTINCT uuid) FROM messages").fetchone()
        fts = conn.execute("SELECT count(*) FROM messages_fts").fetchone()[0]
    finally:
        conn.close()
    assert tot == distinti == fts == RIGHE_PRIMA + RIGHE_GRANDE


def test_il_lavoro_dopo_risana_da_solo_e_lo_dice(ucciso):
    """Il lavoro successivo della coda, anche su un ALTRO DB, rimette leggibile quello rimasto a metà."""
    cartella, db, _ = ucciso
    coda = ingest_worker.cartella_file(str(cartella))
    coda.mkdir(parents=True, exist_ok=True)
    jid = "20261122T000000Z-0123abcd"
    _sorgente(coda / f"{jid}.jsonl", 5, "c")
    codice, esito = ingest_worker.esegui_coda(jid, "altro", ".jsonl", db_dir=str(cartella))
    assert codice == 0 and esito["righe"] == 5
    assert esito["risanamento"] == {"risanati": ["prova"], "falliti": {}}
    assert _leggi_ro(db) == RIGHE_PRIMA


def test_un_db_rovinato_davvero_non_viene_detto_risanato(tmp_path):
    """La controprova del controllo d'integrità: se il file è rotto, `risana` lo dice."""
    db = tmp_path / "rotto.db"
    archive_indexer.index_file(str(_sorgente(tmp_path / "s.jsonl", 2000, "d")), str(db))
    dati = bytearray(db.read_bytes())
    for inizio in range(8192, len(dati) - 4096, 8192):      # pagine sporcate, intestazione salva
        dati[inizio:inizio + 4096] = b"\xff" * 4096
    db.write_bytes(bytes(dati))
    db.with_name(db.name + "-journal").write_bytes(b"\x00" * 512)   # un journal non vuoto e non valido
    cura = ingest_worker.risana(str(tmp_path))
    assert cura["risanati"] == [] and "rotto" in cura["falliti"], cura


def test_il_modo_risana_stampa_una_riga_json_ed_esce_zero_se_non_resta_niente(ucciso, monkeypatch, capsys):
    cartella, _, _ = ucciso
    monkeypatch.setattr(ingest_worker, "DB_DIR", str(cartella))
    monkeypatch.setattr(ingest_worker.risana, "__defaults__", (str(cartella),))
    assert ingest_worker.main(["risana"]) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1]) == {"risanati": ["prova"], "falliti": {}}


# ── il journal che non è «caldo» (24/11/2026, visto da Sagoma sulla prova di STA-04) ──
# Il `kill -9` caduto dopo che SQLite ha creato il journal e prima che ne abbia scritto
# l'intestazione lascia un file non vuoto che SQLite non considera da annullare.

def _db_sano(tmp_path: Path) -> Path:
    db = tmp_path / "prova.db"
    assert archive_indexer.index_file(str(_sorgente(tmp_path / "s.jsonl", RIGHE_PRIMA, "e")), str(db)) == RIGHE_PRIMA
    db.with_name(db.name + "-journal").write_bytes(b"\x00" * 512)
    return db


def test_un_journal_non_caldo_si_toglie_e_il_db_e_quello_di_prima(tmp_path):
    db = _db_sano(tmp_path)
    assert _leggi_ro(db) == RIGHE_PRIMA, "il lettore in sola lettura lo legge già: nessun dato perso"
    cura = ingest_worker.risana(str(tmp_path))
    assert cura == {"risanati": ["prova"], "falliti": {}}, cura
    assert not db.with_name(db.name + "-journal").exists()
    assert _leggi_ro(db) == RIGHE_PRIMA


def test_il_journal_di_un_altro_scrittore_vero_non_si_tocca(tmp_path):
    db = _db_sano(tmp_path)
    altro = sqlite3.connect(str(db), isolation_level=None)
    altro.execute("BEGIN IMMEDIATE")          # un altro processo tiene il DB in scrittura
    try:
        cura = ingest_worker.risana(str(tmp_path))
    finally:
        altro.execute("ROLLBACK")
        altro.close()
    assert cura["risanati"] == [] and "un altro processo tiene il DB" in cura["falliti"]["prova"], cura
    assert db.with_name(db.name + "-journal").exists(), "il journal di chi sta scrivendo è rimasto"
