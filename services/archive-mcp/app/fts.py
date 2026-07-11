"""
Logica FTS5 pura — stdlib-only (sqlite3, re), zero dipendenze da settings/MCP.

Estratta da db.py così che la CI possa testarla con `uvx pytest` senza installare
il runtime del server (stesso pattern di gateway/archive_indexer, miniapp_core).

Contiene: sanitizzazione difensiva della query (auto-quoting dei termini con
caratteri speciali), la ricerca su una connessione con distinzione ESPLICITA fra
"nessun risultato" e "sintassi FTS5 non valida" (il bug capitale), il conteggio,
il contesto attorno a un messaggio e la scheda di un DB.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any

# ── errore parlante ──────────────────────────────────────────────────────────


class FtsSyntaxError(ValueError):
    """Query FTS5 malformata. Sollevata al posto di restituire lista vuota:
    un `[]` da errore di sintassi è indistinguibile da 'nessun match' e produce
    falsi negativi silenziosi — l'esatto contrario dello scopo dell'archivio."""


_SYNTAX_HINT = (
    "sintassi FTS5 non valida. Regole: operatori in MAIUSCOLO (AND OR NOT NEAR); "
    "i termini con - . / @ : # ' o punti vanno tra virgolette (es. \"flutter-elinux\", "
    "\"0.7.9\", \"github.com\"); le famiglie di nomi col prefisso (palant*). "
    "Se cercavi un termine letterale con caratteri speciali, mettilo tra doppi apici."
)

# ── sanitizzazione difensiva ─────────────────────────────────────────────────

# Un token è "già sicuro" per FTS5 se è fatto solo di word-char unicode
# (lettere accentate incluse) più un eventuale `*` di prefisso: `nb_list`,
# `palant*`, `perché`. Tutto il resto (trattini, punti, slash, apostrofi…) è
# sintassi per il parser e va quotato per essere cercato come letterale.
_SAFE_TOKEN = re.compile(r"^\w+\*?$", re.UNICODE)
_FTS_OPERATORS = {"AND", "OR", "NOT", "NEAR"}
# spezza preservando: stringhe già quotate e sequenze non-spazio
_SPLIT = re.compile(r'"[^"]*"|\S+')
# costrutti FTS "strutturali": se la query li usa, NON la si tocca (quotare
# spezzerebbe la semantica). NEAR, parentesi di gruppo, column filter `col:term`.
_ADVANCED = re.compile(r"\bNEAR\b|[()]|\w+\s*:", re.UNICODE)


def sanitize_query(query: str) -> str:
    """Quota i termini con caratteri speciali (`flutter-elinux` → `"flutter-elinux"`),
    lasciando intatti operatori, frasi già quotate e prefissi. Pensata per il
    caso comune 'lista di termini'.

    Conservativa: se la query usa sintassi FTS avanzata (NEAR, parentesi,
    `col:term`) la restituisce INVARIATA — sanitizzarla ne cambierebbe la
    semantica. `search` prova comunque la versione sanitizzata e, se il parser
    la rifiuta, ricade sull'originale prima di dichiarare l'errore.
    """
    q = query or ""
    if _ADVANCED.search(q):
        return q
    out: list[str] = []
    for tok in _SPLIT.findall(q):
        if tok.startswith('"') and tok.endswith('"'):
            out.append(tok)              # frase già quotata: intatta
        elif tok in _FTS_OPERATORS:
            out.append(tok)              # operatore FTS: intatto
        elif _SAFE_TOKEN.match(tok):
            out.append(tok)              # già sicuro (parola, prefisso)
        else:
            out.append('"' + tok.replace('"', '""') + '"')  # letterale → quota
    return " ".join(out)


# ── ricerca ──────────────────────────────────────────────────────────────────

_SORTS = {
    "rank": "bm25(messages_fts)",
    "oldest": "ts ASC",
    "newest": "ts DESC",
}


def _run_match(conn: sqlite3.Connection, match: str, *, where_extra: str,
               params_extra: list, order: str, limit: int,
               snippet_tokens: int) -> list[dict[str, Any]]:
    sql = (
        f"SELECT uuid, project, ts, bm25(messages_fts) AS rank, "
        f"snippet(messages_fts, -1, '«', '»', '…', {int(snippet_tokens)}) AS snip "
        f"FROM messages_fts WHERE messages_fts MATCH ?{where_extra} "
        f"ORDER BY {order} LIMIT ?"
    )
    cur = conn.execute(sql, [match, *params_extra, int(limit)])
    return [dict(r) for r in cur]


def search_conn(conn: sqlite3.Connection, query: str, *, limit: int = 20,
                raw: bool = False, sort: str = "rank",
                since: str = "", until: str = "", project: str = "",
                snippet_tokens: int = 32) -> list[dict[str, Any]]:
    """Cerca su UNA connessione. Distingue 0-risultati da errore di sintassi
    (solleva FtsSyntaxError). In modalità smart (default) prova la query
    sanitizzata e, se il parser la rifiuta, ricade sulla query originale così da
    non rompere mai ciò che 'raw' avrebbe accettato."""
    order = _SORTS.get(sort, _SORTS["rank"])
    where = ""
    extra: list = []
    if since:
        where += " AND ts >= ?"
        extra.append(since)
    if until:
        where += " AND ts <= ?"
        extra.append(until)
    if project:
        where += " AND project = ?"
        extra.append(project)

    candidates = [query] if raw else [sanitize_query(query), query]
    last_exc: sqlite3.OperationalError | None = None
    for match in candidates:
        try:
            rows = _run_match(conn, match, where_extra=where, params_extra=extra,
                              order=order, limit=limit, snippet_tokens=snippet_tokens)
        except sqlite3.OperationalError as exc:
            last_exc = exc
            continue
        for r in rows:
            r["snippet"] = r.pop("snip")
        return rows
    raise FtsSyntaxError(f"{_SYNTAX_HINT} (dettaglio: {last_exc})")


def count_conn(conn: sqlite3.Connection, query: str, *, raw: bool = False,
               since: str = "", until: str = "", project: str = "") -> int:
    """Numero di match (non limitato). Stessa disciplina d'errore di search."""
    where = ""
    extra: list = []
    if since:
        where += " AND ts >= ?"
        extra.append(since)
    if until:
        where += " AND ts <= ?"
        extra.append(until)
    if project:
        where += " AND project = ?"
        extra.append(project)
    sql = f"SELECT count(*) FROM messages_fts WHERE messages_fts MATCH ?{where}"
    candidates = [query] if raw else [sanitize_query(query), query]
    last_exc: sqlite3.OperationalError | None = None
    for match in candidates:
        try:
            return int(conn.execute(sql, [match, *extra]).fetchone()[0])
        except sqlite3.OperationalError as exc:
            last_exc = exc
    raise FtsSyntaxError(f"{_SYNTAX_HINT} (dettaglio: {last_exc})")


def context_conn(conn: sqlite3.Connection, uuid: str, *, before: int = 3,
                 after: int = 3) -> list[dict[str, Any]]:
    """I messaggi attorno a `uuid` nello stesso project, ordinati per (ts, uuid),
    con il CONTENUTO PIENO (non lo snippet troncato). Vuoto se l'uuid non c'è."""
    row = conn.execute(
        "SELECT project, ts FROM messages WHERE uuid = ?", (uuid,)).fetchone()
    if row is None:
        return []
    project, ts = row["project"], row["ts"]
    # ancora per (ts, uuid): stabile anche con ts uguali (dedup deterministico)
    prev = conn.execute(
        "SELECT uuid, project, ts, content FROM messages "
        "WHERE project = ? AND (ts, uuid) < (?, ?) "
        "ORDER BY ts DESC, uuid DESC LIMIT ?",
        (project, ts, uuid, int(before)),
    ).fetchall()
    center_after = conn.execute(
        "SELECT uuid, project, ts, content FROM messages "
        "WHERE project = ? AND (ts, uuid) >= (?, ?) "
        "ORDER BY ts ASC, uuid ASC LIMIT ?",
        (project, ts, uuid, int(after) + 1),
    ).fetchall()
    out = [dict(r) for r in reversed(prev)] + [dict(r) for r in center_after]
    for r in out:
        r["is_match"] = (r["uuid"] == uuid)
    return out


def db_stats_conn(conn: sqlite3.Connection) -> dict[str, Any]:
    """Righe, intervallo temporale e n. di etichette di un DB (per describe)."""
    rows = int(conn.execute("SELECT count(*) FROM messages").fetchone()[0])
    oldest = newest = ""
    labels = 0
    if rows:
        lo, hi = conn.execute("SELECT min(ts), max(ts) FROM messages").fetchone()
        oldest, newest = lo or "", hi or ""
        labels = int(conn.execute(
            "SELECT count(DISTINCT project) FROM messages").fetchone()[0])
    return {"rows": rows, "oldest": oldest, "newest": newest, "labels": labels}
