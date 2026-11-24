"""ingest_worker — il processo one-shot del servizio compose `ingest` (P16, 11/10/2026).

Gira nell'immagine del gateway ma in un container suo, con il suo `mem_limit`: se un
export grosso sfora, il kernel uccide questo, e il gateway (OAuth, proxy MCP, pagine)
resta su. Lo lancia la CLI sull'host (`vps1777 ingest-coda`, oppure i comandi
`archive-*`), mai il gateway: «il gateway non esegue processi».

Due modi:
  coda --id <id> --db <nome> --suffisso <.ext> [--project P] [--description D]
      indicizza il file `/var/lib/archive/coda/<id><ext>` nel DB `<nome>` e lo
      cancella; stampa UNA riga JSON con l'esito ({"righe", "totale"} o {"errore"}).
      Lo usano la coda di /admin/archive e `vps1777 archive-ingest`, che mette il file
      nella stessa cartella (dal 12/10/2026 non indicizza più dentro il gateway).
  indexer <argomenti di archive_indexer>
      passa tutto a `archive_indexer.main` (archive-migra, archive-retag).
  risana
      rimette leggibili i DB rimasti a metà di una scrittura (vedi `risana`); stampa UNA
      riga JSON ({"risanati": [...], "falliti": {...}}). Esce 0 se non resta niente di rotto.

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


def _pulisci_orfani(cartella: Path, tranne: Path) -> tuple[int, int]:
    """(tolti, non tolti): i file di lavori mai conclusi, più vecchi di ORFANO_DOPO_S."""
    tolti = falliti = 0
    soglia = time.time() - ORFANO_DOPO_S
    for p in cartella.glob("*"):
        if p == tranne or not p.is_file():
            continue
        try:
            if p.stat().st_mtime < soglia:
                p.unlink()
                tolti += 1
        except OSError:
            falliti += 1        # resta lì: l'esito lo dice, la prossima corsa riprova
    return tolti, falliti


def risana(db_dir: str = DB_DIR) -> dict:
    """Rimette leggibili i DB la cui ultima scrittura è morta a metà. {"risanati", "falliti"}.

    22/11/2026, misurato uccidendo l'indicizzatore con `kill -9` a metà di un file: un ingest è
    UNA transazione, quindi il DB resta intero (nessuna riga a metà), ma accanto resta il
    journal della transazione interrotta. Finché c'è, chi apre il DB in sola lettura (archive-mcp
    monta il volume `:ro`) riceve «attempt to write a readonly database» e lo salta: un DB con
    anni di conversazioni spariva dalle ricerche finché qualcuno non ci caricava un altro file.
    Succede davvero: il tetto di memoria del lavoro uccide proprio così.

    La cura la può fare solo chi ha il volume in scrittura, cioè questo processo: aprire il DB
    in scrittura e leggerlo basta, SQLite annulla da sé la transazione interrotta. Poi si
    controlla che sia sano (`quick_check`), e se non lo è lo si dice: «risanato» non si
    dichiara sulla fiducia. Un DB su cui un altro processo sta scrivendo DAVVERO non viene
    toccato: il suo journal non è abbandonato e SQLite lo sa dal lock.
    """
    risanati: list[str] = []
    falliti: dict[str, str] = {}
    for db in sorted(Path(db_dir).glob("*.db")):
        journal = db.with_name(db.name + "-journal")
        try:
            if not journal.is_file() or journal.stat().st_size == 0:
                continue
            conn = sqlite3.connect(str(db), timeout=5)
            try:
                conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
                esiti = [r[0] for r in conn.execute("PRAGMA quick_check(1)").fetchall()]
            finally:
                conn.close()
            if esiti != ["ok"]:
                falliti[db.stem] = "annullata la scrittura interrotta, ma il DB non è sano: " \
                                   + "; ".join(esiti)[:300]
            elif journal.is_file() and journal.stat().st_size > 0 \
                    and (perche := _togli_journal_residuo(db, journal)):
                falliti[db.stem] = perche
            else:
                risanati.append(db.stem)
        except (sqlite3.Error, OSError) as exc:
            falliti[db.stem] = str(exc)[:300]
    return {"risanati": risanati, "falliti": falliti}


def _togli_journal_residuo(db: Path, journal: Path) -> str | None:
    """Toglie un journal rimasto dopo che SQLite ha già fatto la sua parte; None se l'ha tolto.

    24/11/2026, visto da Sagoma (la prova di STA-04 rossa una volta su tre col PC carico) e
    riprodotto: se il `kill -9` cade dopo che SQLite ha CREATO il journal e prima che ne abbia
    scritto l'intestazione, il journal non è «caldo». SQLite non ha niente da annullare e non
    lo cancella; il DB è intero, e un lettore in sola lettura lo legge. Restava però lì, e
    `risana` lo dava per fallito. Prova di proprietà: si prende il lock di scrittura
    (BEGIN IMMEDIATE). Se lo si ottiene, nessun altro sta scrivendo e il journal non è di
    nessuno: si toglie tenendo il lock. Se no, c'è davvero un altro scrittore e non si tocca.
    """
    conn = sqlite3.connect(str(db), timeout=1, isolation_level=None)
    try:
        try:
            conn.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError:
            return ("il journal è ancora lì e un altro processo tiene il DB in scrittura: "
                    "non lo tocco")
        try:
            journal.unlink(missing_ok=True)
        finally:
            conn.execute("ROLLBACK")
    finally:
        conn.close()
    return None


def esegui_coda(jid: str, db: str, suffisso: str, project: str = "",
                description: str = "", *, db_dir: str = DB_DIR) -> tuple[int, dict]:
    """(codice d'uscita, esito). Logica senza argparse: la provano i test."""
    if not ID_RE.match(jid) or not DB_RE.match(db) or suffisso not in SUFFISSI:
        return 2, {"errore": "argomenti non validi"}
    cartella = cartella_file(db_dir)
    sorgente = cartella / f"{jid}{suffisso}"
    db_path = Path(db_dir) / f"{db}.db"
    try:
        _tolti, non_tolti = _pulisci_orfani(cartella, sorgente)
        if not sorgente.is_file():
            return 3, {"errore": "il file del lavoro non c'è più nella coda"}
        # prima di scrivere: un lavoro di prima ucciso a metà può aver lasciato un altro DB
        # illeggibile, e questo è l'unico processo che lo può rimettere a posto
        cura = risana(db_dir)
        n = archive_indexer.index_file(str(sorgente), str(db_path), project=project)
        if description:
            archive_indexer.set_meta(db_path, "description", description)
        esito = {"righe": n, "totale": archive_indexer.count_rows(db_path)}
        if cura["risanati"] or cura["falliti"]:
            esito["risanamento"] = cura
        if non_tolti:
            esito["orfani_non_tolti"] = non_tolti
        return 0, esito
    # BadZipFile non è un OSError: uno zip rotto è un rifiuto parlante, non un crash
    except (ValueError, OSError, RuntimeError, sqlite3.Error, zipfile.BadZipFile) as exc:
        return 3, {"errore": str(exc)[:600]}
    except Exception as exc:  # noqa: BLE001 — un difetto nostro: l'esito lo deve dire comunque
        # Senza questo ramo chi aveva caricato il file non riceveva NESSUN esito (il servizio
        # moriva col traceback) e il file spariva lo stesso nel `finally`.
        return 3, {"errore": f"errore imprevisto dell'indicizzatore "
                             f"({type(exc).__name__}): {str(exc)[:500]}"}
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
    sub.add_parser("risana", help="rimette leggibili i DB rimasti a metà di una scrittura")
    args = ap.parse_args(argv)
    if args.modo == "risana":
        cura = risana()
        print(json.dumps(cura, ensure_ascii=False), flush=True)
        return 1 if cura["falliti"] else 0
    codice, esito = esegui_coda(args.id, args.db, args.suffisso, args.project,
                                args.description)
    print(json.dumps(esito, ensure_ascii=False), flush=True)
    return codice


if __name__ == "__main__":
    sys.exit(main())
