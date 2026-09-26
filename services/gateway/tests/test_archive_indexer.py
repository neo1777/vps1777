"""Test dell'indexer archive (stdlib-only, offline)."""
from __future__ import annotations

import json
import sqlite3
import sys

import pytest
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


def test_document_label_un_livello() -> None:
    """`documents/` dell'export: la prima sottocartella se c'è, `document` per i file
    sciolti (oggi l'app la scrive piatta)."""
    f = archive_indexer._document_label
    assert f("documents/0123456789__nota.md") == "document"
    assert f("documents/appunti/sotto/nota.md") == "document:appunti"


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


# ── export claude.ai a 5 zip (dal 29/08/2026) ────────────────────────────────

def _export_a_5_zip(tmp_path: Path) -> dict:
    """Il formato NUOVO dell'export claude.ai, ricalcato sul primo ricevuto
    (29/08/2026): un manifest coi link one-shot + 5 zip per categoria. I due
    piccoli (memories, light_metadata) NON contengono nessuno dei membri che
    l'indexer usava per riconoscere l'export → prima di 0.43.16 venivano
    rifiutati come «zip non riconosciuto»."""
    import json
    import zipfile
    d = tmp_path / "export5"
    d.mkdir()
    convs = [{"uuid": "c1", "name": "chat vps", "chat_messages": [
        {"uuid": "m1", "sender": "human", "created_at": "2026-08-29T10:00:00Z",
         "text": "parliamo del gateway", "content": [{"type": "text", "text": "parliamo del gateway"}]},
        {"uuid": "m2", "sender": "assistant", "created_at": "2026-08-29T10:00:01Z",
         "text": "certo", "content": [{"type": "text", "text": "certo"}]},
    ]}]
    proj = {"uuid": "p1", "name": "prog", "docs": [
        {"uuid": "d1", "filename": "note.txt", "created_at": "2026-08-01", "content": "documento sirena"}]}
    design = {"uuid": "dc1", "title": "Chat", "project": {"uuid": "dp", "name": "Design System"},
              "messages": [{"uuid": "dm1", "role": "user", "content": "bottone quarzo",
                            "created_at": "2026-08-02T00:00:00Z"}]}
    memories = {"account_uuid": "acc",
                "conversations_memory": "Neo lavora in Dart e Flutter.",
                "project_memories": {"p1": "Il libro è al capitolo 81."},
                "memory_files": [
                    {"path": "/areas/vps1777.md", "updated_at": "2026-08-19T23:12:04+00:00",
                     "content": "---\nname: vps1777\n---\nArchivio e nb1777 sulla VPS, parola falco."},
                    {"path": "/areas/vuoto.md", "updated_at": "2026-08-19T23:12:05+00:00",
                     "content": "   "},
                ]}
    users = [{"uuid": "acc", "full_name": "neo", "email_address": "neo@example.org"}]
    login = {"login_events": [
        {"account_uuid": "acc", "timestamp": "2026-08-21T10:45:32+00:00", "ip_address": "203.0.113.7",
         "user_agent": {"browser_family": "Electron", "os_family": "Linux", "os_version": None},
         "method": "google", "location_info": {"country": "IT", "city": None}},
        {"account_uuid": "acc", "timestamp": "2026-08-22T08:00:00+00:00", "ip_address": "203.0.113.8",
         "user_agent": {"browser_family": "Firefox"}, "method": "magic_link", "location_info": {}},
    ]}
    def z(name: str, membri: dict) -> Path:
        p = d / name
        with zipfile.ZipFile(p, "w") as zf:
            for k, v in membri.items():
                zf.writestr(k, json.dumps(v))
        return p
    return {
        "conversations": z("conversations-000.zip", {"conversations.json": convs}),
        "projects": z("projects-000.zip", {"projects/p1.json": proj}),
        "design_chats": z("design_chats-000.zip", {"design_chats/dc1.json": design}),
        "memories": z("memories-000.zip", {"memories/acc.json": memories}),
        "light_metadata": z("light_metadata-000.zip", {"users.json": users, "login_history.json": login}),
    }


def test_export_a_5_zip_ogni_zip_e_riconosciuto_da_solo(tmp_path: Path) -> None:
    """La regressione: memories-000 e light_metadata-000 non hanno né
    conversations.json né design_chats/ né projects/. Ognuno dei 5 deve entrare
    da solo, in un DB suo, senza «zip non riconosciuto»."""
    zips = _export_a_5_zip(tmp_path)
    attesi = {"conversations": 2, "projects": 1, "design_chats": 1,
              "memories": 3,          # conversations + project + 1 file (il vuoto si salta)
              "light_metadata": 3}    # 1 utente + 2 accessi
    for nome, zp in zips.items():
        db = tmp_path / f"{nome}.db"
        n = archive_indexer.index_file(str(zp), str(db))
        assert n == attesi[nome], (nome, n)


def test_export_a_5_zip_si_accumula_in_un_db_solo_ed_e_idempotente(tmp_path: Path) -> None:
    """Il gesto reale: 5 zip, stesso nome DB, ordine qualunque. Tutto cercabile,
    etichette per categoria, e un secondo giro non duplica nulla."""
    zips = _export_a_5_zip(tmp_path)
    db = tmp_path / "claude-ai-290826.db"
    ordine = ["light_metadata", "memories", "design_chats", "projects", "conversations"]
    totale = sum(archive_indexer.index_file(str(zips[k]), str(db)) for k in ordine)
    assert totale == 10
    assert archive_indexer.count_rows(db) == 10
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        etichette = {r[0] for r in conn.execute("SELECT DISTINCT project FROM messages")}
        assert {"chat vps", "project:prog", "design:Design System", "memory:conversations",
                "memory:project:p1", "memory:file:/areas/vps1777.md",
                "account:user", "account:login"} <= etichette
        # il memory_file porta il suo updated_at come ts, e il suo testo è cercabile
        r = conn.execute("SELECT project, ts FROM messages_fts WHERE messages_fts MATCH 'falco'").fetchall()
        assert r == [("memory:file:/areas/vps1777.md", "2026-08-19T23:12:04+00:00")]
        # gli accessi: una riga per evento, ts = timestamp, sottodizionari appiattiti,
        # i None NON finiscono nel testo
        righe = conn.execute(
            "SELECT ts, content, sender FROM messages WHERE project='account:login' ORDER BY ts").fetchall()
        assert [r[0] for r in righe] == ["2026-08-21T10:45:32+00:00", "2026-08-22T08:00:00+00:00"]
        assert "ip_address: 203.0.113.7" in righe[0][1]
        assert "browser_family=Electron" in righe[0][1] and "os_version" not in righe[0][1]
        assert "method: magic_link" in righe[1][1]
        assert {r[2] for r in righe} == {"account"}
    finally:
        conn.close()
    # secondo giro, stesso DB: 0 nuove righe (dedup per uuid, anche sugli uuid derivati)
    for k in ordine:
        archive_indexer.index_file(str(zips[k]), str(db))
    assert archive_indexer.count_rows(db) == 10


def test_export_unico_con_memories_json_alla_radice_resta_valido(tmp_path: Path) -> None:
    """Il layout VECCHIO (fino ad agosto 2026: `memories.json` alla radice) non
    si rompe con il nuovo: i due si riconoscono entrambi."""
    db = tmp_path / "m.db"
    archive_indexer.index_file(str(_claude_zip_memories(tmp_path)), str(db))
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        assert conn.execute(
            "SELECT count(*) FROM messages WHERE project='memory:conversations'").fetchone()[0] >= 1
    finally:
        conn.close()


def test_speaker_derivato_anche_su_db_nato_v3(tmp_path: Path) -> None:
    """#271 (05/09/2026): un DB nato GIÀ v3 non migra mai, quindi la derivazione
    di `speaker` agganciata alla migrazione non lo toccava — le righe nuove
    restavano con speaker='' e il filtro speaker=human rispondeva 0 SENZA
    errore (misurato in produzione: 6.606 sender='human' con speaker vuoto).
    Ora `popola_speaker` gira dopo il write, accanto a `popola_voice`.
    Controprovato mordace: senza quella chiamata questo test è ROSSO."""
    db = tmp_path / "out.db"
    archive_indexer.index_jsonl(str(_jsonl(tmp_path)), str(db), project="proj")
    conn = sqlite3.connect(db)
    coppie = list(conn.execute(
        "SELECT sender, speaker FROM messages WHERE sender IN ('user','assistant')"))
    conn.close()
    assert coppie, "la fixture doveva scrivere righe user/assistant"
    attesi = {"user": "human", "assistant": "assistant"}
    for sender, speaker in coppie:
        assert speaker == attesi[sender], (
            f"sender={sender!r} ha speaker={speaker!r}: la derivazione non è girata")


def test_speaker_popolato_da_ogni_percorso_di_ingest(tmp_path: Path) -> None:
    """Guard-rail della #279: `speaker` esce POPOLATO da ogni percorso d'ingest.

    La derivazione vive in `write_rows` (`popola_speaker`, dalla cura della #271):
    questo test inchioda il CONTRATTO dichiarato in REVIEW.md — lo zip claude.ai
    via `index_file` (il ramo CLI che la #279 denunciava) e il jsonl Claude Code
    via `index_jsonl` non devono mai più produrre righe con `speaker=''`.
    Se un percorso d'ingest nuovo salterà `write_rows`, questo test non lo vede:
    il punto d'aggancio della derivazione è UNO, e chi ne aggiunge un altro
    deve estendere anche qui.
    """
    import zipfile
    # percorso 1 — zip claude.ai via index_file (il ramo della #279)
    zp = tmp_path / "export.zip"
    convs = [{"uuid": "c1", "name": "chat", "chat_messages": [
        {"uuid": "m1", "sender": "human", "created_at": "2026-01-01T00:00:00Z", "text": "ciao"},
        {"uuid": "m2", "sender": "assistant", "created_at": "2026-01-01T00:00:01Z",
         "content": [{"type": "text", "text": "risposta"}]},
    ]}]
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("conversations.json", json.dumps(convs))
    db_zip = tmp_path / "zip.db"
    assert archive_indexer.index_file(str(zp), str(db_zip)) > 0
    # percorso 2 — jsonl Claude Code via index_jsonl
    db_cc = tmp_path / "cc.db"
    assert archive_indexer.index_jsonl(str(_jsonl(tmp_path)), str(db_cc), project="p") > 0
    for db in (db_zip, db_cc):
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            vuoti = conn.execute(
                "SELECT count(*) FROM messages WHERE speaker=''").fetchone()[0]
            assert vuoti == 0, f"{db.name}: {vuoti} righe con speaker='' (contratto #279)"
            # e la derivazione è GIUSTA, non solo non-vuota
            for sender, speaker in conn.execute(
                    "SELECT DISTINCT sender, speaker FROM messages"
                    " WHERE sender IN ('human','assistant')"):
                assert speaker == sender, f"{db.name}: sender={sender!r} → speaker={speaker!r}"
        finally:
            conn.close()


# ── subagents/ nel bundle (16/09/2026): 662 transcript, 356 MB, mai entrati ──

_SID = "35a3364f-fa89-4c01-ba1a-fc73b66beec5"


def _bundle_con_subagente(tmp_path: Path) -> Path:
    """Un mini-bundle in memoria: la sessione MADRE in sessions/ e UN transcript
    di sub-agente in subagents/<sid>/, ricalcato su uno reale (stesso sessionId
    della madre, `isSidechain: true`, `agentId`, uuid PROPRI per riga). La madre
    porta anche il titolo (`ai-title` sul sid): è la riga che un agente col
    titolo avrebbe sovrascritto."""
    import zipfile
    madre = "\n".join([
        f'{{"type":"ai-title","aiTitle":"Titolo della madre","sessionId":"{_SID}"}}',
        f'{{"type":"user","uuid":"m-u1","timestamp":"2026-09-16T10:00:00Z","sessionId":"{_SID}","cwd":"/home/x/Scrivania/vps1777","message":{{"role":"user","content":"parola-della-madre"}}}}',
        f'{{"type":"assistant","uuid":"m-a1","timestamp":"2026-09-16T10:00:01Z","sessionId":"{_SID}","cwd":"/home/x/Scrivania/vps1777","message":{{"role":"assistant","content":[{{"type":"tool_use","id":"toolu_1","name":"Agent","input":{{"prompt":"vai"}}}}]}}}}',
    ])
    agente = "\n".join([
        f'{{"parentUuid":null,"isSidechain":true,"agentId":"a5cfecb82923cb1ec","type":"user","uuid":"s-u1","timestamp":"2026-09-16T10:00:02Z","sessionId":"{_SID}","cwd":"/home/x/Scrivania/vps1777","message":{{"role":"user","content":"mandato-per-l-agente parola-dell-agente"}}}}',
        f'{{"parentUuid":"s-u1","isSidechain":true,"agentId":"a5cfecb82923cb1ec","type":"assistant","uuid":"s-a1","timestamp":"2026-09-16T10:00:03Z","sessionId":"{_SID}","cwd":"/home/x/Scrivania/vps1777","message":{{"role":"assistant","content":[{{"type":"text","text":"referto-dell-agente"}}]}}}}',
        f'{{"type":"ai-title","aiTitle":"Titolo dell agente","sessionId":"{_SID}"}}',
        '{"type":"fork-context-ref","ref":"x"}',
    ])
    zp = tmp_path / "bundle.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("MANIFEST.json", json.dumps({"subagenti": {"file": 1, "bytes": len(agente), "dove": "subagents/<sid>/"}}))
        z.writestr(f"sessions/{_SID}.jsonl", madre)
        z.writestr(f"subagents/{_SID}/agent-a5cfecb82923cb1ec.jsonl", agente)
    return zp


def test_subagente_indicizzato_legato_alla_madre_senza_collisione(tmp_path: Path) -> None:
    """Il transcript in subagents/<sid>/ entra come CONVERSAZIONE (non più
    «non-indicizzato-ridondante»), con etichetta `subagent:<cwd>`, mandato →
    sender='mandato', avvistamento col path (sid della madre + hash dell'agente);
    e la madre resta intatta: righe, etichetta e titolo."""
    zp = _bundle_con_subagente(tmp_path)
    db = tmp_path / "out.db"
    archive_indexer.index_file(str(zp), str(db))
    con = sqlite3.connect(db)
    # nessuna lapide sul membro: né «ridondante» né «sconosciuto»
    assert con.execute(
        "SELECT count(*) FROM skipped WHERE source='bundle' AND detail LIKE 'subagents/%'"
    ).fetchone()[0] == 0
    righe = {u: (p, s) for u, p, s in con.execute(
        "SELECT uuid, project, sender FROM messages WHERE uuid IN ('m-u1','m-a1','s-u1','s-a1')")}
    assert righe["s-u1"] == ("subagent:vps1777", "mandato"), righe
    assert righe["s-a1"] == ("subagent:vps1777", "assistant"), righe
    assert righe["m-u1"] == ("vps1777", "user"), "la madre ha cambiato etichetta o mittente"
    assert con.execute("SELECT count(*) FROM messages WHERE content LIKE '%referto-dell-agente%'"
                       ).fetchone()[0] == 1
    # il legame madre→agente: dall'avvistamento, che porta sid e hash
    fonti = [r[0] for r in con.execute(
        "SELECT source FROM sightings WHERE uuid='s-a1'")]
    assert fonti == [f"subagents/{_SID}/agent-a5cfecb82923cb1ec.jsonl"], fonti
    assert con.execute(
        "SELECT count(*) FROM sightings WHERE source LIKE ?", (f"subagents/{_SID}/%",)
    ).fetchone()[0] == 3, "due messaggi + il titolo, ognuno col suo avvistamento"
    # i due titoli convivono: quello dell'agente NON sovrascrive quello della madre
    titoli = sorted(r[0] for r in con.execute("SELECT content FROM messages WHERE sender='title'"))
    assert titoli == ["Titolo dell agente", "Titolo della madre"], titoli
    assert con.execute("SELECT count(*) FROM revisions").fetchone()[0] == 0, \
        "una revisione qui = una riga della madre sovrascritta dall'agente"


def test_subagente_reingest_idempotente(tmp_path: Path) -> None:
    """Due ingest dello stesso bundle: stesse righe, stessi avvistamenti, zero revisioni."""
    zp = _bundle_con_subagente(tmp_path)
    db = tmp_path / "out.db"
    archive_indexer.index_file(str(zp), str(db))
    archive_indexer.index_file(str(zp), str(db))
    con = sqlite3.connect(db)
    assert con.execute("SELECT count(*) FROM messages WHERE project LIKE 'subagent:%'").fetchone()[0] == 3
    assert con.execute("SELECT count(*) FROM sightings WHERE source LIKE 'subagents/%'").fetchone()[0] == 3
    assert con.execute("SELECT count(*) FROM revisions").fetchone()[0] == 0


def test_canary_prefissi_del_bundle_che_l_indexer_conosce(tmp_path: Path) -> None:
    """CANARY. Il bundle lo produce un'altra app: quando aggiunge una cartella
    top-level, qui nessun test si rompe da solo — il membro cade nell'`else` con
    una lapide e sparisce dall'archivio (è successo con subagents/: 662 file).
    Questo test fissa l'insieme in TRE modi che devono concordare:
      1. la tupla dichiarata (BUNDLE_PREFISSI_INDICIZZATI + i file);
      2. il COMPORTAMENTO: un membro per ogni prefisso dichiarato entra in
         `messages` e non lascia lapidi `bundle`;
      3. un prefisso INVENTATO lascia la lapide `membro-sconosciuto`, non
         «ridondante» — così l'assenza di un ramo si legge nel ledger.
    Se il lato-bundle aggiunge un prefisso, aggiornare la tupla E il dispatch,
    e questo elenco è ciò che il test speculare del bundle deve leggere."""
    import zipfile
    assert archive_indexer.BUNDLE_PREFISSI_INDICIZZATI == (
        "sessions", "subagents", "mcp-logs", "workfiles", "recupero", "documents")
    assert archive_indexer.BUNDLE_FILE_INDICIZZATI == ("inventario/inventario-sessioni.tsv", "MANIFEST.md")
    assert archive_indexer.BUNDLE_FILE_IN_META == ("MANIFEST.json",)
    assert archive_indexer.BUNDLE_FILE_RIDONDANTI == ("inventario/inventario-sessioni.json",)

    cc = ('{"type":"user","uuid":"%s","timestamp":"2026-09-16T10:00:00Z","cwd":"/x/p",'
          '"message":{"role":"user","content":"segno-%s"}}')
    membri = {
        f"sessions/{_SID}.jsonl": cc % ("c-sess", "sessions"),
        f"subagents/{_SID}/agent-0.jsonl": cc % ("c-sub", "subagents"),
        f"mcp-logs/{_SID}/nb1777/1.jsonl": '{"sessionId":"%s","msg":"segno-mcp-logs"}' % _SID,
        "workfiles/-home-x/nota.md": "segno-workfiles",
        "documents/0123456789__nota.md": "segno-documents",
        f"recupero/sessioni/{_SID}.md": (f"---\ncontratto: R1\ntipo: sessione\n"
                                         f"sessionId: {_SID}\n---\nsegno-recupero"),
        "inventario/inventario-sessioni.tsv": "sid\tsegno-inventario",
        "MANIFEST.md": "# segno-manifest-md",
        "MANIFEST.json": "{}",
        "inventario/inventario-sessioni.json": "{}",
        "cartella-inventata/x.jsonl": cc % ("c-inv", "inventata"),
    }
    assert {m.split("/", 1)[0] for m in membri if "/" in m} >= set(archive_indexer.BUNDLE_PREFISSI_INDICIZZATI)
    zp = tmp_path / "bundle.zip"
    with zipfile.ZipFile(zp, "w") as z:
        for nome, corpo in membri.items():
            z.writestr(nome, corpo)
    db = tmp_path / "out.db"
    archive_indexer.index_file(str(zp), str(db))
    con = sqlite3.connect(db)
    for segno in ("sessions", "subagents", "mcp-logs", "workfiles", "recupero", "documents",
                  "inventario", "manifest-md"):
        assert con.execute("SELECT count(*) FROM messages WHERE content LIKE ?",
                           (f"%segno-{segno}%",)).fetchone()[0] >= 1, f"prefisso {segno} non indicizzato"
    # il detail comincia col nome del membro; dopo i «:» c'è il perché
    lapidi = {d.split(":", 1)[0]: r for r, d in con.execute(
        "SELECT reason, detail FROM skipped WHERE source LIKE 'bundle%'")}
    assert lapidi == {
        "MANIFEST.json": "manifest-in-meta",
        # il bundle ha recupero/: il json è ridondante DAVVERO (vedi il test sul motivo)
        "inventario/inventario-sessioni.json": "non-indicizzato-ridondante",
        "cartella-inventata/x.jsonl": "membro-sconosciuto",
    }, lapidi
    assert con.execute("SELECT count(*) FROM messages WHERE content LIKE '%segno-inventata%'"
                       ).fetchone()[0] == 0


# ── La scheda in cache (20/09/2026) ──────────────────────────────────────────
# /admin/archive «impallata»: db_info fa count(*) + GROUP BY su ogni DB (2-4 min
# sui 23 DB della VPS) dentro il loop async. La cura: scheda calcolata una volta
# per (dimensione, mtime) del file, e chiamata in un thread.

def test_db_info_cache_non_riquery_finche_il_file_non_cambia(tmp_path: Path, monkeypatch) -> None:
    import os
    db = tmp_path / "c.db"
    archive_indexer.write_rows(db, [("u1", "alpha", "2026-01-01", "uno")])
    archive_indexer._DB_INFO_CACHE.clear()
    assert archive_indexer.db_info(db)["rows"] == 1
    # da qui sqlite è VIETATO: se la cache regge, nessuno lo chiama
    def _no(*a, **k):
        raise AssertionError("query rifatta con file invariato")
    monkeypatch.setattr(archive_indexer.sqlite3, "connect", _no)
    info = archive_indexer.db_info(db)
    assert info["rows"] == 1
    info["top"].append("sporco")  # chi modifica la copia non sporca la cache
    assert archive_indexer.db_info(db)["top"] == [{"label": "alpha", "rows": 1}]
    # `cache=False` ignora la cache e quindi interroga davvero
    with pytest.raises(AssertionError):
        archive_indexer.db_info(db, cache=False)
    # il file cambia (mtime) → la scheda si ricalcola
    monkeypatch.undo()
    archive_indexer.write_rows(db, [("u2", "beta", "2026-01-02", "due")])
    st = db.stat()
    os.utime(db, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    assert archive_indexer.db_info(db)["rows"] == 2


def test_list_db_infos_salta_i_sidecar_vec_e_dimentica_i_cancellati(tmp_path: Path) -> None:
    a = tmp_path / "a.db"
    archive_indexer.write_rows(a, [("u1", "p", "t", "x")])
    (tmp_path / "a.vec.db").write_bytes(b"non un archivio")
    (tmp_path / "nota.txt").write_text("no")
    archive_indexer._DB_INFO_CACHE.clear()
    infos = archive_indexer.list_db_infos(tmp_path)
    assert [i["name"] for i in infos] == ["a"]
    assert str(a) in archive_indexer._DB_INFO_CACHE
    a.unlink()
    assert archive_indexer.list_db_infos(tmp_path) == []
    assert str(a) not in archive_indexer._DB_INFO_CACHE
    assert archive_indexer.list_db_infos(tmp_path / "manca") == []


# ── recupero/ nel bundle (contratto R1, 24/09/2026): stirpi, archi e memorie ──
# Fino a qui arrivavano sulla VPS solo dentro inventario-sessioni.json, scartato
# come «ridondante», e sparivano con lo zip. Dati TUTTI sintetici: sid inventati,
# percorsi finti, testi di prova.

_SID_A = "0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0"
_SID_B = "1a2b3c4d-5e6f-4a0b-9c8d-7e6f5a4b3c2d"
_STIRPE = "2b3c4d5e-6f70-4b1c-8d9e-0f1a2b3c4d5e"
_MEM_PATH = "/percorso/sintetico/progetto/memory/nota-di-prova.md"
_MEM_MEMBRO = "recupero/memorie/abcdef0123__nota-di-prova.md"


def _scheda(campi: dict, corpo: str) -> str:
    """Una scheda nel formato del contratto: front-matter fra due `---`, poi il corpo."""
    return "---\n" + "".join(f"{k}: {v}\n" for k, v in campi.items()) + "---\n" + corpo


def _tsv(intestazione: tuple, *righe: tuple) -> str:
    return "\n".join("\t".join(r) for r in (intestazione, *righe)) + "\n"


def _membri_recupero(memoria: str = "testo-memoria versione uno") -> dict:
    """I membri `recupero/` di un bundle minimo ma completo: una scheda per tipo e i
    tre .tsv. La scheda di sessione porta heading e grassetti come quelle vere: è
    ciò che, senza la regola ⓪ di classify_voice, la farebbe uscire `pasted_ai`."""
    return {
        f"recupero/sessioni/{_SID_A}.md": _scheda({
            "contratto": "R1", "tipo": "sessione", "sessionId": _SID_A,
            "titolo": "sessione di prova", "cwd": "/percorso/sintetico/progetto",
            "first_ts": "2026-09-10T10:00:00.000Z", "last_ts": "2026-09-10T10:05:00.000Z",
            "last_uuid": "rc-a1", "file": f"sessions/{_SID_A}.jsonl",
            "stato": "turno-chiuso", "stato_fonte": "transcript",
            "stirpe": _STIRPE, "stirpe_pos": "1", "stirpe_n": "2",
            "n_commit": "2", "n_fili": "1", "n_memorie_scritte": "1",
            "campo-futuro": "ignorato",   # un campo in più NON cambia versione
        }, "# sessione di prova\n\n## Stato\n\n**turno-chiuso** · transcript\n\n"
           "## Ultime parole\n\n- umano [verbatim]: segno-ultime-parole\n\n"
           "## Fili aperti\n\n1. filo di prova\n2. altro filo\n3. terzo filo\n\n"
           "## Commit\n\n**abc1234** · commit di prova\n"),
        f"recupero/stirpi/{_STIRPE}.md": _scheda({
            "contratto": "R1", "tipo": "stirpe", "id": _STIRPE,
            "membri": f"{_SID_A},{_SID_B}", "n": "2",
        }, f"# Stirpe\n\n{_SID_A} → continua → {_SID_B} · clone · forte · prova-sintetica\n"),
        _MEM_MEMBRO: _scheda({
            "contratto": "R1", "tipo": "memoria", "path": _MEM_PATH,
            "sistema": "claude-code", "livello": "strutturale", "md5": "0" * 32,
            "mtime": "2026-09-09T08:00:00Z", "cartella": "/percorso/sintetico/progetto/memory",
            "scritta_da": _SID_A, "omonimi": "0", "doppioni": "0",
        }, memoria + "\n"),
        "recupero/sessioni.tsv": _tsv(
            archive_indexer._TABELLE_RECORD["sessioni"] + ("colonna-futura",),
            (_SID_A, "sessione di prova", "/percorso/sintetico/progetto",
             "2026-09-10T10:00:00.000Z", "2026-09-10T10:05:00.000Z", "rc-a1",
             f"sessions/{_SID_A}.jsonl", "turno-chiuso", "transcript", _STIRPE, "1", "2", "1",
             "ignorata")),
        "recupero/archi.tsv": _tsv(
            archive_indexer._TABELLE_RECORD["archi"],
            (_SID_A, _SID_B, "continua", "clone", "forte", "prova-sintetica", "app",
             "0.9", "1", "2026-09-10T11:00:00Z")),
        "recupero/memorie.tsv": _tsv(
            archive_indexer._TABELLE_RECORD["memorie"],
            (_MEM_PATH, "claude-code", "strutturale", "0" * 32, "2026-09-09T08:00:00Z",
             _SID_A, _MEM_MEMBRO)),
    }


def _bundle_recupero(tmp_path: Path, *, nome: str = "bundle.zip", recupero: dict | None = None,
                     manifest: dict | None = None, extra: dict | None = None) -> Path:
    """Un bundle con la sessione madre in sessions/ (due messaggi, rc-u1 → rc-a1),
    l'inventario json, il MANIFEST e i membri `recupero/` passati (default: completi)."""
    import zipfile
    sessione = "\n".join([
        json.dumps({"type": "user", "uuid": "rc-u1", "timestamp": "2026-09-10T10:00:00.000Z",
                    "sessionId": _SID_A, "cwd": "/percorso/sintetico/progetto",
                    "message": {"role": "user", "content": "domanda di prova"}}),
        json.dumps({"type": "assistant", "uuid": "rc-a1", "parentUuid": "rc-u1",
                    "timestamp": "2026-09-10T10:05:00.000Z", "sessionId": _SID_A,
                    "cwd": "/percorso/sintetico/progetto",
                    "message": {"role": "assistant", "content": [{"type": "text", "text": "risposta"}]}}),
    ])
    if manifest is None:
        manifest = {"generated": "2026-09-24T20:00:00",
                    "previsione_ingest": {"righe_in_tabella": 2, "per_prefisso": {"sessions": 2}},
                    "recupero": {"contratto": "R1", "radice": "recupero/",
                                 "schede": {"sessioni": 1, "stirpi": 1, "memorie": 1}}}
    membri = {"MANIFEST.json": json.dumps(manifest),
              f"sessions/{_SID_A}.jsonl": sessione,
              "inventario/inventario-sessioni.json": "{}",
              **(_membri_recupero() if recupero is None else recupero),
              **(extra or {})}
    zp = tmp_path / nome
    with zipfile.ZipFile(zp, "w") as z:
        for n, corpo in membri.items():
            # data del membro FISSA: `writestr(nome, …)` userebbe l'ora corrente, e la
            # stirpe (che nel front-matter non ha un ts) la prende come suo ts — due zip
            # nati a cavallo di un secondo davano DB diversi (test del ponte, 1 su 10).
            z.writestr(zipfile.ZipInfo(n, date_time=(2026, 9, 24, 12, 0, 0)), corpo)
    return zp


def _uid_scheda(membro: str, idx: int = 0) -> str:
    return archive_indexer._uid("recupero", membro, str(idx))


def test_recupero_le_schede_entrano_come_righe(tmp_path: Path) -> None:
    """Le tre schede diventano righe di `messages` con la forma del contratto:
    etichetta, sender, ts, uuid stabile, `ts_source='data-export'`, un avvistamento
    ciascuna — e speaker/voice POPOLATI (REVIEW.md: uno speaker vuoto è un bug)."""
    db = tmp_path / "out.db"
    archive_indexer.index_file(str(_bundle_recupero(tmp_path)), str(db))
    con = sqlite3.connect(db)
    q = ("SELECT project, sender, ts, parent_uuid, ts_source, speaker, voice, content_flags,"
         " content FROM messages WHERE uuid=?")
    sess = con.execute(q, (_uid_scheda(f"recupero/sessioni/{_SID_A}.md"),)).fetchone()
    assert sess is not None, "la scheda di sessione non è entrata"
    # ts = last_ts + 1 ms: la scheda viene DOPO l'ultimo messaggio (vedi il test sull'ordine)
    assert sess[:5] == ("recupero:sessioni", "recupero", "2026-09-10T10:05:00.001Z", "rc-a1",
                        "data-export"), sess[:5]
    assert sess[8].startswith(f"[recupero/sessioni/{_SID_A}.md]\n# sessione di prova")
    assert "segno-ultime-parole" in sess[8]
    # la voce: la scheda ha heading, grassetti e un elenco numerato — senza la regola ⓪
    # uscirebbe pasted_ai, cioè le parole vere dell'owner marcate «incollate da un'AI»
    assert (sess[5], sess[6]) == ("unknown", "unknown"), sess[5:7]
    assert "scheda_recupero" in json.loads(sess[7])

    stirpe = con.execute(q, (_uid_scheda(f"recupero/stirpi/{_STIRPE}.md"),)).fetchone()
    assert stirpe is not None and stirpe[:2] == ("recupero:stirpi", "recupero")
    assert stirpe[3] == "", "la stirpe non appartiene a UNA conversazione"
    assert _SID_B in stirpe[8], "i sid interi nel corpo: l'arco si trova con FTS"

    mem = con.execute(q, (archive_indexer._uid("recupero-memoria", _MEM_PATH),)).fetchone()
    assert mem is not None, "la memoria non è entrata con l'uuid del suo PATH d'origine"
    assert mem[:5] == ("recupero:memorie", "memory", "2026-09-09T08:00:00Z", "", "data-export")
    assert "testo-memoria versione uno" in mem[8]

    assert con.execute("SELECT count(*) FROM messages WHERE speaker='' OR voice=''"
                       ).fetchone()[0] == 0, "speaker/voice vuoti in uscita"
    # un avvistamento per ogni riga-scheda, col nome del membro
    fonti = sorted(r[0] for r in con.execute(
        "SELECT source FROM sightings WHERE source LIKE 'recupero/%'"))
    assert fonti == sorted([f"recupero/sessioni/{_SID_A}.md", f"recupero/stirpi/{_STIRPE}.md",
                            _MEM_MEMBRO]), fonti
    # e nessuna lapide: il bundle rispetta il contratto
    assert con.execute("SELECT count(*) FROM skipped WHERE source='bundle-recupero'"
                       ).fetchone()[0] == 0
    # FTS: il sessionId (che il corpo della scheda non ripete) si trova dal membro
    assert con.execute("SELECT count(*) FROM messages_fts WHERE messages_fts MATCH ?",
                       (f'"{_SID_A}" AND "sessione di prova"',)).fetchone()[0] >= 1


def test_recupero_la_scheda_e_una_foglia_della_conversazione(tmp_path: Path) -> None:
    """Il chunk 0 della scheda pende dall'ultimo messaggio (`last_uuid`): camminando
    `parent_uuid` come fa `get_conversation` di archive-mcp (stessa CTE), dal primo
    messaggio si arriva alla scheda e dalla scheda si risale alla chat intera."""
    db = tmp_path / "out.db"
    archive_indexer.index_file(str(_bundle_recupero(tmp_path)), str(db))
    scheda = _uid_scheda(f"recupero/sessioni/{_SID_A}.md")
    con = sqlite3.connect(db)
    assert con.execute("SELECT parent_uuid FROM messages WHERE uuid=?",
                       (scheda,)).fetchone()[0] == "rc-a1"

    def thread(uuid: str) -> set:
        return {r[0] for r in con.execute(
            "WITH RECURSIVE "
            " up(u) AS (SELECT ? UNION SELECT m.parent_uuid FROM messages m JOIN up"
            "   ON m.uuid = up.u WHERE m.parent_uuid <> ''), "
            " down(u) AS (SELECT ? UNION SELECT m.uuid FROM messages m JOIN down"
            "   ON m.parent_uuid = down.u) "
            "SELECT u FROM up UNION SELECT u FROM down", (uuid, uuid)) if r[0]}

    assert thread("rc-u1") == {"rc-u1", "rc-a1", scheda}, "dal primo messaggio"
    assert thread(scheda) == {"rc-u1", "rc-a1", scheda}, "dalla scheda"


def test_recupero_i_pezzi_di_una_scheda_lunga_sono_in_catena(tmp_path: Path) -> None:
    """Una scheda che supera un chunk: il chunk 0 pende da `last_uuid`, ogni altro
    dal precedente — la scheda resta UN ramo, non N foglie sorelle."""
    membri = _membri_recupero()
    lungo = "\n\n".join(f"paragrafo {i} " + "x" * 900 for i in range(20))
    membri[f"recupero/sessioni/{_SID_A}.md"] = _scheda(
        {"contratto": "R1", "tipo": "sessione", "sessionId": _SID_A,
         "last_ts": "2026-09-10T10:05:00.000Z", "last_uuid": "rc-a1"}, lungo)
    db = tmp_path / "out.db"
    archive_indexer.index_file(str(_bundle_recupero(tmp_path, recupero=membri)), str(db))
    con = sqlite3.connect(db)
    membro = f"recupero/sessioni/{_SID_A}.md"
    pezzi = [_uid_scheda(membro, i) for i in range(3)]
    padri = [con.execute("SELECT parent_uuid FROM messages WHERE uuid=?", (u,)).fetchone()
             for u in pezzi]
    assert padri[0] == ("rc-a1",) and padri[1] == (pezzi[0],) and padri[2] == (pezzi[1],), padri


def test_recupero_i_tsv_riempiono_le_tabelle_e_non_messages(tmp_path: Path) -> None:
    """I .tsv sono relazioni: vanno in `sessioni`/`archi`/`memorie`, per NOME di
    colonna (la colonna in più si ignora), con le affinità che servono alle query
    del Livello 2 (`chiusura=1` deve trovare l'arco). Nessuno diventa testo."""
    db = tmp_path / "out.db"
    archive_indexer.index_file(str(_bundle_recupero(tmp_path)), str(db))
    con = sqlite3.connect(db)
    s = con.execute("SELECT titolo, last_uuid, file, stirpe, stirpe_pos, n_commit, ingest_date"
                    " FROM sessioni WHERE sessionId=?", (_SID_A,)).fetchone()
    assert s[:6] == ("sessione di prova", "rc-a1", f"sessions/{_SID_A}.jsonl", _STIRPE, 1, 2), s
    assert s[6], "ingest_date vuota"
    assert con.execute("SELECT relazione, via, peso FROM archi WHERE chiusura=1 AND da=?",
                       (_SID_A,)).fetchall() == [("continua", "clone", 0.9)]
    assert con.execute("SELECT membro, scritta_da FROM memorie WHERE path=?",
                       (_MEM_PATH,)).fetchone() == (_MEM_MEMBRO, _SID_A)
    assert con.execute("SELECT count(*) FROM messages WHERE content LIKE '%sessionId%titolo%'"
                       " OR content LIKE '%prova-sintetica%app%'").fetchone()[0] == 0, \
        "un .tsv è finito in messages"
    assert con.execute("SELECT count(*) FROM sightings WHERE source LIKE 'recupero/%.tsv'"
                       ).fetchone()[0] == 0


def test_recupero_reingest_idempotente(tmp_path: Path) -> None:
    """Lo stesso bundle due volte: stesse righe, stesse tabelle, zero revisioni."""
    zp = _bundle_recupero(tmp_path)
    db = tmp_path / "out.db"
    archive_indexer.index_file(str(zp), str(db))
    con = sqlite3.connect(db)
    prima = [con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
             for t in ("messages", "sessioni", "archi", "memorie", "sightings", "skipped")]
    con.close()
    archive_indexer.index_file(str(zp), str(db))
    con = sqlite3.connect(db)
    dopo = [con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            for t in ("messages", "sessioni", "archi", "memorie", "sightings", "skipped")]
    assert dopo == prima, (prima, dopo)
    assert con.execute("SELECT count(*) FROM revisions").fetchone()[0] == 0


def test_recupero_memoria_cambiata_lascia_una_revisione(tmp_path: Path) -> None:
    """Il nome del membro e l'uuid dipendono dal PERCORSO d'origine, non dal testo:
    una memoria cambiata fra due bundle è la STESSA riga con testo nuovo, e la
    versione uscente va in `revisions` — non un doppione, non una sparizione."""
    db = tmp_path / "out.db"
    uno = _bundle_recupero(tmp_path, nome="uno.zip")
    due = _bundle_recupero(tmp_path, nome="due.zip",
                           recupero=_membri_recupero(memoria="testo-memoria versione DUE"))
    archive_indexer.index_file(str(uno), str(db))
    archive_indexer.index_file(str(due), str(db))
    con = sqlite3.connect(db)
    uid = archive_indexer._uid("recupero-memoria", _MEM_PATH)
    assert con.execute("SELECT count(*) FROM messages WHERE project='recupero:memorie'"
                       ).fetchone()[0] == 1, "la memoria cambiata ha fatto un doppione"
    assert "versione DUE" in con.execute("SELECT content FROM messages WHERE uuid=?",
                                         (uid,)).fetchone()[0]
    rev = con.execute("SELECT content, ts_source FROM revisions WHERE uuid=?", (uid,)).fetchall()
    assert len(rev) == 1 and "versione uno" in rev[0][0], rev
    assert rev[0][1] == "data-export", "la revisione conserva il regime della versione uscente"
    assert con.execute("SELECT count(*) FROM revisions").fetchone()[0] == 1, \
        "solo la memoria è cambiata: nessun'altra revisione"


def test_recupero_membro_fuori_contratto_lascia_la_sua_lapide(tmp_path: Path) -> None:
    """Un membro `recupero/` che non rispetta il contratto NON entra e NON sparisce:
    lascia una lapide col motivo e il perché. I membri sani accanto entrano lo stesso."""
    ok = {"contratto": "R1", "tipo": "sessione", "sessionId": _SID_B,
          "last_ts": "2026-09-11T09:00:00Z", "last_uuid": ""}
    cattivi = {
        "recupero/sessioni/senza-fm.md": "# niente front-matter\n\ntesto-perso-1",
        "recupero/sessioni/aperto.md": "---\ncontratto: R1\ntipo: sessione\ntitolo: testo-perso-2\n",
        "recupero/sessioni/riga-storta.md": "---\ncontratto: R1\nriga senza due punti\n---\ntesto-perso-3",
        "recupero/sessioni/r2.md": _scheda({**ok, "contratto": "R2"}, "testo-perso-4"),
        "recupero/sessioni/senza-contratto.md": _scheda(
            {k: v for k, v in ok.items() if k != "contratto"}, "testo-perso-5"),
        "recupero/stirpi/tipo-sbagliato.md": _scheda({**ok}, "testo-perso-6"),
        "recupero/memorie/senza-path.md": _scheda(
            {"contratto": "R1", "tipo": "memoria", "mtime": "2026-09-09T08:00:00Z"}, "testo-perso-7"),
        "recupero/altro/x.md": "---\ncontratto: R1\n---\ntesto-perso-8",
        "recupero/sessioni/x.json": '{"type": "user"}',
    }
    membri = {**_membri_recupero(), **cattivi,
              f"recupero/sessioni/{_SID_B}.md": _scheda(ok, "scheda-sana-accanto"),
              "recupero/archi.tsv": _tsv(("da", "a", "relazione", "via"), (_SID_A, _SID_B, "x", "y")),
              "recupero/sessioni.tsv": _tsv(
                  archive_indexer._TABELLE_RECORD["sessioni"],
                  (_SID_A,) + ("v",) * 12,
                  (_SID_B, "con\tun tab in più") + ("v",) * 11,
                  ("",) + ("v",) * 12)}
    db = tmp_path / "out.db"
    archive_indexer.index_file(str(_bundle_recupero(tmp_path, recupero=membri)), str(db))
    con = sqlite3.connect(db)
    lapidi = {}
    for src, reason, detail in con.execute(
            "SELECT source, reason, detail FROM skipped WHERE source IN ('bundle','bundle-recupero')"):
        chiave = detail.split(":", 1)[0]
        lapidi.setdefault(chiave, []).append((src, reason))
    atteso = {
        "recupero/sessioni/senza-fm.md": "recupero-senza-front-matter",
        "recupero/sessioni/aperto.md": "recupero-senza-front-matter",
        "recupero/sessioni/riga-storta.md": "recupero-front-matter-malformato",
        "recupero/sessioni/r2.md": "recupero-contratto-ignoto",
        "recupero/sessioni/senza-contratto.md": "recupero-contratto-ignoto",
        "recupero/stirpi/tipo-sbagliato.md": "recupero-fuori-contratto",
        "recupero/memorie/senza-path.md": "recupero-fuori-contratto",
        "recupero/archi.tsv": "recupero-tsv-fuori-contratto",
        "recupero/sessioni.tsv riga 3": "recupero-tsv-fuori-contratto",
        "recupero/sessioni.tsv riga 4": "recupero-tsv-fuori-contratto",
    }
    for membro, motivo in atteso.items():
        assert lapidi.get(membro) == [("bundle-recupero", motivo)], (membro, lapidi.get(membro))
    # fuori dalle forme del contratto: la lapide di sempre, `membro-sconosciuto`
    for membro in ("recupero/altro/x.md", "recupero/sessioni/x.json"):
        assert lapidi.get(membro) == [("bundle", "membro-sconosciuto")], (membro, lapidi.get(membro))
    # il perché è scritto: chi legge la lapide sa cosa fare
    r2 = con.execute("SELECT detail FROM skipped WHERE detail LIKE 'recupero/sessioni/r2.md%'"
                     ).fetchone()[0]
    assert "'R2'" in r2 and "R1" in r2 and "RECUPERO_CONTRATTO" in r2, r2
    assert "relazione" not in con.execute(
        "SELECT detail FROM skipped WHERE detail LIKE 'recupero/archi.tsv%'").fetchone()[0].split(
        "(contratto")[0].split("non ha")[1], "la lapide deve nominare le colonne MANCANTI"
    # niente del materiale cattivo è entrato; il sano accanto sì
    assert con.execute("SELECT count(*) FROM messages WHERE content LIKE '%testo-perso-%'"
                       ).fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM messages WHERE content LIKE '%scheda-sana-accanto%'"
                       ).fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM archi").fetchone()[0] == 0, \
        "un .tsv con l'intestazione incompleta ha riempito la tabella a metà"
    assert [r[0] for r in con.execute("SELECT sessionId FROM sessioni")] == [_SID_A], \
        "solo la riga sana di sessioni.tsv doveva entrare"


def test_manifest_json_va_in_meta_e_non_diventa_testo(tmp_path: Path) -> None:
    """`previsione_ingest` e `recupero` del manifest arrivano nella scheda `meta`
    (json), il membro non diventa testo e lascia una lapide che dice dov'è finito.
    Un bundle successivo senza `recupero` TOGLIE la chiave: la scheda parla
    dell'ultimo bundle, non di uno precedente."""
    db = tmp_path / "out.db"
    archive_indexer.index_file(str(_bundle_recupero(tmp_path)), str(db))
    prev = json.loads(archive_indexer.get_meta(db, "bundle_previsione_ingest"))
    assert prev["per_prefisso"] == {"sessions": 2}
    assert json.loads(archive_indexer.get_meta(db, "bundle_recupero"))["radice"] == "recupero/"
    assert archive_indexer.get_meta(db, "bundle_generated") == "2026-09-24T20:00:00"
    con = sqlite3.connect(db)
    assert con.execute("SELECT count(*) FROM messages WHERE content LIKE '%righe_in_tabella%'"
                       ).fetchone()[0] == 0
    assert con.execute("SELECT reason FROM skipped WHERE detail LIKE 'MANIFEST.json:%'"
                       ).fetchall() == [("manifest-in-meta",)]
    con.close()
    archive_indexer.index_file(str(_bundle_recupero(
        tmp_path, nome="dopo.zip", manifest={"generated": "2026-09-25T08:00:00",
                                             "previsione_ingest": {"righe_in_tabella": 2}})), str(db))
    assert archive_indexer.get_meta(db, "bundle_recupero", "ASSENTE") == "ASSENTE"
    assert archive_indexer.get_meta(db, "bundle_generated") == "2026-09-25T08:00:00"
    # un manifest illeggibile lo dice, e l'ingest delle sessioni prosegue
    db2 = tmp_path / "rotto.db"
    import zipfile
    zp = tmp_path / "rotto.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("MANIFEST.json", "{non json")
        z.writestr(f"sessions/{_SID_A}.jsonl", json.dumps(
            {"type": "user", "uuid": "x1", "timestamp": "2026-09-10T10:00:00Z",
             "message": {"role": "user", "content": "c"}}))
    assert archive_indexer.index_file(str(zp), str(db2)) == 1
    con = sqlite3.connect(db2)
    assert con.execute("SELECT reason FROM skipped WHERE detail LIKE 'MANIFEST.json:%'"
                       ).fetchall() == [("manifest-illeggibile",)]


def test_inventario_json_il_motivo_dice_se_i_dati_sono_entrati(tmp_path: Path) -> None:
    """La lapide del json dell'inventario diceva «ridondante» SENZA CONDIZIONI, ed
    era falso: stirpi, archi e memorie stavano solo lì. Ora dipende dal bundle:
    con recupero/ — o col ponte workfiles/_recupero-1777/, che è un alias — è
    ridondante davvero; senza nessuno dei due, dice che i dati NON entrano."""
    import zipfile

    def motivo(nome: str, extra: dict) -> tuple:
        zp = tmp_path / f"{nome}.zip"
        with zipfile.ZipFile(zp, "w") as z:
            z.writestr("MANIFEST.json", "{}")
            z.writestr(f"sessions/{_SID_A}.jsonl", json.dumps(
                {"type": "user", "uuid": f"{nome}-1", "timestamp": "2026-09-10T10:00:00Z",
                 "message": {"role": "user", "content": "c"}}))
            z.writestr("inventario/inventario-sessioni.json", "{}")
            for n, c in extra.items():
                z.writestr(n, c)
        db = tmp_path / f"{nome}.db"
        archive_indexer.index_file(str(zp), str(db))
        with sqlite3.connect(db) as con:
            return con.execute("SELECT reason, detail FROM skipped WHERE detail LIKE"
                               " 'inventario/inventario-sessioni.json:%'").fetchone()

    r, _d = motivo("con", {f"recupero/stirpi/{_STIRPE}.md": _membri_recupero()[
        f"recupero/stirpi/{_STIRPE}.md"]})
    assert r == "non-indicizzato-ridondante"
    r, _d = motivo("ponte", {f"workfiles/_recupero-1777/stirpi/{_STIRPE}.md": _membri_recupero()[
        f"recupero/stirpi/{_STIRPE}.md"]})
    assert r == "non-indicizzato-ridondante", "il ponte è un alias: i dati entrano"
    r, d = motivo("senza", {})
    assert r == "non-indicizzato-senza-recupero" and "NON entrano" in d, (r, d)


def test_write_rows_accetta_ts_source_come_decima_colonna(tmp_path: Path) -> None:
    """`ts_source='data-export'` era nello schema dal 20/07 e nessun codice poteva
    scriverlo. La decima colonna è facoltativa: senza, il regime resta 'messaggio'
    (come prima); con un valore fuori elenco l'ingest si ferma parlante."""
    db = tmp_path / "t.db"
    archive_indexer.write_rows(db, [
        ("u9", "p", "2026-01-01T00:00:00Z", "nove campi", "user", "", "", "", ""),
        ("u10", "p", "2026-01-01T00:00:00Z", "dieci campi", "memory", "", "", "", "", "data-export"),
        ("u4", "p", "2026-01-01T00:00:00Z", "quattro campi"),
    ])
    with sqlite3.connect(db) as con:
        assert dict(con.execute("SELECT uuid, ts_source FROM messages")) == {
            "u9": "messaggio", "u10": "data-export", "u4": "messaggio"}
    with pytest.raises(ValueError, match="ts_source 'ignoto'"):
        archive_indexer.write_rows(db, [("u11", "p", "", "x", "", "", "", "", "", "ignoto")])


def test_tabelle_record_coincidono_con_lo_schema(tmp_path: Path) -> None:
    """Le colonne che `write_rows` scrive (`_TABELLE_RECORD`) e quelle dello schema
    sono due elenchi: se divergono, una colonna del .tsv non entra mai — o l'INSERT
    fallisce solo sui bundle veri. E le tabelle nascono anche su un DB che esisteva
    prima di loro, senza toccare i messaggi."""
    db = _db_v2(tmp_path, [("vecchia", "p", "2026-01-01", "riga di prima", "user")])
    archive_indexer.write_rows(db, [("nuova", "p", "2026-01-02", "riga di dopo")])
    con = sqlite3.connect(db)
    for tabella, colonne in archive_indexer._TABELLE_RECORD.items():
        info = con.execute(f"PRAGMA table_info({tabella})").fetchall()
        assert tuple(r[1] for r in info) == colonne + ("ingest_date",), tabella
    pk = {t: tuple(r[1] for r in sorted(con.execute(f"PRAGMA table_info({t})"), key=lambda r: r[5])
                   if r[5]) for t in archive_indexer._TABELLE_RECORD}
    assert pk == {"sessioni": ("sessionId", "file"), "archi": ("da", "a", "relazione", "via"),
                  "memorie": ("path",)}, pk
    assert con.execute("SELECT count(*) FROM messages").fetchone()[0] == 2
    with pytest.raises(ValueError, match="tabella sconosciuta"):
        archive_indexer.write_rows(db, [archive_indexer._Record("messages", {"uuid": "x"})])



# ── correzioni di revisione (24/09/2026): ordine, pezzi vecchi, ponte ─────────

def test_recupero_la_scheda_viene_dopo_l_ultimo_messaggio(tmp_path: Path) -> None:
    """`get_conversation` ordina per (ts, uuid). Con lo stesso ts dell'ultimo
    messaggio l'ordine lo decideva lo sha1: qui l'ultimo messaggio ha un uuid che
    ogni sha1 esadecimale precede ('z' > 'f'), cioè il caso in cui la scheda
    usciva PRIMA. Con +1 ms esce in coda; i pezzi di una scheda lunga a +1 ms
    l'uno dall'altro, nell'ordine del testo. E senza millesimi nella fonte si
    parte dal secondo dopo: `…00.001Z` ordinerebbe prima di `…00Z`."""
    import zipfile
    membri = _membri_recupero()
    lungo = "\n\n".join(f"paragrafo-{i:02d} " + "x" * 900 for i in range(20))
    membri[f"recupero/sessioni/{_SID_A}.md"] = _scheda(
        {"contratto": "R1", "tipo": "sessione", "sessionId": _SID_A,
         "last_ts": "2026-09-10T10:05:00.000Z", "last_uuid": "zzzz-ultimo"}, lungo)
    zp = _bundle_recupero(tmp_path, recupero=membri)
    with zipfile.ZipFile(zp, "a") as z:   # l'ultimo messaggio, con l'uuid «alto»
        z.writestr(f"sessions/{_SID_A}__f2.jsonl", json.dumps(
            {"type": "assistant", "uuid": "zzzz-ultimo", "parentUuid": "rc-a1",
             "timestamp": "2026-09-10T10:05:00.000Z", "sessionId": _SID_A,
             "message": {"role": "assistant", "content": [{"type": "text", "text": "fine"}]}}))
    db = tmp_path / "out.db"
    archive_indexer.index_file(str(zp), str(db))
    con = sqlite3.connect(db)
    scheda0 = _uid_scheda(f"recupero/sessioni/{_SID_A}.md")
    assert scheda0 < "zzzz-ultimo", "il caso deve essere quello in cui lo sha1 perdeva"
    ordine = [r[0] for r in con.execute(
        "SELECT uuid FROM messages WHERE uuid IN ('rc-u1','rc-a1','zzzz-ultimo')"
        " OR project='recupero:sessioni' ORDER BY ts ASC, uuid ASC")]
    assert ordine[:3] == ["rc-u1", "rc-a1", "zzzz-ultimo"], ordine
    pezzi = [_uid_scheda(f"recupero/sessioni/{_SID_A}.md", i) for i in range(len(ordine) - 3)]
    assert len(pezzi) >= 2 and ordine[3:] == pezzi, "la scheda in coda, pezzi nell'ordine del testo"
    ts = [r[0] for r in con.execute(
        "SELECT ts FROM messages WHERE project='recupero:sessioni' ORDER BY ts")]
    assert ts[:2] == ["2026-09-10T10:05:00.001Z", "2026-09-10T10:05:00.002Z"], ts
    assert archive_indexer._ts_dopo("2026-09-10T10:05:00Z", 1) == "2026-09-10T10:05:01.000Z"
    assert archive_indexer._ts_dopo("2026-09-10T10:05:00Z", 1) > "2026-09-10T10:05:00Z"
    assert archive_indexer._ts_dopo("formato-ignoto", 1) == "formato-ignoto"


def test_recupero_scheda_con_meno_pezzi_toglie_quelli_in_piu(tmp_path: Path) -> None:
    """Una scheda di 2 pezzi riscritta in 1: il pezzo 2 NON resta orfano in
    `messages` (né in FTS, né negli avvistamenti) a fingersi corrente; la sua
    versione esce in `revisions`, come farebbe un REPLACE (D18)."""
    membro = f"recupero/sessioni/{_SID_A}.md"
    campi = {"contratto": "R1", "tipo": "sessione", "sessionId": _SID_A,
             "last_ts": "2026-09-10T10:05:00.000Z", "last_uuid": "rc-a1"}
    # il primo paragrafo supera da solo il pezzo da 8000: il secondo fa il pezzo 2
    lungo = "\n\n".join(["inizio-scheda " + "x" * 8100, "coda-da-togliere " + "y" * 100])
    uno = _membri_recupero()
    uno[membro] = _scheda(campi, lungo)
    due = _membri_recupero()
    due[membro] = _scheda(campi, "scheda-corta-nuova")
    db = tmp_path / "out.db"
    archive_indexer.index_file(str(_bundle_recupero(tmp_path, nome="uno.zip", recupero=uno)), str(db))
    p0, p1 = _uid_scheda(membro, 0), _uid_scheda(membro, 1)
    con = sqlite3.connect(db)
    assert con.execute("SELECT count(*) FROM messages WHERE uuid IN (?,?)",
                       (p0, p1)).fetchone()[0] == 2, "la fixture doveva fare due pezzi"
    con.close()
    archive_indexer.index_file(str(_bundle_recupero(tmp_path, nome="due.zip", recupero=due)), str(db))
    con = sqlite3.connect(db)
    assert [r[0] for r in con.execute(
        "SELECT uuid FROM messages WHERE project='recupero:sessioni'")] == [p0]
    assert con.execute("SELECT count(*) FROM messages_fts WHERE messages_fts MATCH"
                       " '\"coda-da-togliere\"'").fetchone()[0] == 0, "l'FTS vede ancora il pezzo tolto"
    assert [r[0] for r in con.execute("SELECT uuid FROM sightings WHERE source=?",
                                      (membro,))] == [p0]
    rev = {u: c for u, c in con.execute("SELECT uuid, content FROM revisions")}
    assert "coda-da-togliere" in rev.get(p1, ""), "il pezzo tolto non è in revisions"
    assert "inizio-scheda" in rev.get(p0, ""), "il pezzo riscritto non è in revisions"
    assert set(rev) == {p0, p1}, rev
    # e rifare lo stesso ingest non tocca più niente
    archive_indexer.index_file(str(_bundle_recupero(tmp_path, nome="due.zip", recupero=due)), str(db))
    assert con.execute("SELECT count(*) FROM revisions").fetchone()[0] == 2


def _dump_db(db: Path) -> dict:
    """Il contenuto di un DB tabella per tabella, senza le date d'ingest."""
    con = sqlite3.connect(db)
    out = {}
    for t in ("messages", "sightings", "skipped", "meta", "revisions",
              "sessioni", "archi", "memorie"):
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({t})")
                if r[1] not in ("ingest_date", "superseded_date")]
        out[t] = sorted(con.execute(f"SELECT {', '.join(cols)} FROM {t}").fetchall(),
                        key=repr)
    con.close()
    return out


def test_ponte_workfiles_e_un_alias_di_recupero(tmp_path: Path) -> None:
    """L'app usa il ponte `workfiles/_recupero-1777/` quando la SUA copia
    dell'indexer non conosce ancora `recupero/`. Lo stesso contenuto dalle due
    radici deve dare lo STESSO DB (a parte le date d'ingest): etichette, uuid,
    testo, avvistamenti, tabelle, lapidi. E nessuna riga `workfile:`."""
    membri = _membri_recupero()
    ponte = {"workfiles/_recupero-1777/" + n[len("recupero/"):]: c for n, c in membri.items()}
    db_r, db_p = tmp_path / "r.db", tmp_path / "p.db"
    archive_indexer.index_file(str(_bundle_recupero(tmp_path, nome="r.zip", recupero=membri)), str(db_r))
    archive_indexer.index_file(str(_bundle_recupero(tmp_path, nome="p.zip", recupero=ponte)), str(db_p))
    a, b = _dump_db(db_r), _dump_db(db_p)
    for t in a:
        assert a[t] == b[t], f"la tabella {t} differisce fra recupero/ e il ponte"
    con = sqlite3.connect(db_p)
    assert con.execute("SELECT count(*) FROM messages WHERE project LIKE 'workfile:%'"
                       ).fetchone()[0] == 0, "il ponte è finito anche fra i workfiles"
    assert con.execute("SELECT count(*) FROM archi").fetchone()[0] == 1
    # e i due insieme nello stesso DB non raddoppiano
    archive_indexer.index_file(str(_bundle_recupero(tmp_path, nome="r.zip", recupero=membri)), str(db_p))
    assert _dump_db(db_p)["messages"] == a["messages"]
    # un membro sbagliato sotto il ponte: la lapide cita il nome VERO nello zip
    db_x = tmp_path / "x.db"
    archive_indexer.index_file(str(_bundle_recupero(tmp_path, nome="x.zip", recupero={
        "workfiles/_recupero-1777/sessioni/rotta.md": "senza front-matter"})), str(db_x))
    with sqlite3.connect(db_x) as c:
        assert c.execute("SELECT reason FROM skipped WHERE detail LIKE"
                         " 'workfiles/_recupero-1777/sessioni/rotta.md:%'").fetchall() == [
            ("recupero-senza-front-matter",)]



# ── filoni in `sessioni` e `documents/` nel bundle (25/09/2026) ───────────────
# Due difetti misurati sul primo DB vero: la chiave sul solo sessionId teneva un
# filone per sessione (1.300 righe per 1.303 schede), e i documenti dell'`export`
# finivano tutti in `membro-sconosciuto`. Dati sintetici.

_RIGA_A = (_SID_A, "sessione di prova", "/percorso/sintetico/progetto",
           "2026-09-10T10:00:00.000Z", "2026-09-10T10:05:00.000Z", "rc-a1",
           f"sessions/{_SID_A}.jsonl", "turno-chiuso", "transcript", _STIRPE, "1", "2", "1")
_RIGA_A_F2 = (_SID_A, "secondo filone", "/percorso/sintetico/altro",
              "2026-09-11T10:00:00.000Z", "2026-09-11T10:05:00.000Z", "rc-f2",
              f"sessions/{_SID_A}__f2.jsonl", "turno-chiuso", "transcript", "", "", "0", "0")


def test_sessioni_due_filoni_dello_stesso_sid_sono_due_righe(tmp_path: Path) -> None:
    """Il filone `__f2` e il principale hanno lo stesso sessionId: due righe, una per
    file. Con la chiave vecchia l'INSERT OR REPLACE ne teneva una sola."""
    membri = _membri_recupero()
    membri["recupero/sessioni.tsv"] = _tsv(archive_indexer._TABELLE_RECORD["sessioni"],
                                           _RIGA_A_F2, _RIGA_A)
    db = tmp_path / "out.db"
    archive_indexer.index_file(str(_bundle_recupero(tmp_path, recupero=membri)), str(db))
    con = sqlite3.connect(db)
    assert con.execute("SELECT file, titolo FROM sessioni WHERE sessionId=? ORDER BY file",
                       (_SID_A,)).fetchall() == [
        (f"sessions/{_SID_A}.jsonl", "sessione di prova"),
        (f"sessions/{_SID_A}__f2.jsonl", "secondo filone")]
    # re-ingest: le stesse due righe, non quattro
    archive_indexer.index_file(str(_bundle_recupero(tmp_path, recupero=membri)), str(db))
    assert con.execute("SELECT count(*) FROM sessioni").fetchone()[0] == 2


def test_sessioni_riga_senza_file_lascia_la_lapide(tmp_path: Path) -> None:
    """`file` è parte della chiave: una riga senza non è un filone, e lo dice."""
    membri = _membri_recupero()
    senza = _RIGA_A[:6] + ("",) + _RIGA_A[7:]
    membri["recupero/sessioni.tsv"] = _tsv(archive_indexer._TABELLE_RECORD["sessioni"],
                                           senza, _RIGA_A_F2)
    db = tmp_path / "out.db"
    archive_indexer.index_file(str(_bundle_recupero(tmp_path, recupero=membri)), str(db))
    con = sqlite3.connect(db)
    assert con.execute("SELECT file FROM sessioni").fetchall() == [
        (f"sessions/{_SID_A}__f2.jsonl",)]
    assert con.execute("SELECT count(*) FROM skipped WHERE reason='recupero-tsv-fuori-contratto'"
                       " AND detail LIKE '%riga 2: chiave vuota (file)%'").fetchone()[0] == 1


def _db_sessioni_chiave_vecchia(tmp_path: Path) -> Path:
    """Un DB come quelli caricati con la v0.51.x: `sessioni` con PRIMARY KEY sessionId,
    costruita A MANO (non dallo _SCHEMA di oggi), con due righe — una col `file` NULL."""
    db = _db_v2(tmp_path, [("vecchia", "p", "2026-01-01", "riga di prima", "user")])
    with sqlite3.connect(db) as c:
        c.execute("""CREATE TABLE sessioni(
            sessionId TEXT PRIMARY KEY, titolo TEXT, cwd TEXT, first_ts TEXT,
            last_ts TEXT, last_uuid TEXT, file TEXT, stato TEXT, stato_fonte TEXT,
            stirpe TEXT, stirpe_pos INTEGER, n_commit INTEGER, n_fili INTEGER,
            ingest_date TEXT)""")
        c.execute("INSERT INTO sessioni VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  _RIGA_A_F2 + ("2026-09-24T20:00:00Z",))
        c.execute("INSERT INTO sessioni VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (_SID_B, "senza file", "", "", "", "", None, "", "", "", None, 0, 0,
                   "2026-09-24T20:00:00Z"))
    return db


def _pk(con: sqlite3.Connection, tabella: str) -> tuple:
    return tuple(r[1] for r in sorted(con.execute(f"PRAGMA table_info({tabella})"),
                                      key=lambda r: r[5]) if r[5])


def test_migrazione_sessioni_alla_chiave_con_file(tmp_path: Path) -> None:
    """Un DB con la tabella vecchia si apre per un ingest: la tabella è ricreata con
    la chiave (sessionId, file), le righe ci sono tutte (il `file` NULL diventa ''),
    e il filone che la chiave vecchia aveva schiacciato torna col re-ingest."""
    db = _db_sessioni_chiave_vecchia(tmp_path)
    prima = sqlite3.connect(db).execute(
        "SELECT sessionId, titolo, last_uuid, stirpe_pos, n_commit, ingest_date FROM sessioni"
        " ORDER BY sessionId").fetchall()
    archive_indexer.write_rows(db, [("nuova", "p", "2026-01-02", "riga di dopo")])
    con = sqlite3.connect(db)
    assert _pk(con, "sessioni") == ("sessionId", "file")
    assert con.execute(
        "SELECT sessionId, titolo, last_uuid, stirpe_pos, n_commit, ingest_date FROM sessioni"
        " ORDER BY sessionId").fetchall() == prima, "una riga persa o cambiata"
    assert con.execute("SELECT file FROM sessioni WHERE sessionId=?",
                       (_SID_B,)).fetchone() == ("",)
    assert con.execute("SELECT count(*) FROM sqlite_master WHERE name LIKE '%chiave_vecchia%'"
                       ).fetchone()[0] == 0, "la tabella d'appoggio è rimasta"
    assert con.execute("SELECT count(*) FROM messages").fetchone()[0] == 2
    # idempotente: la seconda volta non c'è niente da migrare
    assert archive_indexer._ensure_sessioni_filoni(con) is False
    con.close()
    membri = _membri_recupero()
    membri["recupero/sessioni.tsv"] = _tsv(archive_indexer._TABELLE_RECORD["sessioni"],
                                           _RIGA_A, _RIGA_A_F2)
    archive_indexer.index_file(str(_bundle_recupero(tmp_path, recupero=membri)), str(db))
    con = sqlite3.connect(db)
    assert con.execute("SELECT count(*) FROM sessioni WHERE sessionId=?",
                       (_SID_A,)).fetchone()[0] == 2, "il filone schiacciato non è tornato"


def test_migrazione_sessioni_fallita_non_tocca_niente(tmp_path: Path, monkeypatch) -> None:
    """In transazione: se la ricopia fallisce, la tabella vecchia resta com'era (stessa
    chiave, stesse righe) e l'errore esce — mai una tabella a metà."""
    db = _db_sessioni_chiave_vecchia(tmp_path)
    monkeypatch.setattr(archive_indexer, "_SCHEMA",
                        archive_indexer._SCHEMA.replace("n_fili      INTEGER,",
                                                        "n_fili      INTEGER CHECK(0),", 1))
    con = sqlite3.connect(db)
    with pytest.raises(sqlite3.IntegrityError):
        archive_indexer._ensure_sessioni_filoni(con)
    assert _pk(con, "sessioni") == ("sessionId",)
    assert con.execute("SELECT count(*) FROM sessioni").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM sqlite_master WHERE name LIKE '%chiave_vecchia%'"
                       ).fetchone()[0] == 0


def test_documents_del_bundle_entrano_come_i_workfiles(tmp_path: Path, monkeypatch) -> None:
    """Uno zip della cartella dell'`export` (MANIFEST.json + sessions/ + documents/) è
    un bundle: i documenti diventano righe `document…` con la stessa trafila dei
    workfiles (testo a chunk, sniff del contenuto, lapidi per binari e immagini senza
    OCR, col `source` loro) — non più `membro-sconosciuto`."""
    import zipfile
    zp = tmp_path / "export.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("MANIFEST.json", "{}")
        z.writestr(f"sessions/{_SID_A}.jsonl", json.dumps(
            {"type": "user", "uuid": "d-u1", "timestamp": "2026-09-10T10:00:00.000Z",
             "cwd": "/percorso/sintetico", "message": {"role": "user", "content": "ciao"}}))
        z.writestr("documents/0123456789__nota.md", "# nota\n\nsegno-documento-piatto")
        z.writestr("documents/appunti/lista.txt", "segno-documento-in-cartella")
        z.writestr("documents/abcdef0123__Dockerfile", "FROM scratch\nsegno-sniffato")
        z.writestr("documents/fedcba9876__dati.bin", b"\x00\x01binario")
        z.writestr("documents/1111111111__foto.png", b"\x89PNG\r\n\x1a\nfinto")
    monkeypatch.delenv("OCR_URL", raising=False)     # niente servizio OCR: lapide dichiarata
    db = tmp_path / "out.db"
    archive_indexer.index_file(str(zp), str(db))
    con = sqlite3.connect(db)
    righe = dict(con.execute(
        "SELECT substr(content, 1, instr(content, ']')), project FROM messages"
        " WHERE project LIKE 'document%'"))
    assert righe == {"[documents/0123456789__nota.md]": "document",
                     "[documents/appunti/lista.txt]": "document:appunti",
                     "[documents/abcdef0123__Dockerfile]": "document"}, righe
    assert con.execute("SELECT count(*) FROM messages WHERE content LIKE"
                       " '%[testo-sniffato]%segno-sniffato%'").fetchone()[0] == 1
    lapidi = set(con.execute("SELECT source, reason, detail FROM skipped"
                             " WHERE detail LIKE 'documents/%'"))
    assert lapidi == {("bundle-documents", "non-testo", "documents/fedcba9876__dati.bin"),
                      ("bundle-documents", "ocr-non-disponibile",
                       "documents/1111111111__foto.png")}, lapidi
    assert con.execute("SELECT count(*) FROM skipped WHERE reason='membro-sconosciuto'"
                       ).fetchone()[0] == 0


# ═══════════════════ SPEAKER degli output degli strumenti (26/09/2026) ══
# Misurato sul primario Claude Code: 75.072 delle 89.950 righe `speaker='human'`
# (83%) erano tool_result — in Claude Code l'output di un comando viaggia in un
# record di tipo `user`. Il filtro «le parole di chi scrive» restituiva soprattutto
# `ls`, referti di script, file letti. Le eccezioni sono parole vere dell'utente
# dentro un tool_result: le risposte alle domande a opzioni e i rifiuti motivati.

_TR_OUTPUT = ('{"type":"user","uuid":"t1","timestamp":"2026-02-02T10:00:00Z","message":'
              '{"role":"user","content":[{"type":"tool_result","tool_use_id":"x",'
              '"content":"total 8\\ndrwxr-xr-x 2 a a 4096 ."}]}}')
_TR_RISPOSTA_1 = ('{"type":"user","uuid":"t2","timestamp":"2026-02-02T10:00:01Z","message":'
                  '{"role":"user","content":[{"type":"tool_result","tool_use_id":"y","content":'
                  '"Your questions have been answered: \\"Da dove parto?\\"=\\"parti da A\\"."}]}}')
_TR_RISPOSTA_2 = ('{"type":"user","uuid":"t3","timestamp":"2026-02-02T10:00:02Z","message":'
                  '{"role":"user","content":[{"type":"tool_result","tool_use_id":"z","content":'
                  '[{"type":"text","text":"The user answered: \\"Quale?\\"=\\"la prima\\""}]}]}}')
_TR_RIFIUTO_PAROLE = ('{"type":"user","uuid":"t4","timestamp":"2026-02-02T10:00:03Z","message":'
                      '{"role":"user","content":[{"type":"tool_result","tool_use_id":"w","content":'
                      '"The user doesn\'t want to proceed with this tool use. The tool use was '
                      'rejected. To tell you how to proceed, the user said:\\nprima leggi il file"}]}}')
_TR_RIFIUTO_MUTO = ('{"type":"user","uuid":"t5","timestamp":"2026-02-02T10:00:04Z","message":'
                    '{"role":"user","content":[{"type":"tool_result","tool_use_id":"v","content":'
                    '"The user doesn\'t want to proceed with this tool use. The tool use was rejected."}]}}')
_TR_CITA_RISPOSTA = ('{"type":"user","uuid":"t6","timestamp":"2026-02-02T10:00:05Z","message":'
                     '{"role":"user","content":[{"type":"tool_result","tool_use_id":"u","content":'
                     '"grep: 12: Your questions have been answered: ..."}]}}')


def test_tool_result_non_e_parola_dell_utente() -> None:
    """Un record `user` fatto SOLO di output di strumenti diventa `sender='strumento'`
    → `speaker='tool'`; le parole vere dell'utente dentro un tool_result restano
    `user` → `human`. Il riconoscimento è ANCORATO all'inizio del testo: una forma
    citata dentro l'output di un grep (t6) non è una risposta."""
    import io as _io
    righe = "\n".join([_TR_OUTPUT, _TR_RISPOSTA_1, _TR_RISPOSTA_2, _TR_RIFIUTO_PAROLE,
                       _TR_RIFIUTO_MUTO, _TR_CITA_RISPOSTA])
    rows = [r for r in archive_indexer._iter_claude_code(_io.StringIO(righe), "p")
            if not isinstance(r, archive_indexer._Skip)]
    sender = {r[0]: r[4] for r in rows}
    assert sender == {"t1": "strumento", "t2": "user", "t3": "user", "t4": "user",
                      "t5": "strumento", "t6": "strumento"}
    assert archive_indexer.speaker_da_sender("strumento") == "tool"


def test_tool_result_di_sidechain_resta_mandato() -> None:
    """L'ordine conta: un tool_result in una sidechain è della macchina come il
    mandato (AN-11, 28/08), e non deve cambiare categoria con questa cura."""
    import io as _io
    riga = ('{"type":"user","uuid":"s1","timestamp":"2026-02-02T10:00:00Z","isSidechain":true,'
            '"message":{"role":"user","content":[{"type":"tool_result","content":"ok"}]}}')
    rows = [r for r in archive_indexer._iter_claude_code(_io.StringIO(riga), "p")
            if not isinstance(r, archive_indexer._Skip)]
    assert rows[0][4] == "mandato"


def test_contratto_bucket_strumento() -> None:
    """Il verdetto del contratto dei bucket per i tre casi nuovi: la corsia app
    confronta solo keep/skip, ma il mittente è parte del verdetto e va inchiodato."""
    import io as _io
    verdicts = archive_indexer.classify_cc(
        _io.StringIO("\n".join([_TR_OUTPUT, _TR_RISPOSTA_1, _TR_RIFIUTO_PAROLE]) + "\n"))
    assert verdicts == ["keep:strumento", "keep:user", "keep:user"]


def _db_cc_vecchio(tmp_path: Path) -> Path:
    """Un DB scritto dall'indexer di PRIMA: i tool_result come `user`/`human`."""
    db = tmp_path / "vecchio.db"
    righe = "\n".join([_TR_OUTPUT, _TR_RISPOSTA_1, _TR_RIFIUTO_PAROLE, _TR_RIFIUTO_MUTO,
                       '{"type":"user","uuid":"p1","timestamp":"2026-02-02T10:00:09Z",'
                       '"message":{"role":"user","content":"parola vera"}}'])
    archive_indexer.write_rows(
        db, archive_indexer._iter_claude_code(_io_mod().StringIO(righe), "p"))
    with sqlite3.connect(db) as c:
        c.execute("UPDATE messages SET sender='user', speaker='human' WHERE uuid LIKE 't%'")
    return db


def _io_mod():
    import io
    return io


def test_migrazione_strumenti_retroattiva_e_idempotente(tmp_path: Path) -> None:
    """Sui DB già caricati la cura è una migrazione, non un re-ingest: il testo non
    cambia, quindi FTS e indice semantico restano validi. Tocca solo le righe
    `user` con `content=''` e `tools` pieni che NON sono parole dell'utente."""
    db = _db_cc_vecchio(tmp_path)
    with sqlite3.connect(db) as c:
        assert archive_indexer._ensure_speaker_strumenti(c) == 2
        stato = dict(c.execute("SELECT uuid, sender || '/' || speaker FROM messages"
                               " WHERE uuid IN ('t1','t2','t4','t5','p1')"))
        assert stato == {"t1": "strumento/tool", "t2": "user/human", "t4": "user/human",
                         "t5": "strumento/tool", "p1": "user/human"}
        assert archive_indexer._ensure_speaker_strumenti(c) == 0, "idempotente"


def test_migrazione_agganciata_all_ingest(tmp_path: Path) -> None:
    """Un ingest in un DB vecchio lo migra: l'aggancio è in `write_rows`, come per
    le altre colonne derivate (#271)."""
    db = _db_cc_vecchio(tmp_path)
    archive_indexer.write_rows(db, iter(()))
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT count(*) FROM messages WHERE speaker='tool'").fetchone()[0] == 2


def test_cli_migra_a_secco_poi_scrive(tmp_path: Path, capsys) -> None:
    """`--migra` senza `--scrivi` calcola il delta VERO e non salva niente (lo stesso
    patto di `--retag`); con `--scrivi` applica."""
    db = _db_cc_vecchio(tmp_path)
    assert archive_indexer.main([str(db), "--migra"]) == 0
    esito = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert esito["strumenti"] == 2 and esito["scritto"] is False
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT count(*) FROM messages WHERE speaker='tool'").fetchone()[0] == 0
    assert archive_indexer.main([str(db), "--migra", "--scrivi"]) == 0
    esito = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert esito["scritto"] is True
    assert esito["speaker_prima"]["human"] == 5 and esito["speaker_dopo"]["tool"] == 2
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT count(*) FROM messages WHERE speaker='tool'").fetchone()[0] == 2


# ═══════════════════ SPEAKER dei turni del programma — #293 (26/09/2026) ══
# Dopo la cura degli strumenti, sul primario restavano 14.878 righe `human`: 9.643
# erano <task-notification>, poi output di comandi locali, riassunti di compattazione,
# testi delle skill, messaggi di altre sessioni. Li inietta il programma in un record
# di tipo user. Le versioni recenti di Claude Code lo DICONO nel record (`origin.kind`,
# `isMeta`, `isCompactSummary`): quello è il fatto. Le forme del testo servono per le
# versioni che non lo scrivevano, e per i DB già caricati, dove i campi non ci sono.

def _cc_user(uuid: str, testo: str, **campi) -> str:
    d = {"type": "user", "uuid": uuid, "timestamp": "2026-02-02T10:00:00Z",
         "message": {"role": "user", "content": testo}, **campi}
    return json.dumps(d)


def test_turni_del_programma_sono_system() -> None:
    import io as _io
    righe = "\n".join([
        # il fatto nel record
        _cc_user("o1", "<task-notification>\n<task-id>x</task-id>",
                 origin={"kind": "task-notification"}),
        _cc_user("o2", "Another Claude session sent a message: ciao",
                 origin={"kind": "peer"}, isMeta=True),
        _cc_user("o3", "qualunque testo", isMeta=True),
        _cc_user("o4", "This session is being continued…", isCompactSummary=True),
        # origin human vince anche su una forma che sembra del programma
        _cc_user("h1", "<task-notification> te lo incollo io", origin={"kind": "human"}),
        # versioni senza i campi: le forme ancorate
        _cc_user("f1", "<task-notification>\n<task-id>y</task-id>"),
        _cc_user("f2", "<local-command-stdout>ok</local-command-stdout>"),
        _cc_user("f3", "Caveat: The messages below were generated by the user while running local commands."),
        _cc_user("f4", "This session is being continued from a previous conversation that ran out of context."),
        _cc_user("f5", "Base directory for this skill: /x/skills/y"),
        _cc_user("f6", "<system-reminder>promemoria</system-reminder>"),
        _cc_user("f7", "<bash-stdout>total 8</bash-stdout>"),
        # restano human: gesti e parole di chi scrive
        _cc_user("u1", "<command-name>/compact</command-name>"),
        _cc_user("u2", "<bash-input>ls</bash-input>"),
        _cc_user("u3", "guarda <task-notification> dentro una frase"),
        _cc_user("u4", "parola vera"),
    ])
    rows = [r for r in archive_indexer._iter_claude_code(_io.StringIO(righe), "p")
            if not isinstance(r, archive_indexer._Skip)]
    sender = {r[0]: r[4] for r in rows}
    sistema = {"o1", "o2", "o3", "o4", "f1", "f2", "f3", "f4", "f5", "f6", "f7"}
    assert {u for u, s in sender.items() if s == "sistema"} == sistema
    assert {u for u, s in sender.items() if s == "user"} == {"h1", "u1", "u2", "u3", "u4"}
    assert archive_indexer.speaker_da_sender("sistema") == "system"


def test_contratto_bucket_sistema() -> None:
    import io as _io
    verdicts = archive_indexer.classify_cc(_io.StringIO("\n".join([
        _cc_user("o1", "<task-notification>", origin={"kind": "task-notification"}),
        _cc_user("u1", "parola vera", origin={"kind": "human"})]) + "\n"))
    assert verdicts == ["keep:sistema", "keep:user"]


def test_migrazione_sistema_retroattiva_e_idempotente(tmp_path: Path) -> None:
    """Nei DB già caricati i campi del record non ci sono: la migrazione legge le
    forme del testo. Le parole vere e gli slash command restano human."""
    import io as _io
    db = tmp_path / "vecchio.db"
    righe = "\n".join([
        _cc_user("f1", "<task-notification>\n<task-id>y</task-id>"),
        _cc_user("f2", "<local-command-stdout>ok</local-command-stdout>"),
        _cc_user("u1", "<command-name>/compact</command-name>"),
        _cc_user("u4", "parola vera")])
    archive_indexer.write_rows(db, archive_indexer._iter_claude_code(_io.StringIO(righe), "p"))
    with sqlite3.connect(db) as c:
        c.execute("UPDATE messages SET sender='user', speaker='human'")
        assert archive_indexer._ensure_speaker_sistema(c) == 2
        stato = dict(c.execute("SELECT uuid, sender || '/' || speaker FROM messages"))
        assert stato == {"f1": "sistema/system", "f2": "sistema/system",
                         "u1": "user/human", "u4": "user/human"}
        assert archive_indexer._ensure_speaker_sistema(c) == 0, "idempotente"
    esito = archive_indexer.migra_derivate(db)
    assert esito["sistema"] == 0 and esito["strumenti"] == 0
