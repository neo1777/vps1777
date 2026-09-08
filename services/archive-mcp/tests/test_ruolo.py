"""Il `ruolo` di un archivio è un CAMPO leggibile da una macchina (#278, cura A).

Il problema che cura, misurato il 07/09/2026: 22 DB caricati, e la scelta di quale
interrogare viveva SOLO dentro la `description` — prosa italiana con dentro
«★ PRIMARIO del versante claude.ai» e «⚠️ SUPERATO COME PRIMARIO — usare quello».
Un umano la legge, un client che deve *scegliere* no. È la stessa classe del
«Chiude #N» in italiano che non chiude una issue: una regola scritta per un lettore
che non sa leggerla riesce a metà, e in silenzio.

🔑 Il test che conta di più qui è quello sul DEFAULT. Le due scorciatoie erano:
   · `""` — sparisce da un rendering e da un `if`, e «vuoto» si legge come
     «trascurabile»;
   · dedurlo dal nome o dalla data — cioè spacciare un'ipotesi per un dato, che è
     esattamente il difetto denunciato dalla issue, riscritto in codice.
   `non dichiarato` è l'unica risposta onesta: dice che nessuno si è pronunciato,
   e non appartiene a `RUOLI`, quindi nessun filtro `ruolo in RUOLI` lo scambia mai
   per una dichiarazione.

STDLIB-ONLY (stesso patto di test_db_conn.py): la CI esegue questa cartella con
`uvx pytest`, che porta pytest e basta — `app.settings` importa pydantic e lì non
c'è. Si stubba ciò che manca e si gira davvero, MAI un `importorskip`: lì
resterebbe verde senza aver eseguito niente.
"""
from __future__ import annotations

import sqlite3
import sys
import types
from pathlib import Path

import pytest

_SCHEMA = """
CREATE TABLE messages(uuid TEXT PRIMARY KEY, project, ts, content);
CREATE VIRTUAL TABLE messages_fts USING fts5(
    uuid, project, ts, content, content='messages', content_rowid='rowid');
"""


def _crea_db(percorso: Path, *, meta: dict[str, str] | None = None) -> None:
    """Un archivio minimo. `meta=None` = DB **senza la tabella meta**, cioè il caso
    dei DB nati prima della feature: è il caso che il default deve reggere."""
    conn = sqlite3.connect(percorso)
    conn.executescript(_SCHEMA)
    conn.execute("INSERT INTO messages(uuid, project, ts, content) VALUES (?,?,?,?)",
                 ("u1", "chatA", "2026-01-01T10:00:00Z", "parliamo di flutter"))
    conn.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
    if meta is not None:
        conn.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
        for k, v in meta.items():
            conn.execute("INSERT INTO meta(key, value) VALUES (?,?)", (k, v))
    conn.commit()
    conn.close()


class _SettingsFinte:
    def __init__(self, dir_db: Path) -> None:
        self.archive_db_dir = str(dir_db)
        self.archive_db_paths: dict[str, Path] = {}


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """Tre DB: uno senza `meta`, uno con un ruolo dichiarato, uno con `meta` ma
    senza la chiave `ruolo`. Sono le TRE strade che portano al default, e vanno
    percorse tutte: una sola coprirebbe un caso e lascerebbe credere di coprirli."""
    _crea_db(tmp_path / "senza-meta.db")
    _crea_db(tmp_path / "dichiarato.db", meta={"ruolo": "primario", "description": "x"})
    _crea_db(tmp_path / "meta-senza-ruolo.db", meta={"description": "solo prosa"})
    monkeypatch.setenv("ARCHIVE_DB_DIR", str(tmp_path))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    for mod in [m for m in list(sys.modules) if m == "app" or m.startswith("app.")]:
        del sys.modules[mod]
    finte = types.ModuleType("app.settings")
    finte.get_settings = lambda: _SettingsFinte(tmp_path)   # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.settings", finte)
    from app import db as modulo
    modulo.reload_registry()
    yield modulo, tmp_path


def _scheda(modulo, nome: str) -> dict:
    for d in modulo.describe():
        if d["name"] == nome:
            return d
    raise AssertionError(f"DB '{nome}' assente dalla describe()")


# ── il DEFAULT ────────────────────────────────────────────────────────────────

def test_un_db_senza_ruolo_risulta_non_dichiarato_e_non_invisibile(db):
    """Le tre strade per non avere un ruolo danno la STESSA risposta, e nessuna
    delle tre fa sparire il DB dalla scheda."""
    modulo, _ = db
    for nome in ("senza-meta", "meta-senza-ruolo"):
        assert _scheda(modulo, nome)["ruolo"] == modulo.RUOLO_NON_DICHIARATO
    assert {d["name"] for d in modulo.describe()} == {
        "senza-meta", "dichiarato", "meta-senza-ruolo"}, \
        "un DB senza ruolo non deve uscire dall'elenco"


def test_il_default_non_e_una_delle_parole_del_vocabolario(db):
    """La proprietà su cui si appoggia chiunque filtri.

    Se `non dichiarato` finisse dentro `RUOLI`, un filtro `ruolo in RUOLI`
    tratterebbe l'assenza di dichiarazione come una dichiarazione — e sarebbe un
    difetto MUTO: il numero uscirebbe plausibile, mai un errore.
    """
    modulo, _ = db
    assert modulo.RUOLO_NON_DICHIARATO not in modulo.RUOLI


def test_il_ruolo_dichiarato_esce_verbatim(db):
    modulo, _ = db
    assert _scheda(modulo, "dichiarato")["ruolo"] == "primario"


# ── il vocabolario ────────────────────────────────────────────────────────────

def test_il_vocabolario_copre_i_db_veri_dell_archivio(db):
    """I quattro valori NON sono una tassonomia astratta: sono le quattro classi
    che si leggono nelle description dei 22 DB in essere (misurato il 07/09/2026).
    Se un giorno se ne aggiunge una, questo test è il posto dove dirlo."""
    modulo, _ = db
    assert modulo.RUOLI == ("primario", "fotografia", "riscontro", "riservato")


@pytest.mark.parametrize("valore", ["primario", "FOTOGRAFIA", " riscontro ", "riservato"])
def test_normalizza_accetta_il_vocabolario_a_prescindere_da_spazi_e_maiuscole(db, valore):
    modulo, _ = db
    assert modulo.normalizza_ruolo(valore) == valore.strip().lower()


def test_la_stringa_vuota_ritira_la_dichiarazione(db):
    """Un ruolo sbagliato dev'essere DISFACIBILE senza inventare un quinto valore
    per dire «non lo so più» — e senza cancellare il DB per ripulirlo."""
    modulo, _ = db
    assert modulo.normalizza_ruolo("") == ""
    assert modulo.normalizza_ruolo("   ") == ""


def test_un_valore_fuori_vocabolario_e_un_errore_parlante(db):
    """Non un silenzio, e nemmeno un `ValueError` nudo: chi sbaglia deve ricevere
    l'elenco. Un vocabolario chiuso che non dice quali sono le parole costringe
    a leggere il sorgente, e chi non lo legge indovina."""
    modulo, _ = db
    with pytest.raises(ValueError) as ex:
        modulo.normalizza_ruolo("principale")
    for parola in modulo.RUOLI:
        assert parola in str(ex.value), f"il rifiuto non nomina '{parola}'"


def test_set_ruolo_rifiuta_PRIMA_di_toccare_la_rete(db, monkeypatch):
    """La validazione locale non è una cortesia: è ciò che impedisce a un valore
    sbagliato di diventare una richiesta HTTP e un audit nel gateway. La rete si
    rende esplosiva, così il test misura che non ci si arriva."""
    modulo, _ = db

    def _vietato(*_a, **_k):
        raise AssertionError("set_ruolo ha chiamato il gateway con un valore non valido")

    monkeypatch.setattr(modulo, "_scrivi_via_gateway", _vietato)
    with pytest.raises(ValueError):
        modulo.set_ruolo("dichiarato", "primarissimo")


# ── additività: la promessa della cura A ──────────────────────────────────────

def test_la_scheda_conserva_i_campi_di_prima(db):
    """ADDITIVO vuol dire questo, e va misurato: chi legge la scheda di prima la
    ritrova intera. Un campo nuovo che si mangia un campo vecchio non è additivo,
    è una rottura con l'aria di un'aggiunta."""
    modulo, _ = db
    scheda = _scheda(modulo, "dichiarato")
    for campo in ("name", "rows", "oldest", "newest", "labels", "snapshot", "description"):
        assert campo in scheda, f"la scheda ha perso '{campo}'"
