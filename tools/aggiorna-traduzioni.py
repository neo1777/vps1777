#!/usr/bin/env python3
"""Riallinea docs/en/MANIFEST.json: per ogni traduzione registra lo sha256 del
SORGENTE italiano com'è ADESSO. Si lancia DOPO aver aggiornato una traduzione —
mai prima: aggiornare l'hash senza toccare la traduzione trasforma il presidio
in un timbro (`tools/tests/test_traduzioni_fresche.py` è il verso che controlla).

Uso:  python3 tools/aggiorna-traduzioni.py            # riallinea tutti gli hash
      python3 tools/aggiorna-traduzioni.py --mostra   # solo stato, non scrive
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parents[1]
MANIFEST = RADICE / "docs" / "en" / "MANIFEST.json"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    dati = json.loads(MANIFEST.read_text(encoding="utf-8"))
    mostra = "--mostra" in sys.argv
    cambiati = 0
    for en, voce in dati["traduzioni"].items():
        src = RADICE / voce["sorgente"]
        nuovo = sha(src)
        stato = "fresca" if nuovo == voce["sorgente_sha256"] else "STANTIA"
        print(f"  {stato:7s}  {en}  ←  {voce['sorgente']}")
        if nuovo != voce["sorgente_sha256"] and not mostra:
            voce["sorgente_sha256"] = nuovo
            cambiati += 1
    if not mostra and cambiati:
        MANIFEST.write_text(json.dumps(dati, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
        print(f"manifest aggiornato: {cambiati} hash riallineati "
              f"(hai DAVVERO aggiornato quelle traduzioni, vero?)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
