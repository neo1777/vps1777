#!/usr/bin/env python3
"""rilievi.py — il deposito dei riti (R.1, dalla nota del proprietario su DD-P8.2).

Ogni rito che rileva qualcosa (sopralluogo, prototipo, retro, una rottura di mise provata,
la CI rossa sul ramo di default) chiude con un DEPOSITO: una riga in RILIEVI.ndjson, con
data, rito, cosa, responsabile e stato. Così il rilievo non resta nel verbale di un giorno.

Grado (R.1, scritto diviso come ha chiesto designer-di-dd, #21): SEGNALE per il conto dei
14 giorni; il deposito è promessa con rito dove il tipo non ha uno script.

  python3 tools/1777/rilievi.py deposita --rito R --cosa "…" --responsabile NOME [--data AAAA-MM-GG]
  python3 tools/1777/rilievi.py chiudi ID
  python3 tools/1777/rilievi.py conta [--oggi AAAA-MM-GG]

`conta` stampa «N aperti da più di 14 giorni, su M aperti, letto il <data>» ed esce 0:
è un segnale, non un blocco. Esce 1 se il registro ha una riga malformata: un controllo che
rifiuta un deposito LO DICE (il caso di APERTI.ndjson, fermato in silenzio dal gate).
Il 14 è lo stesso numero della DD-P8.6, scelto per coerenza e non misurato.
Vie d'uscita (C6): se la coda si riempie più in fretta di quanto si svuota, si alza la soglia
di cosa è un rilievo, non si smette di depositare; se al primo mese più di metà dei rilievi
supera i 14 giorni, il 14 si misura.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

REGISTRO = pathlib.Path("RILIEVI.ndjson")
CAMPI = {"id", "data", "rito", "cosa", "responsabile", "stato"}
SOGLIA_GIORNI = 14


def oggi_utc() -> dt.date:
    return dt.datetime.now(tz=dt.UTC).date()


def leggi() -> tuple[list[dict], list[str]]:
    voci, errori = [], []
    if not REGISTRO.is_file():
        return voci, errori
    for n, riga in enumerate(REGISTRO.read_text(encoding="utf-8").splitlines(), 1):
        if not riga.strip():
            continue
        try:
            v = json.loads(riga)
        except json.JSONDecodeError:
            errori.append(f"riga {n}: non è JSON")
            continue
        manca = CAMPI - set(v) if isinstance(v, dict) else CAMPI
        if manca:
            errori.append(f"riga {n}: mancano {sorted(manca)}")
            continue
        if v["stato"] not in ("aperto", "chiuso"):
            errori.append(f"riga {n}: stato «{v['stato']}» (vale aperto o chiuso)")
            continue
        try:
            dt.date.fromisoformat(v["data"])
        except (TypeError, ValueError):
            errori.append(f"riga {n}: data «{v['data']}» non è AAAA-MM-GG")
            continue
        voci.append(v)
    return voci, errori


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("deposita")
    d.add_argument("--rito", required=True)
    d.add_argument("--cosa", required=True)
    d.add_argument("--responsabile", required=True)
    d.add_argument("--data", default=oggi_utc().isoformat())
    c = sub.add_parser("chiudi")
    c.add_argument("id", type=int)
    k = sub.add_parser("conta")
    k.add_argument("--oggi", default=oggi_utc().isoformat())
    a = ap.parse_args()

    voci, errori = leggi()
    if errori:
        for e in errori:
            print(
                f"✗ ROSSO [rilievi] {REGISTRO}: {e} — il deposito è rifiutato, e lo dico",
                file=sys.stderr,
            )
        return 1

    if a.cmd == "deposita":
        v = {
            "id": max((x["id"] for x in voci), default=0) + 1,
            "data": a.data,
            "rito": a.rito,
            "cosa": a.cosa,
            "responsabile": a.responsabile,
            "stato": "aperto",
        }
        with REGISTRO.open("a", encoding="utf-8") as f:
            f.write(json.dumps(v, ensure_ascii=False) + "\n")
        print(f"✓ depositato il rilievo {v['id']} in {REGISTRO}")
        return 0
    if a.cmd == "chiudi":
        if not any(x["id"] == a.id for x in voci):
            print(f"✗ nessun rilievo con id {a.id}", file=sys.stderr)
            return 1
        oggi = oggi_utc().isoformat()
        righe = [
            dict(x, stato="chiuso", chiuso_il=oggi) if x["id"] == a.id else x
            for x in voci
        ]
        REGISTRO.write_text(
            "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in righe),
            encoding="utf-8",
        )
        print(f"✓ chiuso il rilievo {a.id}")
        return 0

    oggi = dt.date.fromisoformat(a.oggi)
    aperti = [x for x in voci if x["stato"] == "aperto"]
    vecchi = [
        x
        for x in aperti
        if (oggi - dt.date.fromisoformat(x["data"])).days > SOGLIA_GIORNI
    ]
    print(
        f"rilievi: {len(vecchi)} aperti da più di {SOGLIA_GIORNI} giorni, su {len(aperti)} aperti, letto il {oggi}"
        + (
            ""
            if REGISTRO.is_file()
            else f" ({REGISTRO} è pigro: nasce al primo deposito)"
        )
    )
    if aperti and len(vecchi) * 2 > len(aperti):
        print(
            f"ⓘ più di metà degli aperti supera i {SOGLIA_GIORNI} giorni: è la soglia per misurare il {SOGLIA_GIORNI} (C6)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
