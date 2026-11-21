"""Giro di revisione del 21/11/2026: un DB che non si può leggere ADESSO non ferma gli altri.

Durante un ingest (una transazione sola, minuti) accanto al DB c'è un journal non vuoto: `_open`
sollevava ArchivioSporco, i cicli sui DB prendevano solo KeyError, e ogni tool multi-DB falliva
per tutta la durata del caricamento. Stesso esito con un file `.db` che non è SQLite. Ora il DB
si salta e si dichiara; chi cerca un uuid e non lo trova riceve l'errore, non un falso «non c'è».
Più quattro difetti piccoli dello stesso giro. Stdlib.
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
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
"""


def _crea(percorso: Path) -> None:
    c = sqlite3.connect(percorso)
    c.executescript(_SCHEMA)
    c.execute("INSERT INTO messages VALUES (?, 'p', '2026-01-01', 'parliamo di memoria')",
              (f"u-{percorso.stem}",))
    c.execute("INSERT INTO messages VALUES (?, 'p', NULL, 'una riga senza data')",
              (f"senzadata-{percorso.stem}",))
    c.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
    c.execute("INSERT INTO meta VALUES ('ruolo', 'primario')")
    c.commit()
    c.close()


class _SettingsFinte:
    def __init__(self, d: Path) -> None:
        self.archive_db_dir = str(d)
        self.archive_db_paths: dict[str, Path] = {}
        self.archive_model_dir = str(d / "modello")


@pytest.fixture()
def db(tmp_path, monkeypatch):
    for nome in ("a", "b"):
        _crea(tmp_path / f"{nome}.db")
    sys.path.insert(0, str(_SERVIZIO))
    for mod in [m for m in list(sys.modules) if m == "app" or m.startswith("app.")]:
        del sys.modules[mod]
    finte = types.ModuleType("app.settings")
    finte.get_settings = lambda: _SettingsFinte(tmp_path)
    monkeypatch.setitem(sys.modules, "app.settings", finte)
    from app import db as modulo
    modulo.reload_registry()
    yield modulo, tmp_path
    for mod in [m for m in list(sys.modules) if m == "app" or m.startswith("app.")]:
        del sys.modules[mod]


def _in_scrittura(cartella: Path, nome: str, modulo=None) -> None:
    if modulo is not None:
        modulo.search("memoria")       # un giro a DB sani, come in produzione: i ruoli sono noti
    (cartella / f"{nome}.db-journal").write_bytes(b"x" * 512)      # il journal di un ingest vivo


def test_un_db_in_scrittura_non_ferma_la_ricerca_negli_altri(db):
    modulo, cartella = db
    _in_scrittura(cartella, "a", modulo)
    righe = modulo.search("memoria")
    assert [r["db"] for r in righe] == ["b"]


def test_count_lo_dichiara_fra_i_saltati(db):
    modulo, cartella = db
    _in_scrittura(cartella, "a", modulo)
    esito = modulo.count("memoria")
    assert esito["per_db"] == {"b": 1} or esito.get("per_db", {}).get("b") == 1
    assert [s["db"] for s in esito["saltati"]] == ["a"]
    assert "in scrittura" in esito["saltati"][0]["motivo"]


def test_un_uuid_nel_db_leggibile_si_trova_lo_stesso(db):
    modulo, cartella = db
    _in_scrittura(cartella, "a")
    assert modulo.get_context("u-b")[0]["db"] == "b"


def test_un_uuid_che_sta_nel_db_saltato_da_l_errore_non_un_falso_non_c_e(db):
    modulo, cartella = db
    _in_scrittura(cartella, "a", modulo)
    with pytest.raises(modulo.ArchivioSporco):
        modulo.get_context("u-a")
    esito = modulo.get_many(["u-a", "u-b"])
    assert esito["mancanti"] == ["u-a"] and [s["db"] for s in esito["saltati"]] == ["a"]


def test_l_anagrafica_non_si_azzera_se_un_db_e_in_scrittura(db, monkeypatch):
    modulo, cartella = db
    from app import redazione
    monkeypatch.setattr(redazione, "valori_noti", lambda conn: {"Nome Cognome"})
    assert modulo.valori_anagrafici() == {"Nome Cognome"}
    monkeypatch.setattr(redazione, "valori_noti", lambda conn: set())   # b non ha valori suoi
    _in_scrittura(cartella, "a")
    (cartella / "a.db").touch()                                          # la firma cambia
    assert "Nome Cognome" in modulo.valori_anagrafici()


def test_un_file_che_non_e_un_db_non_rompe_la_lettura_per_uuid(db):
    modulo, cartella = db
    (cartella / "aa_rotto.db").write_bytes(b"questo non e' sqlite" * 200)
    modulo.reload_registry()
    assert modulo.get_context("u-b")[0]["db"] == "b"
    assert modulo.get_many(["u-b"])["mancanti"] == []


def test_una_riga_senza_data_ha_il_suo_contesto(db):
    modulo, _ = db
    righe = modulo.get_context("senzadata-a", db="a")
    assert any(r["uuid"] == "senzadata-a" and r["is_match"] for r in righe)
    assert any(r["uuid"] == "u-a" for r in righe)                        # e i vicini datati


def test_un_guasto_del_db_non_diventa_errore_di_sintassi(db):
    modulo, _ = db
    from app import fts

    class _Interrotta:
        def execute(self, *a, **k):
            raise sqlite3.OperationalError("interrupted")
    with pytest.raises(sqlite3.OperationalError):
        fts.count_conn(_Interrotta(), "memoria")
    assert not issubclass(sqlite3.OperationalError, fts.FtsSyntaxError)

    class _Sbagliata:
        def execute(self, *a, **k):
            raise sqlite3.OperationalError('fts5: syntax error near "AND"')
    with pytest.raises(fts.FtsSyntaxError):
        fts.count_conn(_Sbagliata(), "memoria AND")


def test_le_virgolette_dentro_una_parola_si_raddoppiano(db):
    from app import semantica
    espr = semantica.query_fts_da_naturale('monitor 27"curvo nuovo')
    c = sqlite3.connect(":memory:")
    c.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
    c.execute("SELECT * FROM t WHERE t MATCH ?", (espr,)).fetchall()     # non solleva
    assert '27""curvo' in espr


def test_un_db_mai_letto_e_in_scrittura_non_entra_nel_perimetro_di_default(db):
    # fail-closed: se il ruolo non si è mai potuto leggere, il DB non si cerca «per caso»
    modulo, cartella = db
    _in_scrittura(cartella, "a")
    assert modulo._ruolo("a") == "riservato"
    assert [r["db"] for r in modulo.search("memoria")] == ["b"]


# ── dalle corse di revisione del 21/11 (Kimi e Claude sul codice della 0.95.2) ──

def test_i_tetti_dei_parametri_di_lettura(db):
    modulo, _ = db
    assert modulo._entro(-1, 0, 200) == 0 and modulo._entro(10**9, 0, 200) == 200
    assert modulo._entro("abc", 1, 5) == 1
    # `before=-1` diventava `LIMIT -1`: tutto il project col testo pieno
    righe = modulo.get_context("u-a", db="a", before=-1, after=-1)
    assert [r["uuid"] for r in righe] == ["u-a"]


def test_un_ruolo_gia_letto_non_si_perde_se_il_db_non_si_legge_per_un_attimo(db, monkeypatch):
    modulo, cartella = db
    c = sqlite3.connect(cartella / "a.db")
    c.execute("UPDATE meta SET value='riservato' WHERE key='ruolo'")
    c.commit()
    c.close()
    assert modulo._ruolo("a") == "riservato"

    def bloccato(conn, chiave):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(modulo.fts, "meta_value_conn", bloccato)
    (cartella / "a.db").touch()                       # lo snapshot cambia: il memo non vale più
    assert modulo._ruolo("a") == "riservato"          # e non «non dichiarato»
