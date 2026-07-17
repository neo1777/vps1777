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


def test_conversation_summary_indexed(tmp_path: Path) -> None:
    """La `summary` di una conversazione claude.ai viene indicizzata come riga
    attribuita `sender='summary'` — prima era persa (nessun codice la leggeva)."""
    import json
    import zipfile
    zp = tmp_path / "export.zip"
    convs = [{
        "uuid": "c1", "name": "Chat lunga", "updated_at": "2026-02-02T00:00:00Z",
        "summary": "Discussione su ARCHIVISUMMARY e migrazione",
        "chat_messages": [
            {"uuid": "m1", "sender": "human", "created_at": "2026-02-02T00:00:00Z", "text": "ciao"},
        ],
    }]
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("conversations.json", json.dumps(convs))
    db = tmp_path / "out.db"
    n = archive_indexer.index_file(str(zp), str(db))
    assert n == 2  # 1 messaggio + 1 summary
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        r = conn.execute(
            "SELECT project, sender FROM messages WHERE content LIKE '%ARCHIVISUMMARY%'").fetchall()
        assert r == [("Chat lunga", "summary")]
        hits = conn.execute(
            "SELECT count(*) FROM messages_fts WHERE messages_fts MATCH 'ARCHIVISUMMARY'").fetchone()[0]
        assert hits == 1
    finally:
        conn.close()


def test_parent_uuid_index_created(tmp_path: Path) -> None:
    """L'indice su `parent_uuid` (che abilita get_conversation) è creato all'ingest,
    anche per i DB migrati da v1 (CREATE INDEX IF NOT EXISTS nello schema)."""
    md = tmp_path / "n.md"
    md.write_text("# t\n\ncorpo", encoding="utf-8")
    db = tmp_path / "out.db"
    archive_indexer.index_file(str(md), str(db))
    conn = sqlite3.connect(str(db))
    try:
        idx = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_parent'").fetchall()
        assert idx == [("idx_parent",)]
    finally:
        conn.close()


def test_skipped_ledger(tmp_path: Path) -> None:
    """I record scartati dall'ingest (no-uuid, vuoti) finiscono nella tabella
    `skipped` — reversibili e leggibili — invece di sparire in silenzio (D3/#56).
    Idempotente: re-indicizzare non duplica le lapidi."""
    import json
    import zipfile
    zp = tmp_path / "export.zip"
    convs = [{
        "uuid": "c1", "name": "Chat",
        "chat_messages": [
            {"uuid": "ok1", "sender": "human", "created_at": "2026-03-03T00:00:00Z", "text": "valido"},
            {"sender": "human", "created_at": "2026-03-03T00:00:01Z", "text": "senza uuid"},
            {"uuid": "empty1", "sender": "human", "created_at": "2026-03-03T00:00:02Z", "text": ""},
        ],
    }]
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("conversations.json", json.dumps(convs))
    db = tmp_path / "out.db"
    n = archive_indexer.index_file(str(zp), str(db))
    assert n == 1  # solo il messaggio valido finisce in messages
    assert archive_indexer.count_skipped(db) == 2  # no-uuid + vuoto
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        reasons = sorted(r[0] for r in conn.execute("SELECT reason FROM skipped").fetchall())
        assert reasons == ["empty", "no-uuid"]
        d = conn.execute("SELECT detail FROM skipped WHERE reason='no-uuid'").fetchone()[0]
        assert "senza uuid" in d  # il dato raw è reversibile, leggibile alla bisogna
    finally:
        conn.close()
    assert archive_indexer.db_info(db)["skipped"] == 2  # conteggio superficiato, non muto
    archive_indexer.index_file(str(zp), str(db))
    assert archive_indexer.count_skipped(db) == 2  # re-index non duplica le lapidi


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


_TG_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"></head><body>
<div class="page_wrap">
 <div class="page_header">
  <div class="content"><div class="text bold">
Gruppo Prova 🚀
  </div></div>
 </div>
 <div class="history">
  <div class="message service" id="message-1"><div class="body details">2 March 2024</div></div>
  <div class="message default clearfix" id="message-10">
   <div class="pull_left userpic_wrap"><div class="userpic"><div class="initials">N</div></div></div>
   <div class="body">
    <div class="pull_right date details" title="02.03.2024 13:10:36 UTC+01:00">13:10</div>
    <div class="from_name">
Neo1777
    </div>
    <div class="text">
Salve &amp; benvenuti<br>seconda riga
    </div>
   </div>
  </div>
  <div class="message default clearfix joined" id="message-11">
   <div class="body">
    <div class="pull_right date details" title="02.03.2024 13:11:00 UTC+01:00">13:11</div>
    <div class="text">
messaggio joined con <a href="https://x.y">un link</a>
    </div>
   </div>
  </div>
  <div class="message default clearfix" id="message-12">
   <div class="pull_left userpic_wrap"><div class="userpic"><div class="initials">E</div></div></div>
   <div class="body">
    <div class="pull_right date details" title="02.03.2024 13:12:00 UTC+01:00">13:12</div>
    <div class="from_name">
Ema
    </div>
    <div class="media_wrap clearfix"><a class="sticker_wrap" href="stickers/s.webp">s</a></div>
   </div>
  </div>
 </div>
</div></body></html>"""


def test_index_file_telegram_html_zip(tmp_path: Path) -> None:
    """Export Telegram HTML (il formato DEFAULT di Telegram Desktop): si
    indicizza direttamente — struttura modellata sull'export reale."""
    import zipfile
    zp = tmp_path / "ChatExport.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("ChatExport_2026-07-10/messages.html", _TG_HTML)
    db = tmp_path / "out.db"
    n = archive_indexer.index_file(str(zp), str(db))
    assert n == 2  # testo + joined; sticker-only e service saltati
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT project, ts, content FROM messages ORDER BY ts").fetchall()
        assert all(r[0] == "Gruppo Prova 🚀" for r in rows)
        # entità decodificate, <br> → newline, mittente presente
        assert rows[0][1] == "2024-03-02T13:10:36+01:00"
        assert rows[0][2] == "[Neo1777] Salve & benvenuti\nseconda riga"
        # joined eredita il mittente; il testo del link resta
        assert rows[1][2] == "[Neo1777] messaggio joined con un link"
        r = conn.execute("SELECT content FROM messages_fts WHERE messages_fts MATCH 'benvenuti'").fetchall()
        assert len(r) == 1
    finally:
        conn.close()


def test_index_file_telegram_html_idempotente(tmp_path: Path) -> None:
    import zipfile
    zp = tmp_path / "ChatExport.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("ChatExport_2026-07-10/messages.html", _TG_HTML)
    db = tmp_path / "out.db"
    archive_indexer.index_file(str(zp), str(db))
    archive_indexer.index_file(str(zp), str(db))  # ricarico lo stesso export
    assert archive_indexer.count_rows(db) == 2   # dedup per (chat, msg_id)


def test_index_file_telegram_html_vuoto_errore(tmp_path: Path) -> None:
    """HTML riconosciuto ma senza messaggi estraibili → errore, non 0 silenzioso."""
    import pytest
    import zipfile
    zp = tmp_path / "ChatExport.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("ChatExport_2026-07-08/messages.html", "<html><body>vuoto</body></html>")
    db = tmp_path / "out.db"
    with pytest.raises(ValueError, match="0 record"):
        archive_indexer.index_file(str(zp), str(db))
    assert not db.exists()


def test_tg_html_ts() -> None:
    assert archive_indexer._tg_html_ts("02.03.2024 13:10:33 UTC+01:00") == "2024-03-02T13:10:33+01:00"
    assert archive_indexer._tg_html_ts("31.12.2025 23:59:59") == "2025-12-31T23:59:59"
    assert archive_indexer._tg_html_ts("roba strana") == "roba strana"


def test_index_file_zip_non_riconosciuto(tmp_path: Path) -> None:
    import pytest
    import zipfile
    zp = tmp_path / "roba.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("foto/gatto.jpg", b"\xff\xd8")
    with pytest.raises(ValueError, match="non riconosciuto"):
        archive_indexer.index_file(str(zp), str(tmp_path / "out.db"))
    assert not (tmp_path / "out.db").exists()


# ── contratto dei bucket + classify_cc (canary anti-drift col preflight app) ──

def test_ai_title_senza_sessionId_non_crasha() -> None:
    """Regression: `_iter_claude_code` referenziava `n_riga` (rimosso) nel ramo
    ai-title → NameError su un titolo SENZA sessionId = crash dell'ingest del file.
    Ora l'uid ripiega sul testo del titolo."""
    import io
    line = '{"type":"ai-title","aiTitle":"titolo orfano"}\n'
    rows = list(archive_indexer._iter_claude_code(io.StringIO(line), "test"))
    assert len(rows) == 1
    assert rows[0][4] == "title" and rows[0][3] == "titolo orfano"


# Il contratto: UN record per bucket. Tenuto INLINE (non un file .jsonl, che il
# .gitignore esclude → non arriverebbe in CI). La copia condivisa per la corsia app
# vive in `_chat/contract/cc_buckets.jsonl`; il suo canary confronta il proprio
# preflight con la mia classify VIVA (`--classify`) sulla stessa fixture, quindi
# regge anche se le due copie divergono — non si fida di un atteso salvato.
_CC_BUCKETS = [
    '{"type":"user","uuid":"u-1","timestamp":"2026-01-01T10:00:00Z","message":{"role":"user","content":"ciao come va"}}',
    '{"type":"assistant","uuid":"a-1","timestamp":"2026-01-01T10:00:01Z","message":{"role":"assistant","content":"bene, procedo"}}',
    '{"type":"ai-title","sessionId":"sess-9","aiTitle":"Titolo con sessione"}',
    '{"type":"ai-title","aiTitle":"Titolo SENZA sessione"}',
    '{"type":"attachment","uuid":"att-1","attachment":{"addedNames":["schema.sql","note.md"]}}',
    '{"type":"attachment","uuid":"att-2","attachment":{"addedNames":[]}}',
    '{"type":"queue-operation","operation":"flush"}',
    '{"type":"user","message":{"role":"user","content":"senza uuid ne ts"}}',
    '{"type":"user","uuid":"u-empty","timestamp":"2026-01-01T10:00:02Z","message":{"role":"user","content":[]}}',
]


def test_contratto_bucket_classify_cc() -> None:
    """Il contratto copre UN record per bucket; `classify_cc` deve dare questa
    sequenza esatta di verdetti. Se cambio l'ordine/i bucket di `_iter_claude_code`,
    questo test si spacca — ed è il segnale che il preflight della corsia app (che
    replica la logica) va ri-verificato. Il canary è una sottrazione: entrambi gli
    strumenti classificano la stessa fixture e i verdetti devono combaciare."""
    import io
    verdicts = archive_indexer.classify_cc(io.StringIO("\n".join(_CC_BUCKETS) + "\n"))
    assert verdicts == [
        "keep:user",
        "keep:assistant",
        "keep:title",          # ai-title con sessionId
        "keep:title",          # ai-title senza sessionId (fix n_riga)
        "keep:attachment",
        "skip:non-message",    # attachment senza addedNames
        "skip:non-message",    # queue-operation (type fuori da _CC_TYPES)
        "skip:no-uuid-o-ts",
        "skip:empty",
    ]


def test_index_file_zip_di_documenti(tmp_path: Path) -> None:
    """Zip che NON è un export ma contiene .md/.txt → indicizzato come documenti
    (fallback 'archive deve indicizzare zip md txt, quel che è'). Ogni membro
    diventa cercabile, col path del membro come progetto/chiave."""
    import zipfile
    zp = tmp_path / "note.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("a.md", "# Primo\n\nParola CHIAVEALFA nel primo doc.")
        z.writestr("sub/b.txt", "Parola CHIAVEBETA nel secondo, dentro una cartella.")
    db = tmp_path / "out.db"
    n = archive_indexer.index_file(str(zp), str(db))
    assert n >= 2
    conn = sqlite3.connect(str(db))
    a = conn.execute("SELECT project FROM messages_fts WHERE messages_fts MATCH 'CHIAVEALFA'").fetchall()
    b = conn.execute("SELECT project FROM messages_fts WHERE messages_fts MATCH 'CHIAVEBETA'").fetchall()
    conn.close()
    assert a == [("a.md",)]
    assert b == [("sub/b.txt",)]
    # idempotente: re-indicizzare lo stesso zip non duplica (uuid stabile)
    archive_indexer.index_file(str(zp), str(db))
    assert archive_indexer.count_rows(db) == n


def test_index_file_zip_documenti_ignora_macosx(tmp_path: Path) -> None:
    """Le resource-fork di macOS (__MACOSX/, ._*) non entrano come documenti
    -fantasma: si indicizza solo il .md reale."""
    import zipfile
    zp = tmp_path / "mac.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("vero.md", "contenuto CHIAVEVERA reale")
        z.writestr("__MACOSX/._vero.md", b"\x00\x05\x16\x07")  # resource fork binaria
        z.writestr("._vero.md", b"\x00\x05\x16\x07")
    db = tmp_path / "out.db"
    n = archive_indexer.index_file(str(zp), str(db))
    assert n == 1
    conn = sqlite3.connect(str(db))
    rows = conn.execute("SELECT project FROM messages").fetchall()
    conn.close()
    assert rows == [("vero.md",)]


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


def test_db_info(tmp_path: Path) -> None:
    db = tmp_path / "out.db"
    archive_indexer.write_rows(db, [
        ("u1", "alpha", "2026-01-01", "uno"),
        ("u2", "alpha", "2026-01-02", "due"),
        ("u3", "beta", "2026-01-03", "tre"),
    ])
    info = archive_indexer.db_info(db, top=2)
    assert info["name"] == "out"
    assert info["rows"] == 3
    assert info["labels"] == 2
    # top ordinato per popolosità, poi alfabetico
    assert info["top"] == [{"label": "alpha", "rows": 2}, {"label": "beta", "rows": 1}]
    assert info["size"] > 0
    assert info["mtime"]  # ISO non vuoto


def test_db_info_assente_o_corrotto(tmp_path: Path) -> None:
    info = archive_indexer.db_info(tmp_path / "manca.db")
    assert info["rows"] == 0 and info["size"] == 0 and info["top"] == []
    rotto = tmp_path / "rotto.db"
    rotto.write_bytes(b"non un sqlite")
    info2 = archive_indexer.db_info(rotto)
    assert info2["rows"] == 0 and info2["size"] > 0  # stat ok, query no


def test_find_db(tmp_path: Path) -> None:
    db = tmp_path / "mio.db"
    archive_indexer.write_rows(db, [("u1", "p", "t", "x")])
    assert archive_indexer.find_db(tmp_path, "mio") == db
    assert archive_indexer.find_db(tmp_path, "altro") is None
    assert archive_indexer.find_db(tmp_path, "") is None
    assert archive_indexer.find_db(tmp_path / "manca", "mio") is None
    # niente traversal: il nome si confronta col listato, non diventa un path
    assert archive_indexer.find_db(tmp_path, "../mio") is None
    assert archive_indexer.find_db(tmp_path, "sub/mio") is None


def test_chunk_rows_deterministico(tmp_path: Path) -> None:
    rows1 = list(archive_indexer._chunk_rows("a\n\nb\n\nc", "n", "t", "k"))
    rows2 = list(archive_indexer._chunk_rows("a\n\nb\n\nc", "n", "t", "k"))
    assert [r[0] for r in rows1] == [r[0] for r in rows2]  # uuid stabili → idempotente


# ── v2: il contenuto pieno (issue #22) ───────────────────────────────────────
# Prima, `extract_text` teneva solo i blocchi type=="text" e scartava
# thinking/tool_use/tool_result come «rumore per la ricerca». Su un export reale
# quel «rumore» valeva 2,6× il parlato — e i tool_use sono le AZIONI.

def _claude_zip_v2(tmp_path: Path) -> Path:
    """Export claude.ai minimale con un messaggio agentico: text + tool_use +
    tool_result + thinking + allegato."""
    import json
    import zipfile
    convs = [{
        "uuid": "c1", "name": "sessione agentica",
        "chat_messages": [
            {   # il caso che il vecchio codice mutilava: `text` piatto valorizzato,
                # `content` ricco mai letto (il ramo destro dell'`or` era morto)
                "uuid": "m1", "sender": "assistant", "created_at": "2026-01-01T00:00:00Z",
                "text": "ho sistemato il file",
                "content": [
                    {"type": "thinking", "thinking": "devo aprire il main"},
                    {"type": "text", "text": "ho sistemato il file"},
                    {"type": "tool_use", "name": "Edit",
                     "input": {"file_path": "lib/main.dart"}},
                    {"type": "tool_result", "content": "1 riga modificata in main.dart"},
                ],
                "attachments": [{"file_name": "screenshot.png"}],
            },
            {   # messaggio di SOLI tool_use: prima spariva del tutto (`if not text`)
                "uuid": "m2", "sender": "assistant", "created_at": "2026-01-01T00:00:01Z",
                "text": "",
                "content": [{"type": "tool_use", "name": "Bash",
                             "input": {"command": "pytest -q"}}],
            },
        ],
    }]
    p = tmp_path / "export.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("conversations.json", json.dumps(convs))
    return p


def test_v2_le_azioni_finiscono_nel_db(tmp_path: Path) -> None:
    db = tmp_path / "v2.db"
    archive_indexer.index_file(str(_claude_zip_v2(tmp_path)), str(db))
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        tools, thinking, attach = conn.execute(
            "SELECT tools, thinking, attachments FROM messages WHERE uuid='m1'").fetchone()
        assert "main.dart" in tools and "Edit" in tools      # tool_use
        assert "1 riga modificata" in tools                  # tool_result
        assert "devo aprire il main" in thinking             # conservato
        assert "screenshot.png" in attach                    # allegato
    finally:
        conn.close()


def test_v2_messaggio_di_soli_tool_non_sparisce(tmp_path: Path) -> None:
    """Una sessione agentica è piena di messaggi senza testo: prima venivano
    scartati da `if not text: continue` e nessuno lo sapeva."""
    db = tmp_path / "v2.db"
    archive_indexer.index_file(str(_claude_zip_v2(tmp_path)), str(db))
    assert archive_indexer.count_rows(db) == 2  # m1 + m2 (prima: solo m1)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        (tools,) = conn.execute("SELECT tools FROM messages WHERE uuid='m2'").fetchone()
        assert "pytest" in tools
    finally:
        conn.close()


def test_v2_la_ricerca_trova_le_azioni(tmp_path: Path) -> None:
    """Il punto dell'issue: `main.dart` non è mai stato scritto nel parlato —
    esiste solo dentro un tool_use. Prima era invisibile alla ricerca."""
    db = tmp_path / "v2.db"
    archive_indexer.index_file(str(_claude_zip_v2(tmp_path)), str(db))
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT uuid FROM messages_fts WHERE messages_fts MATCH ?",
            ('"main.dart"',)).fetchall()
        assert [r[0] for r in rows] == ["m1"]
        rows = conn.execute(
            "SELECT uuid FROM messages_fts WHERE messages_fts MATCH ?",
            ("pytest",)).fetchall()
        assert [r[0] for r in rows] == ["m2"]
    finally:
        conn.close()


def test_v2_thinking_conservato_ma_non_indicizzato(tmp_path: Path) -> None:
    """`thinking` si salva (recuperabile) ma NON entra nell'FTS: su un export reale
    sono ~9.400 blocchi di ragionamento, e inquinerebbero ogni MATCH."""
    db = tmp_path / "v2.db"
    archive_indexer.index_file(str(_claude_zip_v2(tmp_path)), str(db))
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        (n,) = conn.execute(
            "SELECT count(*) FROM messages WHERE thinking LIKE '%devo aprire%'").fetchone()
        assert n == 1                                    # c'è nella tabella
        rows = conn.execute(
            "SELECT uuid FROM messages_fts WHERE messages_fts MATCH ?",
            ('"devo aprire il main"',)).fetchall()
        assert rows == []                                # ma non nell'FTS
    finally:
        conn.close()


def test_v2_migrazione_da_db_v1(tmp_path: Path) -> None:
    """Un DB con lo schema vecchio (4 colonne) si migra senza perdere righe."""
    db = tmp_path / "old.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE messages(uuid TEXT PRIMARY KEY, project TEXT, ts TEXT, content TEXT);
        CREATE VIRTUAL TABLE messages_fts USING fts5(
            uuid, project, ts, content, content='messages', content_rowid='rowid');
    """)
    conn.execute("INSERT INTO messages VALUES ('x1','p','2026-01-01','vecchio messaggio')")
    conn.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
    conn.commit()
    conn.close()

    assert archive_indexer.migrate_v1_to_v2(db) is True
    assert archive_indexer.migrate_v1_to_v2(db) is False      # idempotente
    assert archive_indexer.count_rows(db) == 1                # niente perso

    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(messages)")}
        assert {"sender", "tools", "thinking", "attachments"} <= cols
        rows = conn.execute(
            "SELECT uuid FROM messages_fts WHERE messages_fts MATCH ?", ("vecchio",)).fetchall()
        assert [r[0] for r in rows] == ["x1"]                 # l'FTS è stata ricostruita
    finally:
        conn.close()


def test_v2_righe_a_4_campi_ancora_accettate(tmp_path: Path) -> None:
    """Retrocompatibilità: un estrattore esterno che produce (uuid, project, ts,
    content) continua a funzionare."""
    db = tmp_path / "compat.db"
    n = archive_indexer.write_rows(db, [("u1", "p", "2026-01-01", "ciao")])
    assert n == 1 and archive_indexer.count_rows(db) == 1


# ── v2b: memories.json e parent_message_uuid (indagine di follow-up su #22) ──

def _claude_zip_memories(tmp_path: Path) -> Path:
    """Export con `memories.json`: la memoria persistente dell'account.
    `project_memories` è una MAPPA {project_uuid: testo}, non una lista."""
    import json
    import zipfile
    convs = [{"uuid": "c1", "name": "chat", "chat_messages": [
        {"uuid": "m1", "sender": "human", "created_at": "2026-01-01T00:00:00Z",
         "text": "primo", "content": [{"type": "text", "text": "primo"}],
         "parent_message_uuid": None},
        {"uuid": "m2", "sender": "assistant", "created_at": "2026-01-01T00:00:01Z",
         "text": "secondo", "content": [{"type": "text", "text": "secondo"}],
         "parent_message_uuid": "m1"},
    ]}]
    memories = [{
        "account_uuid": "acc",
        "conversations_memory": "Neo lavora principalmente in Dart e Flutter.",
        "project_memories": {
            "proj-uuid-1": "Il libro di game development è al capitolo 81.",
            "proj-uuid-2": "vps1777 ospita archive1777 e nb1777.",
        },
    }]
    p = tmp_path / "export.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("conversations.json", json.dumps(convs))
        z.writestr("memories.json", json.dumps(memories))
        # users.json c'è nell'export reale ma NON va indicizzato (email, telefono)
        z.writestr("users.json", json.dumps([{"full_name": "neo1777",
                                              "email_address": "x@y.z"}]))
    return p


def test_v2_memories_indicizzate(tmp_path: Path) -> None:
    """`memories.json` è la fonte che più di ogni altra determina cosa l'assistente
    crede dell'utente — e non veniva indicizzata affatto."""
    db = tmp_path / "m.db"
    archive_indexer.index_file(str(_claude_zip_memories(tmp_path)), str(db))
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        labels = {r[0] for r in conn.execute(
            "SELECT DISTINCT project FROM messages WHERE project LIKE 'memory:%'")}
        assert "memory:conversations" in labels
        assert "memory:project:proj-uuid-1" in labels   # la mappa, non una lista
        assert "memory:project:proj-uuid-2" in labels
        rows = conn.execute(
            "SELECT project FROM messages_fts WHERE messages_fts MATCH ?",
            ('"Dart e Flutter"',)).fetchall()
        assert rows and rows[0][0] == "memory:conversations"
    finally:
        conn.close()


def test_v2_users_json_indicizzato_lupload_non_filtra(tmp_path: Path) -> None:
    """`users.json` (anagrafica: nome, email, telefono) SI indicizza.

    L'ingestione non filtra: se l'utente carica un file, l'archivio lo contiene
    verbatim. Decidere all'INGRESSO che un dato è "troppo sensibile" è la stessa
    mossa che faceva `extract_text` scartando i tool_use perché "rumore" — una
    policy di output applicata dove nessuno la può più rivedere.

    La protezione dei dati sensibili è un problema di OUTPUT (mascheramento in
    ricerca, cifratura at-rest, ACL) e va risolta dove si legge.
    """
    db = tmp_path / "m.db"
    archive_indexer.index_file(str(_claude_zip_memories(tmp_path)), str(db))
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        (n,) = conn.execute(
            "SELECT count(*) FROM messages WHERE content LIKE '%x@y.z%'").fetchone()
        assert n == 1                                   # c'è, verbatim
        rows = conn.execute(
            "SELECT project FROM messages_fts WHERE messages_fts MATCH ?",
            ("neo1777",)).fetchall()
        assert any(r[0] == "account:user" for r in rows)  # ed è cercabile
    finally:
        conn.close()


def test_v2_parent_uuid_salvato(tmp_path: Path) -> None:
    """L'albero della conversazione (rami, riscritture, ritorni indietro): 11.214
    messaggi su 13.723 hanno un parent, e non se ne salvava nessuno."""
    db = tmp_path / "m.db"
    archive_indexer.index_file(str(_claude_zip_memories(tmp_path)), str(db))
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        (parent,) = conn.execute(
            "SELECT parent_uuid FROM messages WHERE uuid='m2'").fetchone()
        assert parent == "m1"
    finally:
        conn.close()


def test_v2_allegato_senza_nome_usa_uuid(tmp_path: Path) -> None:
    """80 allegati reali hanno `file_name: null` ma un `file_uuid` valido: meglio un
    id cercabile che un allegato invisibile."""
    import json
    import zipfile
    convs = [{"uuid": "c1", "name": "chat", "chat_messages": [
        {"uuid": "m1", "sender": "human", "created_at": "2026-01-01T00:00:00Z",
         "text": "ecco", "content": [{"type": "text", "text": "ecco"}],
         "files": [{"file_uuid": "5cd72e4f-dead-beef", "file_name": None}]},
    ]}]
    p = tmp_path / "e.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("conversations.json", json.dumps(convs))
    db = tmp_path / "a.db"
    archive_indexer.index_file(str(p), str(db))
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        (att,) = conn.execute("SELECT attachments FROM messages WHERE uuid='m1'").fetchone()
        assert "5cd72e4f-dead-beef" in att
    finally:
        conn.close()


# ── H39: tetti su upload/decompressione (zip-bomb / OOM) ─────────────────────
# La lezione: un limite su un input COMPRESSO non è un limite. Si conta ciò che
# l'archivio DIVENTA, byte per byte, non ciò che dichiara.


def _small_caps(monkeypatch) -> None:
    """Abbassa i tetti a valori minuscoli per testare i rami di errore senza
    dover generare gigabyte. Si patcha il modulo, non si toccano le costanti reali."""
    monkeypatch.setattr(archive_indexer, "MAX_MEMBER_BYTES", 2000)
    monkeypatch.setattr(archive_indexer, "MAX_ARCHIVE_BYTES", 4000)
    monkeypatch.setattr(archive_indexer, "MAX_FILE_BYTES", 2000)


def test_zip_member_oltre_il_tetto_fallisce_parlante(tmp_path, monkeypatch) -> None:
    import json
    import zipfile

    import pytest
    _small_caps(monkeypatch)
    # conversations.json che DECOMPRESSO supera MAX_MEMBER_BYTES (2000): un solo
    # messaggio con un text enorme. Lo zip compresso resta piccolo (zip-bomb-lite).
    convs = [{"uuid": "c1", "name": "chat", "chat_messages": [
        {"uuid": "m1", "sender": "human", "created_at": "2026-01-01", "text": "x" * 50_000},
    ]}]
    zp = tmp_path / "bomb.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("conversations.json", json.dumps(convs))
    assert zp.stat().st_size < 2000  # il COMPRESSO è sotto il tetto: il pericolo è a valle
    with pytest.raises(ValueError, match="DECOMPRESSO|tetto"):
        archive_indexer.index_file(str(zp), str(tmp_path / "o.db"))


def test_zip_troppi_membri_fallisce(tmp_path, monkeypatch) -> None:
    import zipfile

    import pytest
    monkeypatch.setattr(archive_indexer, "MAX_ZIP_MEMBERS", 5)
    zp = tmp_path / "many.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("conversations.json", "[]")
        for i in range(10):
            z.writestr(f"projects/p{i}.json", "{}")
    with pytest.raises(ValueError, match="troppi file"):
        archive_indexer.index_file(str(zp), str(tmp_path / "o.db"))


def test_budget_cumulativo_su_piu_membri(tmp_path, monkeypatch) -> None:
    import json
    import zipfile

    import pytest
    # Ogni membro sta sotto MAX_MEMBER_BYTES, ma la SOMMA supera MAX_ARCHIVE_BYTES:
    # è la zip-bomb "a tanti file medi". Il budget condiviso deve fermarla.
    monkeypatch.setattr(archive_indexer, "MAX_MEMBER_BYTES", 100_000)
    monkeypatch.setattr(archive_indexer, "MAX_ARCHIVE_BYTES", 3000)
    dc = {"uuid": "d", "title": "Chat", "messages": [
        {"uuid": "m", "role": "user", "created_at": "2026-01-01",
         "content": {"role": "user", "content": "y" * 2000}}]}
    zp = tmp_path / "sum.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("conversations.json", "[]")
        for i in range(5):
            z.writestr(f"design_chats/d{i}.json", json.dumps(dc))
    with pytest.raises(ValueError, match="archivio supera"):
        archive_indexer.index_file(str(zp), str(tmp_path / "o.db"))


def test_file_jsonl_oltre_il_tetto(tmp_path, monkeypatch) -> None:
    import json

    import pytest
    _small_caps(monkeypatch)
    big = tmp_path / "big.jsonl"
    line = json.dumps({"type": "user", "uuid": "u1", "timestamp": "t",
                       "message": {"content": "z" * 5000}})
    big.write_text(line + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="troppo grande|MAX_FILE"):
        archive_indexer.index_file(str(big), str(tmp_path / "o.db"))


def test_zip_normale_sotto_i_tetti_passa(tmp_path) -> None:
    import json
    import zipfile
    # Guardia di non-regressione: coi tetti REALI un export piccolo passa liscio.
    convs = [{"uuid": "c1", "name": "chat", "chat_messages": [
        {"uuid": "m1", "sender": "human", "created_at": "2026-01-01", "text": "ciao"}]}]
    zp = tmp_path / "ok.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("conversations.json", json.dumps(convs))
    assert archive_indexer.index_file(str(zp), str(tmp_path / "o.db")) == 1


def test_meta_description(tmp_path: Path) -> None:
    """La descrizione dell'archivio (D5) vive nella tabella `meta`: scritta con
    set_meta (upload admin / tool MCP), letta con get_meta, superficiata da
    db_info. Assente → stringa vuota, mai un errore."""
    md = tmp_path / "n.md"
    md.write_text("# t\n\ncorpo", encoding="utf-8")
    db = tmp_path / "out.db"
    archive_indexer.index_file(str(md), str(db))
    assert archive_indexer.get_meta(db, "description") == ""
    assert archive_indexer.db_info(db)["description"] == ""
    archive_indexer.set_meta(db, "description", "note di lavoro 1777")
    assert archive_indexer.get_meta(db, "description") == "note di lavoro 1777"
    assert archive_indexer.db_info(db)["description"] == "note di lavoro 1777"


def test_skipped_no_collapse(tmp_path: Path) -> None:
    """Il caso provato da b82df434 (16/07): tre scarti GEMELLI (stesso tipo, niente
    ts) devono produrre TRE lapidi, non una. L'uid era sha1(source·reason·detail·ts)
    con detail=tipo e ts vuoto → collassavano via INSERT OR IGNORE: il contatore
    della perdita perdeva. Ora il detail porta la posizione nel file (unica per riga,
    stabile fra re-ingest: dedup fra ingest sì, collasso dentro l'ingest no)."""
    p = tmp_path / "s.jsonl"
    p.write_text("\n".join([
        '{"type":"user","uuid":"ok1","timestamp":"2026-01-01T00:00:00Z","message":{"content":"valido"}}',
        '{"type":"user","message":{"content":"senza ts 1"}}',
        '{"type":"user","message":{"content":"senza ts 2"}}',
        '{"type":"user","message":{"content":"senza ts 3"}}',
    ]), encoding="utf-8")
    db = tmp_path / "out.db"
    n = archive_indexer.index_file(str(p), str(db))
    assert n == 1  # solo il valido
    assert archive_indexer.count_skipped(db) == 3  # TRE lapidi, non una
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        details = [r[0] for r in conn.execute(
            "SELECT detail FROM skipped WHERE reason='no-uuid-o-ts' ORDER BY detail").fetchall()]
        assert len(details) == 3 and len(set(details)) == 3  # uniche
    finally:
        conn.close()
    # la proprietà che NON va persa: re-ingest dello stesso file NON duplica le lapidi
    archive_indexer.index_file(str(p), str(db))
    assert archive_indexer.count_skipped(db) == 3


def test_claude_code_metadati(tmp_path: Path) -> None:
    """Le righe non-user/assistant NON spariscono più in un continue muto (D3, 17/07):
    i metadati operativi lasciano una lapide 'non-message' (contata → la quadratura
    chiude), l'ai-title diventa una riga cercabile e l'attachment coi nomi-file è
    indicizzato (parità col path claude.ai)."""
    p = tmp_path / "s.jsonl"
    p.write_text("\n".join([
        '{"type":"user","uuid":"u1","timestamp":"2026-01-01T00:00:00Z","message":{"content":"ciao"}}',
        '{"type":"ai-title","aiTitle":"CHIAVETITOLO configurazione tick","sessionId":"s1"}',
        '{"type":"attachment","uuid":"att1","timestamp":"2026-01-01T00:00:01Z","cwd":"/x/proj","parentUuid":"u1","attachment":{"addedNames":["CHIAVEFILE.dart"]}}',
        '{"type":"mode","sessionId":"s1"}',            # metadato operativo → lapide
        '{"type":"queue-operation","sessionId":"s1"}', # idem
    ]), encoding="utf-8")
    db = tmp_path / "out.db"
    n = archive_indexer.index_file(str(p), str(db))
    assert n == 3  # user + ai-title + attachment (indicizzati)
    assert archive_indexer.count_skipped(db) == 2  # mode + queue-operation (contati, non spariti)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        assert conn.execute("SELECT count(*) FROM messages_fts WHERE messages_fts MATCH 'CHIAVETITOLO'").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM messages_fts WHERE messages_fts MATCH 'CHIAVEFILE'").fetchone()[0] == 1
        reasons = sorted(r[0] for r in conn.execute("SELECT reason FROM skipped").fetchall())
        assert reasons == ["non-message", "non-message"]
    finally:
        conn.close()
