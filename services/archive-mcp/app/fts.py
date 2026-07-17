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


def _thread_ids(conn: sqlite3.Connection, uuid: str) -> set[str]:
    """Gli uuid del thread connesso a `uuid` via `parent_uuid` (antenati +
    discendenti), camminando l'albero con due CTE ricorsive. Insieme = 1 solo
    (il messaggio stesso) quando l'arco manca — fonti chunked (pdf/telegram/memory)
    e db storici del prototipo, che `parent_uuid` non ce l'hanno. Su un DB v1 (4
    colonne, senza `parent_uuid`) ritorna il solo `uuid` → i chiamanti ripiegano
    sul comportamento storico invece di rompersi."""
    try:
        rows = conn.execute(
            "WITH RECURSIVE "
            " up(u) AS (SELECT ? UNION "
            "   SELECT m.parent_uuid FROM messages m JOIN up ON m.uuid = up.u "
            "   WHERE m.parent_uuid <> ''), "
            " down(u) AS (SELECT ? UNION "
            "   SELECT m.uuid FROM messages m JOIN down ON m.parent_uuid = down.u) "
            "SELECT u FROM up UNION SELECT u FROM down",
            (uuid, uuid),
        ).fetchall()
    except sqlite3.OperationalError:
        return {uuid}  # DB v1 senza colonna parent_uuid
    return {r[0] for r in rows if r[0]}


def context_conn(conn: sqlite3.Connection, uuid: str, *, before: int = 3,
                 after: int = 3) -> list[dict[str, Any]]:
    """I messaggi attorno a `uuid`, col CONTENUTO PIENO (non lo snippet troncato).

    Se il messaggio fa parte di un thread (`parent_uuid`), i vicini vengono dallo
    STESSO thread — non più dalla sola vicinanza temporale nello stesso project, che
    poteva mischiare conversazioni diverse (era l'over-claim di «stesso thread»).
    Sulle fonti senza arco (chunked / db storici) ricade sull'adiacenza per
    (ts, uuid) dello stesso project — il comportamento storico. Vuoto se l'uuid non c'è."""
    row = conn.execute(
        "SELECT project, ts FROM messages WHERE uuid = ?", (uuid,)).fetchone()
    if row is None:
        return []
    project, ts = row["project"], row["ts"]
    ids = _thread_ids(conn, uuid)
    if len(ids) > 1:
        # threaded: la finestra ±N si prende DENTRO il thread, ordinato (ts, uuid).
        qmarks = ",".join("?" * len(ids))
        seq = [dict(r) for r in conn.execute(
            f"SELECT uuid, project, ts, content FROM messages WHERE uuid IN ({qmarks}) "
            "ORDER BY ts ASC, uuid ASC", tuple(ids)).fetchall()]
        pos = next((i for i, r in enumerate(seq) if r["uuid"] == uuid), None)
        if pos is not None:
            out = seq[max(0, pos - int(before)): pos + int(after) + 1]
            for r in out:
                r["is_match"] = (r["uuid"] == uuid)
            return out
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


def conversation_conn(conn: sqlite3.Connection, uuid: str, *,
                      limit: int = 200) -> list[dict[str, Any]]:
    """Il thread di conversazione che CONTIENE `uuid` — camminando l'albero
    `parent_uuid` (antenati + discendenti), col contenuto pieno e in ordine (ts, uuid).
    Per LEGGERE una chat intera, non solo la finestra ±N di `context_conn`.

    Dove l'arco manca — fonti chunked (pdf/telegram/memory) e db storici — ricade
    sull'ordine lineare dello stesso archivio (`project`). La ricostruzione FEDELE
    dell'ordine sulla coda-documenti (colonna `seq`) è un passo evolutivo DICHIARATO
    fuori scope oggi. Vuoto se l'uuid non c'è."""
    anchor = conn.execute(
        "SELECT project FROM messages WHERE uuid = ?", (uuid,)).fetchone()
    if anchor is None:
        return []
    ids = _thread_ids(conn, uuid)
    if len(ids) > 1:
        qmarks = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT uuid, project, ts, content, sender FROM messages "
            f"WHERE uuid IN ({qmarks}) ORDER BY ts ASC, uuid ASC LIMIT ?",
            (*ids, int(limit))).fetchall()
    else:
        # fallback lineare (coda-documenti / db storici senza arco)
        rows = conn.execute(
            "SELECT uuid, project, ts, content, sender FROM messages "
            "WHERE project = ? ORDER BY ts ASC, uuid ASC LIMIT ?",
            (anchor["project"], int(limit))).fetchall()
    out = [dict(r) for r in rows]
    for r in out:
        r["is_match"] = (r["uuid"] == uuid)
    return out


def projects_conn(conn: sqlite3.Connection, *, top: int = 1000) -> list[dict[str, Any]]:
    """Le etichette `project` di un DB con quanti messaggi ciascuna — per NAVIGARE
    l'archivio invece di solo cercarlo (era uno dei tool di browse persi, B4)."""
    return [{"project": p or "", "rows": int(n)} for p, n in conn.execute(
        "SELECT project, count(*) FROM messages "
        "GROUP BY project ORDER BY count(*) DESC, project LIMIT ?",
        (max(0, int(top)),)).fetchall()]


def stats_by_period_conn(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Istogramma temporale per ANNO (`substr(ts,1,4)`) — «quando» l'archivio è
    fitto, prima di cercare. I ts vuoti (fonti senza data) sono esclusi."""
    return [{"period": per, "rows": int(n)} for per, n in conn.execute(
        "SELECT substr(ts, 1, 4) AS period, count(*) FROM messages "
        "WHERE ts <> '' GROUP BY period ORDER BY period").fetchall()]


def meta_value_conn(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    """Una voce dalla scheda `meta` del DB (es. `description`, D5). `default` se la
    tabella manca (DB precedenti alla feature) o la chiave non c'è."""
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (str(key),)).fetchone()
    except sqlite3.OperationalError:
        return default
    return row[0] if row and row[0] is not None else default


def db_stats_conn(conn: sqlite3.Connection) -> dict[str, Any]:
    """Righe, intervallo temporale e n. di etichette di un DB (per describe)."""
    rows = int(conn.execute("SELECT count(*) FROM messages").fetchone()[0])
    oldest = newest = ""
    labels = 0
    if rows:
        # min(NULLIF(ts,'')): le righe-STATO (memory:*, account:user) hanno ts vuoto —
        # non sono EVENTI, non hanno una data di nascita. Senza NULLIF la stringa vuota
        # vince su min() e `oldest` diventa "" — il tool direbbe «non so da quando»
        # sapendolo. NULLIF le esclude dal minimo; max() le ignora già (vuoto ordina prima).
        lo, hi = conn.execute(
            "SELECT min(NULLIF(ts,'')), max(ts) FROM messages").fetchone()
        oldest, newest = lo or "", hi or ""
        labels = int(conn.execute(
            "SELECT count(DISTINCT project) FROM messages").fetchone()[0])
    return {"rows": rows, "oldest": oldest, "newest": newest, "labels": labels}
