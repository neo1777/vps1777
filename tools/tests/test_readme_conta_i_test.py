"""Il README dice quanti test ha il repo: quel numero si conta, non si ricorda.

Nato dalla rilettura di Neo del 23/11/2026: «Over 1,400 tests» era vero ma fermo da mesi, mentre i test
erano diventati più di 1.800. Un numero in vetrina che nessuno ricalcola è un'affermazione che invecchia
da sola. Qui si contano le funzioni `test_` (i casi parametrizzati e i test bash restano fuori: il conto
è per difetto) e si chiede che il numero dichiarato non superi il vero e non resti indietro di oltre 400.
"""
from __future__ import annotations

import re
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]
DEF = re.compile(r"^\s*(?:async\s+)?def test_", re.M)
NUMERI = {"six": 6, "sei": 6, "seven": 7, "sette": 7, "eight": 8, "otto": 8}
FRASI = {
    "README.md": re.compile(r"\*\*Over ([\d,]+) tests across (\w+) suites\*\*"),
    "README.it.md": re.compile(r"\*\*Oltre ([\d.]+) test in (\w+) suite\*\*"),
}


def _conta() -> dict[str, int]:
    """Funzioni di test per cartella (le cartelle sono le suite che `tools/check.sh` lancia una alla volta)."""
    per: dict[str, int] = {}
    for f in RADICE.rglob("test_*.py"):
        rel = f.relative_to(RADICE)
        if rel.parts[0] not in ("services", "tools") or ".venv" in rel.parts:
            continue
        n = len(DEF.findall(f.read_text(encoding="utf-8")))
        if n:
            per[str(rel.parent)] = per.get(str(rel.parent), 0) + n
    return per


def _dichiarato(nome: str) -> tuple[int, int]:
    m = FRASI[nome].search((RADICE / nome).read_text(encoding="utf-8"))
    assert m, f"{nome}: la frase sul numero dei test non c'è più (o ha cambiato forma): aggiorna questo presidio"
    return int(re.sub(r"\D", "", m.group(1))), NUMERI[m.group(2).lower()]


def test_il_numero_dei_test_nel_readme_e_contato():
    per = _conta()
    veri = sum(per.values())
    for nome in FRASI:
        detti, suite = _dichiarato(nome)
        assert detti <= veri, f"{nome} dichiara oltre {detti} test, ma se ne contano {veri}"
        assert veri - detti <= 400, f"{nome} dichiara oltre {detti} test: sono {veri}, il numero è rimasto indietro"
        assert suite == len(per), f"{nome} dichiara {suite} suite, le cartelle con test sono {len(per)}: {sorted(per)}"


def test_i_due_readme_dicono_lo_stesso_numero():
    assert _dichiarato("README.md") == _dichiarato("README.it.md")
