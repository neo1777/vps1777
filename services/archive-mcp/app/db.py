"""
Storage layer — astratto su SQLite FTS5.

Mantiene la registry `DBS: dict[name, Path]` filtrata ai DB esistenti (degraded
mode: i mancanti vengono rimossi all'avvio con un warning). Orchestra il
multi-DB (registry + freshness + limit globale) sopra la logica FTS pura di
`fts.py` (stdlib-only, testabile senza il runtime del server).

Per swap futuro a Postgres: implementa `_open` e le funzioni di fts con backend
diverso.
"""
from __future__ import annotations

import datetime
import logging
import os
import json
import urllib.request
import urllib.error
import sqlite3
from pathlib import Path
from typing import Any

from . import fts
from .fts import FtsSyntaxError  # noqa: F401 — riesportato per server.py
from .settings import get_settings

log = logging.getLogger(__name__)


def _snapshot(path: Path) -> str:
    """Data di ultima modifica del file DB (ISO, UTC) — la 'freschezza' del DB:
    ogni risposta la porta, così una sessione sa quanto è vecchio ciò che legge."""
    try:
        return datetime.datetime.utcfromtimestamp(
            path.stat().st_mtime).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        return ""


def _db_dir() -> Path | None:
    s = get_settings()
    return Path(s.archive_db_dir) if s.archive_db_dir else None


def _scan_dir(db_dir: Path) -> dict[str, Path]:
    """Tutti i *.db nella dir → {nome-file-senza-estensione: path}."""
    if not db_dir.is_dir():
        return {}
    return {p.stem: p for p in sorted(db_dir.glob("*.db")) if p.is_file()}


def load_registry() -> dict[str, Path]:
    s = get_settings()
    out: dict[str, Path] = {}
    # 1. auto-discovery: ogni *.db nella dir compare SENZA restart.
    db_dir = _db_dir()
    if db_dir:
        out.update(_scan_dir(db_dir))
    # 2. ARCHIVE_DB_PATHS: override/aggiunta di path espliciti (fuori dalla dir).
    missing: list[str] = []
    for name, p in s.archive_db_paths.items():
        if p.exists() and p.is_file():
            out[name] = p
        else:
            missing.append(f"{name}={p}")
    if missing:
        # Un path DICHIARATO ma con file assente è un errore di config.
        log.warning("DB dichiarati ma non trovati sul volume: %s", ", ".join(missing))
    if not out:
        # Archivio vuoto = stato normale di un'installazione nuova, non un errore.
        log.info(
            "Archivio vuoto — aggiungi DB SQLite FTS5 in %s (o via ARCHIVE_DB_PATHS) "
            "per abilitare la ricerca.", db_dir or "(dir non impostata)",
        )
    return out


def _dir_sig() -> tuple:
    """Firma della dir DB (nome+mtime+size di ogni *.db) per rilevare cambi."""
    db_dir = _db_dir()
    if not db_dir or not db_dir.is_dir():
        return ()
    sig = []
    for p in sorted(db_dir.glob("*.db")):
        if p.is_file():
            st = p.stat()
            sig.append((p.name, st.st_mtime_ns, st.st_size))
    return tuple(sig)


_DBS: dict[str, Path] = load_registry()
_SIG: tuple = _dir_sig()


def _maybe_reload() -> None:
    """Ricarica la registry se la dir DB è cambiata (upload/ingest nuovo)."""
    if _dir_sig() != _SIG:
        log.info("dir DB cambiata — ricarico la registry")
        reload_registry()


def available_dbs() -> list[str]:
    _maybe_reload()
    return sorted(_DBS)


def reload_registry() -> list[str]:
    """Ricarica la registry (scan della dir + ARCHIVE_DB_PATHS)."""
    global _DBS, _SIG
    _DBS = load_registry()
    _SIG = _dir_sig()
    return sorted(_DBS)


def _open(name: str) -> sqlite3.Connection:
    if name not in _DBS:
        raise KeyError(f"DB '{name}' non disponibile. Disponibili: {available_dbs()}")
    conn = sqlite3.connect(f"file:{_DBS[name]}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _targets(db: str) -> list[str]:
    if not db:
        return list(_DBS)
    if db not in _DBS:
        raise KeyError(f"DB '{db}' non disponibile. Disponibili: {available_dbs()}")
    return [db]


def search(query: str, db: str = "", limit: int = 20, *, raw: bool = False,
           sort: str = "rank", since: str = "", until: str = "",
           project: str = "", snippet_tokens: int = 32) -> list[dict[str, Any]]:
    """Search FTS5 nel DB indicato (o in TUTTI se db == "").

    Su più DB il `limit` è GLOBALE (non più per-DB) e i risultati sono fusi e
    ri-ordinati per `sort` prima del taglio — niente più concatenamento cieco.
    Ogni riga porta `db` e `snapshot` (freschezza del DB). Un errore di sintassi
    FTS5 solleva FtsSyntaxError (non restituisce lista vuota muta)."""
    _maybe_reload()  # pesca eventuali DB caricati/indicizzati dopo l'avvio
    collected: list[dict[str, Any]] = []
    for name in _targets(db):
        try:
            conn = _open(name)
        except KeyError:
            continue
        try:
            snap = _snapshot(_DBS[name])
            rows = fts.search_conn(
                conn, query, limit=limit, raw=raw, sort=sort, since=since,
                until=until, project=project, snippet_tokens=snippet_tokens)
            for r in rows:
                r["db"] = name
                r["snapshot"] = snap
            collected.extend(rows)
        except sqlite3.OperationalError as exc:
            # schema non conforme (DB estraneo nella dir): salta, non è fatale
            log.warning("DB %s schema error: %s", name, exc)
        finally:
            conn.close()
    # ordinamento GLOBALE + limit globale: bm25 crescente (più rilevante prima),
    # ts per newest/oldest. Fra DB diversi il bm25 non è perfettamente
    # comparabile (documentato), ma è meglio del concatenamento per-DB.
    if sort == "newest":
        collected.sort(key=lambda r: r.get("ts") or "", reverse=True)
    elif sort == "oldest":
        collected.sort(key=lambda r: r.get("ts") or "")
    else:
        collected.sort(key=lambda r: r.get("rank", 0.0))
    return collected[:limit]


def count(query: str, db: str = "", *, raw: bool = False, since: str = "",
          until: str = "", project: str = "") -> dict[str, Any]:
    """Numero di match per DB e totale (non limitato) — abilita frequenze e
    prevalenze, impossibili con la sola `search` limitata."""
    _maybe_reload()
    per_db: dict[str, int] = {}
    warnings: list[str] = []
    for name in _targets(db):
        try:
            conn = _open(name)
        except KeyError:
            continue
        try:
            per_db[name] = fts.count_conn(
                conn, query, raw=raw, since=since, until=until, project=project)
            # canary: se un termine è collassato sul suo prefisso (`C++`→`C`), il
            # numero appena letto è un falso positivo — dillo, non lasciarlo muto.
            if not raw:
                warnings.extend(
                    f"[{name}] {w}" for w in fts.collapse_warnings_conn(conn, query))
        except sqlite3.OperationalError as exc:
            log.warning("DB %s schema error: %s", name, exc)
        finally:
            conn.close()
    out: dict[str, Any] = {"total": sum(per_db.values()), "per_db": per_db}
    if warnings:
        out["warnings"] = warnings
    return out


def check_term(term: str, db: str = "") -> dict[str, Any]:
    """Diagnostica il COLLASSO di un termine con caratteri speciali (`C++`, `C#`,
    `g++`, `.NET`, `F#`) — il canary di setaccio esposto come tool. Per ogni DB
    confronta count(term) con count(prefisso-alfanumerico): se coincidono, per
    quell'indice `term` == `prefix` e i risultati sono falsi positivi (la causa del
    falso ricordo dell'11/07). Chiede all'INDICE, non alla doc; si auto-tara sui DB
    ricostruiti con tokenchars (lì i conteggi divergono → collapsed=False)."""
    _maybe_reload()
    cands = fts.collapse_candidates(term)
    prefix = cands[0][1] if cands else ""
    per_db: dict[str, Any] = {}
    for name in _targets(db):
        try:
            conn = _open(name)
        except KeyError:
            continue
        try:
            n_term = fts.count_conn(conn, term)
            n_pref = fts.count_conn(conn, prefix) if prefix else n_term
            per_db[name] = {
                "count_term": n_term,
                "count_prefix": n_pref if prefix else None,
                "collapsed": bool(prefix and n_pref > 0 and n_term == n_pref),
            }
        except (sqlite3.OperationalError, FtsSyntaxError) as exc:
            log.warning("DB %s check_term error: %s", name, exc)
        finally:
            conn.close()
    return {"term": term, "prefix": prefix or None, "per_db": per_db}


def get_context(uuid: str, db: str = "", *, before: int = 3,
                after: int = 3) -> list[dict[str, Any]]:
    """I messaggi attorno a uno `uuid` col contenuto PIENO — supera il
    troncamento dello snippet di search. Cerca nel DB indicato o in tutti."""
    _maybe_reload()
    for name in _targets(db):
        try:
            conn = _open(name)
        except KeyError:
            continue
        try:
            ctx = fts.context_conn(conn, uuid, before=before, after=after)
            if ctx:
                snap = _snapshot(_DBS[name])
                for r in ctx:
                    r["db"] = name
                    r["snapshot"] = snap
                return ctx
        except sqlite3.OperationalError as exc:
            log.warning("DB %s schema error: %s", name, exc)
        finally:
            conn.close()
    return []


def get_conversation(uuid: str, db: str = "", *, limit: int = 200) -> list[dict[str, Any]]:
    """Il thread INTERO che contiene `uuid` (camminando parent_uuid), col contenuto
    pieno. Cerca il DB che contiene l'uuid, o in tutti."""
    _maybe_reload()
    for name in _targets(db):
        try:
            conn = _open(name)
        except KeyError:
            continue
        try:
            conv = fts.conversation_conn(conn, uuid, limit=limit)
            if conv:
                snap = _snapshot(_DBS[name])
                for r in conv:
                    r["db"] = name
                    r["snapshot"] = snap
                return conv
        except sqlite3.OperationalError as exc:
            log.warning("DB %s schema error: %s", name, exc)
        finally:
            conn.close()
    return []


def list_projects(db: str = "", *, top: int = 1000) -> list[dict[str, Any]]:
    """Le etichette `project` (con conteggi) per DB — per NAVIGARE l'archivio, non
    solo cercarlo. Su più DB i risultati portano `db` e sono ordinati per conteggio."""
    _maybe_reload()
    out: list[dict[str, Any]] = []
    for name in _targets(db):
        try:
            conn = _open(name)
        except KeyError:
            continue
        try:
            for r in fts.projects_conn(conn, top=top):
                r["db"] = name
                out.append(r)
        except sqlite3.OperationalError as exc:
            log.warning("DB %s schema error: %s", name, exc)
        finally:
            conn.close()
    out.sort(key=lambda r: r.get("rows", 0), reverse=True)
    return out


def archive_stats(db: str = "") -> list[dict[str, Any]]:
    """Istogramma temporale per ANNO, per DB — «quando» l'archivio è fitto, prima
    di cercare. Ogni riga porta `db`."""
    _maybe_reload()
    out: list[dict[str, Any]] = []
    for name in _targets(db):
        try:
            conn = _open(name)
        except KeyError:
            continue
        try:
            for r in fts.stats_by_period_conn(conn):
                r["db"] = name
                out.append(r)
        except sqlite3.OperationalError as exc:
            log.warning("DB %s schema error: %s", name, exc)
        finally:
            conn.close()
    return out


def describe() -> list[dict[str, Any]]:
    """Scheda di ogni DB: righe, intervallo temporale, n. etichette, snapshot
    (freschezza). Più ricca di list_databases (che resta list[str] per compat)."""
    _maybe_reload()
    out: list[dict[str, Any]] = []
    for name in sorted(_DBS):
        try:
            conn = _open(name)
        except KeyError:
            continue
        try:
            info = fts.db_stats_conn(conn)
            info["description"] = fts.meta_value_conn(conn, "description")
        except sqlite3.OperationalError:
            info = {"rows": 0, "oldest": "", "newest": "", "labels": 0, "description": ""}
        finally:
            conn.close()
        info["name"] = name
        info["snapshot"] = _snapshot(_DBS[name])
        out.append(info)
    return out


def set_description(db: str, description: str) -> dict[str, Any]:
    """Imposta la descrizione di un archivio — **inoltrandola al gateway** (D9).

    Perché non scrive qui: questo container monta il volume degli archivi in
    SOLA LETTURA, per scelta deliberata (`compose.yaml`: «a scrivere i .db è il
    gateway, non questo servizio»). Fino al 20/07/2026 questa funzione apriva
    comunque il DB in scrittura e la docstring dichiarava «è l'UNICA scrittura
    ammessa da questo layer»: due affermazioni entrambe vere, ognuna nel suo
    file, che insieme mentivano — il tool prometteva una scrittura che il suo
    container non poteva fare, e chi lo chiamava riceveva
    `attempt to write a readonly database`.

    L'inoltro non è un'architettura nuova: la docstring di `set_meta` nel gateway
    dichiarava GIÀ «la usano l'upload (admin) e il tool MCP set_description».
    Era il pezzo che qualcuno aveva dato per esistente e che non era mai stato
    scritto.

    Il canale è quello di casa (`/internal/*` + `x-vps1777-internal`), sulla rete
    interna. Gli errori risalgono parlanti: chi chiama deve sapere *perché* non
    ha scritto, non ricevere un silenzio.
    """
    _maybe_reload()
    if db not in _DBS:
        raise KeyError(f"DB '{db}' non disponibile. Disponibili: {available_dbs()}")

    base = os.environ.get("GATEWAY_INTERNAL_BASE", "http://gateway:8080").rstrip("/")
    secret = _leggi_segreto()
    if not secret:
        # fail-closed e PARLANTE: senza segreto la scrittura non parte, e chi
        # chiama lo scopre subito invece di credere di aver scritto.
        raise RuntimeError(
            "set_description non configurata: manca il segreto interno "
            "(GATEWAY_SECRET/GATEWAY_SECRET_FILE) — la scrittura passa dal gateway."
        )
    req = urllib.request.Request(
        f"{base}/internal/archive/description",
        data=json.dumps({"db": db, "description": str(description)}).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-vps1777-internal": secret},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            esito = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as ex:
        corpo = ex.read().decode("utf-8", "replace")[:200]
        raise RuntimeError(f"il gateway ha rifiutato la scrittura ({ex.code}): {corpo}") from ex
    except urllib.error.URLError as ex:
        raise RuntimeError(f"gateway non raggiungibile per la scrittura: {ex.reason}") from ex
    return {"db": db, "description": str(description), "via": "gateway", "esito": esito}


def _leggi_segreto() -> str:
    """Il segreto interno, da variabile o da file (come fa il gateway)."""
    v = os.environ.get("GATEWAY_SECRET", "").strip()
    if v:
        return v
    p = os.environ.get("GATEWAY_SECRET_FILE", "").strip()
    if p:
        try:
            return Path(p).read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    return ""

