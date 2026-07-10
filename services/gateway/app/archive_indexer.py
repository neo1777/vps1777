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
    .zip Telegram  → export Desktop JSON (result.json, anche in sottocartella)
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

def extract_text(content: object) -> str:
    """Testo leggibile da un campo `content` (stringa, lista di blocchi o dict).

    stringa → così com'è. lista (blocchi Claude) → si prendono i `text`; il
    resto (thinking/tool_use/tool_result) è rumore per la ricerca e si scarta.
    dict → forma annidata delle design chats claude.ai ({"role", "content"}):
    si scende in `content`/`text` (ricorsivo — l'interno può essere str o lista).
    """
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [str(b["text"]) for b in content
                 if isinstance(b, dict) and b.get("type") == "text" and b.get("text")]
        return "\n".join(parts).strip()
    if isinstance(content, dict):
        inner = content.get("content")
        if inner is None:
            inner = content.get("text")
        return extract_text(inner) if inner is not None else ""
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


# ── dispatch ─────────────────────────────────────────────────────────────────

SUPPORTED = (".jsonl", ".zip", ".md", ".txt", ".json", ".pdf")


def _index_zip(path: Path, db_path: Union[str, Path]) -> int:
    """Dispatch dei .zip dal CONTENUTO (il nome non dice niente): export
    claude.ai o export Telegram Desktop JSON. Tutto il resto è un errore
    parlante — un "ok, 0 record" qui è sempre una bugia."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
    telegram_jsons = [n for n in names if Path(n).name == "result.json"]
    if "conversations.json" in names or any(
            n.startswith(("design_chats/", "projects/")) for n in names):
        n, kind = write_rows(db_path, _iter_claude_zip(path)), "export claude.ai"
    elif telegram_jsons:
        n, kind = write_rows(db_path, _iter_telegram_zip(path, telegram_jsons)), "export Telegram"
    elif any(Path(m).name.startswith("messages") and m.endswith(".html") for m in names):
        raise ValueError(
            "export Telegram in formato HTML (messages.html): il testo non è "
            "estraibile. Riesporta da Telegram Desktop scegliendo il formato "
            "JSON (machine-readable) e carica il result.json o il suo zip.")
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
