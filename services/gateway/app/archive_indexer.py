#!/usr/bin/env python3
"""
archive_indexer — costruisce/aggiorna un DB SQLite FTS5 per archive-mcp da fonti
eterogenee, tutte ridotte allo stesso schema.

Schema prodotto (compatibile col `search` di archive-mcp):
    messages(uuid PRIMARY KEY, project, ts, content)          -- sorgente
    messages_fts USING fts5(uuid, project, ts, content, content='messages', ...)

Formati (dispatch per estensione in `index_file`; i .zip si riconoscono dal
contenuto, non dal nome):
    .jsonl        → sessione Claude Code (record user/assistant)
    .zip claude.ai → export account (conversations.json + design_chats/ + projects/docs)
    .zip Telegram  → export Desktop JSON (result.json) o HTML (messages*.html),
                     anche in sottocartella ChatExport_*/
    .json         → export Telegram Desktop (result.json) o sessione Claude Code
    .md / .txt    → testo/markdown generico (ponte per output di altri tool), spezzato in chunk
    (.db)         → NON qui: è un drop-in, si copia direttamente nella dir
Uno zip non riconosciuto — o riconosciuto ma senza messaggi estraibili — è un
ERRORE esplicito, mai un successo a 0 righe (stesso principio dei PDF-immagine).

Indexer CONDIVISO, due usi:
  - server-side: il gateway lo importa e chiama `index_file(...)` in /admin/archive
  - locale:      `python3 archive_indexer.py <input> out.db --project nome`

Solo stdlib (json, zipfile, sqlite3, hashlib). Idempotente per `uuid`
(INSERT OR REPLACE): re-indicizzare non duplica; fonti diverse nello stesso DB
si accumulano. L'FTS si ricostruisce a fine ingest ('rebuild') — coerente e
immune alla corruzione da REPLACE dei trigger external-content.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import IO, Iterable, Iterator, NamedTuple, Union

Row = tuple[str, str, str, str]  # (uuid, project, ts, content) — forma breve, ancora accettata
RowFull = tuple[str, str, str, str, str, str, str, str, str]
# (uuid, project, ts, content, sender, tools, thinking, attachments, parent_uuid)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages(
    uuid        TEXT PRIMARY KEY,
    project     TEXT,
    ts          TEXT,
    content     TEXT,
    sender      TEXT DEFAULT '',
    tools       TEXT DEFAULT '',
    thinking    TEXT DEFAULT '',
    attachments TEXT DEFAULT '',
    parent_uuid TEXT DEFAULT ''
);
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    uuid, project, ts, content, tools, attachments,
    content='messages', content_rowid='rowid'
);
"""
# NOTA sullo schema FTS — perché `tools` sì e `thinking` no.
#
# `tools` (tool_use + tool_result) È il contenuto informativo di un messaggio
# agentico: il file aperto, il comando lanciato, la query eseguita. Scartarlo
# significa costruire un archivio di sole DICHIARAZIONI, in cui una ricerca su un
# tratto identitario premia la frase più esplicita — chiunque l'abbia detta — perché
# non c'è nessuna AZIONE che possa contraddirla. Va nell'FTS: è ciò che si cerca.
#
# `thinking` si conserva nella tabella (recuperabile da get_context / SQL) ma NON si
# indicizza: sono ~9.400 blocchi di ragionamento dell'assistente su un export reale,
# e nessuno li sta cercando quando interroga l'archivio. Indicizzarli inquinerebbe
# ogni `MATCH` e ogni `bm25`. Non buttarli ≠ metterli in mezzo.
#
# Chi volesse cercarli può aggiungerli all'FTS: `fts.py` supporta già il column
# filter `col:term`, quindi la ricerca mirata è a costo zero.
#
# MIGRAZIONE: le colonne nuove hanno DEFAULT '' → un DB v1 (4 colonne) si apre e si
# legge. Per portarlo allo schema nuovo servono ALTER TABLE + rebuild dell'FTS:
# vedi `migrate_v1_to_v2()` in fondo al file.


# ── core: scrittura DB ───────────────────────────────────────────────────────

_NCOLS = 9  # uuid, project, ts, content, sender, tools, thinking, attachments, parent_uuid


def _pad(row: tuple) -> RowFull:
    """Normalizza una riga alla forma piena. Accetta ancora le righe a 4 campi
    (uuid, project, ts, content): gli estrattori esterni non si rompono."""
    return tuple(row) + ("",) * (_NCOLS - len(row))  # type: ignore[return-value]


def write_rows(db_path: Union[str, Path], rows: Iterable[tuple], *, batch: int = 500) -> int:
    """Scrive/aggiorna le righe in db_path e ricostruisce l'FTS. Ritorna #righe.

    Riusabile da qualunque estrattore (server-side o locale). `rows` è un
    iterabile/generatore → streaming, memoria costante.

    Accetta righe a 4 campi (forma storica) o a 8 (forma piena, con
    sender/tools/thinking/attachments): le prime vengono completate con stringhe
    vuote, così un estrattore di terze parti continua a funzionare.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_SCHEMA)
        _ensure_v2(conn)  # DB creato da una versione precedente → aggiunge le colonne
        n = 0
        buf: list[RowFull] = []

        def flush() -> None:
            if buf:
                conn.executemany(
                    "INSERT OR REPLACE INTO messages"
                    "(uuid, project, ts, content, sender, tools, thinking, attachments,"
                    " parent_uuid) VALUES (?,?,?,?,?,?,?,?,?)", buf,
                )
                buf.clear()

        for row in rows:
            buf.append(_pad(row))
            n += 1
            if len(buf) >= batch:
                flush()
        flush()
        conn.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
        conn.commit()
        return n
    finally:
        conn.close()


def _ensure_v2(conn: sqlite3.Connection) -> bool:
    """Porta un DB v1 (4 colonne) allo schema v2, in modo idempotente.

    Ritorna True se ha migrato. L'FTS viene ricostruita comunque a fine ingest
    (`'rebuild'`), quindi qui basta aggiungere le colonne e rifare la tabella FTS
    se ha ancora la forma vecchia.
    """
    have = {r[1] for r in conn.execute("PRAGMA table_info(messages)")}
    missing = [c for c in ("sender", "tools", "thinking", "attachments", "parent_uuid")
               if c not in have]
    if not missing:
        return False
    for col in missing:
        conn.execute(f"ALTER TABLE messages ADD COLUMN {col} TEXT DEFAULT ''")
    # l'FTS external-content deve rispecchiare le colonne indicizzate: si rifà.
    conn.execute("DROP TABLE IF EXISTS messages_fts")
    conn.executescript(_SCHEMA)
    return True


def migrate_v1_to_v2(db_path: Union[str, Path]) -> bool:
    """Migra un DB esistente allo schema v2 (colonne nuove + FTS ricostruita).

    Idempotente: su un DB già v2 non fa nulla e ritorna False. NON re-indicizza le
    fonti: i messaggi già presenti restano com'erano (tools/thinking vuoti). Per
    popolarli va ri-eseguito l'ingest sulla fonte originale — che è idempotente per
    `uuid` (INSERT OR REPLACE), quindi non duplica.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        migrated = _ensure_v2(conn)
        if migrated:
            conn.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
            conn.commit()
        return migrated
    finally:
        conn.close()


def count_rows(db_path: Union[str, Path]) -> int:
    """Numero di messaggi in un DB (per la UI). 0 se non leggibile/assente."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            return int(conn.execute("SELECT count(*) FROM messages").fetchone()[0])
        finally:
            conn.close()
    except sqlite3.Error:
        return 0


def db_info(db_path: Union[str, Path], *, top: int = 5) -> dict:
    """Scheda di un DB per le UI (admin + Mini App): righe, etichette distinte,
    le `top` etichette più popolose, dimensione file e ultima modifica.
    Robusto: DB assente o illeggibile → scheda a zero, mai un'eccezione."""
    p = Path(db_path)
    out: dict = {"name": p.stem, "rows": 0, "labels": 0, "top": [],
                 "size": 0, "mtime": ""}
    try:
        out["size"] = p.stat().st_size
        out["mtime"] = _file_ts(p)
    except OSError:
        pass
    try:
        conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        try:
            out["rows"] = int(conn.execute("SELECT count(*) FROM messages").fetchone()[0])
            out["labels"] = int(conn.execute(
                "SELECT count(DISTINCT project) FROM messages").fetchone()[0])
            out["top"] = [
                {"label": label or "", "rows": n}
                for label, n in conn.execute(
                    "SELECT project, count(*) FROM messages "
                    "GROUP BY project ORDER BY count(*) DESC, project LIMIT ?",
                    (max(0, top),),
                )
            ]
        finally:
            conn.close()
    except sqlite3.Error:
        pass
    return out


def find_db(db_dir: Union[str, Path], name: str) -> Union[Path, None]:
    """Path del DB `name` dentro db_dir — SOLO se combacia con lo stem di un
    *.db reale della dir (niente path traversal per costruzione: si confronta
    col listato, non si costruisce un path dall'input)."""
    d = Path(db_dir)
    if not name or not d.is_dir():
        return None
    for p in d.glob("*.db"):
        if p.is_file() and p.stem == name:
            return p
    return None


# ── helper testo ─────────────────────────────────────────────────────────────

class Blocks(NamedTuple):
    """I pezzi di un messaggio, separati invece che buttati."""
    text: str       # il parlato
    tools: str      # tool_use + tool_result — LE AZIONI
    thinking: str   # il ragionamento dell'assistente


def _tool_line(b: dict) -> str:
    """Un blocco tool_use/tool_result reso una riga cercabile.

    `tool_use`  → "«Read» {\"file_path\": \"lib/main.dart\"}"  ← il dato che conta
    `tool_result` → il testo del risultato (può essere str o lista di blocchi)
    """
    kind = b.get("type")
    if kind == "tool_use":
        name = str(b.get("name") or "tool")
        inp = b.get("input")
        arg = inp if isinstance(inp, str) else json.dumps(inp, ensure_ascii=False) if inp else ""
        return f"{name} {arg}".strip()
    if kind == "tool_result":
        c = b.get("content")
        if isinstance(c, str):
            return c.strip()
        if isinstance(c, list):
            return "\n".join(
                str(x.get("text", "")) for x in c
                if isinstance(x, dict) and x.get("text")).strip()
        return json.dumps(c, ensure_ascii=False) if c else ""
    return ""


def extract_blocks(content: object) -> Blocks:
    """Scompone un campo `content` (stringa, lista di blocchi, dict) nei suoi pezzi.

    Sostituisce la vecchia `extract_text`, che teneva SOLO i blocchi `type=="text"`
    e scartava il resto come «rumore per la ricerca». Su un export claude.ai reale
    (13.723 messaggi) quel «rumore» era: 9.634 `tool_use`, 9.610 `tool_result`,
    9.402 `thinking` — e il campo `content` nel suo insieme vale **2,6× il campo
    `text`**. I `tool_use` sono le AZIONI: il file aperto, il comando lanciato. Sono
    il contenuto informativo del messaggio, non il suo rumore.

    dict → forma annidata delle design chats claude.ai ({"role", "content"}):
    si scende in `content`/`text` (ricorsivo — l'interno può essere str o lista).
    """
    if isinstance(content, str):
        return Blocks(content.strip(), "", "")
    if isinstance(content, list):
        texts: list[str] = []
        tools: list[str] = []
        thinks: list[str] = []
        for b in content:
            if not isinstance(b, dict):
                continue
            kind = b.get("type")
            if kind == "text" and b.get("text"):
                texts.append(str(b["text"]))
            elif kind in ("tool_use", "tool_result"):
                line = _tool_line(b)
                if line:
                    tools.append(line)
            elif kind == "thinking" and b.get("thinking"):
                thinks.append(str(b["thinking"]))
        return Blocks("\n".join(texts).strip(),
                      "\n".join(tools).strip(),
                      "\n".join(thinks).strip())
    if isinstance(content, dict):
        inner = content.get("content")
        if inner is None:
            inner = content.get("text")
        return extract_blocks(inner) if inner is not None else Blocks("", "", "")
    return Blocks("", "", "")


def extract_text(content: object) -> str:
    """Solo il parlato. Wrapper retrocompatibile su `extract_blocks`.

    Resta per gli estrattori che vogliono il vecchio comportamento (e per i test
    storici). Chi indicizza dovrebbe usare `extract_blocks`, che non perde le azioni.
    """
    return extract_blocks(content).text


def _uid(*parts: str) -> str:
    """uuid deterministico da parti (per fonti senza id nativo → dedup stabile)."""
    return hashlib.sha1("\x1f".join(parts).encode("utf-8", "replace")).hexdigest()


# ── estrattore: sessione Claude Code (.jsonl) ────────────────────────────────

_CC_TYPES = ("user", "assistant")


def _iter_claude_code(fh: IO[str], project: str) -> Iterator[RowFull]:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get("type") not in _CC_TYPES:
            continue
        uuid, ts = d.get("uuid"), d.get("timestamp")
        if not uuid or not ts:
            continue
        msg = d.get("message") or {}
        blocks = extract_blocks(msg.get("content"))
        # PRIMA: `if not text: continue` — un messaggio fatto di soli tool_use (una
        # sessione agentica ne è piena) spariva senza lasciare traccia. Ora basta che
        # abbia UN contenuto qualsiasi.
        if not (blocks.text or blocks.tools or blocks.thinking):
            continue
        proj = project or Path(str(d.get("cwd") or "unknown")).name or "unknown"
        yield (uuid, proj, ts, blocks.text, str(msg.get("role") or d.get("type") or ""),
               blocks.tools, blocks.thinking, "", str(d.get("parentUuid") or ""))


# ── estrattore: export account claude.ai (.zip) ──────────────────────────────

def _attachment_names(m: dict) -> str:
    """Nomi dei file allegati a un messaggio, cercabili. Su un export reale sono
    1.520 i messaggi con allegati: oggi non se ne salva nessuno, e «quale file mi
    aveva mandato?» è una domanda senza risposta.

    Fallback sul `file_uuid`: 80 allegati hanno `file_name: null` ma un uuid valido.
    Meglio un id cercabile che un allegato invisibile.
    """
    out: list[str] = []
    for key in ("attachments", "files"):
        for a in (m.get(key) or []):
            if isinstance(a, dict):
                n = (a.get("file_name") or a.get("name") or a.get("file_type")
                     or a.get("file_uuid") or "")
                if n:
                    out.append(str(n))
            elif isinstance(a, str):
                out.append(a)
    return "\n".join(out)


def _iter_memories(data: object) -> Iterator[RowFull]:
    """`memories.json` dell'export claude.ai — la MEMORIA PERSISTENTE dell'account.

    Contiene `conversations_memory` (ciò che l'assistente "sa" dell'utente e porta in
    OGNI conversazione) e `project_memories` (una per Project). Oggi non viene
    indicizzato affatto: l'archivio non contiene la fonte che più di ogni altra
    determina cosa l'assistente crede dell'utente.

    Perché conta: è testo scritto DA un assistente SU una persona, senza citazioni e
    senza fonti. È esattamente il tipo di materiale che, riletto mesi dopo da un'altra
    sessione, diventa indistinguibile da una dichiarazione di prima persona.
    Indicizzarlo lo rende almeno **interrogabile e confrontabile** con le fonti.
    """
    items = data if isinstance(data, list) else [data]
    for acc in items:
        if not isinstance(acc, dict):
            continue
        conv_mem = acc.get("conversations_memory")
        if isinstance(conv_mem, str) and conv_mem.strip():
            yield from _chunk_rows_full(conv_mem, "memory:conversations",
                                        "", "memory-conversations", sender="memory")
        # `project_memories` è una MAPPA {project_uuid: testo}, non una lista.
        # (Su un export reale: 9 progetti, 74.404 caratteri — più di 7× la
        # conversations_memory. Trattarla come lista ne perde il contenuto.)
        pm = acc.get("project_memories")
        entries: list[tuple[str, object]] = []
        if isinstance(pm, dict):
            entries = list(pm.items())
        elif isinstance(pm, list):
            entries = [(str(i), p) for i, p in enumerate(pm)]

        for key, p in entries:
            if isinstance(p, str):
                body = p
            elif isinstance(p, dict):
                body = str(p.get("memory") or p.get("content") or p.get("text") or "")
                key = str(p.get("name") or p.get("project_uuid") or key)
            else:
                continue
            if body.strip():
                label = f"memory:project:{key}"
                yield from _chunk_rows_full(body, label, "", label, sender="memory")


def _chunk_rows_full(text: str, name: str, ts: str, key: str, *,
                     sender: str = "", chunk_chars: int = 1500) -> Iterator[RowFull]:
    """Come `_chunk_rows`, ma emette righe nella forma piena (con `sender`)."""
    for uuid, proj, t, content in _chunk_rows(text, name, ts, key, chunk_chars=chunk_chars):
        yield (uuid, proj, t, content, sender, "", "", "", "")


def _iter_conversations(convs: list, fallback: str) -> Iterator[RowFull]:
    if not isinstance(convs, list):
        convs = [convs]
    for c in convs:
        if not isinstance(c, dict):
            continue
        name = c.get("name") or c.get("title") or fallback
        for m in (c.get("chat_messages") or c.get("messages") or []):
            if not isinstance(m, dict):
                continue
            uuid = m.get("uuid")
            if not uuid:
                continue
            # PRIMA: `m.get("text") or extract_text(m.get("content"))`.
            # Nell'export claude.ai `text` è SEMPRE valorizzato (misurato: 0 messaggi
            # con text vuoto e content pieno) → il ramo destro dell'`or` non si
            # eseguiva MAI, e il campo `content` — che vale 2,6× `text` e contiene
            # tool_use/tool_result/thinking — non veniva letto nemmeno una volta.
            blocks = extract_blocks(m.get("content"))
            text = blocks.text or (m.get("text") or "")
            attach = _attachment_names(m)
            if not (text or blocks.tools or blocks.thinking or attach):
                continue
            sender = m.get("sender") or m.get("role") or ""
            content = f"[{sender}] {text}" if sender and text else text
            yield (uuid, name, m.get("created_at") or "", content, str(sender),
                   blocks.tools, blocks.thinking, attach,
                   str(m.get("parent_message_uuid") or ""))


def _iter_claude_zip(zip_path: Union[str, Path]) -> Iterator[RowFull]:
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        if "conversations.json" in names:
            with z.open("conversations.json") as f:
                yield from _iter_conversations(json.load(f), "claude-conversations")
        # memories.json — la memoria persistente dell'account. Non veniva indicizzata:
        # l'archivio non conteneva la fonte che più di ogni altra determina cosa
        # l'assistente crede dell'utente. NOTA: `users.json` NON si indicizza — contiene
        # dati personali (email, telefono verificato) e nessun contenuto cercabile.
        if "memories.json" in names:
            with z.open("memories.json") as f:
                try:
                    yield from _iter_memories(json.load(f))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass
        for n in names:
            if n.startswith("design_chats/") and n.endswith(".json"):
                with z.open(n) as f:
                    try:
                        data = json.load(f)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
                if isinstance(data, dict):
                    # il title è sempre il generico "Chat": l'etichetta utile è
                    # il progetto di appartenenza. `name` vince su `title` in
                    # _iter_conversations, quindi la si impone qui.
                    proj = data.get("project")
                    pname = proj.get("name") if isinstance(proj, dict) else ""
                    data = {**data, "name": f"design:{pname or data.get('title') or 'chat'}"}
                yield from _iter_conversations(data, "claude-design-chats")
        for n in names:
            if n.startswith("projects/") and n.endswith(".json"):
                with z.open(n) as f:
                    try:
                        proj = json.load(f)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
                if not isinstance(proj, dict):
                    continue
                pname = f"project:{proj.get('name') or 'senza-nome'}"
                for doc in (proj.get("docs") or []):
                    if not isinstance(doc, dict):
                        continue
                    content = doc.get("content") or ""
                    uuid = doc.get("uuid") or _uid(pname, doc.get("filename") or "", content[:64])
                    if not content:
                        continue
                    fn = doc.get("filename") or ""
                    body = f"[{fn}]\n{content}" if fn else content
                    yield (uuid, pname, doc.get("created_at") or "", body)


# ── helper testo condiviso ───────────────────────────────────────────────────

def _file_ts(path: Path) -> str:
    try:
        import datetime
        return datetime.datetime.utcfromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        return ""


def _chunk_rows(text: str, name: str, ts: str, key: str, *, chunk_chars: int = 1500) -> Iterator[Row]:
    """Spezza un testo in chunk cercabili (per paragrafi, raggruppati ~chunk_chars).
    uuid deterministico (key + indice) → re-index idempotente."""
    buf: list[str] = []
    size = idx = 0
    for para in text.split("\n\n"):
        buf.append(para)
        size += len(para)
        if size >= chunk_chars:
            joined = "\n".join(buf).strip()
            if joined:
                yield (_uid(key, str(idx)), name, ts, joined)
                idx += 1
            buf, size = [], 0
    joined = "\n".join(buf).strip()
    if joined:
        yield (_uid(key, str(idx)), name, ts, joined)


# ── estrattore: testo / markdown generico ────────────────────────────────────

def _iter_text(path: Union[str, Path], project: str) -> Iterator[Row]:
    """Ponte per l'output di altri tool (web2md, lettoremd, pulizia-transcript):
    qualunque .md/.txt diventa messaggi indicizzabili."""
    path = Path(path)
    name = project or path.stem
    with open(path, encoding="utf-8", errors="replace") as fh:
        yield from _chunk_rows(fh.read(), name, _file_ts(path), name)


# ── estrattore: PDF (pypdf) ──────────────────────────────────────────────────

def _iter_pdf(path: Union[str, Path], project: str) -> Iterator[Row]:
    """Estrae il testo da un PDF (pypdf) e lo spezza in chunk. Il PDF è un
    documento: niente struttura conversazione, solo testo cercabile."""
    from pypdf import PdfReader
    path = Path(path)
    name = project or path.stem
    reader = PdfReader(str(path))
    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 — pypdf inciampa su pagine malformate: si salta
            continue
    yield from _chunk_rows("\n\n".join(pages), name, _file_ts(path), name)


# ── estrattore: export Telegram (result.json) ────────────────────────────────

def _tg_text(text: object) -> str:
    """`text` di Telegram: stringa o lista di (str | {type, text})."""
    if isinstance(text, str):
        return text
    if isinstance(text, list):
        parts = [t if isinstance(t, str) else str(t.get("text", ""))
                 for t in text if isinstance(t, (str, dict))]
        return "".join(parts)
    return ""


def _iter_telegram(data: dict) -> Iterator[Row]:
    """Export Telegram Desktop JSON: singola chat ({name,id,messages}) o full
    ({chats:{list:[...]}}). Ogni messaggio 'message' → riga."""
    if isinstance(data.get("messages"), list):
        chats = [data]
    elif isinstance(data.get("chats"), dict):
        chats = data["chats"].get("list") or []
    else:
        chats = []
    for chat in chats:
        if not isinstance(chat, dict):
            continue
        cname = chat.get("name") or f"telegram-{chat.get('id') or 'chat'}"
        cid = str(chat.get("id") or cname)
        for m in (chat.get("messages") or []):
            if not isinstance(m, dict) or m.get("type") != "message":
                continue
            body = _tg_text(m.get("text")).strip()
            if not body:
                continue
            sender = m.get("from") or ""
            yield (_uid("tg", cid, str(m.get("id"))), cname, m.get("date") or "",
                   f"[{sender}] {body}" if sender else body)


def _iter_telegram_zip(zip_path: Union[str, Path], members: list[str]) -> Iterator[Row]:
    """result.json dentro uno zip (l'export Desktop arriva spesso come cartella
    zippata: ChatExport_.../result.json). Più member = più chat, si accumulano."""
    with zipfile.ZipFile(zip_path) as z:
        for m in members:
            with z.open(m) as f:
                try:
                    data = json.load(f)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
            if isinstance(data, dict):
                yield from _iter_telegram(data)


# ── estrattore: export Telegram Desktop HTML (messages*.html) ────────────────
# Il formato DEFAULT di "Esporta cronologia chat" è HTML — molti utenti non
# trovano (o non hanno) il selettore JSON. L'HTML è machine-generated e
# stabile: div.message[id] › title con data completa › from_name › div.text.
# I messaggi "joined" (stesso mittente del precedente) non ripetono from_name.

def _tg_html_ts(raw: str) -> str:
    """'02.03.2024 13:10:33 UTC+01:00' → '2024-03-02T13:10:33+01:00' (ISO,
    ordinabile e coerente col formato JSON). Se non combacia → raw."""
    m = re.match(
        r"(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}:\d{2}:\d{2})"
        r"(?:\s+UTC([+-]\d{2}):?(\d{2}))?", raw.strip())
    if not m:
        return raw.strip()
    day, mon, year, hms, oh, om = m.groups()
    return f"{year}-{mon}-{day}T{hms}" + (f"{oh}:{om or '00'}" if oh else "")


class _TgHtmlParser(HTMLParser):
    """Estrae (msg_id, sender, ts, text) da un messages*.html di Telegram
    Desktop. Solo stdlib; ignora service message e media senza testo."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chat_title = ""
        self.msgs: list[tuple[str, str, str, str]] = []
        self._depth = 0            # nesting dei soli <div>
        self._msg_depth = 0        # profondità del div.message aperto (0 = fuori)
        self._msg_id = ""
        self._joined = False
        self._ts = ""
        self._sender = ""
        self._last_sender = ""     # per i "joined" (mittente ereditato)
        self._texts: list[str] = []
        self._cap = ""             # cosa sto catturando: text | from_name | title
        self._cap_depth = 0
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "br":
            if self._cap:
                self._buf.append("\n")
            return
        if tag != "div":
            return
        self._depth += 1
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        if "message" in classes and "default" in classes:
            self._flush_msg()      # difensivo: chiude un eventuale precedente
            self._msg_depth = self._depth
            self._msg_id = (a.get("id") or "").removeprefix("message")
            self._joined = "joined" in classes
            self._ts = self._sender = ""
            self._texts = []
        elif self._msg_depth:
            if "date" in classes and "details" in classes and a.get("title"):
                self._ts = self._ts or _tg_html_ts(a["title"])
            elif classes == ["from_name"] and not self._cap:
                self._cap, self._cap_depth, self._buf = "from_name", self._depth, []
            elif classes == ["text"] and not self._cap:
                self._cap, self._cap_depth, self._buf = "text", self._depth, []
        elif classes == ["text", "bold"] and not self.chat_title and not self._cap:
            self._cap, self._cap_depth, self._buf = "title", self._depth, []

    def handle_endtag(self, tag: str) -> None:
        if tag != "div":
            return
        if self._cap and self._depth == self._cap_depth:
            got = "".join(self._buf).strip()
            if self._cap == "from_name":
                self._sender = self._sender or got
            elif self._cap == "text":
                if got:
                    self._texts.append(got)
            elif self._cap == "title":
                self.chat_title = got
            self._cap = ""
        if self._msg_depth and self._depth == self._msg_depth:
            self._flush_msg()
        self._depth = max(0, self._depth - 1)

    def handle_data(self, data: str) -> None:
        if self._cap:
            self._buf.append(data)

    def _flush_msg(self) -> None:
        if not self._msg_depth:
            return
        sender = self._sender or (self._last_sender if self._joined else "")
        if self._sender:
            self._last_sender = self._sender
        text = "\n".join(self._texts).strip()
        if text and self._msg_id:
            self.msgs.append((self._msg_id, sender, self._ts, text))
        self._msg_depth = 0
        self._msg_id = self._ts = self._sender = ""
        self._texts = []


def _iter_telegram_html_zip(zip_path: Union[str, Path], members: list[str]) -> Iterator[Row]:
    """messages.html, messages2.html, … dentro uno zip export (in ordine
    numerico, così i 'joined' a cavallo dei file ereditano il mittente giusto
    per file — al peggio il primo joined di un file resta senza mittente).

    Nota dedup: l'HTML non contiene l'id numerico della chat → la chiave usa il
    titolo. Ricaricare lo stesso export non duplica; mischiare HTML e JSON
    della STESSA chat nello stesso DB invece sì (chiavi diverse) — documentato.
    """
    def order(name: str) -> tuple:
        m = re.search(r"messages(\d*)\.html$", name)
        return (name.rsplit("/", 1)[0], int(m.group(1) or 1) if m else 0)

    with zipfile.ZipFile(zip_path) as z:
        for member in sorted(members, key=order):
            with z.open(member) as f:
                html_text = f.read().decode("utf-8", errors="replace")
            p = _TgHtmlParser()
            p.feed(html_text)
            p.close()
            cname = p.chat_title or "telegram-chat"
            for msg_id, sender, ts, text in p.msgs:
                yield (_uid("tg", cname, msg_id), cname, ts,
                       f"[{sender}] {text}" if sender else text)


# ── dispatch ─────────────────────────────────────────────────────────────────

SUPPORTED = (".jsonl", ".zip", ".md", ".txt", ".json", ".pdf")


def _index_zip(path: Path, db_path: Union[str, Path]) -> int:
    """Dispatch dei .zip dal CONTENUTO (il nome non dice niente): export
    claude.ai o export Telegram Desktop JSON. Tutto il resto è un errore
    parlante — un "ok, 0 record" qui è sempre una bugia."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
    telegram_jsons = [n for n in names if Path(n).name == "result.json"]
    telegram_htmls = [n for n in names
                      if re.fullmatch(r"messages\d*\.html", Path(n).name)]
    if "conversations.json" in names or any(
            n.startswith(("design_chats/", "projects/")) for n in names):
        n, kind = write_rows(db_path, _iter_claude_zip(path)), "export claude.ai"
    elif telegram_jsons:
        # JSON preferito quando c'è: più fedele (id numerici, entities, service)
        n, kind = write_rows(db_path, _iter_telegram_zip(path, telegram_jsons)), "export Telegram"
    elif telegram_htmls:
        n, kind = (write_rows(db_path, _iter_telegram_html_zip(path, telegram_htmls)),
                   "export Telegram HTML")
    else:
        raise ValueError(
            "zip non riconosciuto: mi aspetto un export claude.ai "
            "(conversations.json / design_chats/ / projects/) oppure un export "
            "Telegram Desktop JSON (result.json).")
    if n == 0:
        if count_rows(db_path) == 0:
            Path(db_path).unlink(missing_ok=True)
        raise ValueError(f"{kind} riconosciuto ma nessun messaggio estraibile (0 record)")
    return n


def index_file(path: Union[str, Path], db_path: Union[str, Path], *, project: str = "") -> int:
    """Indicizza `path` nel DB, scegliendo l'estrattore dall'estensione/contenuto."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".zip":
        return _index_zip(path, db_path)
    if suffix == ".pdf":
        n = write_rows(db_path, _iter_pdf(path, project))
        if n == 0 and count_rows(db_path) == 0:
            # PDF senza layer di testo: quasi sempre uno screenshot/scan. pypdf
            # non estrae nulla → servirebbe OCR (fuori scope). Messaggio chiaro
            # invece di un DB vuoto silenzioso.
            Path(db_path).unlink(missing_ok=True)
            raise ValueError(
                "PDF senza testo estraibile (immagine/screenshot?). Per leggerlo serve "
                "OCR: sull'host usa `vps1777 archive-ingest <file>` — NotebookLM lo legge "
                "(anche le immagini) e ne indicizza il testo. Oppure carica il sorgente .md/.txt.")
        return n
    if suffix == ".json":
        # .json ambiguo: Telegram (oggetto con messages/chats) vs Claude Code
        # (in realtà JSONL → json.load fallisce → ripiego sul lettore a righe).
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            data = None
        if isinstance(data, dict) and ("messages" in data or "chats" in data):
            return write_rows(db_path, _iter_telegram(data))
    if suffix in (".jsonl", ".json"):
        with open(path, encoding="utf-8", errors="replace") as fh:
            return write_rows(db_path, _iter_claude_code(fh, project))
    if suffix in (".md", ".txt"):
        return write_rows(db_path, _iter_text(path, project))
    raise ValueError(f"formato non supportato: {suffix} (supportati: {', '.join(SUPPORTED)}, oppure carica un .db)")


def index_jsonl(source: Union[str, Path, IO[str]], db_path: Union[str, Path],
                *, project: str = "") -> int:
    """Compat/streaming: indicizza una sessione Claude Code da path o file-like."""
    if hasattr(source, "read"):
        return write_rows(db_path, _iter_claude_code(source, project))  # type: ignore[arg-type]
    with open(source, encoding="utf-8", errors="replace") as fh:
        return write_rows(db_path, _iter_claude_code(fh, project))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="archive_indexer",
        description="Indicizza sessioni/export in un DB FTS5 per archive-mcp.",
    )
    ap.add_argument("input", help="file di input (.jsonl / .zip / .md / .txt)")
    ap.add_argument("db", help="file .db SQLite di output (creato/aggiornato)")
    ap.add_argument("--project", default="", help="etichetta progetto (default: dedotta dalla fonte)")
    args = ap.parse_args(argv)
    if not Path(args.input).is_file():
        print(f"input non trovato: {args.input}", file=sys.stderr)
        return 1
    try:
        n = index_file(args.input, args.db, project=args.project)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"indicizzati {n} record → {args.db} (totale nel DB: {count_rows(args.db)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
