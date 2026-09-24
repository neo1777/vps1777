"""get_session / get_stirpe — il Livello 2 del contratto `recupero/` R1 (24/09/2026).

Il DB sintetico lo produce l'INDEXER VERO del gateway (stdlib-only), da un bundle
costruito qui: così questi test provano anche il contratto fra le due parti — se
l'indexer cambia la forma delle tabelle o delle schede, è qui che si rompe, non in
produzione. Dati tutti sintetici: sid inventati, percorsi finti.

Due livelli, come il resto di questa cartella:
  · `fts.*_conn` su una connessione (logica pura);
  · `db.get_session` / `db.get_stirpe` sul multi-DB, con le settings stubbate come
    in test_db_conn.py (la CI esegue questa cartella con `uvx pytest`: pydantic non
    c'è, e un `importorskip` farebbe un verde che non esegue niente).
"""
from __future__ import annotations

import ast
import json
import shutil
import sqlite3
import sys
import types
import zipfile
from pathlib import Path

import pytest

_QUI = Path(__file__).resolve()
sys.path.insert(0, str(_QUI.parents[1] / "app"))
sys.path.insert(0, str(_QUI.parents[2] / "gateway" / "app"))
import archive_indexer  # noqa: E402
import fts  # noqa: E402

A = "0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0"     # madre, nella stirpe
B = "1a2b3c4d-5e6f-4a0b-9c8d-7e6f5a4b3c2d"     # figlia di A (clone)
C = "2c3d4e5f-6a7b-4c8d-9e0f-1a2b3c4d5e6f"     # figlia di B, MAI consegnata: solo negli archi
D = "3d4e5f6a-7b8c-4d9e-8f0a-2b3c4d5e6f7a"     # arco senza chiusura: fuori dalla stirpe
E = "0f1e2d3c-ffff-4aaa-8bbb-cccccccccccc"     # stessi primi 8 caratteri di A: l'ambiguità
S = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d"     # id della stirpe

_SESSIONI_COL = archive_indexer._TABELLE_RECORD["sessioni"]
_ARCHI_COL = archive_indexer._TABELLE_RECORD["archi"]


def _scheda(campi: dict, corpo: str) -> str:
    return "---\n" + "".join(f"{k}: {v}\n" for k, v in campi.items()) + "---\n" + corpo


def _tsv(intest: tuple, *righe: tuple) -> str:
    return "\n".join("\t".join(r) for r in (intest, *righe)) + "\n"


def _riga_sessione(sid: str, first: str, last: str, last_uuid: str, pos: str,
                   stirpe: str = S) -> tuple:
    return (sid, f"titolo {sid[:8]}", "/percorso/sintetico/progetto", first, last, last_uuid,
            f"sessions/{sid}.jsonl", "turno-chiuso", "transcript", stirpe, pos, "1", "0")


def _bundle(percorso: Path, *, last_ts_a: str = "2026-09-10T10:05:00.000Z") -> Path:
    """Un bundle con la conversazione di A, le schede di A, B, E e della stirpe, e i
    tre .tsv (archi A→B, B→C con chiusura=1, A→D senza)."""
    msg = [
        {"type": "user", "uuid": "a-u1", "timestamp": "2026-09-10T10:00:00.000Z",
         "sessionId": A, "cwd": "/percorso/sintetico/progetto",
         "message": {"role": "user", "content": "domanda di prova"}},
        {"type": "assistant", "uuid": "a-a1", "parentUuid": "a-u1",
         "timestamp": last_ts_a, "sessionId": A, "cwd": "/percorso/sintetico/progetto",
         "message": {"role": "assistant", "content": [{"type": "text", "text": "risposta"}]}},
        {"type": "ai-title", "aiTitle": "titolo della sessione A", "sessionId": A},
    ]
    membri = {
        "MANIFEST.json": json.dumps({"generated": "2026-09-24T20:00:00"}),
        f"sessions/{A}.jsonl": "\n".join(json.dumps(m) for m in msg),
        f"recupero/sessioni/{A}.md": _scheda({
            "contratto": "R1", "tipo": "sessione", "sessionId": A,
            "last_ts": last_ts_a, "last_uuid": "a-a1", "stirpe": S, "stirpe_pos": "1",
        }, "# titolo A\n\n## Stato\n\nsegno-scheda-A\n"),
        f"recupero/sessioni/{B}.md": _scheda({
            "contratto": "R1", "tipo": "sessione", "sessionId": B,
            "last_ts": "2026-09-11T09:00:00.000Z", "last_uuid": "",
        }, "# titolo B\n\nsegno-scheda-B\n"),
        f"recupero/sessioni/{E}.md": _scheda({
            "contratto": "R1", "tipo": "sessione", "sessionId": E,
            "last_ts": "2026-09-12T09:00:00.000Z", "last_uuid": "",
        }, "# titolo E\n\nsegno-scheda-E\n"),
        f"recupero/stirpi/{S}.md": _scheda({
            "contratto": "R1", "tipo": "stirpe", "id": S, "membri": f"{A},{B}", "n": "2",
        }, f"# Stirpe\n\n{A} → clone → {B}\n"),
        "recupero/sessioni.tsv": _tsv(
            _SESSIONI_COL,
            _riga_sessione(A, "2026-09-10T10:00:00.000Z", last_ts_a, "a-a1", "1"),
            _riga_sessione(B, "2026-09-11T08:00:00.000Z", "2026-09-11T09:00:00.000Z", "", "2"),
            _riga_sessione(E, "2026-09-12T08:00:00.000Z", "2026-09-12T09:00:00.000Z", "", "",
                           stirpe="")),
        "recupero/archi.tsv": _tsv(
            _ARCHI_COL,
            (A, B, "clone", "uuid-condivisi", "forte", "p1", "app", "1.0", "1", "x"),
            (B, C, "continua", "clear", "forte", "p2", "app", "0.8", "1", "x"),
            (A, D, "cita", "testo", "debole", "p3", "app", "0.1", "0", "x")),
    }
    zp = percorso.with_suffix(".zip")
    with zipfile.ZipFile(zp, "w") as z:
        for n, c in membri.items():   # data fissa: il DB non dipende dall'ora del test
            z.writestr(zipfile.ZipInfo(n, date_time=(2026, 9, 24, 12, 0, 0)), c)
    archive_indexer.index_file(str(zp), str(percorso))
    return percorso


def _vecchio(percorso: Path) -> Path:
    """Un DB nato PRIMA del contratto R1: messaggi e avvistamenti, niente tabelle
    `sessioni`/`archi` — la conversazione di A c'è, la scheda no."""
    conn = sqlite3.connect(percorso)
    conn.executescript("""
        CREATE TABLE messages(uuid TEXT PRIMARY KEY, project, ts, content,
            sender DEFAULT '', parent_uuid DEFAULT '');
        CREATE VIRTUAL TABLE messages_fts USING fts5(
            uuid, project, ts, content, content='messages', content_rowid='rowid');
        CREATE TABLE sightings(uuid, source, ingest_date, PRIMARY KEY(uuid, source));
    """)
    conn.execute("INSERT INTO messages(uuid, project, ts, content, sender) VALUES "
                 "('a-u1','progetto','2026-09-10T10:00:00.000Z','domanda di prova','user')")
    conn.execute("INSERT INTO sightings VALUES ('a-u1', ?, '')", (f"sessions/{A}.jsonl",))
    conn.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
    conn.commit()
    conn.close()
    return percorso


@pytest.fixture()
def conn(tmp_path):
    c = sqlite3.connect(_bundle(tmp_path / "nuovo.db"))
    yield c
    c.close()


# ── logica pura, su una connessione ───────────────────────────────────────────

def test_candidati_prefisso_id_intero_e_estremi_degli_archi(conn) -> None:
    assert fts.candidati_sessione_conn(conn, A[:8]) == sorted([A, E]), "prefisso ambiguo"
    assert fts.candidati_sessione_conn(conn, A) == [A], "l'id intero vince sul prefisso"
    assert fts.candidati_sessione_conn(conn, A[:10]) == [A], "un carattere in più scioglie"
    assert fts.candidati_sessione_conn(conn, C[:8]) == [C], "noto solo come estremo di un arco"
    assert fts.candidati_sessione_conn(conn, "0f1e2d3c%") == [], "% non è un jolly"


def test_sessione_porta_riga_scheda_conversazione_archi_stirpe(conn) -> None:
    s = fts.sessione_conn(conn, A)
    assert s["sessione"]["titolo"] == f"titolo {A[:8]}"
    assert s["sessione"]["last_uuid"] == "a-a1" and s["sessione"]["stirpe_pos"] == 1
    assert "segno-scheda-A" in s["scheda"]
    conv = s["conversazione"]
    assert conv["messaggi"] == 3, conv                   # due messaggi + il titolo
    assert conv["per_sender"] == {"user": 1, "assistant": 1, "title": 1}, conv
    assert (conv["primo_ts"], conv["ultimo_ts"]) == ("2026-09-10T10:00:00.000Z",
                                                     "2026-09-10T10:05:00.000Z")
    assert conv["fonti"] == [f"sessions/{A}.jsonl"]
    assert {(a["da"], a["a"]) for a in s["archi"]} == {(A, B), (A, D)}
    assert s["archi_totali"] == 2
    assert s["stirpe"]["id"] == S and A in s["stirpe"]["scheda"]
    assert s["note"] == [], s["note"]


def test_sessione_nota_solo_dagli_archi_lo_dice(conn) -> None:
    s = fts.sessione_conn(conn, C)
    assert s["sessione"] is None and s["scheda"] is None
    assert any("estremo di un arco" in n for n in s["note"]), s["note"]
    assert [(a["da"], a["a"]) for a in s["archi"]] == [(B, C)]


def test_sessione_archi_troncati_e_scheda_troncata_si_dichiarano(conn) -> None:
    s = fts.sessione_conn(conn, A, limit=1, max_chars=10)
    assert len(s["archi"]) == 1 and s["archi_totali"] == 2
    assert any("archi troncati: 1 di 2" in n for n in s["note"]), s["note"]
    assert "troncato: 10 di" in s["scheda"]


def test_stirpe_e_la_chiusura_sugli_archi_con_chiusura_1(conn) -> None:
    """Da B: A (madre) e C (figlia mai consegnata) sì, D no (arco senza chiusura).
    C resta nella stirpe senza riga in `sessioni`, e lo dice."""
    st = fts.stirpe_conn(conn, B)
    assert [m["sessionId"] for m in st["membri"]] == [A, B, C], "ordine: first_ts, poi i senza riga"
    assert st["senza_riga"] == [C]
    assert [m["in_sessioni"] for m in st["membri"]] == [True, True, False]
    assert {(a["da"], a["a"]) for a in st["archi"]} == {(A, B), (B, C)}
    assert st["stirpi_dichiarate"] == [S] and A in st["schede_stirpe"][S]
    assert any("senza riga" in n for n in st["note"]), st["note"]


def test_stirpe_troncata_e_stirpe_sola(conn) -> None:
    st = fts.stirpe_conn(conn, A, limit=2)
    assert len(st["membri"]) == 2 and any("troncata" in n for n in st["note"])
    nomi = {m["sessionId"] for m in st["membri"]}
    assert all(a["da"] in nomi and a["a"] in nomi for a in st["archi"]), \
        "un arco verso un membro rimasto fuori"
    sola = fts.stirpe_conn(conn, E)
    assert [m["sessionId"] for m in sola["membri"]] == [E]
    assert any("sola" in n for n in sola["note"]), sola["note"]


# ── multi-DB: risoluzione, scelta del DB, errori parlanti ─────────────────────

class _SettingsFinte:
    def __init__(self, dir_db: Path) -> None:
        self.archive_db_dir = str(dir_db)
        self.archive_db_paths: dict[str, Path] = {}


def _modulo_db(tmp_path: Path, monkeypatch):
    """`app.db` con la dir `tmp_path`, settings stubbate (vedi test_db_conn.py)."""
    monkeypatch.setenv("ARCHIVE_DB_DIR", str(tmp_path))
    sys.path.insert(0, str(_QUI.parents[1]))
    for mod in [m for m in list(sys.modules) if m == "app" or m.startswith("app.")]:
        del sys.modules[mod]
    finte = types.ModuleType("app.settings")
    finte.get_settings = lambda: _SettingsFinte(tmp_path)   # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.settings", finte)
    from app import db as modulo
    modulo.reload_registry()
    return modulo


@pytest.fixture()
def db(tmp_path, monkeypatch):
    _bundle(tmp_path / "nuovo.db")
    _vecchio(tmp_path / "vecchio.db")
    for z in tmp_path.glob("*.zip"):
        z.unlink()
    modulo = _modulo_db(tmp_path, monkeypatch)
    assert modulo.available_dbs() == ["nuovo", "vecchio"]
    return modulo, tmp_path


def test_get_session_risolve_il_prefisso_e_porta_db_e_snapshot(db) -> None:
    modulo, _ = db
    s = modulo.get_session(B[:8])
    assert s["sessionId"] == B and s["db"] == "nuovo" and s["snapshot"]
    assert "segno-scheda-B" in s["scheda"]
    assert "anche_in" not in s


def test_prefisso_ambiguo_elenca_i_candidati(db) -> None:
    modulo, _ = db
    with pytest.raises(modulo.SessioneNonRisolta) as exc:
        modulo.get_session(A[:8])
    msg = str(exc.value)
    assert "ambiguo" in msg and A in msg and E in msg and "(nuovo)" in msg, msg


def test_troppo_corto_e_errore_parlante(db) -> None:
    modulo, _ = db
    with pytest.raises(modulo.SessioneNonRisolta, match="almeno 8 caratteri"):
        modulo.get_session(A[:5])


def test_db_vecchio_dice_che_e_nato_prima_del_contratto_e_dove_sta_la_chat(db) -> None:
    """Mai uno zero muto: sul DB senza tabelle la risposta dice PERCHÉ non può
    rispondere, e se la conversazione c'è comunque, dove."""
    modulo, _ = db
    for tool in (modulo.get_session, modulo.get_stirpe):
        with pytest.raises(modulo.SessioneNonRisolta) as exc:
            tool(A, "vecchio")
        msg = str(exc.value)
        assert "non ha la tabella sessioni" in msg, msg
        assert "prima del contratto R1" in msg, msg
        assert "La CONVERSAZIONE però c'è" in msg and "vecchio (1 righe)" in msg, msg


def test_sessione_assente_ovunque_distingue_i_db_che_non_potevano_cercare(db) -> None:
    modulo, _ = db
    with pytest.raises(modulo.SessioneNonRisolta) as exc:
        modulo.get_session("ffffffff-0000-4000-8000-000000000000")
    msg = str(exc.value)
    assert "cercata in: nuovo" in msg and "SENZA tabella sessioni" in msg and "vecchio" in msg, msg


def test_risponde_il_db_piu_aggiornato_e_gli_altri_vanno_in_anche_in(tmp_path, monkeypatch) -> None:
    """La stessa sessione in due archivi (primario e fotografia): risponde quello
    col last_ts più recente, e l'altro non sparisce — `anche_in`, come per #272."""
    _bundle(tmp_path / "a-vecchia-foto.db")
    _bundle(tmp_path / "b-primario.db", last_ts_a="2026-09-20T10:00:00.000Z")
    for z in tmp_path.glob("*.zip"):
        z.unlink()
    modulo = _modulo_db(tmp_path, monkeypatch)
    s = modulo.get_session(A)
    assert s["db"] == "b-primario" and s["anche_in"] == ["a-vecchia-foto"], s
    assert s["sessione"]["last_ts"] == "2026-09-20T10:00:00.000Z"
    # a parità di last_ts vince il primo per nome
    shutil.copy(tmp_path / "a-vecchia-foto.db", tmp_path / "c-copia.db")
    modulo.reload_registry()
    st = modulo.get_stirpe(B)
    assert st["db"] == "a-vecchia-foto" and st["anche_in"] == ["b-primario", "c-copia"], st


def test_i_due_tool_sono_registrati_e_chiamano_db(tmp_path) -> None:
    """Registrati DOPO la sostituzione del decoratore (quindi con la redazione in
    uscita) e cablati sulle funzioni di db.py: «definito» non è «esposto»."""
    sorgente = (_QUI.parents[1] / "app" / "server.py").read_text(encoding="utf-8")
    albero = ast.parse(sorgente)
    riga_sostituzione = next(n.lineno for n in albero.body if isinstance(n, ast.Assign)
                             and "_tool_con_redazione" in ast.dump(n))
    for nome in ("get_session", "get_stirpe"):
        fn = next(n for n in albero.body if isinstance(n, ast.FunctionDef) and n.name == nome)
        assert any("tool" in ast.dump(d) for d in fn.decorator_list), f"{nome} non registrato"
        assert fn.lineno > riga_sostituzione, f"{nome} sopra la redazione"
        assert f"'{nome}'" in ast.dump(fn.body[-1]), f"{nome} non chiama db.{nome}"
