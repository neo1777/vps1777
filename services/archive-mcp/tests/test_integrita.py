"""Il journal caldo si vede, e l'errore dice la cosa giusta.

🔓 Round-16, rilievo `bd02ca6f` (audio B, lente «cosa NON è coperto da niente»):
   il gateway monta `archive-data` in `:rw`, questo servizio in `:ro`. Se il
   gateway muore a metà scrittura resta un journal caldo, e **da qui nessuno può
   ripararlo** — il kernel vieta la scrittura. `H46` traccia la convivenza dei
   due mount e dichiara che il `:rw` è funzionale: non copre il caso CRASH.

⚠️ IL TEST CHE CONTA È QUELLO DI POLARITÀ (`test_senza_guardia_...`): dimostra
   che SENZA la guardia SQLite dà «attempt to write a readonly database» — un
   errore VERO che parla del PERMESSO e manda a cercare nei mount, che sono
   giusti. *Un test che verifica solo il caso sano non distingue una guardia che
   funziona da una che non c'è.*
"""
from __future__ import annotations

import sqlite3
import sys
import types
from pathlib import Path

import pytest

# ⚠️ LA CI ESEGUE QUESTA SUITE CON `uvx pytest` — cioè STDLIB-ONLY, e il nome
#   dello step lo dice: «Test archive-mcp FTS (stdlib-only)» (ci.yml:156).
#   `app.db` importa `app.settings`, che importa pydantic: importarlo qui
#   farebbe fallire la RACCOLTA, non il test. **È il difetto che la voce
#   `39b5a89d` descrive** — un test che tira una dipendenza assente non dà
#   rosso sul merito: sparisce o rompe il job per un'altra ragione.
#   ⇒ stubbo `app.settings` PRIMA dell'import. Il codice sotto test resta quello
#     vero: lo stub copre solo ciò che `db.py` non usa in queste funzioni.
if "pydantic" not in sys.modules:
    try:
        import pydantic  # noqa: F401
    except ModuleNotFoundError:
        _fake = types.ModuleType("app.settings")
        # solo ciò che `db.py` legge all'import: registry vuota, nessun percorso.
        _fake.get_settings = lambda: types.SimpleNamespace(   # type: ignore[attr-defined]
            archive_db_dir="", archive_db_paths={})
        sys.modules.setdefault("app.settings", _fake)

from app import db as dbmod  # noqa: E402


def _crea_db(tmp_path: Path, nome: str = "archivio.db") -> Path:
    p = tmp_path / nome
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE messages (uuid TEXT, ts TEXT, text TEXT)")
    conn.execute("INSERT INTO messages VALUES ('u1', '2026-08-03', 'ciao')")
    conn.commit()
    conn.close()
    return p


def _registra(monkeypatch, percorso: Path, nome: str = "arch") -> None:
    monkeypatch.setattr(dbmod, "_DBS", {nome: percorso})
    monkeypatch.setattr(dbmod, "_maybe_reload", lambda: None)


def test_db_sano_si_apre_e_risulta_ok(tmp_path, monkeypatch):
    p = _crea_db(tmp_path)
    _registra(monkeypatch, p)
    conn = dbmod._open("arch")          # non deve sollevare
    assert conn.execute("SELECT count(*) FROM messages").fetchone()[0] == 1
    conn.close()
    assert dbmod.integrita("arch")["arch"]["esito"] == "ok"


def test_journal_caldo_blocca_la_lettura_con_un_errore_che_dice_la_causa(tmp_path, monkeypatch):
    p = _crea_db(tmp_path)
    (tmp_path / (p.name + "-journal")).write_bytes(b"\xd9\xd5\x05\xf9 journal non vuoto")
    _registra(monkeypatch, p)

    with pytest.raises(dbmod.ArchivioSporco) as exc:
        dbmod._open("arch")

    testo = str(exc.value)
    # il messaggio deve mandare nel posto GIUSTO, non sui permessi
    assert "journal caldo" in testo
    assert "NON è un problema di permessi" in testo
    assert "dal lato che scrive" in testo
    assert dbmod.integrita("arch")["arch"]["esito"] == "sporco"


def test_journal_VUOTO_non_e_un_journal_caldo(tmp_path, monkeypatch):
    """Un `-journal` di zero byte è residuo normale, non una scrittura interrotta.

    Senza questa riga la guardia sarebbe un allarme che scatta sempre — e un
    allarme che scatta sempre è spento.
    """
    p = _crea_db(tmp_path)
    (tmp_path / (p.name + "-journal")).write_bytes(b"")
    _registra(monkeypatch, p)
    dbmod._open("arch").close()          # non deve sollevare
    assert dbmod.integrita("arch")["arch"]["esito"] == "ok"


def test_senza_guardia_sqlite_da_un_errore_che_manda_sui_PERMESSI(tmp_path):
    """POLARITÀ — cosa succedeva PRIMA di questa cura, misurato e non ricordato.

    Riproduce l'apertura in `mode=ro` di un DB con journal caldo SENZA passare da
    `_open`: SQLite fallisce, ma il testo parla di «readonly database». Chi lo
    legge va a controllare i mount, li trova giusti, e non pensa a un archivio
    interrotto.
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
        "Se questo cambia, la ragione della guardia va riscritta, non il test."
    )
    # e la parola che servirebbe non c'è: è tutto il punto
    assert "journal" not in testo
