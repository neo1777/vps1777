"""Ogni `uses:` dei workflow è pinnato a un SHA di commit — o il test lo nomina.

🔓 Voce `a80025f1` (abdd732a): «40 affermazioni-garanzia in prosa nei doc di
   sicurezza NON citano un id di findings.yml». Questa è una di quelle, ed è
   `SECURITY.md:213-217`:

     «**GitHub Actions pinnate a SHA** (v0.27.0). Ogni action è pinnata al commit
      SHA (non al tag mobile): un tag ripuntato a monte non può iniettare codice.»

   Verificata il 10/08 su `origin/main`: **16 `uses:` su 16 pinnati a SHA(40)**.
   La garanzia REGGE — e proprio per questo merita un presidio invece di una frase:
   *una promessa vera e non presidiata è una promessa che nessuno saprà quando
   smette di esserlo.*

⚠️ PERCHÉ UN TEST E NON UN `contains:` IN `findings.yml`. Il gate delle evidenze
   cerca STRINGHE dentro i file. Qui non funziona per costruzione:
     · gli SHA cambiano a ogni bump di Dependabot ⇒ una stringa fissa marcirebbe
       in poche settimane, e marcirebbe **in silenzio** (evidence mancante = rosso
       su una garanzia che invece regge: un falso allarme che insegna a ignorare);
     · e soprattutto: un `contains` prova che UNA riga è pinnata, non che lo siano
       TUTTE. La garanzia è universale, l'evidenza sarebbe esistenziale.
   ⇒ *quando una promessa dice «ogni», l'evidenza non può essere un esempio.*
   Il test qui invece **enumera** e chiede la relazione, come
   `test_dependabot_copre_i_servizi.py`: «esiste un `uses:` che nessuno SHA copre?».

🔑 E il difetto che questo test PREVIENE non è teorico: basta che un domani una
   di noi aggiunga `uses: qualcuno/azione@v4` — la forma che ogni README del
   mondo suggerisce — e la garanzia di SECURITY.md diventa falsa senza che nessun
   file cambi il proprio testo.

STDLIB-ONLY: `tools/tests/` gira con `uvx pytest tools/tests/` (ci.yml), che non
ha PyYAML. Niente import di terze parti, e niente `importorskip` — uno skip qui
si leggerebbe come un pass.
"""
from __future__ import annotations

import re
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]
WORKFLOWS = RADICE / ".github" / "workflows"

# `uses:` con valore, ignorando i commenti in coda (`@sha  # v4.2.2` è la forma
# che Dependabot scrive, ed è quella giusta: il commento dice a un umano quale
# tag era, lo SHA dice alla macchina cosa eseguire).
USES = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)")
SHA40 = re.compile(r"@[0-9a-f]{40}$")


def _riferimenti():
    """(file, riga, valore) di ogni `uses:` nei workflow."""
    fuori = []
    for wf in sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml")):
        for n, riga in enumerate(wf.read_text(encoding="utf-8").splitlines(), 1):
            m = USES.match(riga)
            if m:
                fuori.append((wf.name, n, m.group(1)))
    return fuori


def _va_pinnato(valore: str) -> bool:
    """Le action LOCALI (`./…`) e quelle per digest docker non hanno un SHA di
    commit da citare: escluderle è corretto, ma va detto qui e non nel silenzio
    di una regex più stretta — se un domani ne comparisse una, chi legge questo
    test deve poter decidere, non scoprire che era già esclusa."""
    return not (valore.startswith("./") or valore.startswith("docker://"))


def test_ci_sono_workflow_da_controllare():
    """La guardia della guardia: se i workflow sparissero o cambiassero cartella,
    il test sotto passerebbe su una lista VUOTA — verde per assenza di bersaglio,
    che è il modo più comune in cui un presidio smette di proteggere."""
    rif = _riferimenti()
    assert WORKFLOWS.is_dir(), f"cartella dei workflow assente: {WORKFLOWS}"
    assert len(rif) >= 10, (
        f"solo {len(rif)} `uses:` trovati in {WORKFLOWS}: erano 16 il 10/08/2026. "
        "Se i workflow si sono spostati, questo test sta guardando nel vuoto."
    )


def test_ogni_uses_e_pinnato_a_uno_sha_di_commit():
    """SECURITY.md: «Ogni action è pinnata al commit SHA (non al tag mobile)»."""
    non_pinnati = [
        f"{f}:{n}  uses: {v}"
        for f, n, v in _riferimenti()
        if _va_pinnato(v) and not SHA40.search(v)
    ]
    assert not non_pinnati, (
        "SECURITY.md dichiara «Ogni action è pinnata al commit SHA (non al tag "
        "mobile): un tag ripuntato a monte non può iniettare codice».\n"
        "Questi `uses:` non lo sono — o si pinnano, o la frase in SECURITY.md va "
        "corretta (le due cose insieme, mai una sola):\n  "
        + "\n  ".join(non_pinnati)
    )
