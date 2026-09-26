"""Test del costruttore dell'indice vettoriale (`tools/costruisci_indice.py`).

Il modello vero (449 MB) non entra in CI: al suo posto un embedder FINTO e
deterministico — il vettore è funzione dell'hash del testo — che registra cosa
gli viene chiesto. Basta a provare ciò che qui conta: quali messaggi entrano
(perimetro), cosa viene dichiarato (`indice_meta`), e soprattutto cosa succede
quando il DB cambia sotto l'indice (rowid orfani, riassegnati, testi cambiati).

DUE FAMIGLIE, come in `test_semantica.py`:
① stdlib-only — perimetro, testo, chunking: girano ovunque, anche nello step
   `uvx pytest` della CI;
② con sqlite-vec — la costruzione vera della tabella vec0. Nello step stdlib-only
   si SALTANO dichiarandolo; girano nello step «deps del lock» di archive-mcp,
   dove sqlite-vec è quello che il server usa per leggere. Il file è elencato lì
   apposta: un test che salta ovunque sarebbe verde senza aver guardato.

Tutti i dati sono sintetici.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import costruisci_indice as ci  # noqa: E402

from app import semantica  # noqa: E402 — il sys.path lo ha messo costruisci_indice


def _ha_vec() -> bool:
    try:
        import sqlite_vec
        c = sqlite3.connect(":memory:")
        c.enable_load_extension(True)
        sqlite_vec.load(c)
        c.close()
        return True
    except Exception:                                   # noqa: BLE001
        return False


vec = pytest.mark.skipif(
    not _ha_vec(),
    reason="sqlite-vec assente (step stdlib-only): questi test girano nello step "
           "«deps del lock» di archive-mcp, dove c'è")


# ── attrezzi ─────────────────────────────────────────────────────────────────

class Finto:
    """Embedder deterministico: stesso testo → stesso vettore unitario."""

    nome = "finto/hash-384"

    def __init__(self, impronta: str = "finto-1", guasto_dopo: int | None = None):
        self.impronta = impronta
        self.visti: list[str] = []
        self.chiamate = 0
        self.guasto_dopo = guasto_dopo

    def __call__(self, testi: list[str]) -> list[bytes]:
        self.chiamate += 1
        if self.guasto_dopo is not None and self.chiamate > self.guasto_dopo:
            raise KeyboardInterrupt
        self.visti += testi
        return [vettore(t) for t in testi]


def vettore(testo: str) -> bytes:
    raw = b""
    k = 0
    while len(raw) < semantica.DIM:
        raw += hashlib.sha256(f"{k}:{testo}".encode()).digest()
        k += 1
    xs = [(b - 127.5) for b in raw[:semantica.DIM]]
    n = math.sqrt(sum(x * x for x in xs))
    return struct.pack(f"{semantica.DIM}f", *(x / n for x in xs))


FRASE = "Questo è un messaggio sintetico di prova, abbastanza lungo da entrare nell'indice"


def nuovo_db(percorso: Path, righe: list[tuple[str, str, str, str]]) -> Path:
    """righe: (uuid, project, ts, content)."""
    c = sqlite3.connect(percorso)
    c.execute("CREATE TABLE messages(uuid TEXT PRIMARY KEY, project TEXT, ts TEXT, "
              "content TEXT, sender TEXT DEFAULT '', tools TEXT DEFAULT '', "
              "thinking TEXT DEFAULT '', attachments TEXT DEFAULT '')")
    c.executemany("INSERT INTO messages(uuid, project, ts, content) VALUES (?,?,?,?)", righe)
    c.commit()
    c.close()
    return percorso


def base(tmp_path: Path) -> Path:
    return nuovo_db(tmp_path / "prova.db", [
        ("u1", "claude-code", "2026-05-02T10:00:00Z", f"{FRASE} uno"),
        ("u2", "claude-code", "2026-06-10T10:00:00Z", f"{FRASE} due"),
        ("u3", "recupero:sessione", "2026-07-01T10:00:00Z", f"{FRASE} tre"),
        ("u4", "recupero:memoria", "", f"{FRASE} quattro, senza ts"),
        ("u5", "claude-code", "2026-05-20T10:00:00Z", "corto"),
        ("u6", "recuperoX", "2026-05-21T10:00:00Z", f"{FRASE} sei"),
    ])


def rw(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(db)


def apri_indice(idx: Path) -> sqlite3.Connection:
    import sqlite_vec
    c = sqlite3.connect(f"file:{idx}?mode=ro", uri=True)
    c.enable_load_extension(True)
    sqlite_vec.load(c)
    c.enable_load_extension(False)
    return c


def msg_rowid_vettori(idx: Path) -> list[int]:
    c = apri_indice(idx)
    try:
        return sorted(r for (r,) in c.execute(
            f"SELECT msg_rowid FROM {semantica.TABELLA}"))
    finally:
        c.close()


def rowid_di(db: Path, uuid: str) -> int:
    c = sqlite3.connect(db)
    try:
        return c.execute("SELECT rowid FROM messages WHERE uuid=?", (uuid,)).fetchone()[0]
    finally:
        c.close()


# ── ① stdlib: testo, pezzi, perimetro ────────────────────────────────────────

def test_spoglia_tiene_le_stringhe_e_scarta_i_binari():
    raw = json.dumps({"input": {"q": "cerca la dashboard"}, "img": "data:image/png;base64,AAAA",
                      "png": "iVBORw0KGgo", "n": 3, "l": ["ok", "una frase vera"]})
    out = ci.spoglia(raw)
    assert "cerca la dashboard" in out and "una frase vera" in out
    assert "data:" not in out and "iVBOR" not in out
    assert "ok" not in out.split("\n"), "stringhe di 3 caratteri o meno: rumore"
    assert ci.spoglia("testo libero, non JSON") == "testo libero, non JSON"
    assert ci.spoglia(None) == "" and ci.spoglia("") == ""


def test_il_testo_include_tool_e_allegati():
    t = ci.testo_indicizzabile("contenuto", json.dumps({"a": "allegato utile"}),
                               json.dumps([{"input": "chiamata di un tool"}]))
    assert t.split("\n") == ["contenuto", "allegato utile", "chiamata di un tool"]


def test_pezzi_con_sovrapposizione_e_tetto():
    assert ci.pezzi("x" * 39) == []
    assert ci.pezzi("x" * 40) == ["x" * 40]
    t = "".join(chr(0x4E00 + i % 500) for i in range(3000))
    ps = ci.pezzi(t)
    assert [len(p) for p in ps] == [1400, 1400, 600]
    assert ps[0][1200:] == ps[1][:200], "l'overlap di 200 caratteri"
    assert len(ci.pezzi("y" * 100_000)) == ci.CHUNK_MAX


def test_il_metro_e_quello_del_server():
    """Prefissi e5 e nome della tabella vengono da `semantica`, e `knn_dedup`
    legge proprio la tabella che il costruttore scrive."""
    import inspect
    assert semantica.PREFISSO_QUERY == "query: "
    assert semantica.PREFISSO_PASSAGGIO == "passage: "
    assert inspect.signature(semantica.knn_dedup).parameters["tabella"].default \
        == semantica.TABELLA
    assert ci._parametri_metro("m", "i")["prefisso"] == semantica.PREFISSO_PASSAGGIO


def test_embedder_onnx_rimette_in_ordine_i_sotto_lotti(tmp_path, monkeypatch):
    """I sotto-lotti ordinati per lunghezza (per la RAM) non devono scambiare i
    vettori fra i testi: il vettore i-esimo è del testo i-esimo."""
    gruppi: list[list[str]] = []

    def codifica(sess, tk, testi):
        gruppi.append(list(testi))
        return [t.encode() for t in testi]

    monkeypatch.setattr(ci.semantica, "apri_modello", lambda d, thread: (None, None))
    monkeypatch.setattr(ci.semantica, "codifica", codifica)
    monkeypatch.setattr(ci, "impronta_modello", lambda d: "x")
    e = ci.EmbedderOnnx(tmp_path, sotto_lotto=3)
    testi = ["ccccc", "a", "dddddddd", "bb", "e" * 20, "f" * 4, "g" * 7]
    assert e(testi) == [t.encode() for t in testi]
    assert all(len(g) <= 3 for g in gruppi)
    piatti = [t for g in gruppi for t in g]
    assert [len(t) for t in piatti] == sorted(len(t) for t in testi)


def test_perimetro_va_dichiarato():
    with pytest.raises(ci.ErroreCostruttore, match="Perimetro non dichiarato"):
        ci.Perimetro().valida()
    with pytest.raises(ci.ErroreCostruttore, match="non si combina"):
        ci.Perimetro(tutto=True, dal="2026-05").valida()
    with pytest.raises(ci.ErroreCostruttore, match="Finestra vuota"):
        ci.Perimetro(dal="2026-07", al="2026-05").valida()
    with pytest.raises(ci.ErroreCostruttore, match="solo con --dal/--al"):
        ci.Perimetro(progetti=("x",), senza_ts="includi").valida()
    with pytest.raises(ci.ErroreCostruttore, match="--tutto"):
        ci.Perimetro(progetti=("*",)).valida()


def test_finestra_con_righe_senza_ts_obbliga_a_scegliere(tmp_path):
    """Il difetto del POC: `ts >= ? AND ts < ?` lasciava fuori le righe senza ts
    SEMPRE e senza dirlo. Qui ci si ferma e si dice quante sono."""
    src = ci.apri_sorgente(base(tmp_path))
    with pytest.raises(ci.ErroreCostruttore, match=r"1 righe SENZA ts") as e:
        ci.analizza(src, ci.Perimetro(dal="2026-05", al="2026-07"))
    assert "--senza-ts includi" in str(e.value)
    fuori = ci.analizza(src, ci.Perimetro(dal="2026-05", al="2026-07", senza_ts="escludi"))
    dentro = ci.analizza(src, ci.Perimetro(dal="2026-05", al="2026-07", senza_ts="includi"))
    uuid = lambda b: {u for u, _ in b.righe.values()}  # noqa: E731
    assert uuid(fuori) == {"u1", "u2", "u6"}
    assert uuid(dentro) == {"u1", "u2", "u6", "u4"}
    assert fuori.senza_ts == dentro.senza_ts == 1
    assert fuori.corti == 1, "u5 è nel perimetro ma troppo corto: contato, non perso"
    assert "righe senza ts: escluse (1)" in ci.Perimetro(
        dal="2026-05", al="2026-07", senza_ts="escludi").descrizione(1)


def test_etichette_project_esatte_e_per_prefisso(tmp_path):
    src = ci.apri_sorgente(base(tmp_path))
    b = ci.analizza(src, ci.Perimetro(progetti=("recupero:*",)))
    assert {u for u, _ in b.righe.values()} == {"u3", "u4"}, "recuperoX non è recupero:*"
    b = ci.analizza(src, ci.Perimetro(progetti=("recupero:*", "claude-code")))
    assert {u for u, _ in b.righe.values()} == {"u1", "u2", "u3", "u4"}
    # senza finestra, le righe senza ts entrano: nessun filtro le esclude
    assert b.senza_ts == 0


def test_prefisso_non_e_un_pattern_like(tmp_path):
    """`_` e `%` in un'etichetta sono lettere, non jolly."""
    db = nuovo_db(tmp_path / "p.db", [("a", "rec_x:1", "2026-01-01", FRASE),
                                     ("b", "recAx:1", "2026-01-01", FRASE)])
    b = ci.analizza(ci.apri_sorgente(db), ci.Perimetro(progetti=("rec_x:*",)))
    assert {u for u, _ in b.righe.values()} == {"a"}


def test_sorgente_in_sola_lettura_e_riconosciuta(tmp_path):
    db = base(tmp_path)
    src = ci.apri_sorgente(db)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        src.execute("DELETE FROM messages")
    (tmp_path / "altro.db").write_bytes(b"")
    with pytest.raises(ci.ErroreCostruttore, match="messages"):
        ci.apri_sorgente(tmp_path / "altro.db")


def test_il_nome_dell_indice_e_il_suo_contratto(tmp_path):
    db = base(tmp_path)
    with pytest.raises(ci.ErroreCostruttore, match=r"\.vec\.db"):
        ci.costruisci(db, Finto(), ci.Perimetro(tutto=True), out=tmp_path / "indice.db")
    with pytest.raises(ci.ErroreCostruttore, match="DB stesso"):
        ci.costruisci(db, Finto(), ci.Perimetro(tutto=True), out=db)


def test_cli_senza_perimetro_esce_2_e_dice_le_scelte(tmp_path, capsys):
    db = base(tmp_path)
    rc = ci.main(["--db", str(db)], fabbrica=lambda m, t: Finto())
    assert rc == 2
    err = capsys.readouterr().err
    assert "--tutto" in err and "--project" in err
    assert not (tmp_path / "prova.vec.db").exists()
    assert not (tmp_path / "prova.vec.db.parziale").exists()


# ── ② con sqlite-vec: costruzione, meta, incrementale ────────────────────────

@vec
def test_costruzione_leggibile_dal_server(tmp_path):
    """L'indice si interroga con le funzioni DEL SERVER (`knn_dedup`,
    `meta_indice`) su un DB con l'indice ATTACHato come fa `db.py`."""
    db = base(tmp_path)
    e = Finto()
    esito = ci.costruisci(db, e, ci.Perimetro(tutto=True))
    idx = semantica.percorso_indice(db)
    assert idx.is_file() and not (tmp_path / "prova.vec.db.parziale").exists()
    assert esito.modo == "ricostruzione"
    assert esito.messaggi == 5 and esito.corti == 1 and esito.vettori == 5
    assert all(t.startswith(semantica.PREFISSO_PASSAGGIO) for t in e.visti), \
        "i passaggi devono portare `passage: `: è metà del contratto e5"

    import sqlite_vec
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("ATTACH DATABASE ? AS vec", (f"file:{idx}?mode=ro",))
    bersaglio = rowid_di(db, "u2")
    q = vettore(semantica.PREFISSO_PASSAGGIO + f"{FRASE} due")
    assert semantica.knn_dedup(conn, q, topn=3)[0] == bersaglio
    m = semantica.meta_indice(conn)
    for chiave in ("modello", "dim", "tabella", "chunk", "perimetro", "db_sorgente",
                   "generato", "messaggi", "vettori", "costruttore", "modello_impronta",
                   "perimetro_json", "ultimo_passaggio"):
        assert m.get(chiave), f"indice_meta senza {chiave}"
    assert m["perimetro"] == "tutto il DB"
    assert m["messaggi"] == "5" and m["vettori"] == "5" and m["dim"] == "384"
    assert m["tabella"] == semantica.TABELLA and m["db_sorgente"] == "prova"
    assert m["stato"] == "completo" and m["modello"] == Finto.nome
    assert json.loads(m["ultimo_passaggio"])["nuovi"] == 5


@vec
def test_secondo_passaggio_senza_cambi_non_ricalcola_niente(tmp_path):
    db = base(tmp_path)
    ci.costruisci(db, Finto(), ci.Perimetro(tutto=True))
    e = Finto()
    esito = ci.costruisci(db, e)            # perimetro: quello dichiarato dall'indice
    assert esito.modo == "incrementale"
    assert esito.differenza == {"invariati": 5, "nuovi": 0, "cambiati": 0,
                                "riassegnati": 0, "orfani": 0, "usciti": 0}
    assert e.chiamate == 0 and esito.vettori == 5


@vec
def test_reingest_insert_or_replace_lascia_orfano_e_nuovo(tmp_path):
    """Il caso reale: l'indexer rimpiazza una riga con INSERT OR REPLACE → rowid
    nuovo. Il vecchio vettore deve SPARIRE (orfano), il nuovo rowid entrare."""
    db = base(tmp_path)
    ci.costruisci(db, Finto(), ci.Perimetro(tutto=True))
    vecchio = rowid_di(db, "u1")
    c = rw(db)
    c.execute("INSERT OR REPLACE INTO messages(uuid, project, ts, content) VALUES (?,?,?,?)",
              ("u1", "claude-code", "2026-05-02T10:00:00Z", f"{FRASE} uno"))
    c.commit()
    c.close()
    nuovo = rowid_di(db, "u1")
    assert nuovo != vecchio

    esito = ci.controlla(db)
    assert not esito.in_pari and esito.differenza["orfani"] == 1
    assert esito.differenza["nuovi"] == 1

    esito = ci.costruisci(db, Finto())
    assert esito.differenza["orfani"] == 1 and esito.differenza["nuovi"] == 1
    assert esito.vettori_tolti == 1 and esito.vettori_aggiunti == 1
    righe = msg_rowid_vettori(semantica.percorso_indice(db))
    assert vecchio not in righe and nuovo in righe
    assert ci.controlla(db).in_pari


@vec
def test_rowid_riusato_da_un_altro_messaggio_viene_ricalcolato(tmp_path):
    """Il caso peggiore: il rowid dell'indice ora appartiene a un ALTRO messaggio.
    Senza registro il server servirebbe il vettore di u6 per il testo di u9."""
    db = base(tmp_path)
    ci.costruisci(db, Finto(), ci.Perimetro(tutto=True))
    rid = rowid_di(db, "u6")                # è il rowid massimo: SQLite lo riusa
    c = rw(db)
    c.execute("DELETE FROM messages WHERE uuid='u6'")
    c.execute("INSERT INTO messages(uuid, project, ts, content) VALUES (?,?,?,?)",
              ("u9", "claude-code", "2026-06-01", f"{FRASE} nove, tutt'altro"))
    c.commit()
    c.close()
    assert rowid_di(db, "u9") == rid, "premessa del test: rowid riusato"
    e = Finto()
    esito = ci.costruisci(db, e)
    assert esito.differenza["riassegnati"] == 1
    assert any("nove" in t for t in e.visti), "il nuovo testo va ricalcolato"
    ic = apri_indice(semantica.percorso_indice(db))
    assert ic.execute("SELECT uuid FROM indice_righe WHERE msg_rowid=?", (rid,)).fetchone()[0] == "u9"
    ic.close()


@vec
def test_testo_cambiato_sullo_stesso_rowid(tmp_path):
    db = base(tmp_path)
    ci.costruisci(db, Finto(), ci.Perimetro(tutto=True))
    c = rw(db)
    c.execute("UPDATE messages SET tools=? WHERE uuid='u2'",
              (json.dumps({"input": "un tool-call aggiunto dopo"}),))
    c.commit()
    c.close()
    e = Finto()
    esito = ci.costruisci(db, e)
    assert esito.differenza["cambiati"] == 1 and esito.vettori == 5
    assert any("tool-call aggiunto" in t for t in e.visti)


@vec
def test_il_perimetro_cresce_e_si_restringe_a_scaglioni(tmp_path):
    db = base(tmp_path)
    ci.costruisci(db, Finto(), ci.Perimetro(dal="2026-05", al="2026-06", senza_ts="escludi"))
    esito = ci.costruisci(db, Finto(), ci.Perimetro(dal="2026-05", al="2026-08",
                                                    senza_ts="includi"))
    assert esito.differenza["invariati"] == 2 and esito.differenza["nuovi"] == 3
    assert "righe senza ts: incluse (1)" in esito.perimetro
    esito = ci.costruisci(db, Finto(), ci.Perimetro(progetti=("recupero:*",)))
    assert esito.differenza["usciti"] == 3 and esito.messaggi == 2
    assert sorted(msg_rowid_vettori(semantica.percorso_indice(db))) == sorted(
        rowid_di(db, u) for u in ("u3", "u4"))


@vec
def test_controlla_non_scrive(tmp_path):
    db = base(tmp_path)
    ci.costruisci(db, Finto(), ci.Perimetro(tutto=True))
    idx = semantica.percorso_indice(db)
    prima = idx.read_bytes()
    c = rw(db)
    c.execute("DELETE FROM messages WHERE uuid='u1'")
    c.commit()
    c.close()
    esito = ci.controlla(db)
    assert esito.differenza["orfani"] == 1 and not esito.in_pari
    assert idx.read_bytes() == prima
    assert ci.main(["--db", str(db), "--controlla"]) == 1


@vec
def test_metro_diverso_rifiuta_l_incrementale(tmp_path):
    """Vettori di due export diversi nello stesso indice: vicini insensati senza
    errori. L'impronta del modello lo impedisce."""
    db = base(tmp_path)
    ci.costruisci(db, Finto("export-a"), ci.Perimetro(tutto=True))
    with pytest.raises(ci.ErroreCostruttore, match="--ricostruisci"):
        ci.costruisci(db, Finto("export-b"))
    assert not (tmp_path / "prova.vec.db.parziale").exists()
    esito = ci.costruisci(db, Finto("export-b"), ricostruisci=True)
    assert esito.modo == "ricostruzione" and esito.perimetro == "tutto il DB"


@vec
def test_indice_del_poc_senza_registro(tmp_path):
    """Un indice come quello del POC (vec0 + meta, niente registro): l'incrementale
    rifiuta, il controllo dice solo ciò che può sapere (gli orfani) e lo dichiara."""
    import sqlite_vec
    db = base(tmp_path)
    idx = semantica.percorso_indice(db)
    c = sqlite3.connect(idx)
    c.enable_load_extension(True)
    sqlite_vec.load(c)
    c.execute(f"CREATE VIRTUAL TABLE {semantica.TABELLA} USING "
              f"vec0(embedding float[{semantica.DIM}], +msg_rowid integer)")
    c.executemany(f"INSERT INTO {semantica.TABELLA}(embedding, msg_rowid) VALUES (?,?)",
                  [(vettore(str(r)), r) for r in (1, 2, 999)])
    c.execute("CREATE TABLE indice_meta (chiave TEXT PRIMARY KEY, valore TEXT)")
    c.execute("INSERT INTO indice_meta VALUES ('perimetro', 'ts >= 2026-05 AND ts < 2026-07')")
    c.commit()
    c.close()
    with pytest.raises(ci.ErroreCostruttore, match="registro"):
        ci.costruisci(db, Finto())
    esito = ci.controlla(db, perimetro=ci.Perimetro(tutto=True))
    assert esito.differenza == {"orfani": 1} and not esito.verificabile
    assert ci.main(["--db", str(db), "--controlla", "--tutto"]) == 1


@vec
def test_interruzione_e_ripresa(tmp_path):
    """Un lotto per transazione: interrotto a metà, il `.parziale` è coerente e
    il rilancio finisce SENZA rifare ciò che era fatto. L'indice servito non
    esiste finché il lavoro non quadra."""
    righe = [(f"m{i}", "claude-code", f"2026-05-{1 + i % 28:02d}", f"{FRASE} numero {i}")
             for i in range(30)]
    db = nuovo_db(tmp_path / "grande.db", righe)
    with pytest.raises(KeyboardInterrupt):
        ci.costruisci(db, Finto(guasto_dopo=2), ci.Perimetro(tutto=True), lotto=5)
    idx = semantica.percorso_indice(db)
    assert not idx.exists() and (tmp_path / "grande.vec.db.parziale").exists()
    e = Finto()
    esito = ci.costruisci(db, e, lotto=5)
    assert esito.modo == "ripresa"
    assert esito.differenza["invariati"] == 10 and esito.differenza["nuovi"] == 20
    assert len(e.visti) == 20 and esito.vettori == 30
    assert idx.is_file() and not (tmp_path / "grande.vec.db.parziale").exists()


@vec
def test_perimetro_vuoto_non_scrive_niente(tmp_path):
    db = base(tmp_path)
    with pytest.raises(ci.ErroreCostruttore, match="Perimetro vuoto"):
        ci.costruisci(db, Finto(), ci.Perimetro(progetti=("nessuno",)))
    assert not list(tmp_path.glob("prova.vec.db*"))


@vec
def test_vettori_della_dimensione_sbagliata_sono_rifiutati(tmp_path):
    class Corto(Finto):
        def __call__(self, testi):
            return [struct.pack("8f", *([1.0] + [0.0] * 7)) for _ in testi]

    with pytest.raises(ci.ErroreCostruttore, match="dimensioni"):
        ci.costruisci(base(tmp_path), Corto(), ci.Perimetro(tutto=True))
    assert not (tmp_path / "prova.vec.db").exists()


@vec
def test_cli_json(tmp_path, capsys):
    db = base(tmp_path)
    rc = ci.main(["--db", str(db), "--project", "recupero:*", "--json"],
                 fabbrica=lambda m, t: Finto())
    assert rc == 0
    esito = json.loads(capsys.readouterr().out)
    assert esito["messaggi"] == 2 and esito["perimetro"] == "project: recupero:*"


@vec
def test_vettore_che_il_registro_non_spiega_blocca_la_pubblicazione(tmp_path):
    """La quadratura registro ↔ vec0: un vettore senza riga nel registro è un
    orfano che il server servirebbe. Non si pubblica, e il controllo lo dice."""
    import sqlite_vec
    db = base(tmp_path)
    ci.costruisci(db, Finto(), ci.Perimetro(tutto=True))
    idx = semantica.percorso_indice(db)
    c = sqlite3.connect(idx)
    c.enable_load_extension(True)
    sqlite_vec.load(c)
    c.execute(f"INSERT INTO {semantica.TABELLA}(rowid, embedding, msg_rowid) VALUES (?,?,?)",
              (10_000, vettore("intruso"), 1))
    c.commit()
    c.close()
    prima = idx.read_bytes()
    with pytest.raises(ci.ErroreCostruttore, match="non quadra"):
        ci.controlla(db)
    with pytest.raises(ci.ErroreCostruttore, match="non quadra"):
        ci.costruisci(db, Finto())
    assert idx.read_bytes() == prima, "l'indice servito non si tocca"


# ── i due grafi del modello (26/09/2026) ─────────────────────────────────────
# Il nostro export ha pooling e normalizzazione DENTRO il grafo e restituisce il
# vettore. L'ONNX ufficiale del repo del modello su Hugging Face (quello che il
# prodotto fa scaricare, `vps1777 indice-modello`) restituisce l'hidden state
# (lotto × token × 384) e chiede anche `token_type_ids`: il pooling lo fa
# `codifica`. Misurato contro l'indice del primario: coseno ≥ 0,9997.

class _Io:
    def __init__(self, name: str, shape: list) -> None:
        self.name, self.shape = name, shape


class _Tk:
    def encode_batch(self, testi):
        # due testi, il secondo più corto: il padding (mask 0) non deve entrare
        class E:
            def __init__(self, ids, mask):
                self.ids, self.attention_mask = ids, mask
        return [E([5, 6, 7], [1, 1, 1]), E([8, 9, 0], [1, 1, 0])][:len(testi)]


class _SessGrafo:
    def __init__(self, ingressi, uscita, funz):
        self._in, self._out, self._f, self.visti = ingressi, uscita, funz, None

    def get_inputs(self):
        return [_Io(n, []) for n in self._in]

    def get_outputs(self):
        return [_Io("out", self._out)]

    def run(self, _, feed):
        self.visti = feed
        return [self._f(feed)]


def test_codifica_col_grafo_che_fa_gia_il_pooling():
    np = pytest.importorskip("numpy")
    vett = np.zeros((2, 384), dtype="float32")
    vett[:, 0] = 1.0
    sess = _SessGrafo(["input_ids", "attention_mask"], ["batch", 384], lambda f: vett)
    out = semantica.codifica(sess, _Tk(), ["a", "b"])
    assert set(sess.visti) == {"input_ids", "attention_mask"}
    assert struct.unpack("384f", out[0])[0] == 1.0


def test_codifica_col_grafo_ufficiale_fa_il_pooling_e_la_norma():
    np = pytest.importorskip("numpy")
    rng = np.random.default_rng(7)
    hidden = rng.normal(size=(2, 3, 384)).astype("float32")
    sess = _SessGrafo(["input_ids", "attention_mask", "token_type_ids"],
                      ["batch", "seq", 384], lambda f: hidden)
    out = semantica.codifica(sess, _Tk(), ["a", "b"])
    assert (sess.visti["token_type_ids"] == 0).all(), "token_type_ids a zero, come il modello si aspetta"
    atteso = hidden[1, :2].mean(axis=0)                  # il padding del secondo NON entra
    atteso = atteso / np.linalg.norm(atteso)
    v = np.array(struct.unpack("384f", out[1]), dtype="float32")
    assert np.allclose(v, atteso, atol=1e-5)
    assert abs(float(np.linalg.norm(v)) - 1.0) < 1e-5
