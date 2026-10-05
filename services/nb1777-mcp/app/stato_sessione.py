"""`python -m app.stato_sessione`: l'età della sessione Google per `vps1777 secrets-status`.

S9 (05/10/2026). La CLI dell'host leggeva l'mtime di `cookies.json` da un busybox, e quel
numero si azzerava ogni volta che `nlm` riscriveva il file. Qui, nel servizio che possiede
i cookie, si stampa una riga JSON con le sole date: {nata_il, ultimo_refresh, sonda}.
Nessun valore di cookie esce da questo processo.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import nlm_profile, sonda
from .settings import get_settings


def main() -> int:
    eta = nlm_profile.eta_sessione(Path(get_settings().nlm_home))
    if eta is None:
        print(json.dumps(None))
        return 1
    print(json.dumps({**eta, "sonda": sonda.ultimo()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
