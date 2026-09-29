"""`tools/check.sh` ripete i job `lint` e `contract` della CI: questo test gli impedisce di restare indietro.

PERCHÉ ESISTE. `check.sh` è una COPIA, e una copia scritta a mano invecchia in silenzio:
il giorno in cui `ci.yml` aggiunge un guardiano o una suite, il comando locale continua a
dire «tutto verde» e il rosso arriva dopo il push. È la forma che `ci.yml` racconta tre
volte per il perimetro di shellcheck — «un elenco scritto a mano invecchia, e chi lo
allarga guarda ciò che aggiunge, non ciò che manca».

⇒ Qui si legge la fonte di verità (i workflow) e si pretende che `check.sh` nomini:
  • ogni script di `security/` o `tools/` che i job `lint` e `contract` eseguono, e il job
    di `verify-features.yml`;
  • accanto all'autoprova, se la CI la lancia;
  • ogni suite pytest, con la sua cartella di lavoro e i suoi `--with`;
  • i due pin (la versione di ruff, il digest di shellcheck);
  • ogni `docker compose … config` e il `uv lock --check`.

⚠️ SOLO LE RIGHE DI CODICE CONTANO, da entrambe le parti: un commento che nomina uno script
non lo esegue. È la lezione di `test_ogni_presidio_ha_il_gancio_pytest.py`, che misurava la
prosa al posto del programma dentro il presidio che doveva accorgersene.

Ciò che la CI esegue e `check.sh` NON ripete sta in `ECCEZIONI`, con il perché nel dato.

Stdlib-only: la CI esegue `tools/tests/` con `uvx pytest`, senza PyYAML. I workflow si
leggono per righe, non con un parser YAML: basta a questa domanda, e il test lo verifica
(i job devono esistere e avere step, o fallisce invece di misurare un insieme vuoto).
"""
from __future__ import annotations

import re
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]
WORKFLOW = RADICE / ".github" / "workflows"
CHECK = RADICE / "tools" / "check.sh"

# Quali job di quale workflow `check.sh` promette di ripetere.
PERIMETRO = {
    "ci.yml": ("lint", "contract"),
    "verify-features.yml": ("verify-features",),
}

# Composto e non scritto: vedi 🪦 in `test_ogni_autoprova_e_agganciata.py`.
FLAG = "--auto" + "prova"

ECCEZIONI = {
    "tools/lock-salti.py": (
        "gira solo su una pull_request e chiede che la PR NOMINI pacchetto e versione "
        "di ogni salto di regime nei lock: in locale il corpo della PR non esiste, e un "
        "verde senza ratifica sarebbe un verde che non ha guardato."
    ),
}

_SCRIPT = re.compile(r"(?<![\w./-])((?:security|tools)/[\w./-]+\.(?:py|sh))")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def passi(workflow: Path, job_voluti: tuple[str, ...]) -> list[dict]:
    """Gli step dei job voluti: {job, wd, codice}. `codice` = le righe del `run:` che
    non sono commenti. Letto per righe: i job sono le chiavi a due spazi sotto `jobs:`."""
    righe = workflow.read_text(encoding="utf-8").splitlines()
    dentro_jobs, job, step, out = False, None, None, []
    i = 0
    while i < len(righe):
        r = righe[i]
        if re.match(r"^\S", r):
            dentro_jobs, job = r.rstrip() == "jobs:", None
        elif dentro_jobs and (m := re.match(r"^  ([\w-]+):\s*$", r)):
            job, step = m.group(1), None
        elif job in job_voluti:
            if re.match(r"^\s*-\s", r):
                step = {"job": job, "wd": None, "codice": []}
                out.append(step)
            if step is not None and (m := re.match(r"^\s*(?:-\s+)?working-directory:\s*(\S+)", r)):
                step["wd"] = m.group(1).strip("'\"")
            if step is not None and (m := re.match(r"^(\s*)(?:-\s+)?run:\s*(.*)$", r)):
                rientro, resto = len(m.group(1)), m.group(2).strip()
                if resto in ("|", ">", "|-", ">-", "|+", ">+"):
                    i += 1
                    while i < len(righe) and (not righe[i].strip()
                                              or len(righe[i]) - len(righe[i].lstrip()) > rientro):
                        step["codice"].append(righe[i].strip())
                        i += 1
                    step["codice"] = [c for c in step["codice"] if c and not c.startswith("#")]
                    continue
                step["codice"] = [resto]
        i += 1
    return out


def righe_logiche(testo: str) -> list[str]:
    """Le righe di codice di uno script bash: via i commenti, unite le continuazioni `\\`."""
    out, corrente = [], ""
    for r in testo.splitlines():
        nuda = r.strip()
        if not corrente and (not nuda or nuda.startswith("#")):
            continue
        if nuda.endswith("\\"):
            corrente += nuda[:-1] + " "
            continue
        out.append(corrente + nuda)
        corrente = ""
    if corrente:
        out.append(corrente)
    return out


def _codice_ci() -> list[dict]:
    tutti = []
    for nome, job in PERIMETRO.items():
        tutti += passi(WORKFLOW / nome, job)
    return tutti


def mancanze(ci: list[dict], check: list[str]) -> list[str]:
    """Ciò che la CI esegue e `check.sh` non nomina. Vuota = check.sh è al passo."""
    corpo = "\n".join(check)
    buchi = []

    def c_e(*pezzi: str) -> bool:
        return any(all(p in riga for p in pezzi) for riga in check)

    for step in ci:
        for riga in step["codice"]:
            # ① gli script di guardia, e l'autoprova accanto se la CI la lancia
            for s in _SCRIPT.findall(riga):
                if s in ECCEZIONI or s.startswith("tools/tests/"):
                    continue
                if not c_e(s):
                    buchi.append(f"script «{s}» (job {step['job']}) assente da check.sh")
                elif FLAG in riga and not any(s in r and ("$AUTOPROVA" in r or FLAG in r)
                                               for r in check):
                    buchi.append(f"«{s}»: la CI ne lancia l'autoprova, check.sh no")
            # ② le suite pytest: cartella di lavoro, bersagli e dipendenze sulla STESSA riga
            if re.search(r"\bpytest\b", riga):
                # i bersagli stanno dopo l'ULTIMO «pytest» (`--with pytest pytest tests/`)
                dopo = riga[riga.rindex("pytest") + len("pytest"):]
                bersagli = [t for t in dopo.split() if not t.startswith("-") and "/" in t]
                con = re.findall(r"--with\s+(\S+)", riga)
                if con == ["pytest"]:
                    con = []
                pezzi = [*bersagli, *con] + ([step["wd"]] if step["wd"] else [])
                if bersagli and not c_e(*pezzi):
                    buchi.append(f"suite pytest {pezzi} (job {step['job']}) assente da check.sh")
            # ③ comandi di guardia che non sono script
            if riga.startswith("docker compose") and " ".join(riga.split()) not in corpo:
                buchi.append(f"«{riga}» assente da check.sh")
            if "uv lock --check" in riga and "uv lock --check" not in corpo:
                buchi.append("«uv lock --check» (i lock concordano col pyproject) assente da check.sh")
            if "migrations/*/run.py" in riga and "migrations/*/run.py" not in corpo:
                buchi.append("l'immutabilità delle migrazioni (job lint) assente da check.sh")
            # ④ i pin: stessa versione di ruff, stesso digest di shellcheck
            for v in re.findall(r"ruff==([\d.]+)", riga):
                if not any(v in r and "ruff" in r.lower() for r in check):
                    buchi.append(f"ruff {v} (pin di ci.yml) non è la versione di check.sh")
            for d in _DIGEST.findall(riga):
                if d not in corpo:
                    buchi.append(f"shellcheck {d[:19]}… (digest di ci.yml) non è quello di check.sh")
    return buchi


# ── il test vero ──────────────────────────────────────────────────────────────

def test_check_sh_ripete_ogni_guardiano_e_ogni_suite_della_ci() -> None:
    ci = _codice_ci()
    trovati = {s["job"] for s in ci if s["codice"]}
    attesi = {j for job in PERIMETRO.values() for j in job}
    assert trovati == attesi, (
        f"step con codice trovati nei job {sorted(trovati)}, attesi {sorted(attesi)}: "
        "o i workflow sono cambiati forma, o questa lettura per righe non li vede più. "
        "Uno zero non è un verde."
    )
    buchi = mancanze(ci, righe_logiche(CHECK.read_text(encoding="utf-8")))
    assert not buchi, (
        "tools/check.sh è rimasto INDIETRO rispetto alla CI:\n  " + "\n  ".join(buchi)
        + "\nAggiungi il controllo a check.sh (è la copia locale di lint e contract), "
          "oppure — se in locale non ha senso — mettilo in ECCEZIONI con il perché."
    )


def test_ogni_eccezione_e_ancora_nella_ci_e_ha_il_suo_perche() -> None:
    """Un'eccezione per uno script che la CI non esegue più non esenta niente: è una voce
    morta, e chi la legge crede che quel controllo esista ancora da qualche parte."""
    eseguiti = {s for step in _codice_ci() for r in step["codice"] for s in _SCRIPT.findall(r)}
    for script, perche in ECCEZIONI.items():
        assert script in eseguiti, f"ECCEZIONI[{script!r}]: la CI non lo esegue più, togli la voce"
        assert len(perche.strip()) >= 40, f"ECCEZIONI[{script!r}]: il perché è troppo corto"


def test_la_sonda_sa_dire_di_no() -> None:
    """Sui passi VERI della CI e su un check.sh a cui manca una riga: deve accorgersene.

    Il caso di controllo è il check.sh vero (zero buchi, verificato sopra); qui gli si
    toglie una riga per volta fra quelle che la sonda deve vedere, e un commento che
    nomina lo script NON deve bastare a coprirlo.
    """
    ci = _codice_ci()
    vero = righe_logiche(CHECK.read_text(encoding="utf-8"))
    for ago in ("security/check_no_leaks.py", "tools/tests/", "services/nb1777-mcp",
                "tools/verify-features.py", "uv lock --check", "compose.build.yaml",
                "migrations/*/run.py"):
        tolto = [r for r in vero if ago not in r]
        assert len(tolto) < len(vero), f"«{ago}» non è in check.sh: il caso di prova non regge"
        assert mancanze(ci, tolto), f"tolta la riga con «{ago}», la sonda dice ancora verde"
        # la stessa riga ridotta a commento: la prosa non esegue niente
        commentato = righe_logiche("\n".join(tolto) + f"\n# qui una volta c'era {ago}\n")
        assert mancanze(ci, commentato), f"«{ago}» in un COMMENTO è stato preso per coperto"
    # l'autoprova tolta, lo script lasciato: dev'essere un buco a sé
    senza_ap = [r.replace("$AUTOPROVA", "") if "doc-riferimenti" in r else r for r in vero]
    assert any("autoprova" in b and "doc-riferimenti" in b for b in mancanze(ci, senza_ap))
    # un pin diverso da quello della CI
    altro_ruff = [r.replace("0.15.", "0.99.") for r in vero]
    assert any("ruff" in b for b in mancanze(ci, altro_ruff))


def test_la_lettura_dei_workflow_vede_le_forme_che_usano(tmp_path: Path) -> None:
    """Le due forme di `run:` (riga singola e blocco), la working-directory, e i commenti
    dentro il blocco che NON diventano codice."""
    finto = tmp_path / "finto.yml"
    testo = (
        "on:\n  push:\n    branches: [main]\n"
        "jobs:\n"
        "  lint:\n    runs-on: x\n    steps:\n"
        "      - uses: actions/checkout@abc\n"
        "      - name: uno\n        run: python3 security/uno.py\n"
        "      - name: due\n        working-directory: services/x\n        run: |\n"
        "          # python3 tools/solo-nel-commento.py\n"
        "          uv run pytest tests/ -v\n"
        "  altro:\n    steps:\n      - run: python3 tools/fuori.py\n"
    )
    finto.write_text(testo, encoding="utf-8")
    p = passi(finto, ("lint",))
    codice = [r for s in p for r in s["codice"]]
    assert "python3 security/uno.py" in codice
    assert "uv run pytest tests/ -v" in codice
    assert not any("solo-nel-commento" in r for r in codice), "un commento è diventato codice"
    assert not any("fuori.py" in r for r in codice), "uno step di un altro job è entrato"
    assert any(s["wd"] == "services/x" for s in p)
