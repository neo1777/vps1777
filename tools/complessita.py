#!/usr/bin/env python3
"""Nessuna funzione oltre complessità 10 che non sia censita, e nessuna censita che cresca.

PERCHÉ ESISTE. Il 22/11/2026 il repo aveva 55 funzioni oltre la complessità ciclomatica 10
(regola C901 di ruff), il 24/11 erano 56 e cinque di quelle già contate erano CRESCIUTE in
tre giorni di rilasci: senza un controllo, un conto fatto a mano invecchia mentre lo si
legge. La scelta di chi possiede il repo (`moduli_critici` in `applicabilita.yml`): il
limite vale in TUTTI i moduli; ogni funzione oltre 10 si esamina una per una, si spezza
dove migliora e si deroga solo dove spezzare darebbe pezzi senza senso, col motivo scritto
e riletto da chi non ha scritto il codice.

CHE COSA FA. Misura con ruff e confronta col censimento `tools/complessita.json`:
  • una funzione oltre la soglia che non è nel censimento → ROSSO (non ne entrano di nuove);
  • una censita che misura PIÙ del dichiarato → ROSSO (non peggiorano);
  • una censita che misura MENO del dichiarato → ROSSO: si abbassa il numero nel censimento
    (o si toglie la riga, se è scesa alla soglia). Il dichiarato è la misura, non un tetto
    largo sotto cui ricrescere;
  • una riga del censimento per una funzione che non c'è più → ROSSO (riga morta);
  • una riga `deroga` senza `motivo` (almeno 40 caratteri) o senza `data` → ROSSO;
  • passata la `fine_semina` scritta in testa al censimento, ogni riga ancora
    `da-esaminare` → ROSSO. Il censimento è una semina: un controllo nuovo su codice che
    esiste nasce col conto e con una data di fine, o diventa una lista che si impara a
    ignorare. Finché la data non è scritta lo strumento lo dice a ogni corsa.
Le deroghe senza `riletta_da` non bloccano FINO alla fine della semina (vengono stampate come
«in attesa di rilettura»); dopo quella data sono rosse anche loro.

LA DEROGA. Il motivo deve reggere il «test della cancellazione»: dire che cosa sarebbero i
pezzi e perché sarebbero passacarte. «È lunga ma lineare» non basta, e la comodità non è
un motivo. Non ha scadenza se il motivo è durevole: la riapre da sé il rosso «CRESCIUTA».

I test restano fuori dal conto (cartelle `tests`, `tests_runtime`, file `test_*.py`,
`conftest.py`): una prova lunga e piatta non è logica intricata da mantenere.

IL CENSIMENTO NON SI RIGENERA DA SOLO, apposta: uno strumento che riscrive il proprio
termine di confronto è un timbro. Le righe si correggono a mano, una per commit.

Uso:  python3 tools/complessita.py [--ruff "uvx ruff@X"]
        esiti: 0 = a posto · 1 = rosso · 2 = NON HA GUARDATO (ruff assente o guasto,
        censimento illeggibile): un controllo che non ha misurato non è un verde.
      python3 tools/complessita.py --autoprova                (lo strumento sa fallire?)
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
CENSIMENTO = RADICE / "tools" / "complessita.json"
# Le stesse cartelle del lint in ci.yml: se là se ne aggiunge una, va aggiunta qui.
CARTELLE = ("services", "tools", "security", "installer", "plugins")
STATI = ("da-esaminare", "deroga")
MOTIVO_MINIMO = 40
_MSG = re.compile(r"`(?P<nome>[^`]+)` is too complex \((?P<n>\d+) > \d+\)")


def e_un_test(percorso: str) -> bool:
    parti = Path(percorso).parts
    nome = parti[-1] if parti else ""
    return (
        any(p in ("tests", "tests_runtime") for p in parti)
        or nome.startswith("test_")
        or nome == "conftest.py"
    )


def misura(ruff: list[str], soglia: int, cartelle, radice: Path) -> dict[str, int]:
    """«percorso::funzione» → complessità, per ogni funzione oltre la soglia."""
    cmd = [
        *ruff, "check", "--isolated", "--select", "C901",
        "--config", f"lint.mccabe.max-complexity={soglia}",
        "--output-format", "json", "--no-cache", *cartelle,
    ]
    r = subprocess.run(cmd, cwd=radice, capture_output=True, text=True, check=False)
    # ruff esce 1 quando trova rilievi: è il caso normale. Oltre 1 è un guasto suo.
    if r.returncode not in (0, 1):
        raise RuntimeError(f"ruff è uscito {r.returncode}: {r.stderr.strip()[:400]}")
    try:
        rilievi = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"ruff non ha dato JSON leggibile: {e}") from e
    trovate: dict[str, int] = {}
    doppie: list[str] = []
    for ril in rilievi:
        if ril.get("code") != "C901":
            continue
        m = _MSG.search(ril.get("message", ""))
        if not m:
            raise RuntimeError(f"messaggio di ruff non riconosciuto: {ril.get('message')!r}")
        rel = Path(ril["filename"]).resolve().relative_to(radice.resolve()).as_posix()
        if e_un_test(rel):
            continue
        chiave = f"{rel}::{m['nome']}"
        if chiave in trovate:
            doppie.append(chiave)
        trovate[chiave] = max(int(m["n"]), trovate.get(chiave, 0))
    if doppie:
        raise RuntimeError(
            "due funzioni oltre la soglia con lo stesso nome nello stesso file "
            f"(il censimento non le distingue): {sorted(set(doppie))}"
        )
    return trovate


def _data(testo: object) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(str(testo))
    except ValueError:
        return None


def _misura_contro_riga(chiave: str, dichiarata: int, n: int | None) -> list[str]:
    if n is None:
        return [
            f"RIGA MORTA: {chiave} non è più oltre la soglia (o non esiste più): "
            "togli la riga dal censimento."
        ]
    if n > dichiarata:
        return [f"CRESCIUTA: {chiave} misura {n}, il censimento dice {dichiarata}."]
    if n < dichiarata:
        return [
            f"SCESA: {chiave} misura {n}, il censimento dice {dichiarata}: "
            "abbassa il numero nel censimento."
        ]
    return []


def _deroga(chiave: str, riga: dict, finita: str | None) -> tuple[list[str], list[str]]:
    rossi: list[str] = []
    note: list[str] = []
    if _data(riga.get("data")) is None:
        rossi.append(f"{chiave}: una deroga vuole la «data» in cui è stata scritta (AAAA-MM-GG).")
    if len((riga.get("motivo") or "").strip()) < MOTIVO_MINIMO:
        rossi.append(
            f"{chiave}: una deroga vuole il «motivo» scritto (almeno {MOTIVO_MINIMO} caratteri)."
        )
    if not (riga.get("riletta_da") or "").strip():
        if finita:
            # Senza questo il censimento si svuoterebbe scrivendo deroghe che nessuno rilegge.
            rossi.append(f"SEMINA FINITA il {finita}: la deroga di {chiave} non è stata riletta.")
        else:
            note.append(f"deroga in attesa di rilettura: {chiave} ({riga.get('complessita')})")
    return rossi, note


def _riga(chiave: str, riga: dict, n: int | None, finita: str | None) -> tuple[list[str], list[str]]:
    """I rossi e le note di UNA riga del censimento. `finita`: la data, se la semina è scaduta."""
    stato = riga.get("stato")
    dichiarata = riga.get("complessita")
    if stato not in STATI:
        return [f"{chiave}: stato {stato!r} non ammesso (ammessi: {', '.join(STATI)})"], []
    if not isinstance(dichiarata, int):
        return [f"{chiave}: «complessita» dev'essere un numero intero"], []
    rossi = _misura_contro_riga(chiave, dichiarata, n)
    if stato == "deroga":
        r, note = _deroga(chiave, riga, finita)
        return rossi + r, note
    if finita:
        rossi.append(f"SEMINA FINITA il {finita}: {chiave} è ancora da esaminare.")
    return rossi, []


def _semina(censimento: dict, oggi: datetime.date) -> tuple[list[str], list[str], str | None]:
    """(rossi, note, la data se la semina è scaduta)."""
    fine = censimento.get("fine_semina")
    if fine is None:
        return [], ["la semina non ha ancora una data di fine («fine_semina» nel censimento)"], None
    giorno = _data(fine)
    if giorno is None:
        return [f"«fine_semina» non è una data AAAA-MM-GG: {fine!r}"], [], None
    return [], [], (str(fine) if oggi > giorno else None)


def confronta(
    misurate: dict[str, int], censimento: dict, oggi: datetime.date
) -> tuple[list[str], list[str]]:
    """(rossi, note). Funzione pura: è quella che l'autoprova mette alla prova."""
    righe = censimento.get("funzioni", {})
    rossi, note, finita = _semina(censimento, oggi)
    for chiave, n in sorted(misurate.items()):
        if chiave not in righe:
            rossi.append(
                f"NUOVA oltre la soglia: {chiave} misura {n}. Spezzala; se spezzarla dà "
                "pezzi senza senso, aggiungi la riga al censimento col motivo."
            )
    for chiave, riga in sorted(righe.items()):
        r, nn = _riga(chiave, riga, misurate.get(chiave), finita)
        rossi += r
        note += nn
    return rossi, note


def _autoprova(ruff: list[str]) -> int:
    """Lo strumento sa dire rosso? Sei casi sul confronto, uno su ruff vero."""
    falliti: list[str] = []

    oggi = datetime.date(2026, 6, 1)

    def atteso(nome: str, misurate: dict, cens: dict, parola: str | None,
               testa: dict | None = None) -> None:
        testa = testa or {"fine_semina": "2026-12-31"}
        rossi, _ = confronta(misurate, {"funzioni": cens, **testa}, oggi)
        if parola is None and rossi:
            falliti.append(f"{nome}: doveva essere verde, ha detto {rossi}")
        if parola is not None and not any(parola in r for r in rossi):
            falliti.append(f"{nome}: doveva dire «{parola}», ha detto {rossi}")

    ok = {"complessita": 12, "stato": "da-esaminare"}
    atteso("pari", {"a.py::f": 12}, {"a.py::f": ok}, None)
    atteso("nuova", {"a.py::f": 12, "a.py::g": 11}, {"a.py::f": ok}, "NUOVA")
    atteso("cresciuta", {"a.py::f": 13}, {"a.py::f": ok}, "CRESCIUTA")
    atteso("scesa", {"a.py::f": 11}, {"a.py::f": ok}, "SCESA")
    atteso("morta", {}, {"a.py::f": ok}, "RIGA MORTA")
    atteso("deroga senza motivo", {"a.py::f": 12},
           {"a.py::f": {"complessita": 12, "stato": "deroga", "motivo": "così",
                        "data": "2026-05-01"}}, "motivo")
    atteso("deroga senza data", {"a.py::f": 12},
           {"a.py::f": {"complessita": 12, "stato": "deroga", "motivo": "x" * 60}}, "«data»")
    atteso("semina finita", {"a.py::f": 12}, {"a.py::f": ok}, "SEMINA FINITA",
           {"fine_semina": "2026-05-31"})
    atteso("semina finita, deroga non riletta", {"a.py::f": 12},
           {"a.py::f": {"complessita": 12, "stato": "deroga", "motivo": "x" * 60,
                        "data": "2026-05-01"}}, "non è stata riletta",
           {"fine_semina": "2026-05-31"})
    atteso("semina finita, deroga riletta", {"a.py::f": 12},
           {"a.py::f": {"complessita": 12, "stato": "deroga", "motivo": "x" * 60,
                        "data": "2026-05-01", "riletta_da": "altri"}}, None,
           {"fine_semina": "2026-05-31"})
    atteso("ultimo giorno della semina", {"a.py::f": 12}, {"a.py::f": ok}, None,
           {"fine_semina": "2026-06-01"})
    atteso("data di fine storta", {"a.py::f": 12}, {"a.py::f": ok}, "non è una data",
           {"fine_semina": "fine anno"})
    atteso("stato inventato", {"a.py::f": 12},
           {"a.py::f": {"complessita": 12, "stato": "va bene"}}, "non ammesso")
    _, note = confronta(
        {"a.py::f": 12},
        {"funzioni": {"a.py::f": {"complessita": 12, "stato": "deroga", "motivo": "x" * 60,
                                  "data": "2026-05-01"}}},
        oggi,
    )
    if not any("data di fine" in n for n in note):
        falliti.append("una semina senza data di fine doveva comparire fra le note")
    if not any("in attesa di rilettura" in n for n in note):
        falliti.append("una deroga non riletta doveva comparire fra le note")

    # ruff vero: una funzione con dodici rami dev'essere VISTA, e un test no.
    rami = "\n".join(f"    if x == {i}:\n        return {i}" for i in range(12))
    sorgente = f"def intricata(x):\n{rami}\n    return -1\n"
    with tempfile.TemporaryDirectory() as d:
        radice = Path(d)
        (radice / "pkg").mkdir()
        (radice / "pkg" / "m.py").write_text(sorgente, encoding="utf-8")
        (radice / "pkg" / "tests").mkdir()
        (radice / "pkg" / "tests" / "test_m.py").write_text(sorgente, encoding="utf-8")
        viste = misura(ruff, 10, ["pkg"], radice)
    if viste != {"pkg/m.py::intricata": 13}:
        falliti.append(f"ruff doveva vedere solo pkg/m.py::intricata a 13, ha visto {viste}")

    for f in falliti:
        print(f"AUTOPROVA FALLITA — {f}")
    if not falliti:
        print("complessita: autoprova a posto (15 casi sul confronto, 1 su ruff vero)")
    return 1 if falliti else 0


def main(argv: list[str]) -> int:
    ruff = ["ruff"]
    if "--ruff" in argv:
        ruff = shlex.split(argv[argv.index("--ruff") + 1])
    if "--autoprova" in argv:
        return _autoprova(ruff)
    try:
        censimento = json.loads(CENSIMENTO.read_text(encoding="utf-8"))
        soglia = censimento["soglia"]
        righe = censimento["funzioni"]
        misurate = misura(ruff, soglia, CARTELLE, RADICE)
    except (OSError, ValueError, KeyError, RuntimeError) as e:
        print(f"complessita: NON HA GUARDATO — {type(e).__name__}: {e}")
        return 2
    rossi, note = confronta(misurate, censimento, datetime.date.today())
    deroghe = [r for r in righe.values() if r.get("stato") == "deroga"]
    attesa = sum(1 for r in deroghe if not (r.get("riletta_da") or "").strip())
    for n in note:
        print(f"nota — {n}")
    for r in rossi:
        print(f"ROSSO — {r}")
    print(
        f"complessita: soglia {soglia}; {len(misurate)} funzioni oltre; "
        f"{len(righe) - len(deroghe)} da esaminare, {len(deroghe)} derogate "
        f"({attesa} in attesa di rilettura); {len(rossi)} rossi"
    )
    return 1 if rossi else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
