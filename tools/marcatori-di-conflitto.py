#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Un merge risolto a metà non entra in main: niente marcatori di conflitto né file `.rej`/`.orig`.

PERCHÉ ESISTE. Il controllo stava solo nell'hook di pre-commit (`tools/hooks/pre-commit`), che si
attiva a mano, si salta con `--no-verify` e non gira su una PR aperta dal browser o da un'altra
macchina. Nessuno dei controlli della CI li cerca: ruff e shellcheck leggono solo `.py` e `.sh`, e in
un YAML o in un Markdown le righe `<<<<<<< HEAD` entrerebbero senza un fiato (rilievo di Sagoma,
24/11). Qui la stessa domanda, sul repo intero, in CI.

COSA GUARDA. Ogni file tracciato da git (`git ls-files`):
  • una riga che comincia con `<<<<<<< ` o `>>>>>>> ` (git le scrive sempre così, col nome dopo);
  • un file `.rej` o `.orig` tracciato: sono gli avanzi di `patch` e di `git mergetool`.
La riga `=======` da sola non si conta: in Markdown è anche la sottolineatura di un titolo, e senza
le altre due non è un conflitto.

COSA NON GUARDA. I file binari (si saltano quelli con un byte nullo) e i file non tracciati.

Uso:   python3 tools/marcatori-di-conflitto.py [--repo DIR]
       python3 tools/marcatori-di-conflitto.py --autoprova
Esce:  0 pulito · 1 trovato qualcosa · 2 non ho potuto guardare (git assente o nessun file tracciato).
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

MARCATORE = re.compile(rb"^(<{7}|>{7}) ")
AVANZI = (".rej", ".orig")


def file_tracciati(repo: Path) -> list[str] | None:
    """I percorsi tracciati, o None se git non risponde."""
    try:
        r = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True,
                           check=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return [p for p in r.stdout.decode("utf-8", "surrogateescape").split("\0") if p]


def guasti_del_file(repo: Path, nome: str) -> list[str]:
    if nome.endswith(AVANZI):
        return [f"{nome}: avanzo di un merge o di una patch (tracciato)"]
    try:
        dati = (repo / nome).read_bytes()
    except OSError:
        return []          # un link rotto o un file tolto dal disco: non è questa la domanda
    if b"\0" in dati:
        return []
    return [f"{nome}:{i}: {riga[:60].decode('utf-8', 'replace')}"
            for i, riga in enumerate(dati.splitlines(), 1) if MARCATORE.match(riga)]


def controlla(repo: Path) -> tuple[int, list[str]]:
    nomi = file_tracciati(repo)
    if not nomi:
        return 2, ["nessun file tracciato letto (git assente, o non è un repo): non ho guardato"]
    guasti = [g for nome in nomi for g in guasti_del_file(repo, nome)]
    return (1 if guasti else 0), guasti


def _repo_finto(cartella: Path, file: dict[str, bytes]) -> Path:
    subprocess.run(["git", "init", "-q", str(cartella)], check=True, timeout=60)
    for nome, dati in file.items():
        (cartella / nome).write_bytes(dati)
    subprocess.run(["git", "-C", str(cartella), "add", "-A"], check=True, timeout=60)
    return cartella


def autoprova() -> int:
    """Pianta ogni guasto e pretende il rosso; pretende il verde dove non c'è niente."""
    casi = [
        ("pulito, con un titolo Markdown sottolineato", {"a.md": b"Titolo\n=======\n\ntesto\n"}, 0),
        ("un conflitto in un YAML", {"a.yml": b"x: 1\n<<<<<<< HEAD\ny: 2\n=======\ny: 3\n>>>>>>> ramo\n"}, 1),
        ("la sola chiusura rimasta", {"a.md": b"testo\n>>>>>>> 1a2b3c\n"}, 1),
        ("un .orig tracciato", {"a.py.orig": b"print(1)\n"}, 1),
        ("un .rej tracciato", {"a.rej": b"--- a\n"}, 1),
        ("un binario coi byte del marcatore", {"a.bin": b"\0<<<<<<< x\n"}, 0),
        ("il marcatore dentro una riga, non in testa", {"a.md": b"si scrive `<<<<<<< HEAD`\n"}, 0),
        ("nessun file tracciato", {}, 2),
    ]
    sbagliati = 0
    for nome, file, atteso in casi:
        with tempfile.TemporaryDirectory() as d:
            esito, _ = controlla(_repo_finto(Path(d), file))
        ok = esito == atteso
        sbagliati += not ok
        print(f"  {'✅' if ok else '🔴'} {nome} → esito {esito} (atteso {atteso})")
    if sbagliati:
        print(f"🔴 autoprova: {sbagliati} casi sbagliati: il guardiano non dice quello che deve")
        return 1
    print("✅ autoprova: sa dire di no a ogni guasto piantato, e sì dove non c'è niente")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument("--autoprova", action="store_true")
    a = ap.parse_args()
    if a.autoprova:
        return autoprova()
    esito, guasti = controlla(a.repo)
    for g in guasti:
        print(f"  ✗ {g}")
    if esito == 0:
        print("✅ nessun marcatore di conflitto e nessun avanzo .rej/.orig nei file tracciati")
    elif esito == 1:
        print(f"🔴 {len(guasti)} punti da un merge o una patch risolti a metà: finisci la risoluzione")
    return esito


if __name__ == "__main__":
    sys.exit(main())
