#!/usr/bin/env python3
"""Calcola la mappa dei temi sui DB indicati e la scrive nel volume (D9, 07/11/2026).

Lo lancia `vps1777 indice-notturno` dopo gli indici, nello stesso job senza rete. Il primo
calcolo cerca i temi; i successivi ripartono da centri e media congelati, così i temi e i
loro marchi restano. `--da-zero` ricomincia (e i marchi vanno riguardati).

Esce 3 se un DB non ha il suo indice per senso: non è un guasto, è una cosa da dire. Non 2,
che è l'esito di python quando non trova il file: quello è un guasto, e va notificato.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import semantica, temi  # noqa: E402


def ancore_da(stato: dict | None, modello: Path) -> dict[str, np.ndarray]:
    """I vettori delle ancore. Dopo il primo calcolo stanno nello stato: il modello costa ~0,9
    GB di RAM, e per una mappa ricalcolata di notte non serve caricarlo ogni volta."""
    salvate = (stato or {}).get("ancore") or {}
    if set(salvate) == set(temi.ANCORE):
        return {k: np.array(v, dtype=np.float32) for k, v in salvate.items()}
    sess, tk = semantica.apri_modello(modello, thread=1)
    return {k: np.frombuffer(semantica.codifica(sess, tk, [semantica.PREFISSO_QUERY + t])[0], dtype=np.float32)
            for k, t in temi.ANCORE.items()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db-dir", type=Path, required=True)
    ap.add_argument("--db", required=True, help="nomi dei DB separati da virgole")
    ap.add_argument("--modello", type=Path, required=True)
    ap.add_argument("--da-zero", action="store_true")
    a = ap.parse_args()
    dest = temi.cartella(a.db_dir)
    stato = None if a.da_zero else temi.leggi_json(dest / temi.FILE_STATO)
    scambi = []
    for nome in [x.strip() for x in a.db.split(",") if x.strip()]:
        db, indice = a.db_dir / f"{nome}.db", a.db_dir / f"{nome}.vec.db"
        if not db.is_file() or not indice.is_file():
            print(f"{nome}: manca il DB o il suo indice per senso, la mappa non lo copre", file=sys.stderr)
            return 3
        dal_db = temi.scambi_di(db, indice, nome)
        temi.testi_degli_scambi(dal_db, db)
        print(f"{nome}: {len(dal_db)} scambi")
        scambi += dal_db
    if not scambi:
        print("nessuno scambio: la mappa non cambia", file=sys.stderr)
        return 3
    mappa, nuovo = temi.calcola(scambi, stato, ancore_da(stato, a.modello))
    mappa["generato"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    temi.scrivi_json(dest / temi.FILE_STATO, nuovo)
    temi.scrivi_json(dest / temi.FILE_TEMI, mappa)
    guardare = sum(1 for t in mappa["temi"] if t["da_guardare"])
    print(f"mappa: {len(mappa['temi'])} temi su {mappa['scambi']} scambi, {guardare} da guardare")
    return 0


if __name__ == "__main__":
    sys.exit(main())
