"""
Storage layer — astratto su SQLite FTS5.

Mantiene la registry `DBS: dict[name, Path]` filtrata ai DB esistenti (degraded
mode: i mancanti vengono rimossi all'avvio con un warning).

Per swap futuro a Postgres: implementa `_open` e `search` con backend diverso.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from .settings import get_settings

log = logging.getLogger(__name__)


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


def search(query: str, db: str = "", limit: int = 20) -> list[dict[str, Any]]:
    """
    Search FTS5 nel DB indicato (o in tutti se db == ""). Ritorna lista di dict.

    Lo schema atteso è: tabella `messages_fts` con colonne (uuid, project, ts, content).
    Se il DB non ha questo schema, il tool ritorna errore.
    """
    _maybe_reload()  # pesca eventuali DB caricati/indicizzati dopo l'avvio
    results: list[dict[str, Any]] = []
    for name in _targets(db):
        try:
            conn = _open(name)
        except KeyError:
            continue
        try:
            cur = conn.execute(
                """SELECT uuid, project, ts, snippet(messages_fts, -1, '«', '»', '…', 32) AS snip
                   FROM messages_fts
                   WHERE messages_fts MATCH ?
                   ORDER BY bm25(messages_fts)
                   LIMIT ?""",
                (query, limit),
            )
            for row in cur:
                results.append({
                    "db": name,
                    "uuid": row["uuid"],
                    "project": row["project"],
                    "ts": row["ts"],
                    "snippet": row["snip"],
                })
        except sqlite3.OperationalError as exc:
            log.warning("DB %s schema error: %s", name, exc)
        finally:
            conn.close()
    return results
