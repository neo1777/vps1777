"""ingest_worker — il processo one-shot del servizio compose `ingest` (P16, 11/10/2026).

Gira nell'immagine del gateway ma in un container suo, con il suo `mem_limit`: se un
export grosso sfora, il kernel uccide questo, e il gateway (OAuth, proxy MCP, pagine)
resta su. Lo lancia la CLI sull'host (`vps1777 ingest-coda`, oppure i comandi
`archive-*`), mai il gateway: «il gateway non esegue processi».

Due modi:
  coda --id <id> --db <nome> --suffisso <.ext> [--project P] [--description D]
      indicizza il file `/var/lib/archive/coda/<id><ext>` nel DB `<nome>` e lo
      cancella; stampa UNA riga JSON con l'esito ({"righe", "totale"} o {"errore"}).
  indexer <argomenti di archive_indexer>
      passa tutto a `archive_indexer.main` (archive-migra, retag, archive-ingest).

Il percorso del file e del DB lo ricostruisce QUI da id e nome, con le stesse regole
del gateway: la CLI li ha già validati, ma un argomento che arriva da un intent scritto
dal servizio esposto non si usa come percorso senza ricontrollarlo.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import zipfile
from pathlib import Path

from . import archive_indexer
from .coda_ingest import DB_RE, ID_RE, SUFFISSI, cartella_file

DB_DIR = os.environ.get("ARCHIVE_DB_DIR", "/var/lib/archive/db")
# un file rimasto in coda da più di così è orfano (un lavoro ucciso dal tetto di
# memoria non arriva al suo `finally`): il giro dopo lo toglie
ORFANO_DOPO_S = 2 * 24 * 3600


def _pulisci_orfani(cartella: Path, tranne: Path) -> int:
    tolti = 0
    soglia = time.time() - ORFANO_DOPO_S
    for p in cartella.glob("*"):
        if p == tranne or not p.is_file():
            continue
        try:
            if p.stat().st_mtime < soglia:
                p.unlink()
                tolti += 1
        except OSError:
            pass
    return tolti


def esegui_coda(jid: str, db: str, suffisso: str, project: str = "",
                description: str = "", *, db_dir: str = DB_DIR) -> tuple[int, dict]:
    """(codice d'uscita, esito). Logica senza argparse: la provano i test."""
    if not ID_RE.match(jid) or not DB_RE.match(db) or suffisso not in SUFFISSI:
        return 2, {"errore": "argomenti non validi"}
    cartella = cartella_file(db_dir)
    sorgente = cartella / f"{jid}{suffisso}"
    db_path = Path(db_dir) / f"{db}.db"
    try:
        _pulisci_orfani(cartella, sorgente)
        if not sorgente.is_file():
            return 3, {"errore": "il file del lavoro non c'è più nella coda"}
        n = archive_indexer.index_file(str(sorgente), str(db_path), project=project)
        if description:
            archive_indexer.set_meta(db_path, "description", description)
        return 0, {"righe": n, "totale": archive_indexer.count_rows(db_path)}
    # BadZipFile non è un OSError: uno zip rotto è un rifiuto parlante, non un crash
    except (ValueError, OSError, RuntimeError, sqlite3.Error, zipfile.BadZipFile) as exc:
        return 3, {"errore": str(exc)[:600]}
    finally:
        sorgente.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["indexer"]:
        return archive_indexer.main(argv[1:]) or 0
    ap = argparse.ArgumentParser(prog="ingest_worker")
    sub = ap.add_subparsers(dest="modo", required=True)
    p = sub.add_parser("coda", help="indicizza un lavoro della coda di /admin/archive")
    p.add_argument("--id", required=True)
    p.add_argument("--db", required=True)
    p.add_argument("--suffisso", required=True)
    p.add_argument("--project", default="")
    p.add_argument("--description", default="")
    sub.add_parser("indexer", help="passa gli argomenti a archive_indexer")
    args = ap.parse_args(argv)
    codice, esito = esegui_coda(args.id, args.db, args.suffisso, args.project,
                                args.description)
    print(json.dumps(esito, ensure_ascii=False), flush=True)
    return codice


if __name__ == "__main__":
    sys.exit(main())
