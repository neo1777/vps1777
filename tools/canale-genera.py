#!/usr/bin/env python3
"""Scrive `canale.json`, il puntatore firmato all'ultima release stabile (SIC-15).

Due usi:

  genera --latest X.Y.Z [--giorni 45]     stampa il canale da firmare: lo usa
                                          .github/workflows/canale.yml, che poi lo firma con cosign
  impacchetta <canale.json>               stampa il file unico da pubblicare (testo + firma +
                                          certificato, presi da <file>, <file>.sig, <file>.pem)
  prova <cartella>                        prepara i file per PROVARE il client: una coppia di chiavi
                                          usa-e-getta, un canale fresco e uno scaduto, firmati

Il perché del canale sta in tools/vps1777.py («il canale firmato»). La regola della scadenza: chi
legge il file lo crede valido fino a `scade_il`; chi firma lo rinfresca molto prima (ogni settimana,
vita di 45 giorni), così un rinfresco saltato non ferma nessuno, e sei saltati sì.

`prova` esiste perché un canale «fresco» non si può tenere nel repo: fra un mese sarebbe scaduto. E
una chiave privata nel repo, anche di prova, è una chiave privata nel repo. Qui nascono al momento,
con openssl, e la chiave privata si cancella appena ha firmato.

Stdlib. Esce 0 · 2 se non ha potuto (openssl assente, versione non valida).
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

GIORNI = 45
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def canale(latest: str, *, adesso: dt.datetime, giorni: int = GIORNI) -> str:
    """Il testo di canale.json: una riga, chiavi in ordine fisso (si firma il file byte per byte)."""
    if not _SEMVER.match(latest):
        raise ValueError(f"«{latest}» non è una versione stabile X.Y.Z")
    if not 1 <= giorni <= 60:
        raise ValueError("la vita del canale va da 1 a 60 giorni (il client rifiuta oltre 60)")
    firmato = adesso.astimezone(dt.timezone.utc).replace(microsecond=0)
    return json.dumps({"schema": 1, "latest": latest, "firmato_il": firmato.isoformat(),
                       "scade_il": (firmato + dt.timedelta(days=giorni)).isoformat()}) + "\n"


def impacchetta(file: Path) -> str:
    """Il file unico che si pubblica: il testo del canale COM'È (la firma vale su quei byte), la firma
    e il certificato. Un file solo perché chi scarica veda sempre testo e firma dello stesso momento."""
    pezzi = {"canale": file.read_text(encoding="utf-8"),
             "sig": file.with_name(file.name + ".sig").read_text(encoding="utf-8"),
             "pem": file.with_name(file.name + ".pem").read_text(encoding="utf-8")}
    if not all(pezzi.values()):
        raise ValueError("testo, firma o certificato vuoti")
    return json.dumps(pezzi) + "\n"


def _firma(openssl: str, chiave: Path, file: Path) -> None:
    grezza = subprocess.run([openssl, "dgst", "-sha256", "-sign", str(chiave), str(file)],
                            capture_output=True, check=True, timeout=60).stdout
    file.with_name(file.name + ".sig").write_bytes(base64.b64encode(grezza) + b"\n")


def prova(cartella: Path, *, adesso: dt.datetime) -> None:
    openssl = shutil.which("openssl")
    if not openssl:
        raise OSError("openssl non c'è")
    cartella.mkdir(parents=True, exist_ok=True)
    privata = cartella / "chiave-privata.pem"
    try:
        subprocess.run([openssl, "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(privata)],
                       capture_output=True, check=True, timeout=60)
        subprocess.run([openssl, "ec", "-in", str(privata), "-pubout", "-out", str(cartella / "chiave.pub")],
                       capture_output=True, check=True, timeout=60)
        (cartella / "fresco.json").write_text(canale("9.9.9", adesso=adesso - dt.timedelta(days=1)), encoding="utf-8")
        (cartella / "scaduto.json").write_text(canale("9.9.9", adesso=adesso - dt.timedelta(days=90)), encoding="utf-8")
        for nome in ("fresco.json", "scaduto.json"):
            _firma(openssl, privata, cartella / nome)
    finally:
        privata.unlink(missing_ok=True)       # ha firmato: non serve più a nessuno


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("genera")
    g.add_argument("--latest", required=True)
    g.add_argument("--giorni", type=int, default=GIORNI)
    i = sub.add_parser("impacchetta")
    i.add_argument("file")
    p = sub.add_parser("prova")
    p.add_argument("cartella")
    a = ap.parse_args(argv)
    adesso = dt.datetime.now(dt.timezone.utc)
    try:
        if a.cmd == "genera":
            sys.stdout.write(canale(a.latest.removeprefix("v"), adesso=adesso, giorni=a.giorni))
        elif a.cmd == "impacchetta":
            sys.stdout.write(impacchetta(Path(a.file)))
        else:
            prova(Path(a.cartella), adesso=adesso)
            print(f"file di prova in {a.cartella}: fresco.json, scaduto.json, le firme accanto, chiave.pub")
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"canale-genera: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
