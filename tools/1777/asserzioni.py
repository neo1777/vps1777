#!/usr/bin/env python3
"""asserzioni.py — Kb.2: nessun file di test senza asserzioni.

È un PAVIMENTO, non una prova: che l'asserzione non sia tautologica lo dice solo un test
visto rosso sul codice di prima (D9). Qui si guarda solo che un'asserzione ci sia.

Per stack:  pytest `assert` (o pytest.raises, self.assert*)
            vitest `expect(` (o assert)
            Dart   `expect(`, `expectLater(`, `verify(`
Un file Dart con solo `expectLater` NON è rosso (Pr.4): la regola è
`expect(Later)?\\(`, e prova-controlli.sh ha il guasto al contrario che lo tiene.

Esce 0 se ogni file di test ha un'asserzione, 1 se no, 2 se non può misurare.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

REGOLE = [
    (
        re.compile(r"(^|/)(test_[^/]*|[^/]*_test)\.py$"),
        re.compile(r"\bassert\b|pytest\.raises|\.assert\w*\("),
    ),
    (
        re.compile(r"\.(test|spec)\.(c|m)?[jt]sx?$"),
        re.compile(r"\bexpect\s*\(|\bassert\b"),
    ),
    (re.compile(r"_test\.dart$"), re.compile(r"\bexpect(Later)?\s*\(|\bverify\s*\(")),
]


def main() -> int:
    r = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "-z"],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        print(
            "[⚪] asserzioni: NON MISURATO — non sono in un repository git",
            file=sys.stderr,
        )
        return 2
    visti, rossi = 0, []
    for f in filter(None, r.stdout.split("\0")):
        for nome, asserzione in REGOLE:
            if nome.search(f) and pathlib.Path(f).is_file():
                visti += 1
                if not asserzione.search(
                    pathlib.Path(f).read_text(encoding="utf-8", errors="replace")
                ):
                    rossi.append(f)
                break
    for f in rossi:
        print(
            f"✗ ROSSO [asserzioni] {f}: file di test senza nessuna asserzione (Kb.2)",
            file=sys.stderr,
        )
    if rossi:
        return 1
    if visti == 0:
        print(
            "ⓘ asserzioni: nessun file di test trovato, niente da giudicare (il test vuoto lo prende K-b)"
        )
        return 0
    print(f"✓ asserzioni: {visti} file di test, tutti con almeno un'asserzione")
    return 0


if __name__ == "__main__":
    sys.exit(main())
