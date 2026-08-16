"""Le connessioni di `db._open()` sono PERSISTENTI, per-thread, e si invalidano.

🔴 PERCHÉ ESISTE, per intero, perché serve a chi lo vedrà fallire.

`db.py` apriva una connessione SQLite a ogni chiamata di ogni tool, e una per ogni DB
dentro il loop `for name in _targets(db)`: nove punti, N aperture per richiesta. Su un DB
in chiaro era una spesa trascurabile — 0,265 ms — e infatti nessuno l'aveva mai toccata.

⭐ **Diventa decisiva nel momento in cui il DB si cifra**, che è la strada scelta in
`docs/CIFRATURA-ARCHIVIO.md`: con SQLCipher l'apertura paga PBKDF2 a 256.000 iterazioni,
misurato **229 ms**, e con 5 DB una singola `search` spenderebbe **1,15 s di sola
derivazione chiave**. La stessa cache che in chiaro vale 7,7x lì vale **3227x**.

🔑 Il test che conta è ①: non «la cache esiste» ma **«quante volte si apre davvero»**.
Gli altri quattro esistono perché una cache di connessioni ha esattamente quattro modi di
essere sbagliata, e tutti e quattro danno risposte plausibili invece di errori:

    ② un `close()` di un chiamante la ucciderebbe per tutti gli altri
    ③ un thread diverso la userebbe e SQLite alzerebbe ProgrammingError
    ④ un DB rigenerato lascerebbe la connessione sul vecchio inode — **dati vecchi,
       nessun errore**: la peggiore delle risposte, fresca all'aspetto
    ⑤ il presidio `journal_caldo` potrebbe sparire insieme all'apertura che lo ospitava

⚠️ Il ⑤ è quello che vale la pena rileggere fra sei mesi: *quando si cachea l'oggetto che
portava un controllo, il controllo se ne va con lui senza che nessun test rosseggi.*

🔬 **DUE FAMIGLIE, e non vanno contate insieme.** Ho eseguito questi sei anche sul `db.py`
di `main`, quello SENZA la cura:

    sul codice curato      6 passati
    sul codice NON curato  ① e ② ROSSI  ·  ③④⑤⑥ verdi

⇒ **solo ① e ② provano la cura**; ③④⑤⑥ passano anche senza, perché senza cache ogni
chiamata riapre e quei quattro guai non possono esistere. Non sono inutili — sono
**guardie di non-regressione**: diventeranno rossi il giorno in cui qualcuno tocca la
cache, che è quando servono. *Ma «sei test provano la persistenza» sarebbe falso, e
sarebbe il genere di falso che nessuno va a controllare perché il verde è pieno.*
"""
from __future__ import annotations

import sqlite3
import sys
import threading
from pathlib import Path

import pytest

_SCHEMA = """
CREATE TABLE messages(uuid TEXT PRIMARY KEY, project, ts, content);
CREATE VIRTUAL TABLE messages_fts USING fts5(
    uuid, project, ts, content, content='messages', content_rowid='rowid');
"""


def _crea_db(percorso: Path, testo: str = "parliamo di flutter") -> None:
    conn = sqlite3.connect(percorso)
    conn.executescript(_SCHEMA)
    conn.execute("INSERT INTO messages(uuid, project, ts, content) VALUES (?,?,?,?)",
                 ("u1", "chatA", "2026-01-01T10:00:00Z", testo))
    conn.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
    conn.commit()
    conn.close()


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """Il modulo `db` con due DB veri, importato DOPO che la dir è impostata."""
    for nome in ("uno", "due"):
        _crea_db(tmp_path / f"{nome}.db")
    monkeypatch.setenv("ARCHIVE_DB_DIR", str(tmp_path))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    # 🔴 ANCHE il package `app`, non solo `app.*` — e questa riga è costata un falso rosso
    #   che sembrava una scoperta. Cancellando i soli sottomoduli, `from app import db`
    #   ritrova l'ATTRIBUTO `db` già appeso al package dal test precedente: il modulo
    #   vecchio, con la sua registry su una tmp_path morta e la cache piena. I test 4 e 5
    #   passavano da soli e fallivano insieme.
    # ⚠️ Il punto da ricordare non è la riga: è che il messaggio d'errore che avevo scritto
    #   («la connessione è rimasta sul file cancellato, risponde con l'archivio di prima»)
    #   descriveva **esattamente** il difetto che il test cerca — quindi il falso rosso
    #   arrivava già spiegato, e la spiegazione era sbagliata. *Un rosso che conferma la
    #   tua ipotesi va isolato prima di essere creduto: `pytest <file>::<un-test-solo>`.*
    for mod in [m for m in list(sys.modules) if m == "app" or m.startswith("app.")]:
        del sys.modules[mod]
    from app import db as modulo
    from app.settings import get_settings
    get_settings.cache_clear()          # le settings sono in lru_cache
    modulo.reload_registry()
    assert modulo.available_dbs() == ["due", "uno"], "la fixture non ha caricato i DB"
    yield modulo, tmp_path


def _conta_aperture(monkeypatch) -> dict:
    """Spia su `sqlite3.connect`: l'unico modo di sapere se la cache MORDE davvero.

    🔑 Contare le aperture e non «c'è un attributo cache» è la differenza fra provare
    l'effetto e provare la forma. *Un test che verifica l'esistenza della cache resta
    verde anche se ogni chiamata la ignora.*
    """
    n = {"aperture": 0}
    originale = sqlite3.connect

    def spia(*a, **k):
        n["aperture"] += 1
        return originale(*a, **k)

    monkeypatch.setattr(sqlite3, "connect", spia)
    return n


def test_1_riusa_invece_di_riaprire(db, monkeypatch):
    """① 50 ricerche su 2 DB: 2 aperture, non 100."""
    modulo, _ = db
    n = _conta_aperture(monkeypatch)
    for _ in range(50):
        modulo.search("flutter")
    assert n["aperture"] == 2, (
        f"{n['aperture']} aperture per 50 search × 2 DB: la cache non morde. "
        "Senza cura ne farebbe 100 — se questo numero risale, il costo della "
        "cifratura torna a moltiplicarsi per ogni richiesta.")


def test_2_close_di_un_chiamante_non_uccide(db):
    """② i nove `finally: conn.close()` restano scritti e devono essere innocui."""
    modulo, _ = db
    prima = modulo._open("uno")
    prima.close()                        # esattamente ciò che fanno i nove chiamanti
    dopo = modulo._open("uno")
    assert prima is dopo, "close() ha buttato via la connessione: la cache è inutile"
    assert dopo.execute("select 1").fetchone() is not None, "connessione morta dopo close()"


def test_3_ogni_thread_ha_la_sua(db):
    """③ SQLite rifiuta l'uso cross-thread: i 13 tool sync girano sul pool di FastMCP."""
    modulo, _ = db
    mia = modulo._open("uno")
    esito: dict = {}

    def in_un_altro_thread():
        try:
            sua = modulo._open("uno")
            esito["riga"] = sua.execute("select 1").fetchone()
            esito["distinta"] = sua is not mia
        except Exception as exc:                       # noqa: BLE001 — è il punto del test
            esito["errore"] = f"{type(exc).__name__}: {exc}"

    t = threading.Thread(target=in_un_altro_thread)
    t.start()
    t.join()
    assert "errore" not in esito, (
        f"un altro thread non riesce a usare _open(): {esito.get('errore')} — "
        "una cache GLOBALE darebbe esattamente questo, alla seconda richiesta HTTP")
    assert esito["distinta"], "i due thread condividono la connessione: ProgrammingError in agguato"


def test_4_un_db_rigenerato_non_serve_dati_vecchi(db, monkeypatch):
    """④ il caso muto: file nuovo, connessione vecchia, risposta plausibile e stantia."""
    modulo, dir_db = db
    prima = modulo._open("uno")
    assert modulo.search("flutter", db="uno"), "la fixture non trova il testo iniziale"

    (dir_db / "uno.db").unlink()                      # rigenerazione: inode NUOVO
    _crea_db(dir_db / "uno.db", "adesso parliamo di rust")

    righe = modulo.search("rust", db="uno")
    assert righe, (
        "la ricerca non vede il contenuto nuovo: la connessione è rimasta sul file "
        "cancellato e sta rispondendo con l'archivio di prima, senza alcun errore")
    assert modulo._open("uno") is not prima, "la firma della dir non ha invalidato la cache"


def test_5_il_presidio_journal_caldo_sopravvive_alla_cache(db):
    """⑤ il controllo che viveva nell'apertura non deve sparire col riuso."""
    modulo, dir_db = db
    modulo._open("uno")                               # ora è in cache
    # 🔑 con dei BYTE dentro: `journal_caldo` chiede «esiste **e non è vuoto**», e un wal
    #   da zero byte è il caso normale di un DB chiuso bene. Prima scrivevo un file vuoto
    #   e il test dava rosso accusando il presidio — *un test sbagliato che incolpa il
    #   codice giusto è il modo più veloce per «curare» qualcosa che funzionava.*
    (dir_db / "uno.db-wal").write_bytes(b"\x00" * 32)
    with pytest.raises(modulo.ArchivioSporco):
        modulo._open("uno")


def test_6_integrita_apre_ancora_per_conto_suo(db):
    """⑥ `verifica()` NON deve passare dalla cache: quick_check vuole il file vero."""
    modulo, _ = db
    from app import integrita
    esiti = integrita.verifica(modulo._DBS)
    assert esiti and all(e["esito"] == "ok" for e in esiti.values()), (
        f"quick_check non passa più: {esiti} — se `verifica()` fosse stata agganciata "
        "alla cache leggerebbe una connessione tenuta aperta invece del file su disco")
