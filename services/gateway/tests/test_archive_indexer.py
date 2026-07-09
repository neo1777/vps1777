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


def test_extract_text_dict_annidato() -> None:
    # forma delle design chats claude.ai: content = {"role", "content"}
    assert archive_indexer.extract_text({"role": "user", "content": "testo interno"}) == "testo interno"
    # interno a blocchi (assistant)
    nested = {"role": "assistant", "content": [{"type": "text", "text": "risposta"}]}
    assert archive_indexer.extract_text(nested) == "risposta"
    # doppio livello e variante "text"
    assert archive_indexer.extract_text({"content": {"content": "fondo"}}) == "fondo"
    assert archive_indexer.extract_text({"text": "via text"}) == "via text"
    # dict senza niente di utile → vuoto, non crash
    assert archive_indexer.extract_text({"role": "user"}) == ""
    assert archive_indexer.extract_text({}) == ""


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


def test_index_file_design_chats_zip(tmp_path: Path) -> None:
    """Le design chats hanno content ANNIDATO ({"role","content"}) — il caso
    reale che produceva 0 righe in silenzio."""
    import json
    import zipfile
    zp = tmp_path / "export.zip"
    dc = {"uuid": "dc1", "title": "Chat",  # il title reale è sempre "Chat"
          "project": {"uuid": "p1", "name": "wallet1777"},
          "messages": [
        {"uuid": "dm1", "role": "user", "created_at": "2026-01-01",
         "content": {"role": "user", "content": "prompt di design zulu"}},
        {"uuid": "dm2", "role": "assistant", "created_at": "2026-01-01",
         "content": {"role": "assistant", "content": [{"type": "text", "text": "proposta yankee"}]}},
    ]}
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("design_chats/dc1.json", json.dumps(dc))
    db = tmp_path / "out.db"
    assert archive_indexer.index_file(str(zp), str(db)) == 2
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        r = conn.execute("SELECT project, content FROM messages_fts WHERE messages_fts MATCH 'zulu'").fetchall()
        # etichetta = progetto di appartenenza (il title generico non serve a nessuno)
        assert r and r[0][0] == "design:wallet1777" and "[user]" in r[0][1]
        assert conn.execute("SELECT count(*) FROM messages_fts WHERE messages_fts MATCH 'yankee'").fetchone()[0] == 1
    finally:
        conn.close()


def test_index_file_telegram_zip(tmp_path: Path) -> None:
    """Export Telegram Desktop JSON zippato come cartella (ChatExport_.../result.json)."""
    import json
    import zipfile
    zp = tmp_path / "ChatExport_2026-07-08.zip"
    result = {"name": "Gruppo", "id": 7, "messages": [
        {"id": 1, "type": "message", "date": "2026-07-01", "from": "Neo", "text": "ciao whiskey"},
    ]}
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("ChatExport_2026-07-08/result.json", json.dumps(result))
        z.writestr("ChatExport_2026-07-08/photos/x.jpg", b"\xff\xd8")  # rumore
    db = tmp_path / "tg.db"
    assert archive_indexer.index_file(str(zp), str(db)) == 1
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        r = conn.execute("SELECT project FROM messages_fts WHERE messages_fts MATCH 'whiskey'").fetchall()
        assert [x[0] for x in r] == ["Gruppo"]
    finally:
        conn.close()


def test_index_file_telegram_html_zip_errore_parlante(tmp_path: Path) -> None:
    """Export Telegram HTML: prima era 'ok, 0 record' — ora errore che spiega."""
    import pytest
    import zipfile
    zp = tmp_path / "ChatExport.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("ChatExport_2026-07-08/messages.html", "<html>...</html>")
        z.writestr("ChatExport_2026-07-08/messages2.html", "<html>...</html>")
    db = tmp_path / "out.db"
    with pytest.raises(ValueError, match="JSON"):
        archive_indexer.index_file(str(zp), str(db))
    assert not db.exists()


def test_index_file_zip_non_riconosciuto(tmp_path: Path) -> None:
    import pytest
    import zipfile
    zp = tmp_path / "roba.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("foto/gatto.jpg", b"\xff\xd8")
    with pytest.raises(ValueError, match="non riconosciuto"):
        archive_indexer.index_file(str(zp), str(tmp_path / "out.db"))
    assert not (tmp_path / "out.db").exists()


def test_index_file_zip_riconosciuto_ma_vuoto(tmp_path: Path) -> None:
    """Zip claude.ai con zero messaggi estraibili → errore, niente DB vuoto."""
    import json
    import pytest
    import zipfile
    zp = tmp_path / "export.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("conversations.json", json.dumps([]))
    db = tmp_path / "out.db"
    with pytest.raises(ValueError, match="0 record"):
        archive_indexer.index_file(str(zp), str(db))
    assert not db.exists()


def test_index_file_zip_vuoto_non_cancella_db_esistente(tmp_path: Path) -> None:
    """Accumulo su DB già popolato: uno zip a 0 righe segnala l'errore ma NON
    tocca i dati già indicizzati."""
    import json
    import pytest
    import zipfile
    db = tmp_path / "out.db"
    archive_indexer.index_jsonl(str(_jsonl(tmp_path)), str(db), project="proj")
    assert archive_indexer.count_rows(db) == 2
    zp = tmp_path / "export.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("conversations.json", json.dumps([]))
    with pytest.raises(ValueError, match="0 record"):
        archive_indexer.index_file(str(zp), str(db))
    assert archive_indexer.count_rows(db) == 2  # intatto


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
