#!/usr/bin/env python3
"""Nessun errore di tipo nuovo, e nessun file censito che ne abbia di più (QUA-03, in semina).

PERCHÉ ESISTE. Il repo è annotato ma nessun type checker girava: «un'annotazione senza type
checker è una promessa» (QUA-03 dello standard 1777). `applicabilita.yml` la dichiarava «n.a.
per typescript», ma la riga vale anche per il Python (rilievo di Sagoma, 24/11/2026). Misurato
il 25/11 con mypy 1.18.2: 160 errori in modo normale, 840 in modo strict. La scelta di chi
possiede il repo (2026-11-25-soglia-qua03-tipi): la stessa forma di QUA-04, mypy normale in CI
con un censimento, nessun errore nuovo, fine semina il 30/04/2027; lo strict dopo.

CHE COSA FA. Misura con mypy, unità per unità, e confronta col censimento `tools/tipi.json`
(file → numero di errori):
  • un file con errori che non è nel censimento → ROSSO (NUOVO);
  • un file censito con PIÙ errori del dichiarato → ROSSO (CRESCIUTO);
  • un file censito con MENO errori → ROSSO (SCESO): si abbassa il numero, o si toglie la riga
    se è arrivato a zero. Il dichiarato è la misura, non un tetto sotto cui ricrescere;
  • una riga per un file senza errori o che non c'è più → ROSSO (RIGA MORTA);
  • passata la `fine_semina`, ogni riga ancora nel censimento → ROSSO (SEMINA FINITA).

LE UNITÀ. Ogni servizio e ogni plugin ha un package `app`: due `app` nella stessa corsa di mypy
si scontrano, quindi si lancia una volta per cartella, dentro la cartella. Poi `tools/`,
`security/` (i file, non package) e `installer/` (come package). I test restano fuori, come in
QUA-04. Le opzioni sono fisse qui sotto e valgono per tutti: cambiarle cambia la misura, e va
fatto rimisurando il censimento nello stesso commit.
  --ignore-missing-imports e --disable-error-code=import-untyped: le librerie di terzi qui non
  sono installate (mypy gira da solo, con `uvx`); i loro tipi diventano Any. È una misura più
  debole di quella con le dipendenze, ma è la stessa a ogni corsa e su ogni macchina.
  --follow-imports=silent: un errore conta nel file che lo contiene, non in chi lo importa.
  --python-version 3.12: quella delle immagini.

IL CENSIMENTO NON SI RIGENERA DA SOLO (come quello di QUA-04): `--stampa` mostra la misura in
forma di censimento, ma lo si scrive a mano, così ogni numero che cambia passa da un commit.

Uso:  python3 tools/tipi.py [--mypy "mypy"]        (default: uvx mypy@MYPY_VERSIONE)
        esiti: 0 = a posto · 1 = rosso · 2 = NON HA GUARDATO (mypy assente, guasto o fermato
        da un errore bloccante; censimento illeggibile): non è un verde.
      python3 tools/tipi.py --stampa [--mypy …]     la misura, in forma di censimento
      python3 tools/tipi.py --autoprova [--mypy …]  lo strumento sa fallire?
Stdlib-only.
"""
from __future__ import annotations

import datetime
import json
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

RADICE = Path(__file__).resolve().parents[1]
CENSIMENTO = RADICE / "tools" / "tipi.json"
MYPY_VERSIONE = "1.18.2"
OPZIONI = (
    "--ignore-missing-imports", "--disable-error-code=import-untyped",
    "--follow-imports=silent", "--python-version", "3.12",
    "--cache-dir=/dev/null", "--no-error-summary", "--hide-error-context",
    "--no-color-output", "--no-pretty", "--show-absolute-path",
)
_ERRORE = re.compile(r"^(?P<file>.+?):\d+: error: ")


def e_un_test(percorso: str) -> bool:
    parti = Path(percorso).parts
    nome = parti[-1] if parti else ""
    return (any(p in ("tests", "tests_runtime") for p in parti)
            or nome.startswith("test_") or nome == "conftest.py")


def _tracciati(radice: Path, *spec: str) -> list[str]:
    r = subprocess.run(["git", "-C", str(radice), "ls-files", *spec], capture_output=True,
                       text=True, check=True, timeout=60)
    return [p for p in r.stdout.splitlines() if p and not e_un_test(p)]


def unita(radice: Path) -> list[tuple[Path, list[str]]]:
    """(cartella da cui lanciare, bersagli): una corsa di mypy per ciascuna."""
    out: list[tuple[Path, list[str]]] = []
    for gruppo in ("services", "plugins"):
        for app in sorted((radice / gruppo).glob("*/app/__init__.py")):
            out.append((app.parent.parent, ["app"]))
    for cartella in ("tools", "security"):
        file = [p for p in _tracciati(radice, f"{cartella}/*.py") if p.count("/") == 1]
        if file:
            out.append((radice, file))
    if _tracciati(radice, "installer/*.py"):
        out.append((radice, ["-p", "installer"]))
    return out


def misura(mypy: list[str], radice: Path) -> dict[str, int]:
    """Percorso dalla radice → numero di errori, per ogni file che ne ha."""
    conti: dict[str, int] = {}
    radice = radice.resolve()
    for cartella, bersagli in unita(radice):
        r = subprocess.run([*mypy, *OPZIONI, *bersagli], cwd=cartella, capture_output=True,
                           text=True, check=False, timeout=900)
        # 0 nessun errore, 1 errori trovati: i casi normali. 2 = un errore bloccante o un guasto.
        if r.returncode not in (0, 1):
            raise RuntimeError(f"mypy è uscito {r.returncode} in {cartella}: "
                               f"{(r.stderr or r.stdout).strip()[:400]}")
        for riga in r.stdout.splitlines():
            m = _ERRORE.match(riga)
            if not m:
                continue
            rel = Path(m["file"]).resolve().relative_to(radice).as_posix()
            if not e_un_test(rel):
                conti[rel] = conti.get(rel, 0) + 1
    return conti


def _data(testo: object) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(str(testo))
    except ValueError:
        return None


def _riga(nome: str, dichiarati: object, n: int, finita: str | None) -> list[str]:
    if not isinstance(dichiarati, int) or dichiarati < 1:
        return [f"{nome}: il numero di errori dev'essere un intero da 1 in su, non {dichiarati!r}"]
    rossi = []
    if n == 0:
        rossi.append(f"RIGA MORTA: {nome} non ha più errori (o non esiste più): togli la riga.")
    elif n > dichiarati:
        rossi.append(f"CRESCIUTO: {nome} ha {n} errori di tipo, il censimento dice {dichiarati}.")
    elif n < dichiarati:
        rossi.append(f"SCESO: {nome} ha {n} errori, il censimento dice {dichiarati}: "
                     "abbassa il numero nel censimento.")
    if finita:
        rossi.append(f"SEMINA FINITA il {finita}: {nome} ha ancora errori di tipo censiti.")
    return rossi


def confronta(misurati: dict[str, int], censimento: dict,
              oggi: datetime.date) -> tuple[list[str], list[str]]:
    """(rossi, note). Funzione pura: è quella che l'autoprova mette alla prova."""
    righe = censimento.get("file", {})
    fine = censimento.get("fine_semina")
    giorno = _data(fine)
    if fine is not None and giorno is None:
        return [f"«fine_semina» non è una data AAAA-MM-GG: {fine!r}"], []
    note = [] if giorno else ["la semina non ha una data di fine («fine_semina» nel censimento)"]
    finita = str(fine) if giorno and oggi > giorno else None
    rossi = [f"NUOVO: {nome} ha {n} errori di tipo e non è nel censimento: correggili."
             for nome, n in sorted(misurati.items()) if nome not in righe]
    for nome, dichiarati in sorted(righe.items()):
        rossi += _riga(nome, dichiarati, misurati.get(nome, 0), finita)
    return rossi, note


def _autoprova(mypy: list[str]) -> int:
    """Lo strumento sa dire rosso? Nove casi sul confronto, uno su mypy vero."""
    falliti: list[str] = []
    oggi = datetime.date(2026, 6, 1)

    def atteso(nome: str, misurati: dict, righe: dict, parola: str | None,
               fine: str = "2026-12-31") -> None:
        rossi, _ = confronta(misurati, {"file": righe, "fine_semina": fine}, oggi)
        if parola is None and rossi:
            falliti.append(f"{nome}: doveva essere verde, ha detto {rossi}")
        if parola is not None and not any(parola in r for r in rossi):
            falliti.append(f"{nome}: doveva dire «{parola}», ha detto {rossi}")

    atteso("pari", {"a.py": 3}, {"a.py": 3}, None)
    atteso("nuovo", {"a.py": 3, "b.py": 1}, {"a.py": 3}, "NUOVO")
    atteso("cresciuto", {"a.py": 4}, {"a.py": 3}, "CRESCIUTO")
    atteso("sceso", {"a.py": 2}, {"a.py": 3}, "SCESO")
    atteso("morta", {}, {"a.py": 3}, "RIGA MORTA")
    atteso("numero storto", {"a.py": 3}, {"a.py": "tre"}, "intero")
    atteso("semina finita", {"a.py": 3}, {"a.py": 3}, "SEMINA FINITA", "2026-05-31")
    atteso("ultimo giorno della semina", {"a.py": 3}, {"a.py": 3}, None, "2026-06-01")
    atteso("data storta", {"a.py": 3}, {"a.py": 3}, "non è una data", "fine aprile")

    # mypy vero: un errore piantato si vede, nel file giusto, e un test no.
    sbagliato = "def f(x: int) -> str:\n    return x\n"
    with tempfile.TemporaryDirectory() as d:
        radice = Path(d)
        subprocess.run(["git", "init", "-q", str(radice)], check=True, timeout=60)
        for rel in ("tools/rotto.py", "tools/sano.py", "tools/test_rotto.py"):
            (radice / rel).parent.mkdir(parents=True, exist_ok=True)
            (radice / rel).write_text(
                "def g(x: int) -> int:\n    return x\n" if "sano" in rel else sbagliato,
                encoding="utf-8")
        subprocess.run(["git", "-C", str(radice), "add", "-A"], check=True, timeout=60)
        visti = misura(mypy, radice)
    if visti != {"tools/rotto.py": 1}:
        falliti.append(f"mypy doveva vedere un errore in tools/rotto.py e basta, ha visto {visti}")

    for f in falliti:
        print(f"AUTOPROVA FALLITA — {f}")
    if not falliti:
        print("tipi: autoprova a posto (9 casi sul confronto, 1 su mypy vero)")
    return 1 if falliti else 0


def main(argv: list[str]) -> int:
    # Il pin sta qui e in nessun altro posto: CI e check.sh lanciano lo strumento senza --mypy.
    mypy = ["uvx", f"mypy@{MYPY_VERSIONE}"]
    if "--mypy" in argv:
        mypy = shlex.split(argv[argv.index("--mypy") + 1])
    if "--autoprova" in argv:
        return _autoprova(mypy)
    try:
        misurati = misura(mypy, RADICE)
        if "--stampa" in argv:
            print(json.dumps(dict(sorted(misurati.items())), indent=2, ensure_ascii=False))
            return 0
        censimento = json.loads(CENSIMENTO.read_text(encoding="utf-8"))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as e:
        print(f"tipi: NON HA GUARDATO — {type(e).__name__}: {e}")
        return 2
    rossi, note = confronta(misurati, censimento, datetime.datetime.now(datetime.timezone.utc).date())
    for n in note:
        print(f"nota — {n}")
    for r in rossi:
        print(f"ROSSO — {r}")
    print(f"tipi: {sum(misurati.values())} errori di tipo in {len(misurati)} file; "
          f"{len(censimento.get('file', {}))} righe nel censimento, fine semina "
          f"{censimento.get('fine_semina')}; {len(rossi)} rossi")
    return 1 if rossi else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
