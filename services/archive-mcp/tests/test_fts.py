"""Test della logica FTS pura (stdlib-only, offline).

fts.py non importa settings/MCP: lo carico come modulo singolo, come i test
stdlib del gateway (archive_indexer, miniapp_core)."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import fts  # noqa: E402

_SCHEMA = """
CREATE TABLE messages(uuid TEXT PRIMARY KEY, project, ts, content);
CREATE VIRTUAL TABLE messages_fts USING fts5(
    uuid, project, ts, content, content='messages', content_rowid='rowid');
"""


def _db(rows):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.executemany(
        "INSERT INTO messages(uuid, project, ts, content) VALUES (?,?,?,?)", rows)
    conn.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
    conn.commit()
    return conn


_ROWS = [
    ("u1", "chatA", "2026-01-01T10:00:00Z", "parliamo di flutter e dart"),
    ("u2", "chatA", "2026-01-02T10:00:00Z", "errore nel gateway con flutter-elinux"),
    ("u3", "chatB", "2026-03-01T10:00:00Z", "vps1777 e il notebook nb_list"),
    ("u4", "chatB", "2026-03-02T10:00:00Z", "ancora flutter, terzo messaggio"),
]


# ── sanitize ──────────────────────────────────────────────────────────────

def test_sanitize_quota_speciali():
    assert fts.sanitize_query("flutter-elinux") == '"flutter-elinux"'
    assert fts.sanitize_query("0.7.9") == '"0.7.9"'
    assert fts.sanitize_query("github.com") == '"github.com"'
    assert fts.sanitize_query("l'archivio") == '"l\'archivio"'


def test_sanitize_preserva_operatori_frasi_prefissi():
    assert fts.sanitize_query('dart OR flutter') == 'dart OR flutter'
    assert fts.sanitize_query('"exact phrase"') == '"exact phrase"'
    assert fts.sanitize_query('dart AND "una frase"') == 'dart AND "una frase"'
    assert fts.sanitize_query('palant*') == 'palant*'
    assert fts.sanitize_query('nb_list') == 'nb_list'          # underscore è word-char
    assert fts.sanitize_query('perché') == 'perché'            # accento preservato


def test_sanitize_conservativa_su_sintassi_avanzata():
    # con NEAR / parentesi / column-filter la query resta INVARIATA (quotarla
    # ne romperebbe la semantica); il fallback raw di search fa il resto
    assert fts.sanitize_query('(dart OR flutter)') == '(dart OR flutter)'
    assert fts.sanitize_query('NEAR(flutter dart, 5)') == 'NEAR(flutter dart, 5)'
    assert fts.sanitize_query('project:chatA') == 'project:chatA'


def test_sanitize_raddoppia_apici_interni():
    # un doppio apice dentro il token va escapato (raddoppiato) dentro le virgolette
    assert fts.sanitize_query('a"b') == '"a""b"'


# ── search: match e sintassi ────────────────────────────────────────────────

def test_search_match_base():
    conn = _db(_ROWS)
    out = fts.search_conn(conn, "dart")
    ids = {r["uuid"] for r in out}
    assert ids == {"u1"}
    assert out[0]["snippet"] and "db" not in out[0]  # db lo aggiunge db.py


def test_search_zero_risultati_non_solleva():
    conn = _db(_ROWS)
    assert fts.search_conn(conn, "inesistente") == []


def test_search_syntax_error_solleva_parlante():
    conn = _db(_ROWS)
    # column filter su colonna inesistente → OperationalError deterministico;
    # raw=True così la sanitizzazione non lo "salva" e il ramo d'errore si esercita
    with pytest.raises(fts.FtsSyntaxError) as ei:
        fts.search_conn(conn, "nonesistecol:foo", raw=True)
    assert "MAIUSCOLO" in str(ei.value)  # il messaggio spiega come correggere


def test_search_smart_trova_termine_con_trattino():
    conn = _db(_ROWS)
    # smart (default): 'flutter-elinux' viene quotato → trova u2
    out = fts.search_conn(conn, "flutter-elinux")
    assert {r["uuid"] for r in out} == {"u2"}


def test_search_smart_fallback_non_rompe_query_raw_valida():
    conn = _db(_ROWS)
    # una query FTS legittima con NEAR deve funzionare in smart-mode (fallback)
    out = fts.search_conn(conn, "NEAR(flutter dart, 5)")
    assert {r["uuid"] for r in out} == {"u1"}


# ── sort / filtri ───────────────────────────────────────────────────────────

def test_search_sort_newest_oldest():
    conn = _db(_ROWS)
    newest = fts.search_conn(conn, "flutter", sort="newest")
    assert [r["uuid"] for r in newest] == ["u4", "u2", "u1"]
    oldest = fts.search_conn(conn, "flutter", sort="oldest")
    assert [r["uuid"] for r in oldest] == ["u1", "u2", "u4"]


def test_search_filtro_since_until():
    conn = _db(_ROWS)
    # solo u4 (2026-03-02) ha 'flutter' dopo il 2026-02-01; u1/u2 sono a gennaio
    assert {r["uuid"] for r in fts.search_conn(conn, "flutter", since="2026-02-01")} == {"u4"}
    # until esclude u4, restano i due di gennaio
    out = fts.search_conn(conn, "flutter", until="2026-02-01")
    assert {r["uuid"] for r in out} == {"u1", "u2"}


def test_search_filtro_project():
    conn = _db(_ROWS)
    out = fts.search_conn(conn, "flutter", project="chatB")
    assert {r["uuid"] for r in out} == {"u4"}


def test_search_snippet_tokens():
    conn = _db(_ROWS)
    out = fts.search_conn(conn, "gateway", snippet_tokens=64)
    assert out and "«gateway»" in out[0]["snippet"]


# ── count ─────────────────────────────────────────────────────────────────

def test_count():
    conn = _db(_ROWS)
    assert fts.count_conn(conn, "flutter") == 3
    assert fts.count_conn(conn, "flutter", project="chatB") == 1
    assert fts.count_conn(conn, "inesistente") == 0


def test_count_syntax_error():
    conn = _db(_ROWS)
    with pytest.raises(fts.FtsSyntaxError):
        fts.count_conn(conn, "nonesistecol:foo", raw=True)


# ── canary termini collassati (la causa dell'11/07) ──────────────────────────

_SCHEMA_TOK = """
CREATE TABLE messages(uuid TEXT PRIMARY KEY, project, ts, content);
CREATE VIRTUAL TABLE messages_fts USING fts5(
    uuid, project, ts, content, content='messages', content_rowid='rowid',
    tokenize="unicode61 tokenchars '+#'");
"""

# righe scelte apposta per il collasso: `C++`/`C#`/`g++` reali + tante `C` isolate
# (coordinate, gradi, copyright) su cui il termine collassa se `+ #` sono separatori
_ROWS_CPP = [
    ("c1", "p", "2026-01-01T10:00:00Z", "adoro programmare in C++ ogni giorno"),
    ("c2", "p", "2026-01-02T10:00:00Z", "il backend è scritto in C#"),
    ("c3", "p", "2026-01-03T10:00:00Z", "coordinate del path 219.54 C 106.20"),
    ("c4", "p", "2026-01-04T10:00:00Z", "16 gradi C sotto quando non ci sei"),
    ("c5", "p", "2026-01-05T10:00:00Z", "compilo con g++ e ottimizzo"),
]


def _db_tok(rows):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_TOK)
    conn.executemany(
        "INSERT INTO messages(uuid, project, ts, content) VALUES (?,?,?,?)", rows)
    conn.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
    conn.commit()
    return conn


def test_collapse_candidates_statica():
    # trovati: il suffisso + # sparisce → un solo token più corto
    assert fts.collapse_candidates("C++") == [("C++", "C")]
    assert fts.collapse_candidates("C#") == [("C#", "C")]
    assert fts.collapse_candidates("g++") == [("g++", "g")]
    assert fts.collapse_candidates(".NET") == [(".NET", "NET")]
    # NON candidati: due token veri (frase, la regge il quoting), prefisso, parole
    assert fts.collapse_candidates("node.js") == []       # separatore IN MEZZO
    assert fts.collapse_candidates("flutter-elinux") == []
    assert fts.collapse_candidates("palant*") == []        # prefisso FTS voluto
    assert fts.collapse_candidates("A*") == []
    assert fts.collapse_candidates("flutter") == []
    # query strutturata: non ci mette becco
    assert fts.collapse_candidates("NEAR(a b, 3)") == []


def test_collapse_warning_su_db_default():
    # DB come i vivi (senza tokenchars): C++ collassa su C → deve AVVISARE
    conn = _db(_ROWS_CPP)
    # prova il difetto nudo: per l'indice default C++ == C == C#
    assert fts.count_conn(conn, "C++") == fts.count_conn(conn, "C")
    warns = fts.collapse_warnings_conn(conn, "C++")
    assert len(warns) == 1
    assert 'collassato su "C"' in warns[0]


def test_collapse_no_warning_con_tokenchars():
    # DB ricostruito col fix: C++ è un token vero → NIENTE avviso (auto-taratura)
    conn = _db_tok(_ROWS_CPP)
    assert fts.count_conn(conn, "C++") < fts.count_conn(conn, "C")  # distinti
    assert fts.collapse_warnings_conn(conn, "C++") == []
    assert fts.collapse_warnings_conn(conn, "C#") == []


def test_tokenchars_separa_i_termini():
    # il cuore del fix all'INDICE: senza, C++/C#/C sono lo stesso token
    default = _db(_ROWS_CPP)
    assert fts.count_conn(default, "C++") == fts.count_conn(default, "C#")  # collassati
    # con tokenchars, ognuno ha la sua identità
    tok = _db_tok(_ROWS_CPP)
    assert fts.count_conn(tok, "C++") == 1     # solo c1
    assert fts.count_conn(tok, "C#") == 1      # solo c2
    assert fts.count_conn(tok, "g++") == 1     # solo c5


# ── context ─────────────────────────────────────────────────────────────────

def test_context_intorno():
    conn = _db(_ROWS)
    ctx = fts.context_conn(conn, "u1", before=2, after=1)
    # u1 è il primo di chatA → niente prima, u2 dopo
    assert [r["uuid"] for r in ctx] == ["u1", "u2"]
    assert ctx[0]["is_match"] is True and ctx[1]["is_match"] is False
    assert ctx[0]["content"] == "parliamo di flutter e dart"  # contenuto PIENO


def test_context_solo_stesso_project():
    conn = _db(_ROWS)
    ctx = fts.context_conn(conn, "u3", before=5, after=5)
    assert {r["project"] for r in ctx} == {"chatB"}  # non sconfina in chatA
    assert [r["uuid"] for r in ctx] == ["u3", "u4"]


def test_context_uuid_assente():
    conn = _db(_ROWS)
    assert fts.context_conn(conn, "non-esiste") == []


# ── stats ─────────────────────────────────────────────────────────────────

def test_db_stats():
    conn = _db(_ROWS)
    st = fts.db_stats_conn(conn)
    assert st["rows"] == 4
    assert st["labels"] == 2
    assert st["oldest"] == "2026-01-01T10:00:00Z"
    assert st["newest"] == "2026-03-02T10:00:00Z"


def test_db_stats_vuoto():
    conn = _db([])
    st = fts.db_stats_conn(conn)
    assert st == {"rows": 0, "oldest": "", "newest": "", "labels": 0}


# ── thread walk: get_conversation + context via parent_uuid (P2) ────────────

_SCHEMA_FULL = """
CREATE TABLE messages(uuid TEXT PRIMARY KEY, project, ts, content,
    sender DEFAULT '', tools DEFAULT '', thinking DEFAULT '',
    attachments DEFAULT '', parent_uuid DEFAULT '');
CREATE VIRTUAL TABLE messages_fts USING fts5(
    uuid, project, ts, content, tools, attachments,
    content='messages', content_rowid='rowid');
CREATE INDEX idx_parent ON messages(parent_uuid);
"""


def _db_full(rows):
    """rows: (uuid, project, ts, content, sender, parent_uuid)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_FULL)
    conn.executemany(
        "INSERT INTO messages(uuid, project, ts, content, sender, parent_uuid) "
        "VALUES (?,?,?,?,?,?)", rows)
    conn.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
    conn.commit()
    return conn


def test_conversation_walks_parent_uuid():
    conn = _db_full([
        ("m1", "P", "2026-01-01T00:00:00Z", "primo", "human", ""),
        ("m2", "P", "2026-01-01T00:00:01Z", "secondo", "assistant", "m1"),
        ("m3", "P", "2026-01-01T00:00:02Z", "terzo", "human", "m2"),
        ("x9", "P", "2026-01-01T00:00:03Z", "altra chat", "human", ""),  # non connesso
    ])
    conv = fts.conversation_conn(conn, "m2")
    assert [r["uuid"] for r in conv] == ["m1", "m2", "m3"]  # il thread, non x9
    assert next(r for r in conv if r["uuid"] == "m2")["is_match"] is True


def test_conversation_fallback_linear_senza_arco():
    conn = _db_full([
        ("d1", "doc", "2026-05-01T00:00:00Z", "chunk uno", "", ""),
        ("d2", "doc", "2026-05-01T00:00:01Z", "chunk due", "", ""),
    ])
    conv = fts.conversation_conn(conn, "d1")
    assert [r["uuid"] for r in conv] == ["d1", "d2"]  # ordine lineare dello stesso project


def test_context_usa_il_thread_non_solo_ts():
    # due conversazioni INTERLACCIATE nello stesso project: l'adiacenza per ts
    # le mischerebbe; il thread parent_uuid no.
    conn = _db_full([
        ("a1", "P", "2026-01-01T00:00:01Z", "A uno", "", ""),
        ("b1", "P", "2026-01-01T00:00:02Z", "B uno", "", ""),
        ("a2", "P", "2026-01-01T00:00:03Z", "A due", "", "a1"),
        ("b2", "P", "2026-01-01T00:00:04Z", "B due", "", "b1"),
        ("a3", "P", "2026-01-01T00:00:05Z", "A tre", "", "a2"),
    ])
    ctx = fts.context_conn(conn, "a2", before=1, after=1)
    assert [r["uuid"] for r in ctx] == ["a1", "a2", "a3"]  # thread A, non [b1,a2,b2]


def test_list_projects():
    conn = _db(_ROWS)
    ps = fts.projects_conn(conn)
    assert {p["project"]: p["rows"] for p in ps} == {"chatA": 2, "chatB": 2}


def test_stats_by_period():
    conn = _db(_ROWS)
    st = fts.stats_by_period_conn(conn)
    assert st == [{"period": "2026", "rows": 4}]


def test_meta_value():
    """La scheda `meta` (D5): default se la tabella manca (DB pre-feature),
    il valore quando c'è."""
    conn = _db(_ROWS)  # schema minimale, senza tabella meta
    assert fts.meta_value_conn(conn, "description") == ""
    conn.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO meta VALUES ('description', 'archivio di prova')")
    assert fts.meta_value_conn(conn, "description") == "archivio di prova"
