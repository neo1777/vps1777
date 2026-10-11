#!/usr/bin/env python3
"""Quanto è indietro il pin di nlm (notebooklm-mcp-cli) rispetto a upstream? (P9, 11/10/2026)

Dependabot ignora i minor di nlm di proposito (vedi .github/dependabot.yml): sotto la 1.0 un
minor può rompere come un major, e il salto si fa a mano con un metodo (changelog, `--help`
dei comandi, chiavi dei JSON, contract-test). Il prezzo era un pin fermo senza che nessuno lo
vedesse. Questo script lo misura: lo lancia rebuild-mensile.yml una volta al mese, e se il
pin è indietro da più di SOGLIA_GIORNI (contati dal primo rilascio stabile saltato) apre
una issue. Non aggiorna niente da sé.

Uscita: 0 = in pari o indietro da poco · 1 = indietro da più di un mese · 2 = non misurabile
(PyPI irraggiungibile, pin non trovato). Stdlib: gira su un runner nudo.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import urllib.request
from pathlib import Path

PACCHETTO = "notebooklm-mcp-cli"
SOGLIA_GIORNI = 30
_RADICE = Path(__file__).resolve().parents[1]
PYPROJECT = _RADICE / "services" / "nb1777-mcp" / "pyproject.toml"
_STABILE = re.compile(r"^\d+(\.\d+)*$")


def pin_attuale(pyproject: Path) -> str:
    m = re.search(rf'"{re.escape(PACCHETTO)}==([^"]+)"', pyproject.read_text(encoding="utf-8"))
    if not m:
        raise ValueError(f"pin {PACCHETTO}==… non trovato in {pyproject}")
    return m.group(1)


def _chiave(versione: str) -> tuple[int, ...]:
    return tuple(int(p) for p in versione.split("."))


def verdetto(pin: str, pypi: dict, *, oggi: dt.date) -> dict:
    """{indietro, giorni, ultima, dal, messaggio}. Contano solo le versioni stabili con
    almeno un file (un rilascio ritirato o una rc non è un ritardo)."""
    uscite: dict[str, dt.date] = {}
    for versione, files in (pypi.get("releases") or {}).items():
        if not files or not _STABILE.match(versione):
            continue
        uscite[versione] = min(dt.date.fromisoformat(f["upload_time"][:10]) for f in files)
    piu_nuove = sorted((v for v in uscite if _chiave(v) > _chiave(pin)), key=_chiave)
    if not piu_nuove:
        return {"indietro": False, "giorni": 0, "ultima": pin, "dal": "",
                "messaggio": f"nlm in pari: pin {pin}, nessuna versione stabile più nuova."}
    dal = min(uscite[v] for v in piu_nuove)
    giorni = (oggi - dal).days
    ultima = piu_nuove[-1]
    indietro = giorni > SOGLIA_GIORNI
    messaggio = (f"nlm pinnato a {pin}; upstream è alla {ultima} ({len(piu_nuove)} versioni "
                 f"stabili più nuove, la prima uscita il {dal.isoformat()}, {giorni} giorni fa). ")
    messaggio += ("Oltre la soglia di un mese: il salto si fa a mano, col metodo scritto in "
                  ".github/dependabot.yml (changelog, --help, JSON, contract-test)."
                  if indietro else f"Sotto la soglia di {SOGLIA_GIORNI} giorni.")
    return {"indietro": indietro, "giorni": giorni, "ultima": ultima,
            "dal": dal.isoformat(), "messaggio": messaggio}


def _leggi_pypi(da_file: str) -> dict:
    if da_file:
        return json.loads(Path(da_file).read_text(encoding="utf-8"))
    with urllib.request.urlopen(f"https://pypi.org/pypi/{PACCHETTO}/json", timeout=30) as r:
        return json.loads(r.read())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pyproject", default=str(PYPROJECT))
    ap.add_argument("--pypi-json", default="", help="un JSON di PyPI già scaricato (per i test)")
    ap.add_argument("--oggi", default="", help="AAAA-MM-GG (default: oggi in UTC)")
    a = ap.parse_args(argv)
    try:
        oggi = (dt.date.fromisoformat(a.oggi) if a.oggi
                else dt.datetime.now(dt.timezone.utc).date())
    except ValueError:
        ap.error(f"--oggi {a.oggi!r}: serve AAAA-MM-GG")
    try:
        v = verdetto(pin_attuale(Path(a.pyproject)), _leggi_pypi(a.pypi_json), oggi=oggi)
    except (OSError, ValueError, KeyError) as exc:
        print(f"nlm-cadenza: non misurabile ({exc})")
        return 2
    print(v["messaggio"])
    return 1 if v["indietro"] else 0


if __name__ == "__main__":
    sys.exit(main())
