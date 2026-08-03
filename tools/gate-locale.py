#!/usr/bin/env python3
"""ESEGUE IN LOCALE GLI STEP DELLA CI **LEGGENDOLI DAL WORKFLOW**, non riscrivendoli.

🔓 PERCHÉ ESISTE — un difetto misurato DUE VOLTE su di me, a un giorno di distanza:

      02/08   in locale `shellcheck -S warning` → verde · la CI senza soglia → ROSSA
      03/08   identico, e stavolta il flag non l'avevo nemmeno scelto io:
              l'avevo copiato dalla controprova di un altro test che lo dichiarava

   ⚠️ E fra le due c'era già la lezione scritta, con la coordinata (`ci.yml`, la riga
   che dice «SOGLIA AL MINIMO» con la sua ragione) e il rimedio in chiaro: *«copia il
   comando dalla sua definizione, non ricostruirlo»*. **Non ha impedito la seconda.**
   🔑 *Una riga scritta parla del passato: si legge quando si rilegge il documento, non
   quando la mano digita il flag.* ⇒ questo file non aggiunge una regola: toglie la
   scelta. Il comando non lo ricostruisci — lo esegui com'è scritto nel workflow.

   ⭐ E ciò che la mia soglia nascondeva non era cosmetico: `SC2030/SC2031` su un `ok=1`
   dentro `$( )`, cioè un esito che viveva in una subshell e si perdeva. Il ramo
   stampava 🔴 e la funzione tornava 0.

⚠️ COSA NON FA, dichiarato perché nessuno lo scopra come se fosse un bug:
   • gli step `uses:` (checkout, setup-python, setup-uv) NON si eseguono — li elenca
     come saltati, con il motivo. *Un gate che tace ciò che non ha guardato è peggio
     di uno che non c'è: il suo verde copre più di quanto ha visto.*
   • uno step con `${{ … }}` non è riproducibile fedelmente ⇒ saltato e dichiarato.
   • **alcuni step hanno effetti sull'ambiente locale** (lo step ruff fa
     `uv tool install`): `--elenco` li mostra PRIMA di eseguirli.
   • l'ambiente non è il runner: una differenza di versione la vedi qui solo se lo
     step la pinna da sé — ed è il motivo per cui `ci.yml` pinna tutto.

ESITO  0 = tutti gli step eseguiti sono passati
       1 = almeno uno FALLITO
       2 = non misurabile (workflow illeggibile, job assente, pyyaml mancante,
           ZERO step eseguibili). *Uno zero di step non è un verde.*

USO    python3 tools/gate-locale.py                 → esegue il job `lint`
       python3 tools/gate-locale.py --elenco        → dice cosa farebbe, senza fare
       python3 tools/gate-locale.py --job contract  → un altro job
       python3 tools/gate-locale.py --solo Shell    → i soli step il cui nome contiene…
       python3 tools/gate-locale.py --autoprova     → prova che sa dire di no
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
WORKFLOW = RADICE / ".github" / "workflows" / "ci.yml"

# Un `uses:` è un'azione di GitHub: qui non c'è il runner che la esegue. Elencarla
# come saltata è l'unica risposta onesta — «non l'ho guardata» non deve somigliare a
# «l'ho guardata e va bene».
SALTA_USES = "step `uses:` — azione GitHub, qui non c'è il runner"
SALTA_EXPR = "contiene ${{ … }}: non riproducibile fedelmente in locale"


def carica(percorso: Path) -> tuple[int, object, str]:
    """(esito, workflow, messaggio). esito 2 = non misurabile."""
    try:
        import yaml
    except ImportError:
        return 2, None, (
            "⚪ NON MISURATO — manca `pyyaml`. Non è un verde: non ho letto il workflow.\n"
            "   uv run --with pyyaml python3 tools/gate-locale.py"
        )
    if not percorso.is_file():
        return 2, None, f"⚪ NON MISURATO — workflow assente: {percorso}"
    try:
        return 0, yaml.safe_load(percorso.read_text(encoding="utf-8")), ""
    except Exception as e:  # noqa: BLE001 — qualunque errore di parsing è «non misurato»
        return 2, None, f"⚪ NON MISURATO — workflow illeggibile: {e}"


def raccogli(wf: object, job: str, solo: str | None) -> tuple[list, list]:
    """(da_eseguire, saltati) — ogni voce è (nome, corpo_o_motivo)."""
    jobs = wf.get("jobs", {}) if isinstance(wf, dict) else {}
    if job not in jobs:
        return [], [("(job assente)", f"il workflow non ha un job «{job}»")]
    esegui, saltati = [], []
    for i, st in enumerate(jobs[job].get("steps", []) or [], 1):
        nome = st.get("name") or f"step {i}"
        if solo and solo.lower() not in nome.lower():
            continue
        if "uses" in st:
            saltati.append((nome, SALTA_USES))
        elif "run" not in st:
            saltati.append((nome, "né `run:` né `uses:`"))
        elif "${{" in st["run"]:
            saltati.append((nome, SALTA_EXPR))
        else:
            esegui.append((nome, st["run"]))
    return esegui, saltati


# ⚠️ `\binstall\b` e non la sottostringa «install»: il primo giro segnava
#    `security/confronta-installer.py` come «tocca l'ambiente» — matchava *install*er,
#    cioè il NOME di un file. Un avviso che scatta su un nome è rumore, e il rumore
#    di un avviso è la strada per cui poi non lo si legge più.
#    L'autoprova porta il caso vero (`confronta-installer` NON deve scattare): una
#    polarità su una stringa inventata proverebbe che la regex gira, non che distingua.
SPIE = (
    re.compile(r"\binstall\b"),
    re.compile(r"\bdocker\s+(?:run|pull|build)\b"),
    re.compile(r"\b(?:apt-get|apk|brew)\b"),
)


def _effetti(corpo: str) -> list[str]:
    """Righe che toccano l'ambiente locale. Vanno viste PRIMA di lanciare."""
    return [
        r.strip()
        for r in corpo.splitlines()
        if r.strip() and not r.strip().startswith("#") and any(s.search(r) for s in SPIE)
    ]


def elenca(esegui: list, saltati: list) -> int:
    print(f"Da {WORKFLOW.relative_to(RADICE)}\n")
    print(f"ESEGUIREBBE ({len(esegui)})")
    for nome, corpo in esegui:
        print(f"  • {nome}")
        for r in _effetti(corpo):
            print(f"      ⚠️ tocca l'ambiente: {r[:96]}")
    print(f"\nSALTA ({len(saltati)}) — dichiarati, non taciuti")
    for nome, motivo in saltati:
        print(f"  ⚪ {nome}\n      {motivo}")
    if not esegui:
        print("\n⚪ NON MISURATO — zero step eseguibili. Uno zero non è un verde.")
        return 2
    return 0


def esegui_step(esegui: list, saltati: list, radice: Path) -> int:
    if not esegui:
        print("⚪ NON MISURATO — zero step eseguibili qui. Uno zero non è un verde.")
        for nome, motivo in saltati:
            print(f"   ⚪ {nome}: {motivo}")
        return 2

    falliti = 0
    for nome, corpo in esegui:
        print(f"\n─── {nome}")
        p = subprocess.run(  # noqa: S602 — il corpo viene dal workflow del repo, non da input
            ["bash", "-eo", "pipefail", "-c", corpo],
            cwd=radice, text=True, capture_output=True, check=False,
        )
        if p.returncode == 0:
            print(f"  ✅ exit 0{('  ' + p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else ''}")
        else:
            falliti += 1
            print(f"  🔴 exit {p.returncode}")
            for riga in (p.stdout + p.stderr).strip().splitlines()[-25:]:
                print(f"     {riga}")

    print(f"\n{len(esegui)} step eseguiti · {falliti} falliti")
    if saltati:
        print(f"⚪ {len(saltati)} saltati (non guardati): "
              + ", ".join(n for n, _ in saltati))
    return 1 if falliti else 0


def autoprova() -> int:
    """Il gate sa dire di no? Su un workflow finto, senza toccare quello vero."""
    import yaml  # già verificato dal chiamante

    ok = 0

    def segna(desc: str, atteso: int, ottenuto: int) -> None:
        nonlocal ok
        buono = atteso == ottenuto
        print(f"  {'✅' if buono else '🔴'} {desc:<44} → esito {ottenuto} (atteso {atteso})")
        if not buono:
            ok = 1

    print("AUTOPROVA — il gate sa dire di no?")
    with tempfile.TemporaryDirectory() as d:
        radice = Path(d)

        def prova(steps: list, solo: str | None = None) -> int:
            wf = {"jobs": {"lint": {"steps": steps}}}
            e, s = raccogli(yaml.safe_load(yaml.safe_dump(wf)), "lint", solo)
            return esegui_step(e, s, radice)

        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            r_verde = prova([{"name": "verde", "run": "true"}])
            r_rosso = prova([{"name": "verde", "run": "true"},
                             {"name": "rosso", "run": "echo guasto >&2; exit 3"}])
            r_vuoto = prova([])
            r_uses = prova([{"name": "solo-azione", "uses": "actions/checkout@v4"}])
            r_expr = prova([{"name": "con-espressione", "run": "echo ${{ github.sha }}"}])
            r_dopo = prova([{"name": "rosso", "run": "exit 1"},
                            {"name": "zzz-verde", "run": "true"}])
        testo = buf.getvalue()

        segna("uno step verde", 0, r_verde)
        segna("uno step rosso", 1, r_rosso)
        segna("zero step (non è un verde)", 2, r_vuoto)
        segna("solo `uses:` → nulla da eseguire", 2, r_uses)
        segna("solo `${{ }}` → nulla da eseguire", 2, r_expr)
        segna("rosso seguito da verde (il verde non copre)", 1, r_dopo)

        # Un gate che fallisce senza dire QUALE step non serve a chi guarda l'output,
        # e un `uses:` saltato in silenzio è un verde che copre più del dovuto.
        nomina = "rosso" in testo
        print(f"  {'✅' if nomina else '🔴'} {'nomina lo step fallito':<44} → {nomina} (atteso True)")
        ok = ok or (0 if nomina else 1)
        dichiara = "solo-azione" in testo and "uses" in testo
        print(f"  {'✅' if dichiara else '🔴'} {'dichiara ciò che ha saltato':<44} → {dichiara} (atteso True)")
        ok = ok or (0 if dichiara else 1)

        # La spia degli effetti sul CASO VERO, non su una stringa inventata: deve
        # distinguere il comando `install` dal NOME di un file che lo contiene.
        # È il caso che sbagliava al primo giro — «confronta-installer» segnato come
        # se toccasse l'ambiente.
        for riga, atteso, perche in (
            ("uv tool install ruff==0.15.22", True, "comando install"),
            ("python3 security/confronta-installer.py", False, "NOME di file, non comando"),
            ('docker run --rm -v "$PWD:/mnt" img', True, "docker run"),
            ("python3 security/check_no_leaks.py", False, "innocuo"),
        ):
            ott = bool(_effetti(riga))
            buono = ott == atteso
            print(f"  {'✅' if buono else '🔴'} spia «{perche}»{'':<{max(0, 30 - len(perche))}} → "
                  f"{'scatta' if ott else 'tace'} (atteso {'scatta' if atteso else 'tace'})")
            if not buono:
                ok = 1

    print("\n✅ il gate sa fallire." if ok == 0
          else "\n🔴 AUTOPROVA FALLITA — il gate non è affidabile.")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--job", default="lint")
    ap.add_argument("--solo", default=None, help="solo gli step il cui nome contiene questo")
    ap.add_argument("--elenco", action="store_true", help="dice cosa farebbe, senza farlo")
    ap.add_argument("--autoprova", action="store_true")
    a = ap.parse_args()

    esito, wf, msg = carica(WORKFLOW)
    if esito != 0:
        print(msg)
        return esito
    if a.autoprova:
        return autoprova()

    esegui, saltati = raccogli(wf, a.job, a.solo)
    return elenca(esegui, saltati) if a.elenco else esegui_step(esegui, saltati, RADICE)


if __name__ == "__main__":
    sys.exit(main())
