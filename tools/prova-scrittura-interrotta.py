#!/usr/bin/env python3
"""prova-scrittura-interrotta.py — i tre pezzi per uccidere l'indicizzatore a metà e vedere come resta il DB.

Serve a chi vuole fare la prova da fuori (un controllo esterno, o a mano): il colpo lo dà chi
chiama, questo file dà solo i pezzi, così la dichiarazione della prova resta di tre righe.
La stessa prova, col colpo incluso, gira in CI: services/gateway/tests/test_ingest_ucciso.py.

  prepara  <cartella>   crea un DB con 40 righe e un sorgente grande da caricare
  scrivi   <cartella>   carica il sorgente grande nel DB: è il processo da uccidere (`kill -9`)
                        mentre esiste <cartella>/prova.db-journal
  integrita <cartella>  risana come fa il servizio `ingest`, poi controlla: integrity_check,
                        indice di ricerca coerente, e le 40 righe di prima (nessuna del lavoro ucciso
                        se è stato ucciso; tutte, se è arrivato in fondo)

Esce: 0 intero · 1 CORROTTO o righe sbagliate · 2 non ho potuto guardare (non è un verde)
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

GATEWAY = Path(__file__).resolve().parents[1] / "services" / "gateway"
sys.path.insert(0, str(GATEWAY))
PRIMA, GRANDE = 40, 60_000


def _sorgente(p: Path, n: int, prefisso: str) -> None:
    with open(p, "w", encoding="utf-8") as fh:
        for i in range(n):
            fh.write(json.dumps({
                "type": "user" if i % 2 == 0 else "assistant", "uuid": f"{prefisso}{i:06d}",
                "timestamp": "2026-01-01T00:00:00Z", "cwd": "/x/proj", "sessionId": "s1",
                "message": {"content": f"riga {prefisso} numero {i} " + "parola " * 40},
            }) + "\n")


def prepara(d: Path) -> int:
    from app import archive_indexer
    d.mkdir(parents=True, exist_ok=True)
    for vecchio in d.glob("prova.db*"):
        vecchio.unlink()
    _sorgente(d / "prima.jsonl", PRIMA, "a")
    _sorgente(d / "grande.jsonl", GRANDE, "b")
    n = archive_indexer.index_file(str(d / "prima.jsonl"), str(d / "prova.db"))
    print(f"pronto: {n} righe in {d / 'prova.db'}, {GRANDE} da caricare")
    return 0 if n == PRIMA else 2


def scrivi(d: Path) -> int:
    from app import archive_indexer
    n = archive_indexer.index_file(str(d / "grande.jsonl"), str(d / "prova.db"), project="p")
    print(f"caricate {n} righe")
    return 0


def integrita(d: Path) -> int:
    from app import ingest_worker
    db = d / "prova.db"
    if not db.is_file():
        print(f"NON MISURATO: {db} non c'è (lancia prima «prepara»)")
        return 2
    cura = ingest_worker.risana(str(d))
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            sano = [r[0] for r in conn.execute("PRAGMA integrity_check").fetchall()] == ["ok"]
            righe, distinte = conn.execute("SELECT count(*), count(DISTINCT uuid) FROM messages").fetchone()
            fts = conn.execute("SELECT count(*) FROM messages_fts").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error as exc:
        print(f"CORROTTO o illeggibile dopo il risanamento: {exc} · risanamento: {cura}")
        return 1
    intero = sano and not cura["falliti"] and righe == distinte == fts and righe in (PRIMA, PRIMA + GRANDE)
    print(f"{'intero' if intero else 'CORROTTO'}: {righe} righe ({distinte} distinte, {fts} nell'indice), "
          f"integrity_check {'ok' if sano else 'ROSSO'}, risanamento {cura}")
    return 0 if intero else 1


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] not in ("prepara", "scrivi", "integrita"):
        print(__doc__)
        return 2
    return {"prepara": prepara, "scrivi": scrivi, "integrita": integrita}[argv[0]](Path(argv[1]).resolve())


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
