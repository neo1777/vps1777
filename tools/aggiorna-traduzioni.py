#!/usr/bin/env python3
"""Riallinea docs/en/MANIFEST.json dopo aver aggiornato una traduzione.

Per ogni coppia il manifest registra DUE impronte: quella del sorgente italiano e quella della
traduzione inglese, com'erano all'ultimo allineamento. Si lancia DOPO aver aggiornato la
traduzione, mai prima.

🔴 Perché due impronte (24/11/2026). Con la sola impronta del sorgente questo strumento era un
timbro: bastava lanciarlo e ogni traduzione tornava «fresca», anche se l'inglese non era stato
toccato. Lo chiedeva a voce («hai DAVVERO aggiornato quelle traduzioni?») e nient'altro. Ora
guarda: se l'italiano è cambiato e l'inglese è IDENTICO a com'era registrato, si RIFIUTA.

Il caso vero in cui l'inglese non va toccato esiste (un refuso corretto solo in italiano): si
dichiara, pagina per pagina, con `--solo-sorgente <pagina-inglese> "<motivo>"`, e il motivo
resta nel manifest.

Uso:  python3 tools/aggiorna-traduzioni.py                 # riallinea ciò che è stato tradotto
      python3 tools/aggiorna-traduzioni.py --mostra        # solo stato, non scrive
      python3 tools/aggiorna-traduzioni.py --solo-sorgente docs/en/CLI.md "refuso in italiano"
Esce: 0 tutto allineato · 1 almeno una traduzione non toccata (rifiutata) · 2 uso sbagliato
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


def allinea(dati: dict, radice: Path, *, scrivi: bool, solo_sorgente: dict[str, str]) -> tuple[int, list[str]]:
    """Ritorna (voci cambiate, pagine rifiutate). Stampa una riga per coppia."""
    cambiate, rifiutate = 0, []
    for en, voce in dati["traduzioni"].items():
        src_ora, en_ora = sha(radice / voce["sorgente"]), sha(radice / en)
        src_mosso = src_ora != voce["sorgente_sha256"]
        en_mosso = en_ora != voce.get("traduzione_sha256")
        if not src_mosso and not en_mosso:
            print(f"  fresca     {en}  ←  {voce['sorgente']}")
            continue
        if src_mosso and not en_mosso and en not in solo_sorgente:
            print(f"  RIFIUTATA  {en}  ←  {voce['sorgente']}: l'italiano è cambiato, l'inglese no")
            rifiutate.append(en)
            continue
        print(f"  {'riallineo' if scrivi else 'STANTIA'}   {en}  ←  {voce['sorgente']}"
              + (f"  (solo sorgente: {solo_sorgente[en]})" if en in solo_sorgente and not en_mosso else ""))
        if scrivi:
            voce["sorgente_sha256"], voce["traduzione_sha256"] = src_ora, en_ora
            if en in solo_sorgente and not en_mosso:
                voce["solo_sorgente"] = solo_sorgente[en]
            else:
                voce.pop("solo_sorgente", None)
            cambiate += 1
    return cambiate, rifiutate


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    mostra = "--mostra" in argv
    solo: dict[str, str] = {}
    while "--solo-sorgente" in argv:
        i = argv.index("--solo-sorgente")
        if len(argv) < i + 3 or not argv[i + 2].strip():
            print("--solo-sorgente vuole la pagina inglese e il motivo", file=sys.stderr)
            return 2
        solo[argv[i + 1]] = argv[i + 2].strip()
        del argv[i:i + 3]
    dati = json.loads(MANIFEST.read_text(encoding="utf-8"))
    sconosciute = [p for p in solo if p not in dati["traduzioni"]]
    if sconosciute:
        print(f"--solo-sorgente: pagine non nel manifest: {sconosciute}", file=sys.stderr)
        return 2
    cambiate, rifiutate = allinea(dati, RADICE, scrivi=not mostra, solo_sorgente=solo)
    if not mostra and cambiate:
        MANIFEST.write_text(json.dumps(dati, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"manifest aggiornato: {cambiate} coppie riallineate")
    if rifiutate:
        print("\nNON riallineate: aggiorna la pagina inglese, poi rilancia. Se l'inglese non va toccato:\n  "
              + "\n  ".join(f'python3 tools/aggiorna-traduzioni.py --solo-sorgente {p} "<motivo>"' for p in rifiutate),
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
