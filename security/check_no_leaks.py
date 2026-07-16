#!/usr/bin/env python3
"""Gate anti-leak: fallisce se nel repo entra roba che online non ci può stare.

Perché esiste
-------------
Il `.gitignore` non basta, per due motivi precisi:
  1. non ferma `git add -f`, e soprattutto
  2. non fa NULLA per un file già tracciato — una volta dentro, è dentro.
Serve un controllo che giri a ogni PR e dica "no" prima del merge, non dopo.

Il vettore vero, quello che ci ha morso: gli **export di sessione** (il transcript
di una chat di lavoro, `AAAA-MM-GG-HHMMSS-<slug>.txt`). Non sembrano segreti — sono
`.txt` con un nome innocuo — ma dentro ci passa tutto ciò che si è detto lavorando:
password incollate, IP, path locali, dati personali. È il file più pericoloso del
repo proprio perché non ha l'aria di esserlo.

Due regole
----------
  R1  nessun file tracciato con la forma di un export di sessione;
  R2  nessun materiale credenziale VERO dentro i file tracciati.

R2 distingue il **segnaposto** dal **materiale**: la doc deve poter scrivere
`tskey-auth-...` per spiegare cosa incollare. Un gate che grida al lupo sui
segnaposto viene disattivato in una settimana, e allora non protegge più niente.
Per questo i pattern pretendono lunghezza e alfabeto reali, non i puntini.

Output
------
Riporta **dove**, mai **cosa**. I log della CI di un repo pubblico sono pubblici:
un guardiano che stampa il segreto che ha trovato lo pubblica lui stesso.

Uso:  python3 security/check_no_leaks.py     (exit 1 = trovato qualcosa)
Stdlib only, come il resto di security/.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# ── R1 — roba che per natura non appartiene al repo ───────────────────────────
# a) `/export` di Claude Code produce: 2026-07-14-084038-<slug-della-prima-riga>.txt
SESSION_EXPORT = re.compile(r"(^|/)\d{4}-\d{2}-\d{2}-\d{6}-.*\.txt$")

# b) I transcript di sessione veri e propri: stessa classe degli export (la
#    conversazione integrale, password incollate comprese). Su una macchina di
#    lavoro ne girano a centinaia: la probabilità che uno finisca in un `add`
#    non è teorica.
SESSION_JSONL = re.compile(r"\.jsonl$")

# c) Database. Un `archive.db` committato per sbaglio non è "un file grosso": è
#    l'intero archivio — decine di migliaia di messaggi — in un oggetto solo.
#    Sono dati di un'installazione, non del progetto: non entrano, punto.
DATABASE = re.compile(r"\.(db|sqlite3?)(-wal|-shm)?$")

# Unica via d'uscita, stretta di proposito: una fixture di test piccola può
# essere un .jsonl legittimo. Un transcript vero non ci sta dentro il tetto.
FIXTURE_DIR = re.compile(r"(^|/)tests?/(fixtures?|data)/")
FIXTURE_MAX_BYTES = 64 * 1024

# ── R2 — materiale credenziale vero (non i segnaposto) ────────────────────────
# Ogni pattern pretende alfabeto+lunghezza reali, così `tskey-auth-...` nella doc
# non lo fa scattare ma `tskey-auth-kA9f…` sì.
SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("auth-key Tailscale", re.compile(r"tskey-[a-z]+-[A-Za-z0-9]{8,}")),
    ("token bot Telegram", re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b")),
    ("chiave age privata", re.compile(r"AGE-SECRET-KEY-1[A-Z0-9]{50,}")),
    (
        "chiave privata PEM",
        re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"),
    ),
    # sshpass con password letterale. `-e` (da env) è la forma giusta e passa;
    # `-p "$VAR"`, `-p '<password>'` e `-p …` sono segnaposto e passano.
    (
        "password letterale in sshpass",
        re.compile(r"""sshpass\s+-p\s*['"]?(?![$<{.…])[^\s'"`$<>]{6,}"""),
    ),
]

# File che PARLANO dei pattern per mestiere (questo gate, e il registro dei
# rilievi che cita le evidenze). Allowlist stretta e motivata: se cresce, è un
# segnale che qualcosa non va — non una comodità.
ALLOWLIST = {
    "security/check_no_leaks.py",
    "security/findings.yml",
}

BINARY_HINT = b"\x00"


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], capture_output=True, check=True
    ).stdout
    return [p for p in out.decode("utf-8", "replace").split("\0") if p]


def main() -> int:
    problems: list[str] = []

    for path in tracked_files():
        # R1 — la forma del nome basta a bocciarlo: non serve guardarci dentro.
        if SESSION_EXPORT.search(path):
            problems.append(
                f"  [R1] {path}\n"
                f"       → export di sessione tracciato. Un transcript di lavoro non va nel repo:\n"
                f"         dentro ci finisce tutto quello che ci si è detti lavorando.\n"
                f"       → toglilo (`git rm --cached`) e tienilo fuori dal repo."
            )
            continue

        if DATABASE.search(path):
            problems.append(
                f"  [R1] {path}\n"
                f"       → database tracciato. Non è «un file grosso»: è l'intero contenuto\n"
                f"         di un'installazione (un archivio può valere decine di migliaia di\n"
                f"         messaggi) in un oggetto solo. I dati non stanno nel repo.\n"
                f"       → `git rm --cached` e tienilo fuori. Nessuna eccezione prevista."
            )
            continue

        if SESSION_JSONL.search(path):
            size = Path(path).stat().st_size if Path(path).is_file() else 0
            if FIXTURE_DIR.search(path) and size <= FIXTURE_MAX_BYTES:
                pass  # fixture piccola e in chiaro sotto tests/: legittima
            else:
                why = (
                    f"supera il tetto fixture ({size} B > {FIXTURE_MAX_BYTES} B)"
                    if FIXTURE_DIR.search(path)
                    else "sta fuori da tests/fixtures/"
                )
                problems.append(
                    f"  [R1] {path}\n"
                    f"       → .jsonl tracciato che {why}.\n"
                    f"         È la stessa classe degli export di sessione: un transcript\n"
                    f"         integrale, password incollate comprese.\n"
                    f"       → se è davvero una fixture, mettila in tests/fixtures/ e tienila\n"
                    f"         piccola; se è un transcript, fuori dal repo."
                )
                continue

        if path in ALLOWLIST:
            continue

        p = Path(path)
        if not p.is_file():
            continue
        try:
            raw = p.read_bytes()
        except OSError:
            continue
        if BINARY_HINT in raw[:8192]:  # binario: niente scansione testuale
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue

        for label, pattern in SECRET_PATTERNS:
            for m in pattern.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                # Riporta la POSIZIONE, mai il valore: questo output finisce in un log pubblico.
                problems.append(
                    f"  [R2] {path}:{line}\n"
                    f"       → sembra {label} (valore non stampato di proposito).\n"
                    f"       → se è un segnaposto per la doc, rendilo evidente (`tskey-auth-...`);\n"
                    f"         se è vero: NON basta toglierlo — quel segreto va considerato bruciato\n"
                    f"         e va RUOTATO. La storia di git non dimentica."
                )
                break  # un rilievo per file/pattern basta a bocciare la build

    if problems:
        print("✗ gate anti-leak: trovata roba che online non ci può stare\n")
        print("\n".join(problems))
        print(
            "\nPerché la build è rossa: quello che finisce in un repo pubblico è pubblico\n"
            "da subito, e rimuoverlo dopo non lo disfa — resta nella storia, nei diff delle\n"
            "PR e in ogni clone. Il momento per fermarlo è adesso, non al prossimo audit."
        )
        return 1

    print("✓ gate anti-leak: nessun export di sessione tracciato, nessun materiale credenziale.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
