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


def load_registry() -> dict[str, Path]:
    s = get_settings()
    requested = s.archive_db_paths
    if not requested:
        # Stato NORMALE di un'installazione nuova: l'archivio nasce vuoto e ogni
        # utente lo popola coi propri DB (vedi README). Non è un errore: i tool
        # rispondono con liste vuote finché non aggiungi un DB.
        log.info(
            "Archivio vuoto (ARCHIVE_DB_PATHS non impostato) — aggiungi i tuoi "
            "DB SQLite FTS5 per abilitare la ricerca.",
        )
        return {}
    out: dict[str, Path] = {}
    missing: list[str] = []
    for name, p in requested.items():
        if p.exists() and p.is_file():
            out[name] = p
        else:
            missing.append(f"{name}={p}")
    if missing:
        # Qui sì è un problema di config: un path è stato DICHIARATO ma il file
        # non esiste sul volume.
        log.warning("DB dichiarati ma non trovati sul volume: %s", ", ".join(missing))
    if not out:
        log.warning(
            "Nessuno dei DB dichiarati è stato caricato — la ricerca tornerà "
            "risultati vuoti finché i file non esistono.",
        )
    return out


_DBS: dict[str, Path] = load_registry()


def available_dbs() -> list[str]:
    return sorted(_DBS)


def reload_registry() -> list[str]:
    """Ricarica la registry leggendo gli env (per dev / test)."""
    global _DBS
    _DBS = load_registry()
    return available_dbs()


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
