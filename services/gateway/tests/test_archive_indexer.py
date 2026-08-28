"""Test dell'indexer archive (stdlib-only, offline)."""
from __future__ import annotations

import json
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
    # ── EMPTY-BLOCK: blocchi PRESENTI ma vuoti (aggiunti 25/07 da abdd732a) ────────
    # 🔴 Perché non bastava `content: []`: il divario di **+6.919 record** del 17/07 non
    #   veniva dai messaggi senza contenuto, ma da quelli col contenuto DICHIARATO E VUOTO
    #   (9.813 casi nel bundle). Il contratto copriva la lista vuota e NON questa classe:
    #   il canary restava verde su una fixture di 9 righe che non conteneva il caso per cui
    #   il canary esiste. *Il divario lo trovò un diff full-bundle, non la guardia.*
    # ⭐ Una guardia va collaudata sul caso che deve PRENDERE — e su quello che deve
    #   LASCIAR PASSARE: l'ultimo record qui sotto è la controprova (testo vero → keep).
    #   Senza di lei, «tutto skip» passerebbe il test come fosse un successo.
    '{"type":"user","uuid":"u-txt0","timestamp":"2026-01-01T10:00:03Z","message":{"role":"user","content":[{"type":"text","text":""}]}}',
    '{"type":"assistant","uuid":"a-think0","timestamp":"2026-01-01T10:00:04Z","message":{"role":"assistant","content":[{"type":"thinking","thinking":""}]}}',
    '{"type":"user","uuid":"u-tr0","timestamp":"2026-01-01T10:00:05Z","message":{"role":"user","content":[{"type":"tool_result","content":""}]}}',
    '{"type":"user","uuid":"u-ok","timestamp":"2026-01-01T10:00:06Z","message":{"role":"user","content":[{"type":"text","text":"vero"}]}}',
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
        "skip:empty",          # content: [] — lista vuota
        "skip:empty",          # text: ""      — blocco presente, vuoto
        "skip:empty",          # thinking: ""  — idem
        "skip:empty",          # tool_result vuoto — idem
        "keep:user",           # CONTROPROVA: testo vero → deve PASSARE
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

    ✅ AGGIORNATO 02/08: LA PRIMA DELLE TRE ORA ESISTE — e questa riga va letta con
    la precisione con cui è stato scritto il buco, perché la frase sopra è ciò che
    rende accettabile l'indicizzazione verbatim.
      · `services/archive-mcp/app/redazione.py` + la sostituzione di `mcp.tool` in
        `server.py`: ogni tool esce redatto, e uno NUOVO lo eredita per costruzione
        (verificato con l'AST da `test_redazione_copre_tutti_i_tool`)
      · scelta fra le tre e sua ragione nel docstring di `redazione.py`; decisione
        di Neo del 02/08 07:09 («la migliore, non la più economica»)
    🔴 E COSA **NON** COPRE, provato da un test invece che dichiarato
    (`test_il_limite_dichiarato_e_vero`) — un filtro sui dati sensibili si giudica
    sui FALSI NEGATIVI, non sui falsi positivi:
      · escono redatti: email e telefoni OVUNQUE (transcript compresi) e i valori
        dell'anagrafica anche scritti a mano dentro un messaggio
      · NON esce redatto: un dato personale senza formato riconoscibile e assente
        dall'anagrafica — il nome di un terzo dentro una conversazione
      · il DB su disco resta IN CHIARO: questo è mascheramento in uscita, non
        cifratura at-rest. Delle tre, le altre due restano da fare.
    ⇒ la frase difendibile non è «i dati personali non escono in chiaro»: è
      «gli identificatori in formato riconoscibile e l'anagrafica non escono in
      chiaro da nessun tool». Più stretta, e vera.

    ⭐ Il ragionamento resta giusto: filtrare all'INGRESSO è la mossa sbagliata.
    📌 Reperto da non perdere: fino al 02/08 questa docstring prometteva tre
    protezioni che non esistevano — «va risolta dove si legge» faceva sembrare
    decisa una zona che nessuno aveva deciso, ed è il compenso citato che rende
    invisibile il debito. Il difetto non era l'indicizzazione: era la promessa.
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


# ═══════════════════════════════════════════════════════════════════════════
# D10/§1 — SNIFF DEL CONTENUTO e D18 — REVISIONI (20/07/2026)
# Due decisioni di Neo nello stesso giro. I test stanno insieme perché insieme
# chiudono la stessa domanda: «cosa fa l'indexer con ciò che non riconosce, e
# con ciò che cambia sotto lo stesso identificatore?»
# ═══════════════════════════════════════════════════════════════════════════

def test_sniff_riconosce_il_testo_travestito():
    """Un file fuori whitelist che È testo va letto, non seppellito.

    Sul bundle reale erano 829 su 2.633 «non-testo» (31%): appunti senza
    estensione, todo, script, Dockerfile, .cjs/.proto/.service/.xsd/.ndjson.
    La classificazione per estensione è un'ETICHETTA, non una misura.
    """
    from archive_indexer import _sniff_e_testo
    assert _sniff_e_testo(b"#!/bin/sh\necho ciao")            # script senza estensione
    assert _sniff_e_testo(b'{"a":1}\n{"b":2}')                # ndjson
    assert _sniff_e_testo("appunti: à è ì ò ù 🔧".encode())    # utf-8 con accenti ed emoji


def test_sniff_non_promuove_i_binari():
    """Il collaudo che conta: i NEGATIVI.

    Un criterio troppo generoso infilerebbe spazzatura binaria nell'indice
    full-text — peggio del problema che risolve.
    """
    from archive_indexer import _sniff_e_testo
    assert not _sniff_e_testo(b"\x89PNG\r\n\x1a\n\x00\x00")   # NUL ⇒ binario
    assert not _sniff_e_testo(b"\xff\xd8\xff\xe0JFIF")        # jpeg
    assert not _sniff_e_testo(b"")                            # vuoto
    assert not _sniff_e_testo(b"\x00" * 10)


def _riga(uuid, contenuto, ts="2026-01-01T00:00:00Z"):
    return (uuid, "proj:test", ts, contenuto, "human", "", "", "", "")


def test_revisioni_non_nascono_su_dati_immutabili(tmp_path):
    """Il NEGATIVO dichiarato da setaccio prima del merge: re-ingerire dati
    immutabili deve produrre ZERO revisioni. Anche una sola = c'è un bug,
    oppure abbiamo scoperto un contenuto che cambia e non lo sapevamo."""
    from archive_indexer import write_rows
    db = tmp_path / "a.db"
    write_rows(db, [_riga("u1", "testo"), _riga("u2", "altro")])
    write_rows(db, [_riga("u1", "testo"), _riga("u2", "altro")])
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT count(*) FROM revisions").fetchone()[0] == 0


def test_revisioni_conservano_la_versione_uscente(tmp_path):
    """Il caso `memory:*`: stesso uuid, contenuto diverso fra due export.

    Prima di questa modifica l'INSERT OR REPLACE faceva vincere l'ultimo e il
    primo spariva senza traccia. Le versioni sopravvivevano solo perché stavano
    in DB separati — un accidente della topologia, non una proprietà.
    """
    from archive_indexer import write_rows
    db = tmp_path / "b.db"
    write_rows(db, [_riga("slot", "versione di maggio")])
    write_rows(db, [_riga("slot", "versione di luglio")])
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT content FROM messages WHERE uuid='slot'").fetchone()[0] \
            == "versione di luglio"          # la ricerca vede l'ultima: API invariata
        assert c.execute("SELECT content FROM revisions WHERE uuid='slot'").fetchone()[0] \
            == "versione di maggio"          # la storia non si perde


def test_revisioni_si_accumulano_e_sono_idempotenti(tmp_path):
    from archive_indexer import write_rows
    db = tmp_path / "c.db"
    for testo in ("prima", "seconda", "terza"):
        write_rows(db, [_riga("s", testo)])
    write_rows(db, [_riga("s", "terza")])     # ri-mando la corrente: nulla di nuovo
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT count(*) FROM revisions WHERE uuid='s'").fetchone()[0] == 2


def test_ts_source_esiste_e_il_default_e_messaggio(tmp_path):
    """Il regime del dato promosso da nota a schema: senza questa colonna, un ts
    sintetico (data-export) sarebbe indistinguibile da un ts vero, e il `newest`
    dichiarerebbe un istante in cui nessun messaggio è mai esistito."""
    from archive_indexer import write_rows
    db = tmp_path / "d.db"
    write_rows(db, [_riga("x", "y")])
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT ts_source FROM messages WHERE uuid='x'").fetchone()[0] == "messaggio"


def test_migrazione_db_preesistente_non_perde_dati(tmp_path):
    """I nove archivi vivi sono nati prima di questa versione: la migrazione
    deve essere trasparente."""
    from archive_indexer import write_rows
    db = tmp_path / "vecchio.db"
    with sqlite3.connect(db) as c:
        c.executescript(
            "CREATE TABLE messages(uuid TEXT PRIMARY KEY, project TEXT, ts TEXT, content TEXT,"
            " sender TEXT DEFAULT '', tools TEXT DEFAULT '', thinking TEXT DEFAULT '',"
            " attachments TEXT DEFAULT '', parent_uuid TEXT DEFAULT '');")
        c.execute("INSERT INTO messages(uuid,project,ts,content) VALUES('old','p','2026-05-01','storico')")
    write_rows(db, [_riga("new", "nuovo")])
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT content FROM messages WHERE uuid='old'").fetchone()[0] == "storico"
        # ⚠️ Questa riga asseriva 'messaggio' e PASSAVA: il test codificava il difetto che
        # b82df434 ha poi trovato in 2ª lettura (una riga migrata NON è un messaggio noto —
        # può essere una memory). Un test verde che certifica il comportamento sbagliato è
        # peggio di nessun test: dà la conferma che nessuno andrà a ricontrollare.
        assert c.execute("SELECT ts_source FROM messages WHERE uuid='old'").fetchone()[0] == "ignoto"
        c.execute("SELECT count(*) FROM revisions")   # la tabella ora esiste


def test_migrazione_non_dichiara_messaggio_cio_che_non_sa(tmp_path):
    """Finding bloccante di b82df434 (2ª lettura, 20/07), prima del merge.

    `ALTER TABLE … ADD COLUMN ts_source DEFAULT 'messaggio'` assegna 'messaggio'
    a TUTTE le righe già in tabella — comprese `memory:*` e `account:user`, che
    NON sono messaggi ma slot riscrivibili: cioè proprio ciò per cui la colonna
    esiste. Sarebbe stata la bugia opposta, scritta in un colpo solo su nove
    archivi vivi, e con l'aria di un dato verificato.
    Il regime di una riga preesistente NON è conoscibile a posteriori: 'ignoto'
    è l'unica etichetta vera.
    """
    from archive_indexer import write_rows
    db = tmp_path / "mig.db"
    with sqlite3.connect(db) as c:
        c.executescript(
            "CREATE TABLE messages(uuid TEXT PRIMARY KEY, project TEXT, ts TEXT, content TEXT,"
            " sender TEXT DEFAULT '', tools TEXT DEFAULT '', thinking TEXT DEFAULT '',"
            " attachments TEXT DEFAULT '', parent_uuid TEXT DEFAULT '');")
        c.execute("INSERT INTO messages(uuid,project,ts,content)"
                  " VALUES('mem','memory:conversations','','slot riscrivibile')")
        c.execute("INSERT INTO messages(uuid,project,ts,content)"
                  " VALUES('msg','proj:x','2026-05-01','un messaggio vero')")
    write_rows(db, [_riga("nuovo", "scritto ora")])
    with sqlite3.connect(db) as c:
        reg = dict(c.execute("SELECT uuid, ts_source FROM messages"))
    # Il discrimine NON è «vecchia o nuova»: è **se un ts c'è**. Ci sono voluti tre giri
    # (default secco → tutte non-classificate → questa) e due bocciature reciproche:
    # b82df434 ha bocciato la prima (asserisce un regime mai verificato sulle memory),
    # setaccio ha bocciato la seconda (errore SIMMETRICO: negare 'messaggio' a righe-evento
    # vere avrebbe reso NULL il newest di nove DB, rompendo ciò che il requisito proteggeva).
    # La proposta «ts pieno ⇒ messaggio» è stata scartata da una MISURA: su cc-bundle-200726,
    # delle 221.514 righe con ts pieno **140.476 (63,4%) non sono conversazioni** — workfile,
    # mcp-log e documenti, il cui ts è il timestamp del file nello zip. Asserzione falsa su
    # quasi due terzi dell'archivio.
    assert reg["mem"] == "ignoto", "una memory migrata NON può risultare 'messaggio'"
    assert reg["msg"] == "ignoto", "nemmeno una riga con ts: il ts può venire dal filesystem"
    assert reg["nuovo"] == "messaggio", "ciò che entra ORA dall'ingest ha il regime noto"


def test_newest_si_calcola_in_negativo(tmp_path):
    """Corollario del fix: il filtro per il `newest` va scritto su ciò che si SA
    (`<> 'data-export'`), non su ciò che si presume (`= 'messaggio'`).

    Con la forma positiva, su un DB migrato le righe 'ignoto' sparirebbero dal
    calcolo — cioè quasi tutte — e il newest risulterebbe troppo VECCHIO.
    """
    from archive_indexer import write_rows
    db = tmp_path / "new.db"
    with sqlite3.connect(db) as c:
        c.executescript(
            "CREATE TABLE messages(uuid TEXT PRIMARY KEY, project TEXT, ts TEXT, content TEXT,"
            " sender TEXT DEFAULT '', tools TEXT DEFAULT '', thinking TEXT DEFAULT '',"
            " attachments TEXT DEFAULT '', parent_uuid TEXT DEFAULT '');")
        c.execute("INSERT INTO messages(uuid,project,ts,content)"
                  " VALUES('vecchio','p','2026-07-19T10:00:00Z','recente ma migrato')")
    write_rows(db, [_riga("nuovo", "meno recente", "2026-01-01T00:00:00Z")])
    with sqlite3.connect(db) as c:
        negativo = c.execute("SELECT MAX(ts) FROM messages WHERE ts_source <> 'data-export'").fetchone()[0]
        positivo = c.execute("SELECT MAX(ts) FROM messages WHERE ts_source = 'messaggio'").fetchone()[0]
    assert negativo == "2026-07-19T10:00:00Z", "la forma negativa vede le righe 'ignoto': corretta"
    # ⚠️ QUESTO SECONDO ASSERT È IL CUORE DEL TEST, non un di più (b82df434, 20/07).
    # In un giro di refactoring era stato tolto, lasciando solo la verifica che la forma GIUSTA
    # funzioni. Ma `= 'messaggio'` è la forma più naturale da scrivere — era la mia prima
    # versione — e senza questa riga la suite resterebbe VERDE mentre qualcuno la "semplifica",
    # riportando il difetto. Un test che protegge un comportamento ma non la DECISIONE che c'è
    # sotto lascia scoperto proprio ciò che è costato tre giri e due bocciature.
    assert positivo != negativo, "la forma positiva DEVE sbagliare: esclude le righe 'ignoto'"
    assert positivo == "2026-01-01T00:00:00Z", "…e sbaglia dando un newest troppo VECCHIO"


# ═══════════════════════════════════════════ VOICE-TAGGING — Fase 1 (speaker) ══

def test_speaker_da_sender_traduce_solo_cio_che_sa():
    """`speaker` è un FATTO: ciò che la fonte non dice resta 'unknown'."""
    f = archive_indexer.speaker_da_sender
    assert f("user") == "human"
    assert f("assistant") == "assistant"
    assert f("USER") == "human", "il case della fonte non deve cambiare il verdetto"
    assert f("  user  ") == "human", "né gli spazi"
    # ⚠️ IL CUORE DEL TEST, e la ragione per cui queste colonne esistono (b82df434, 02/08).
    # `attachment` e `title` sono nature della RIGA, non mittenti — misurato su un DB vivo:
    # 2.327 + 1.132 righe su 61.100. La tentazione naturale è mapparle su 'human' (un
    # allegato l'ha caricato un umano, no?) o su 'assistant'. Entrambe fabbricherebbero
    # un'attribuzione che la fonte NON contiene, che è esattamente il difetto che il
    # voice-tagging esiste per curare. Se qualcuno "completa" la mappa, questo test cade.
    assert f("attachment") == "unknown", "un allegato non dice CHI l'ha scritto"
    assert f("title") == "unknown", "un titolo non è un mittente"
    assert f("memory") == "unknown"
    assert f("") == "unknown"
    assert f(None) == "unknown", "nessun crash sul NULL della colonna"
    assert f("Mario Rossi") == "unknown", (
        "un nome sconosciuto NON diventa 'human' per somiglianza: la spec prevede i nomi "
        "Telegram come umani, ma da qui nome-persona ed etichetta-di-sistema sono "
        "indistinguibili. Si tara in Fase 2, col golden-set.")


def _db_v2(tmp_path: Path, righe) -> Path:
    """Un DB nello schema v2 (senza le colonne del voice-tagging), come quelli già vivi."""
    db = tmp_path / "v2.db"
    with sqlite3.connect(db) as c:
        c.execute(
            "CREATE TABLE messages(uuid TEXT PRIMARY KEY, project TEXT, ts TEXT,"
            " content TEXT, sender TEXT DEFAULT '', tools TEXT DEFAULT '',"
            " thinking TEXT DEFAULT '', attachments TEXT DEFAULT '',"
            " parent_uuid TEXT DEFAULT '', ts_source TEXT DEFAULT 'messaggio')")
        c.executemany("INSERT INTO messages(uuid,project,ts,content,sender)"
                      " VALUES(?,?,?,?,?)", righe)
    return db


def test_migrate_v3_aggiunge_colonne_e_deriva_speaker(tmp_path: Path):
    db = _db_v2(tmp_path, [
        ("u1", "p", "2026-01-01T00:00:00Z", "domanda", "user"),
        ("a1", "p", "2026-01-01T00:00:01Z", "risposta", "assistant"),
        ("t1", "p", "2026-01-01T00:00:02Z", "un titolo", "title"),
        ("f1", "p", "2026-01-01T00:00:03Z", "un allegato", "attachment"),
    ])
    assert archive_indexer.migrate_v2_to_v3(db) is True
    with sqlite3.connect(db) as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(messages)")}
        assert {"speaker", "voice", "quoted_share", "voice_conf", "content_flags"} <= cols
        got = dict(c.execute("SELECT uuid, speaker FROM messages"))
        vuoti = c.execute("SELECT count(*) FROM messages WHERE speaker=''").fetchone()[0]
        # 🔻 AGGIORNATO 02/08 (Fase 3): questa riga asseriva `voice == 0` — «la Fase 1 non
        #    deve scrivere `voice`, è una stima e la stima arriva in Fase 2». La ragione
        #    era ed è giusta, ma diceva **una cosa più stretta di quello che voleva dire**:
        #    proibiva il valore invece di pretendere che fosse CALCOLATO. Ora la migrazione
        #    chiama `popola_voice`, quindi la stima c'è ed è legittima — e il principio
        #    resta, girato dalla parte utile: dopo la migrazione **nessuna riga resta senza
        #    classificazione**, perché una colonna a metà è peggio di una vuota (chi la
        #    interroga non distingue «non è di quel tipo» da «non è mai stata guardata»).
        senza_voice = c.execute("SELECT count(*) FROM messages WHERE voice=''").fetchone()[0]
        voci = c.execute("SELECT count(*) FROM messages WHERE voice<>''").fetchone()[0]
    assert got == {"u1": "human", "a1": "assistant", "t1": "unknown", "f1": "unknown"}
    assert vuoti == 0, "dopo la migrazione nessuna riga resta senza asse-mittente"
    assert senza_voice == 0, (
        "una riga con `voice=''` dopo la migrazione è una riga che NESSUNO ha guardato, e "
        "sui filtri della Fase 3 sarebbe indistinguibile da una riga 'di un altro tipo'")
    assert voci == 4, "e la classificazione dev'essere stata CALCOLATA, non lasciata al default"


def test_migrate_v3_e_idempotente(tmp_path: Path):
    db = _db_v2(tmp_path, [("u1", "p", "2026-01-01T00:00:00Z", "x", "user")])
    assert archive_indexer.migrate_v2_to_v3(db) is True
    assert archive_indexer.migrate_v2_to_v3(db) is False, "la seconda volta non migra nulla"
    with sqlite3.connect(db) as c:
        assert archive_indexer.popola_speaker(c) == 0, "e non riscrive nessuna riga"
        assert c.execute("SELECT speaker FROM messages").fetchone()[0] == "human"


def test_speaker_non_sovrascrive_un_valore_gia_scritto(tmp_path: Path):
    """`popola_speaker` tocca SOLO `speaker=''`.

    Serve perché la Fase 2 (e il retag della Fase 4) scriveranno valori più precisi di
    quelli derivabili da `sender` — es. un nome Telegram riconosciuto come umano. Se la
    derivazione li riscrivesse a ogni ingest, il lavoro fine verrebbe cancellato dal
    lavoro grezzo, e in silenzio.
    """
    db = _db_v2(tmp_path, [("u1", "p", "2026-01-01T00:00:00Z", "x", "Mario Rossi")])
    archive_indexer.migrate_v2_to_v3(db)
    with sqlite3.connect(db) as c:
        c.execute("UPDATE messages SET speaker='human' WHERE uuid='u1'")
        assert archive_indexer.popola_speaker(c) == 0
        assert c.execute("SELECT speaker FROM messages").fetchone()[0] == "human"


# ═══════════════════════════ VOICE-TAGGING — Fase 2 (classify_voice) ══
# Il principio di taratura e' ASIMMETRICO (spec §2): falsi negativi accettabili,
# falsi positivi CARI. Questi test lo proteggono nei due versi.

def test_classify_il_falso_positivo_e_il_caso_che_conta():
    """Una frase VERA di chi scrive non deve MAI diventare `pasted`.

    ⚠️ E' il test piu' importante dei cinque, ed e' quello che si e' tentati di
    non scrivere perche' «tanto non succede». Il caso-C++ e' successo proprio
    cosi': una frase vera attribuita alla persona sbagliata. Qui la direzione e'
    l'altra — una frase propria marcata come altrui — e il costo e' lo stesso:
    l'archivio smette di poter dire di chi sono le parole.
    """
    v = archive_indexer.classify_voice(
        "Io il C++ praticamente non lo conosco. Io sono Dart, e sono un amatoriale. "
        "Ne parlavamo ieri alle 14:30 e anche stamattina alle 9:15.",
        sender="user", project="chat qualunque")
    assert v[0] == "own", f"una frase propria con due ORARI dentro resta own, non {v[0]}"
    assert v[2] >= 0.5


def test_classify_transcript_serve_piu_di_un_segnale():
    testo = "(0:12) allora vediamo (1:45) come dicevo (2:30) e qui si chiude"
    # con il titolo-trappola: due segnali indipendenti → transcript
    v = archive_indexer.classify_voice(testo, sender="user", project="Analisi transcript video")
    assert v[0] == "pasted_transcript"
    assert "video_ts" in v[3] and "trap_title" in v[3], "le bandiere sono l'autopsia del verdetto"
    # ⚠️ SENZA il titolo, TRE timestamp NON bastano — e questo test l'ha scoperto
    # cadendo: la mia aspettativa era piu' permissiva del codice, e il codice aveva
    # ragione. Tre orari citati in una chat sono plausibili («alle 9:15, alle 14:30
    # e alle 18:00»); un transcript vero ne ha decine. Il principio dice falsi
    # positivi CARI ⇒ da solo, il segnale deve essere molto forte (TS_VIDEO_MIN*3).
    v2 = archive_indexer.classify_voice(testo, sender="user", project="chat")
    assert v2[0] != "pasted_transcript", "tre timestamp da soli non bastano"
    assert "video_ts" in v2[3], "ma la bandiera si alza lo stesso: il segnale c'e', non basta"
    # con SEI, il segnale e' forte abbastanza da reggere da solo
    molti = testo + " (3:10) e poi (4:20) e infine (5:00)"
    v3 = archive_indexer.classify_voice(molti, sender="user", project="chat")
    assert v3[0] == "pasted_transcript"
    assert v3[2] < v[2], "ma con UN segnale solo la CONFIDENZA resta sotto quella a due"


def test_classify_character_vuole_il_progetto_E_la_recita():
    """Il project da solo NON basta piu' — e lo dice una MISURA, non un'opinione.

    La regola originale («il project lo dichiara, la piu' affidabile delle
    sette») e' stata giudicata dal golden set del 27/08: 0/8, con 4 own veri
    marcati character — i falsi CARI che il principio vieta. Il nome del
    progetto dice il DOMINIO, non che questo messaggio e' recitato: dentro
    «GDR» l'owner apre PR e da' istruzioni in voce propria.
    """
    # progetto GDR + recita nel testo (azione fra asterischi) → character
    v = archive_indexer.classify_voice("*si siede al tavolo* Il mago avanza di due caselle.",
                                       sender="user", project="GDR1777 — il caso graphify")
    assert v[0] == "character"
    assert "project_gdr" in v[3] and "recita" in v[3], "servono ENTRAMBI i segnali"
    # progetto GDR ma voce propria (il caso 6/7 del gold): own, non character
    v2 = archive_indexer.classify_voice("Perfetto, se abbiamo tutto procediamo con issue o pr",
                                        sender="user", project="GDR1777 — il caso graphify")
    assert v2[0] == "own", f"chi lavora SUL progetto parla in voce propria (era {v2[0]})"
    assert "project_gdr" in v2[3], "ma la bandiera resta: il segnale c'e', non basta"
    # il **grassetto** markdown non e' una recita
    v3 = archive_indexer.classify_voice("questo e' **importante** da capire",
                                        sender="user", project="GDR1777")
    assert v3[0] == "own", "gli asterischi doppi sono markdown, non un'azione RP"


def test_classify_pasted_ai_parla_anche_italiano():
    """La regola vecchia assumeva AI=inglese: sul gold `pasted_ai` MAI emessa
    contro 8 casi veri, tutti in italiano. I segnali veri del corpus sono tre.
    """
    # ① il tick di automazione: header [… TICK …] in apertura
    v = archive_indexer.classify_voice(
        "[CRON TICK Linux — canale su NotebookLM | interval 10min]\n\n"
        "Sei in tick automatico headless, nessuna interazione possibile.",
        sender="user", project="dashboard")
    assert v[0] == "pasted_ai" and "cron_tick" in v[3]
    # ② l'incipit di assegnazione di ruolo, anche dietro il prefisso dell'ingest
    v2 = archive_indexer.classify_voice(
        "[human] Role: Sei un esperto di NLP e ottimizzazione testuale.",
        sender="human", project="chat")
    assert v2[0] == "pasted_ai" and "prompt_template" in v2[3]
    # ③ struttura da template SENZA incipit — e con le newline COLLASSATE in
    #   doppi spazi, come fa un ingest di questo corpus (misurato: 35k char, 0 \n)
    v3 = archive_indexer.classify_voice(
        "Trasforma la trascrizione seguendo questi passi.  # Steps  "
        "1. **Analisi**: individua i temi.  2. **Espansione**: arricchisci.  "
        "3. **Verifica**: rileggi tutto.",
        sender="human", project="chat")
    assert v3[0] == "pasted_ai", f"heading+numerato+grassetti = template (era {v3[0]})"
    # ④ il confine del falso caro: la STESSA struttura da un assistant e' la sua
    #   prosa normale, non un incollato
    v4 = archive_indexer.classify_voice(
        "Ecco il piano.  # Steps  1. **Analisi**: i temi.  2. **Espansione**: "
        "arricchisci.  3. **Verifica**: rileggi.",
        sender="assistant", project="chat")
    assert v4[0] == "own", f"per un assistant heading e grassetti sono prosa (era {v4[0]})"
    # ⑤ e una frase propria che NOMINA un ruolo non e' un template
    v5 = archive_indexer.classify_voice(
        "secondo me il ruolo: quello del revisore, non fa per me",
        sender="human", project="chat")
    assert v5[0] == "own", "un'etichetta sola in mezzo alla prosa non basta"


def test_classify_blocco_inglese_da_umano_e_MIXED_non_pasted_ai():
    """Il caso-scuola: l'umano scrive la cornice, l'AI il materiale.

    Fondere i due assi renderebbe questo caso inesprimibile — ed e' il caso che
    ci ha fatto sbagliare. `speaker=human` E `voice=mixed`: entrambi veri.
    """
    testo = ("Guarda cosa mi ha risposto:\n"
             "The system should be designed with the assumption that the network "
             "is not reliable, and that any of the components can fail at any time; "
             "this is the only way to build software that will not surprise you in "
             "production when it matters the most for the users of the platform.")
    v = archive_indexer.classify_voice(testo, sender="user", project="chat")
    assert v[0] == "mixed", f"da umano e' mixed, non pasted_ai (era {v[0]})"
    assert "en_in_it" in v[3]
    # lo stesso testo da un assistant non ha una cornice umana davanti
    v2 = archive_indexer.classify_voice(testo, sender="assistant", project="chat")
    assert v2[0] == "pasted_ai"


def test_classify_non_inventa_su_cio_che_non_sa():
    """Vuoto e mittente ignoto: `unknown`, non un default comodo."""
    assert archive_indexer.classify_voice("")[0] == "unknown"
    assert archive_indexer.classify_voice("   \n  ")[0] == "unknown"
    v = archive_indexer.classify_voice("testo qualunque senza bandiere",
                                       sender="attachment", project="doc")
    assert v[0] == "unknown", "un allegato non dice chi ha scritto: non e' own"
    assert v[2] == 0.0, "e la confidenza zero lo dichiara"


# ════════════════ VOICE-TAGGING — il POPOLAMENTO, che alla Fase 2 mancava ══════
# 🔴 Il difetto che questi test avrebbero preso e non c'era nessuno a prenderlo:
#    `classify_voice` esisteva, era testata da nove casi, ed era chiamata SOLO dai
#    test. Nessun punto del codice di produzione la usava ⇒ la colonna `voice` era
#    vuota su tutto l'archivio, e i filtri della Fase 3 avrebbero risposto ZERO a
#    ogni interrogazione, senza un errore e senza un log.
# ⭐ La Fase 2 SEMBRAVA fatta perché aveva le due cose che si guardano — la funzione
#    e i suoi test. Mancava l'unica che conta: qualcuno che la chiami.

def test_ingest_classifica_la_voce_delle_righe_che_scrive(tmp_path: Path):
    """DOPO un ingest, `voice` è popolato. È il test che avrebbe preso il buco.

    Non prova `classify_voice` (ci sono già nove casi per quello): prova che
    l'indexer LA CHIAMI. Sono due cose diverse, e per una settimana solo la prima
    era coperta.
    """
    src = tmp_path / "c.jsonl"
    src.write_text(
        '{"uuid":"u1","sessionId":"s","type":"user",'
        '"message":{"role":"user","content":"una frase mia qualunque"},'
        '"timestamp":"2026-01-01T00:00:00Z"}\n', encoding="utf-8")
    db = tmp_path / "a.db"
    archive_indexer.index_jsonl(str(src), str(db), project="p")

    with sqlite3.connect(db) as c:
        vuoti = c.execute("SELECT count(*) FROM messages WHERE voice=''").fetchone()[0]
        tutte = c.execute("SELECT count(*) FROM messages").fetchone()[0]
    assert tutte > 0, "l'ingest non ha scritto niente: il test non prova nulla"
    assert vuoti == 0, (
        "riga ingerita e MAI classificata: `voice=''` sopravvive all'ingest. È il "
        "difetto della Fase 2 — la funzione c'era e non la chiamava nessuno")


def test_popola_voice_e_idempotente_e_non_ritocca_i_giudizi(tmp_path: Path):
    """Seconda passata: zero righe. E `unknown` NON viene ri-classificato.

    🔑 `unknown` è un GIUDIZIO («guardata, non riconosciuta»), non un vuoto. Se
    `popola_voice` lo ripescasse, ogni ritocco delle soglie riscriverebbe in
    silenzio decisioni già prese — e il retag della Fase 4 non avrebbe più un
    prima/dopo da confrontare.
    """
    db = _db_v2(tmp_path, [("u1", "p", "2026-01-01T00:00:00Z", "x", "user"),
                           ("u2", "p", "2026-01-01T00:01:00Z", "y", "attachment")])
    archive_indexer.migrate_v2_to_v3(db)
    with sqlite3.connect(db) as c:
        assert archive_indexer.popola_voice(c) == 0, "la seconda passata deve scrivere ZERO"
        unknown = c.execute("SELECT count(*) FROM messages WHERE voice='unknown'").fetchone()[0]
        assert unknown > 0, "il caso serve: senza righe `unknown` non prova niente"
        assert archive_indexer.popola_voice(c) == 0, "e `unknown` non è ripescabile"


def test_il_vuoto_e_lo_sconosciuto_restano_due_stati(tmp_path: Path):
    """`voice=''` (nessuno l'ha guardata) ≠ `voice='unknown'` (guardata, non riconosciuta).

    🖐️ Condizione posta da `71d540e6` firmando i nomi delle classi, e la ragione è
    sua: *se collassassero in un nome solo, chi cerca `voice:unknown` crederebbe di
    avere «le righe difficili» mentre ha «le righe mai lette» — e stavolta lo
    crederebbe un utente, non noi che sappiamo com'è fatto.*
    ⭐ È la regola più ricorrente che abbiamo — `None` = non misurato ≠ `0` = misurato
    e vuoto — al posto dove costa meno oggi: dopo la Fase 3 separarli richiederebbe
    un DROP+rebuild dell'indice.
    """
    db = _db_v2(tmp_path, [("u1", "p", "2026-01-01T00:00:00Z", "x", "attachment")])
    with sqlite3.connect(db) as c:
        archive_indexer._ensure_v3(c)
        prima = c.execute("SELECT voice FROM messages").fetchone()[0]
        assert prima == "", "prima del classificatore la riga NON è 'unknown': è non-guardata"
        archive_indexer.popola_voice(c)
        dopo = c.execute("SELECT voice FROM messages").fetchone()[0]
    assert dopo == "unknown", "dopo, è un giudizio — e ha un nome diverso dal vuoto"


def test_popola_voice_non_gira_a_vuoto_se_una_regola_torna_stringa_vuota(monkeypatch,
                                                                        tmp_path: Path):
    """La guardia anti-loop, provata invece che dichiarata.

    Il ciclo esce quando `voice=''` non trova più righe: una regola che tornasse `''`
    lascerebbe la riga eleggibile per sempre. Su un DB da 61k righe sarebbe un blocco
    silenzioso dell'ingest — non un errore, un processo che non finisce.
    """
    db = _db_v2(tmp_path, [("u1", "p", "2026-01-01T00:00:00Z", "x", "user")])
    monkeypatch.setattr(archive_indexer, "classify_voice",
                        lambda *a, **k: ("", 0.0, 0.0, ""))
    with sqlite3.connect(db) as c:
        archive_indexer._ensure_v3(c)
        assert archive_indexer.popola_voice(c) == 1
        assert c.execute("SELECT voice FROM messages").fetchone()[0] == "unknown", (
            "la guardia deve scrivere un valore NON vuoto, o il ciclo non termina")


# ═══════════════ VOICE-TAGGING Fase 4 — il retag, e il suo default a secco ════

def test_retag_a_secco_calcola_e_non_scrive(tmp_path: Path):
    """Il delta è REALE (calcolato riga per riga), ma niente viene salvato.

    🛡️ È la proprietà che rende il comando usabile: un referto che si può chiedere
    senza conseguenze. Se il dry-run stimasse invece di calcolare, il numero che
    guida la decisione di scrivere sarebbe diverso da quello che poi succede.
    """
    db = _db_v2(tmp_path, [("u1", "p", "2026-01-01T00:00:00Z", "testo mio", "user")])
    archive_indexer.migrate_v2_to_v3(db)
    with sqlite3.connect(db) as c:
        c.execute("UPDATE messages SET voice='SEGNAPOSTO'")
        c.commit()
        esito = archive_indexer.retag_voice(c, scrivi=False)
        assert esito["righe"] == 1
        assert esito["cambiate"] == 1, "il delta dev'essere calcolato, non stimato"
        assert esito["scritto"] is False
        assert c.execute("SELECT voice FROM messages").fetchone()[0] == "SEGNAPOSTO", (
            "a secco il DB NON deve cambiare: è tutto il senso del default")


def test_retag_con_scrivi_applica_e_riporta_lo_stesso_delta(tmp_path: Path):
    """Ciò che il secco prometteva è ciò che lo scrivi fa. Se divergessero, il
    referto sarebbe una previsione e non un'anteprima."""
    db = _db_v2(tmp_path, [("u1", "p", "2026-01-01T00:00:00Z", "testo mio", "user")])
    archive_indexer.migrate_v2_to_v3(db)
    with sqlite3.connect(db) as c:
        c.execute("UPDATE messages SET voice='SEGNAPOSTO'")
        c.commit()
        secco = archive_indexer.retag_voice(c, scrivi=False)
        vero = archive_indexer.retag_voice(c, scrivi=True)
        c.commit()
        assert vero["cambiate"] == secco["cambiate"]
        assert vero["dopo"] == secco["dopo"]
        assert vero["scritto"] is True
        assert c.execute("SELECT voice FROM messages").fetchone()[0] != "SEGNAPOSTO"


def test_retag_riscrive_anche_cio_che_popola_voice_non_tocca(tmp_path: Path):
    """La differenza fra i due, che è la ragione per cui il retag esiste.

    `popola_voice` tocca SOLO `voice=''` — giustamente, o ogni ritocco delle soglie
    riscriverebbe in silenzio giudizi già presi. `retag_voice` riscrive apposta, ed
    è per questo che non parte da solo.
    """
    db = _db_v2(tmp_path, [("u1", "p", "2026-01-01T00:00:00Z", "testo mio", "user")])
    archive_indexer.migrate_v2_to_v3(db)
    with sqlite3.connect(db) as c:
        c.execute("UPDATE messages SET voice='vecchio_giudizio'")
        c.commit()
        assert archive_indexer.popola_voice(c) == 0, "popola_voice non tocca i giudizi"
        assert c.execute("SELECT voice FROM messages").fetchone()[0] == "vecchio_giudizio"
        archive_indexer.retag_voice(c, scrivi=True)
        c.commit()
        assert c.execute("SELECT voice FROM messages").fetchone()[0] != "vecchio_giudizio"


def test_retag_dalla_riga_di_comando_non_scrive_senza_scrivi(tmp_path: Path, capsys):
    """L'entrypoint CLI ha lo stesso default della funzione.

    🔑 Non è ridondante col test sulla funzione: il default vive in DUE posti (la
    firma e l'argparse) e possono divergere. Una `store_true` scritta al contrario
    renderebbe il comando distruttivo per difetto, con la funzione ancora prudente.
    """
    db = _db_v2(tmp_path, [("u1", "p", "2026-01-01T00:00:00Z", "testo mio", "user")])
    archive_indexer.migrate_v2_to_v3(db)
    with sqlite3.connect(db) as c:
        c.execute("UPDATE messages SET voice='SEGNAPOSTO'")
        c.commit()
    assert archive_indexer.main([str(db), "--retag"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["scritto"] is False and out["cambiate"] == 1
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT voice FROM messages").fetchone()[0] == "SEGNAPOSTO"


# ── etichette, titoli-ts, mandati (cure del 28/08/2026, bundle 20260811 alla mano) ──

def test_label_da_cwd_windows_local_agent_e_normale() -> None:
    """I tre difetti misurati: path Windows intero come label, «outputs» che
    collassa sessioni diverse, e il caso normale che non deve cambiare."""
    f = archive_indexer._label_da_cwd
    assert f(r"C:\Users\Administrator\AppData\Roaming\Claude\local-agent-mode-sessions\a4052b44") == "local-agent:a4052b44"
    assert f("/home/x/.config/Claude/local-agent-mode-sessions/35d8973d-aaaa/d196a35c-bbbb/local_af4e235a-8b8f-43e1/outputs") == "local-agent:af4e235a"
    assert f("/home/x/Scrivania/vps1777") == "vps1777"
    assert f("") == "unknown"


def test_workfile_label_due_livelli() -> None:
    """Il secchio unico da 126k righe si spacchetta; i file in radice restano a un livello."""
    f = archive_indexer._workfile_label
    assert f("workfiles/-home-x-Scrivania/vps1777-installer/LICENSE") == "workfile:-home-x-Scrivania/vps1777-installer"
    assert f("workfiles/-home-x-Scrivania/appunto.txt") == "workfile:-home-x-Scrivania"
    assert f("workfiles") == "workfile"


def test_titolo_eredita_ultimo_ts(tmp_path: Path) -> None:
    """ai-title non porta timestamp (misurato): il titolo eredita l'ultimo ts
    visto; se arriva PRIMA di ogni messaggio resta '' — onesto, non inventato."""
    import io as _io
    righe = "\n".join([
        '{"type":"ai-title","aiTitle":"Titolo precoce","sessionId":"s0"}',
        '{"type":"user","uuid":"u1","timestamp":"2026-02-02T10:00:00Z","cwd":"/x/p","message":{"content":"ciao"}}',
        '{"type":"ai-title","aiTitle":"Titolo maturo","sessionId":"s1"}',
    ])
    rows = [r for r in archive_indexer._iter_claude_code(_io.StringIO(righe), "p")
            if not isinstance(r, archive_indexer._Skip)]
    per_titolo = {r[3]: r[2] for r in rows if r[4] == "title"}
    assert per_titolo["Titolo precoce"] == ""
    assert per_titolo["Titolo maturo"] == "2026-02-02T10:00:00Z"


def test_mandato_non_e_user(tmp_path: Path) -> None:
    """AN-11 modellata: la riga TIPO user scritta dalla macchina (isSidechain nei
    transcript, parent_tool_use_id negli audit) diventa sender='mandato' →
    speaker='assistant'. Il verso opposto: lo user vero resta 'user'→'human'.
    È il difetto B3 della vecchia app — e l'errore del Laboratorio dell'11/07 —
    chiuso nello schema invece che nella prudenza di chi legge."""
    import io as _io
    righe = "\n".join([
        '{"type":"user","uuid":"m1","timestamp":"2026-02-02T10:00:00Z","isSidechain":true,"cwd":"/x/p","message":{"content":"Sei l\'agente A di un esperimento"}}',
        '{"type":"user","uuid":"m2","timestamp":"2026-02-02T10:00:01Z","parent_tool_use_id":"toolu_01","message":{"content":"mandato da audit"}}',
        '{"type":"user","uuid":"v1","timestamp":"2026-02-02T10:00:02Z","cwd":"/x/p","message":{"content":"parola vera di Neo"}}',
        '{"type":"assistant","uuid":"a1","timestamp":"2026-02-02T10:00:03Z","message":{"content":"risposta"}}',
    ])
    rows = [r for r in archive_indexer._iter_claude_code(_io.StringIO(righe), "p")
            if not isinstance(r, archive_indexer._Skip)]
    sender_per_uuid = {r[0]: r[4] for r in rows}
    assert sender_per_uuid["m1"] == "mandato"
    assert sender_per_uuid["m2"] == "mandato"
    assert sender_per_uuid["v1"] == "user"
    assert sender_per_uuid["a1"] == "assistant"
    assert archive_indexer.speaker_da_sender("mandato") == "assistant"
    assert archive_indexer.speaker_da_sender("user") == "human"


def test_confine_mixed_transcript_nei_due_versi() -> None:
    """Il criterio dell'owner, letto nel gold (28/08/2026): la cornice decide.

    ② con cornice → mixed: «ottengo quanto segue:» + trascrizione piena di
    timestamp è materiale INCORNICIATO. ③ senza cornice → transcript: il dump
    che parte col prompt di shell non contiene nessuna parola dell'owner.
    E i guardiani sono STRETTI: «flutter:» non è una cornice (il downgrade non
    scatta), la prosa normale non è materiale-da-subito (l'upgrade non scatta).
    """
    ts = " ".join(f"({m}:0{s})" for m in range(1, 10) for s in range(0, 9, 2))
    con_cornice = "[human] ottengo quanto segue: " + ts
    voce, _q, _c, flags = archive_indexer.classify_voice(con_cornice, "user", "chat")
    assert voce == "mixed" and "cornice_propria" in flags

    senza = "[human] flutter: Error GET request " + ts
    voce2, _q, _c, _f = archive_indexer.classify_voice(senza, "user", "chat")
    assert voce2 == "pasted_transcript", "«flutter:» non è una cornice"

    inglese = ("the process could not complete because the file was not found "
               "and the system will now retry with the same parameters again " * 3)
    dump = "neo1777@host:~/proj$ rm -rf build\n" + inglese
    voce3, _q, _c, flags3 = archive_indexer.classify_voice(dump, "user", "chat")
    assert voce3 == "pasted_transcript" and "senza_cornice" in flags3

    con_parole = "[human] questo il log ora: " + inglese
    voce4, _q, _c, _f4 = archive_indexer.classify_voice(con_parole, "user", "chat")
    assert voce4 == "mixed", "con la cornice dell'owner il blocco inglese resta mixed"


# ── B5: occhi (OCR) e apriscatole (zip annidati) — 28/08/2026 ────────────────

def _bundle_con_workfile(tmp_path: Path, membro: str, contenuto: bytes) -> Path:
    """Un bundle minimo (MANIFEST.json + sessions/) con UN workfile dentro."""
    import zipfile
    zp = tmp_path / "bundle.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("MANIFEST.json", "{}")
        z.writestr("sessions/vuota.jsonl", "")
        z.writestr(membro, contenuto)
    return zp


def test_zip_annidato_si_apre_e_la_bomba_no(tmp_path: Path) -> None:
    """Un livello si apre (il .md dentro lo zip diventa cercabile); il secondo
    livello NON si apre e lascia una lapide dichiarata — profondità 1, anti-bomba."""
    import io as _io
    import sqlite3
    import zipfile
    interno = _io.BytesIO()
    with zipfile.ZipFile(interno, "w") as zi:
        zi.writestr("appunti/nota.md", "parola-sepolta-nel-livello-uno")
        zi.writestr("bomba.zip", b"PK\x03\x04finto")
    zp = _bundle_con_workfile(tmp_path, "workfiles/-home-x-Scrivania/arch.zip",
                              interno.getvalue())
    db = tmp_path / "out.db"
    archive_indexer.index_file(str(zp), str(db))
    con = sqlite3.connect(db)
    trovato = con.execute(
        "SELECT count(*) FROM messages WHERE content LIKE '%parola-sepolta-nel-livello-uno%'"
    ).fetchone()[0]
    lapide = con.execute(
        "SELECT count(*) FROM skipped WHERE reason='zip-annidato-oltre-profondita'"
    ).fetchone()[0]
    assert trovato >= 1, "il .md dentro lo zip annidato non è stato indicizzato"
    assert lapide == 1, "lo zip di secondo livello doveva lasciare una lapide, non aprirsi"


def test_skill_e_uno_zip_e_si_apre(tmp_path: Path) -> None:
    """I .skill SONO zip (misurato con file(1)): il loro SKILL.md diventa cercabile."""
    import io as _io
    import sqlite3
    import zipfile
    interno = _io.BytesIO()
    with zipfile.ZipFile(interno, "w") as zi:
        zi.writestr("SKILL.md", "# la-skill-sepolta\nistruzioni preziose")
    zp = _bundle_con_workfile(tmp_path, "workfiles/-home-x-Scrivania/docs/x.skill",
                              interno.getvalue())
    db = tmp_path / "out.db"
    archive_indexer.index_file(str(zp), str(db))
    con = sqlite3.connect(db)
    assert con.execute("SELECT count(*) FROM messages WHERE content LIKE '%la-skill-sepolta%'"
                       ).fetchone()[0] >= 1


def test_ocr_assente_lascia_lapide_dichiarata(tmp_path: Path, monkeypatch) -> None:
    """Senza tesseract l'immagine NON sparisce in silenzio: lapide col motivo."""
    import sqlite3
    monkeypatch.delenv("OCR_URL", raising=False)
    import zipfile
    zp = tmp_path / "bundle.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("MANIFEST.json", "{}")
        z.writestr("sessions/vuota.jsonl", "")
        z.writestr("workfiles/-home-x-Scrivania/shot.png", b"\x89PNG\r\n\x1a\nfinto")
        z.writestr("workfiles/-home-x-Scrivania/nota.md", "una riga vera")  # n>0
    db = tmp_path / "out.db"
    archive_indexer.index_file(str(zp), str(db))
    con = sqlite3.connect(db)
    assert con.execute("SELECT count(*) FROM skipped WHERE reason='ocr-non-disponibile'"
                       ).fetchone()[0] == 1


def test_ocr_presente_indicizza_marcato(tmp_path: Path, monkeypatch) -> None:
    """Col binario presente il testo entra marcato [ocr]; l'immagine muta lascia
    la lapide 'ocr-vuoto' — i due versi dello stesso occhio."""
    import io as _io
    import sqlite3
    monkeypatch.setenv("OCR_URL", "http://ocr-finto/ocr")

    class _Risposta(_io.BytesIO):
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def finto_urlopen(req, timeout=0):
        corpo = req.data or b""
        testo = b"testo-letto-dallo-screenshot" if corpo.startswith(b"\x89PNG") else b""
        return _Risposta(testo)

    monkeypatch.setattr(archive_indexer.urllib.request, "urlopen", finto_urlopen)
    import zipfile
    zp = tmp_path / "bundle.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("MANIFEST.json", "{}")
        z.writestr("sessions/vuota.jsonl", "")
        z.writestr("workfiles/-home-x-Scrivania/shot.png", b"\x89PNG\r\n\x1a\nfinto")
        z.writestr("workfiles/-home-x-Scrivania/muta.jpg", b"\xff\xd8\xff\xe0finto")
    db = tmp_path / "out.db"
    archive_indexer.index_file(str(zp), str(db))
    con = sqlite3.connect(db)
    riga = con.execute("SELECT content FROM messages WHERE content LIKE '%[ocr]%'").fetchone()
    assert riga and "testo-letto-dallo-screenshot" in riga[0]
    assert con.execute("SELECT count(*) FROM skipped WHERE reason='ocr-vuoto'"
                       ).fetchone()[0] == 1


def test_membro_oversize_lascia_lapide_e_l_ingest_prosegue(tmp_path: Path, monkeypatch) -> None:
    """Il bug che ha ucciso il re-ingest del 28/08: un membro-zip oltre il tetto
    per-membro faceva propagare il ValueError e moriva l'INGEST INTERO. Ora:
    lapide `membro-oltre-tetto`, e il file accanto viene comunque indicizzato."""
    import io as _io
    import sqlite3
    import zipfile
    monkeypatch.setattr(archive_indexer, "MAX_MEMBER_BYTES", 64)  # tetto piccolo
    interno = _io.BytesIO()
    with zipfile.ZipFile(interno, "w") as zi:
        zi.writestr("zavorra.txt", "x" * 4096)                    # 4KB >> 64B
    zp = tmp_path / "bundle.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("MANIFEST.json", "{}")
        z.writestr("sessions/vuota.jsonl", "")
        z.writestr("workfiles/-home-x-Scrivania/grosso.zip", interno.getvalue())
        z.writestr("workfiles/-home-x-Scrivania/nota.md", "riga-superstite")
    db = tmp_path / "out.db"
    archive_indexer.index_file(str(zp), str(db))                  # NON deve alzare
    con = sqlite3.connect(db)
    assert con.execute("SELECT count(*) FROM messages WHERE content LIKE '%riga-superstite%'"
                       ).fetchone()[0] >= 1, "il file accanto è morto col membro oversize"
    assert con.execute("SELECT count(*) FROM skipped WHERE reason='membro-oltre-tetto'"
                       ).fetchone()[0] == 1
