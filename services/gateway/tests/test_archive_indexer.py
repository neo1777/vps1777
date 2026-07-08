"""Test dell'indexer archive (stdlib-only, offline)."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# archive_indexer è stdlib-only: lo importo come modulo singolo, senza tirare
# dentro il pacchetto app/ (che avrebbe deps pesanti).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import archive_indexer  # noqa: E402


def _jsonl(tmp_path: Path) -> Path:
    p = tmp_path / "s.jsonl"
    p.write_text("\n".join([
        '{"type":"user","uuid":"u1","timestamp":"2026-01-01T00:00:00Z","cwd":"/x/proj","message":{"content":"ciao mondo notebook"}}',
        '{"type":"assistant","uuid":"a1","timestamp":"2026-01-01T00:00:01Z","message":{"content":[{"type":"thinking","thinking":"ragiono"},{"type":"text","text":"risposta con vps1777"}]}}',
        '{"type":"mode","sessionId":"s"}',            # metadata → ignorato
        '{"type":"user","uuid":"","timestamp":"t","message":{"content":"senza uuid"}}',  # scartato
        "",                                            # riga vuota
        "non-json",                                    # riga non valida → saltata
    ]), encoding="utf-8")
    return p


def test_index_conta_solo_user_assistant(tmp_path: Path) -> None:
    db = tmp_path / "out.db"
    n = archive_indexer.index_jsonl(str(_jsonl(tmp_path)), str(db), project="proj")
    assert n == 2  # user + assistant validi; metadata/senza-uuid/rumore scartati
    assert archive_indexer.count_rows(db) == 2


def test_search_query_di_archive_mcp(tmp_path: Path) -> None:
    db = tmp_path / "out.db"
    archive_indexer.index_jsonl(str(_jsonl(tmp_path)), str(db), project="proj")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        # la query ESATTA che usa archive-mcp/db.py
        rows = conn.execute(
            "SELECT uuid, project, ts, snippet(messages_fts,-1,'«','»','…',16) "
            "FROM messages_fts WHERE messages_fts MATCH ? ORDER BY bm25(messages_fts)",
            ("notebook",),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "u1"
        assert rows[0][1] == "proj"
    finally:
        conn.close()


def test_idempotenza_reindex(tmp_path: Path) -> None:
    db = tmp_path / "out.db"
    src = _jsonl(tmp_path)
    archive_indexer.index_jsonl(str(src), str(db), project="proj")
    archive_indexer.index_jsonl(str(src), str(db), project="proj")  # re-index
    assert archive_indexer.count_rows(db) == 2  # nessun duplicato (dedup per uuid)
    # e la ricerca regge (niente corruzione FTS dopo il rebuild)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT count(*) FROM messages_fts WHERE messages_fts MATCH 'vps1777'"
        ).fetchone()
        assert rows[0] == 1
    finally:
        conn.close()


def test_extract_text() -> None:
    assert archive_indexer.extract_text("ciao") == "ciao"
    blocks = [{"type": "text", "text": "a"}, {"type": "tool_use", "name": "x"}, {"type": "text", "text": "b"}]
    assert archive_indexer.extract_text(blocks) == "a\nb"
    assert archive_indexer.extract_text(None) == ""
    assert archive_indexer.extract_text([]) == ""


def test_index_file_claude_zip(tmp_path: Path) -> None:
    import json
    import zipfile
    zp = tmp_path / "export.zip"
    convs = [{
        "uuid": "c1", "name": "Chat su vps1777",
        "chat_messages": [
            {"uuid": "m1", "sender": "human", "created_at": "2026-01-01T00:00:00Z", "text": "parliamo di notebook"},
            {"uuid": "m2", "sender": "assistant", "created_at": "2026-01-01T00:00:01Z",
             "content": [{"type": "text", "text": "certo, gateway"}]},
        ],
    }]
    proj = {"name": "prog", "docs": [{"uuid": "d1", "filename": "note.txt",
                                      "created_at": "2026-01-01", "content": "documento vps1777"}]}
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("conversations.json", json.dumps(convs))
        z.writestr("projects/p1.json", json.dumps(proj))
    db = tmp_path / "out.db"
    n = archive_indexer.index_file(str(zp), str(db))
    assert n == 3  # 2 messaggi + 1 doc
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        # match sul contenuto: 'gateway' solo nel msg assistant della conversazione
        r1 = conn.execute("SELECT project FROM messages_fts WHERE messages_fts MATCH 'gateway'").fetchall()
        assert [x[0] for x in r1] == ["Chat su vps1777"]
        # 'documento' solo nel doc di progetto
        r2 = conn.execute("SELECT project FROM messages_fts WHERE messages_fts MATCH 'documento'").fetchall()
        assert [x[0] for x in r2] == ["project:prog"]
    finally:
        conn.close()


def test_index_file_markdown(tmp_path: Path) -> None:
    md = tmp_path / "note.md"
    md.write_text("# Titolo\n\nParagrafo su vps1777.\n\nAltro paragrafo.\n", encoding="utf-8")
    db = tmp_path / "out.db"
    n = archive_indexer.index_file(str(md), str(db), project="note")
    assert n >= 1
    assert archive_indexer.count_rows(db) == n


def test_index_file_unsupported(tmp_path: Path) -> None:
    import pytest
    bad = tmp_path / "x.rtf"
    bad.write_bytes(b"{\\rtf1}")
    with pytest.raises(ValueError):
        archive_indexer.index_file(str(bad), str(tmp_path / "o.db"))


def test_index_file_telegram_json(tmp_path: Path) -> None:
    import json
    j = tmp_path / "result.json"
    j.write_text(json.dumps({
        "name": "Canale", "id": 42, "type": "personal_chat",
        "messages": [
            {"id": 1, "type": "message", "date": "2026-01-01T00:00:00", "from": "Neo", "text": "prova zenith"},
            {"id": 2, "type": "service", "action": "pin_message"},  # ignorato
            {"id": 3, "type": "message", "date": "2026-01-01T00:01:00", "from": "Neo",
             "text": [{"type": "bold", "text": "gras "}, "e normale"]},
        ],
    }), encoding="utf-8")
    db = tmp_path / "tg.db"
    n = archive_indexer.index_file(str(j), str(db))
    assert n == 2  # i due 'message', non il 'service'
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        r = conn.execute("SELECT content FROM messages_fts WHERE messages_fts MATCH 'zenith'").fetchall()
        assert len(r) == 1 and "[Neo]" in r[0][0]
        # entities appiattite
        r2 = conn.execute("SELECT content FROM messages_fts WHERE messages_fts MATCH 'normale'").fetchall()
        assert r2 and "gras e normale" in r2[0][0]
    finally:
        conn.close()


def test_tg_text_flatten() -> None:
    assert archive_indexer._tg_text("ciao") == "ciao"
    assert archive_indexer._tg_text(["a", {"type": "bold", "text": "b"}, "c"]) == "abc"
    assert archive_indexer._tg_text(None) == ""


def test_chunk_rows_deterministico(tmp_path: Path) -> None:
    rows1 = list(archive_indexer._chunk_rows("a\n\nb\n\nc", "n", "t", "k"))
    rows2 = list(archive_indexer._chunk_rows("a\n\nb\n\nc", "n", "t", "k"))
    assert [r[0] for r in rows1] == [r[0] for r in rows2]  # uuid stabili → idempotente
