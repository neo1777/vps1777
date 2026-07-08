#!/usr/bin/env python3
"""
archive_indexer — costruisce/aggiorna un DB SQLite FTS5 per archive-mcp da fonti
eterogenee, tutte ridotte allo stesso schema.

Schema prodotto (compatibile col `search` di archive-mcp):
    messages(uuid PRIMARY KEY, project, ts, content)          -- sorgente
    messages_fts USING fts5(uuid, project, ts, content, content='messages', ...)

Formati (dispatch per estensione in `index_file`):
    .jsonl        → sessione Claude Code (record user/assistant)
    .zip          → export account claude.ai (conversations.json + design_chats/ + projects/docs)
    .md / .txt    → testo/markdown generico (ponte per output di altri tool), spezzato in chunk
    (.db)         → NON qui: è un drop-in, si copia direttamente nella dir

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
import sqlite3
import sys
import zipfile
from pathlib import Path
from typing import IO, Iterable, Iterator, Union

Row = tuple[str, str, str, str]  # (uuid, project, ts, content)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages(
    uuid    TEXT PRIMARY KEY,
    project TEXT,
    ts      TEXT,
    content TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    uuid, project, ts, content,
    content='messages', content_rowid='rowid'
);
"""


# ── core: scrittura DB ───────────────────────────────────────────────────────

def write_rows(db_path: Union[str, Path], rows: Iterable[Row], *, batch: int = 500) -> int:
    """Scrive/aggiorna le righe in db_path e ricostruisce l'FTS. Ritorna #righe.

    Riusabile da qualunque estrattore (server-side o locale). `rows` è un
    iterabile/generatore → streaming, memoria costante.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_SCHEMA)
        n = 0
        buf: list[Row] = []

        def flush() -> None:
            if buf:
                conn.executemany(
                    "INSERT OR REPLACE INTO messages(uuid, project, ts, content) "
                    "VALUES (?,?,?,?)", buf,
                )
                buf.clear()

        for row in rows:
            buf.append(row)
            n += 1
            if len(buf) >= batch:
                flush()
        flush()
        conn.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
        conn.commit()
        return n
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


# ── helper testo ─────────────────────────────────────────────────────────────

def extract_text(content: object) -> str:
    """Testo leggibile da un campo `content` (stringa o lista di blocchi).

    stringa → così com'è. lista (blocchi Claude) → si prendono i `text`; il
    resto (thinking/tool_use/tool_result) è rumore per la ricerca e si scarta.
    """
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [str(b["text"]) for b in content
                 if isinstance(b, dict) and b.get("type") == "text" and b.get("text")]
        return "\n".join(parts).strip()
    return ""


def _uid(*parts: str) -> str:
    """uuid deterministico da parti (per fonti senza id nativo → dedup stabile)."""
    return hashlib.sha1("\x1f".join(parts).encode("utf-8", "replace")).hexdigest()


# ── estrattore: sessione Claude Code (.jsonl) ────────────────────────────────

_CC_TYPES = ("user", "assistant")


def _iter_claude_code(fh: IO[str], project: str) -> Iterator[Row]:
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
        text = extract_text((d.get("message") or {}).get("content"))
        if not text:
            continue
        proj = project or Path(str(d.get("cwd") or "unknown")).name or "unknown"
        yield (uuid, proj, ts, text)


# ── estrattore: export account claude.ai (.zip) ──────────────────────────────

def _iter_conversations(convs: list, fallback: str) -> Iterator[Row]:
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
            text = m.get("text") or extract_text(m.get("content"))
            if not uuid or not text:
                continue
            sender = m.get("sender") or m.get("role") or ""
            content = f"[{sender}] {text}" if sender else text
            yield (uuid, name, m.get("created_at") or "", content)


def _iter_claude_zip(zip_path: Union[str, Path]) -> Iterator[Row]:
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        if "conversations.json" in names:
            with z.open("conversations.json") as f:
                yield from _iter_conversations(json.load(f), "claude-conversations")
        for n in names:
            if n.startswith("design_chats/") and n.endswith(".json"):
                with z.open(n) as f:
                    try:
                        data = json.load(f)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
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


# ── estrattore: testo / markdown generico ────────────────────────────────────

def _iter_text(path: Union[str, Path], project: str, *, chunk_chars: int = 1500) -> Iterator[Row]:
    """Spezza un file testo/markdown in chunk cercabili (per paragrafi, raggruppati).

    Ponte per l'output di altri tool (web2md, lettoremd, pulizia-transcript):
    qualunque .md/.txt diventa messaggi indicizzabili. uuid deterministico
    (nome file + indice) → re-index idempotente. ts = mtime del file.
    """
    path = Path(path)
    name = project or path.stem
    ts = ""
    try:
        import datetime
        ts = datetime.datetime.utcfromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        pass
    buf: list[str] = []
    size = 0
    idx = 0

    def emit() -> Row | None:
        nonlocal idx
        text = "\n".join(buf).strip()
        if not text:
            return None
        row = (_uid(name, str(idx)), name, ts, text)
        idx += 1
        return row

    with open(path, encoding="utf-8", errors="replace") as fh:
        for para in fh.read().split("\n\n"):
            buf.append(para)
            size += len(para)
            if size >= chunk_chars:
                r = emit()
                if r:
                    yield r
                buf, size = [], 0
    r = emit()
    if r:
        yield r


# ── dispatch ─────────────────────────────────────────────────────────────────

SUPPORTED = (".jsonl", ".zip", ".md", ".txt", ".json")


def index_file(path: Union[str, Path], db_path: Union[str, Path], *, project: str = "") -> int:
    """Indicizza `path` nel DB, scegliendo l'estrattore dall'estensione."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".zip":
        return write_rows(db_path, _iter_claude_zip(path))
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
