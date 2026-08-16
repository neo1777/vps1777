"""Il journal caldo si vede, e l'errore dice la causa giusta.

🔓 Round-16, rilievo `bd02ca6f` (audio B, lente «cosa NON è coperto da niente»):
   il gateway monta `archive-data` in `:rw`, archive-mcp in `:ro`. Se il gateway
   muore a metà scrittura resta un journal caldo, e **da qui nessuno può
   ripararlo** — il kernel vieta la scrittura. `H46` traccia la convivenza dei
   due mount e dichiara che il `:rw` è funzionale: non copre il caso CRASH.

⚠️ IL TEST CHE CONTA È QUELLO DI POLARITÀ (in fondo): dimostra che SENZA la
   guardia SQLite dà «attempt to write a readonly database» — un errore VERO che
   parla del PERMESSO e manda a cercare nei mount, che sono giusti. *Un test che
   verifica solo il caso sano non distingue una guardia che funziona da una che
   non c'è.*
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

# ⚠️ STDLIB-ONLY, la stessa forma di `test_fts.py:13`. La CI esegue questa suite
#   con `uvx pytest` (ci.yml:156, e il nome dello step lo dice): importare
#   `app.db` tirerebbe pydantic e romperebbe la RACCOLTA — non questo test, il
#   JOB, insieme agli altri 46. *Misurato: run 30806066015, exit 2.*
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import integrita  # noqa: E402


def _crea_db(tmp_path: Path, nome: str = "archivio.db") -> Path:
    p = tmp_path / nome
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE messages (uuid TEXT, ts TEXT, text TEXT)")
    conn.execute("INSERT INTO messages VALUES ('u1', '2026-08-03', 'ciao')")
    conn.commit()
    conn.close()
    return p


def test_db_sano_risulta_ok(tmp_path):
    p = _crea_db(tmp_path)
    assert integrita.journal_caldo(p) is None
    assert integrita.verifica({"arch": p})["arch"]["esito"] == "ok"


def test_journal_caldo_si_vede(tmp_path):
    p = _crea_db(tmp_path)
    (tmp_path / (p.name + "-journal")).write_bytes(b"\xd9\xd5\x05\xf9 journal non vuoto")

    j = integrita.journal_caldo(p)
    assert j is not None and j.name.endswith("-journal")
    assert integrita.verifica({"arch": p})["arch"]["esito"] == "sporco"


def test_il_messaggio_manda_nel_posto_GIUSTO_non_sui_permessi(tmp_path):
    """Il testo dell'errore è la metà della cura: senza, si va a guardare i mount."""
    p = _crea_db(tmp_path)
    j = tmp_path / (p.name + "-journal")
    j.write_bytes(b"x")
    testo = integrita.messaggio_sporco("arch", j)

    assert "journal caldo" in testo
    assert "NON è un problema di permessi" in testo
    assert "dal lato che SCRIVE" in testo
    # e NON deve suggerire di guardare i permessi come causa
    assert "readonly" not in testo.lower()


def test_journal_VUOTO_non_e_un_journal_caldo(tmp_path):
    """Un `-journal` di zero byte è residuo normale, non una scrittura interrotta.

    Senza questa riga la guardia sarebbe un allarme che scatta sempre — e un
    allarme che scatta sempre è spento.
    """
    p = _crea_db(tmp_path)
    (tmp_path / (p.name + "-journal")).write_bytes(b"")
    assert integrita.journal_caldo(p) is None
    assert integrita.verifica({"arch": p})["arch"]["esito"] == "ok"


def test_db_corrotto_risulta_corrotto(tmp_path):
    """`verifica()` sa dire di no anche senza journal: controprova su quick_check."""
    p = _crea_db(tmp_path)
    dati = bytearray(p.read_bytes())
    # la pagina 1 dopo l'header di 100 byte contiene lo schema: sfasciare lì è
    # un danno che `quick_check` DEVE vedere. (Il primo tentativo colpiva i byte
    # 2000-2400 — spazio libero su un DB piccolo: `quick_check` diceva «ok», e
    # il test sarebbe stato verde per la ragione sbagliata.)
    dati[100:600] = b"\xff" * 500
    p.write_bytes(bytes(dati))
    assert integrita.verifica({"arch": p})["arch"]["esito"] in ("corrotto", "non_misurabile")


def test_POLARITA_senza_guardia_sqlite_manda_sui_PERMESSI(tmp_path):
    """Cosa succedeva PRIMA di questa cura — misurato, non ricordato.

    Apre in `mode=ro` un DB con journal caldo SENZA passare dalla guardia:
    SQLite fallisce, ma il testo parla di «readonly database». Chi lo legge va a
    controllare i mount, li trova giusti, e non pensa a un archivio interrotto.
    """
    p = _crea_db(tmp_path)
    (tmp_path / (p.name + "-journal")).write_bytes(b"\xd9\xd5\x05\xf9 journal non vuoto")

    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        with pytest.raises(sqlite3.OperationalError) as exc:
            conn.execute("SELECT count(*) FROM messages").fetchone()
    finally:
        conn.close()

    testo = str(exc.value).lower()
    assert "readonly" in testo or "read-only" in testo, (
        f"atteso un errore sui permessi, ottenuto: {exc.value!r}. "
        "Se questo cambia, va riscritta la RAGIONE della guardia, non il test."
    )
    assert "journal" not in testo      # la parola che servirebbe non c'è: è il punto
