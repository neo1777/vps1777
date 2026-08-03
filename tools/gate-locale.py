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

USO    python3 tools/gate-locale.py                 → TUTTI i job del workflow
       python3 tools/gate-locale.py --job lint      → un job solo
       python3 tools/gate-locale.py --elenco        → dice cosa farebbe, senza fare
       python3 tools/gate-locale.py --solo Shell    → i soli step il cui nome contiene…
       python3 tools/gate-locale.py --autoprova     → prova che sa dire di no

📌 Il default è TUTTI i job perché la prima stesura girava il solo `lint` e dava un
   verde su un job su tre senza nominare gli altri — e `contract` era proprio quello
   che quel giorno aveva bocciato due PR. Un job che qui non si può eseguire (oggi
   `build`: solo `uses:` e una `strategy.matrix`) esce come ⚪ **non misurabile** e
   viene detto in coda, non lasciato annegare nel verde degli altri.
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
    """(da_eseguire, saltati) — da_eseguire è (nome, corpo, working_directory, nota).

    ⚠️ `working-directory` NON è un dettaglio: due step di `contract` girano in
       `services/nb1777-mcp`, e senza onorarlo `uv run pytest tests/` cercherebbe
       `tests/` nella radice e darebbe un rosso che la CI non dà. *Riprodurre il
       comando senza il CONTESTO in cui gira è la stessa classe di difetto che
       questo file esiste per chiudere, un livello più in basso.*
    📌 `if:` invece non lo VALUTO — non c'è un evento GitHub qui. Lo step si esegue
       comunque e la condizione viene stampata accanto: «gira anche quando in CI
       forse no» è un dato che chi legge deve avere, non una cosa da tacere.
    """
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
        elif (guasto := _guasta_il_repo(st["run"])):
            saltati.append((nome, f"{SALTA_REPO}: `{guasto}`"))
        else:
            nota = f"`if: {st['if']}` — non valutata qui, lo step gira comunque" if "if" in st else ""
            esegui.append((nome, st["run"], st.get("working-directory"), nota))
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

# ── E POI C'È CIÒ CHE NON BASTA SEGNALARE. ────────────────────────────────────────────
#
# 🔴 SUCCESSO DAVVERO, il 03/08: `ci.yml` ha uno step «Migrations immutability» che fa
#    `git fetch origin main --depth=1`. In CI è giusto — il runner clona per un giro
#    solo. In LOCALE quel comando scrive `.git/shallow` e **tronca la storia del repo
#    di lavoro**: `origin/main` è passato a 2 commit visibili su 380 veri. Per tre ore
#    `merge-base`, `--is-ancestor` e `rev-list --count` hanno risposto a tutte e tre
#    in modo plausibile e sbagliato — «branch non mergiato, ahead 138» su una storia
#    che non c'era. Nessun errore, nessun avviso: **il danno è silenzioso e sopravvive
#    al processo che l'ha fatto.**
#
# ⚠️ PERCHÉ NON BASTA UNA `SPIA`. Le SPIE stampano «tocca l'ambiente» e lo step gira
#    lo stesso: è la scala giusta per `apt-get` (rumoroso, reversibile, e chi legge
#    decide). Qui no — quando l'avviso si legge, il `.git/shallow` è già scritto.
#    *Un guardiano che parla si elude; su un danno irreversibile serve quello che
#    blocca.* ⇒ questi step **non si eseguono**, e il motivo viene dichiarato.
#
# 📌 PERCHÉ NON RISCRIVO IL COMANDO (togliere `--depth=1` e lanciarlo). Sarebbe la
#    cura peggiore: questo file esiste per **leggere** gli step invece di riscriverli,
#    e uno step riscritto non prova più ciò che la CI esegue. Meglio un buco
#    dichiarato che una copia che si spaccia per l'originale.
#
# ⚠️ LIMITE, scritto perché non lo si scopra dopo: è un match sul TESTO del comando.
#    Un `--depth` costruito a runtime (`git fetch $FLAGS`) non lo vedo. Non è un caso
#    ipotetico che copro a metà: è un caso che **dichiaro di non coprire**.
GUASTA_IL_REPO = (
    # tronca la storia: silenzioso, e falsa ogni sonda su merge-base/ancestry
    re.compile(r"\bgit\s+(?:fetch|clone|pull)\b[^\n]*--(?:depth|shallow-since|shallow-exclude)\b"),
    # cambiano il HEAD sotto i piedi di chi sta lavorando nella working tree
    re.compile(r"\bgit\s+(?:checkout|switch)\s+(?!-{1,2}(?:help|version)\b)[^\n]*"),
    re.compile(r"\bgit\s+reset\s+[^\n]*--hard\b"),
    # cancella file non tracciati: il lavoro in corso di un'altra sessione
    re.compile(r"\bgit\s+clean\b[^\n]*-[a-z]*[fd]"),
)
SALTA_REPO = "modifica il REPO DI LAVORO in modo non reversibile"


def _guasta_il_repo(corpo: str) -> str | None:
    """La prima riga di codice che romperebbe il repo locale, o None.

    Solo il CODICE: una riga di commento che nomina `--depth` per spiegare perché
    non si usa non deve far saltare lo step. È lo stesso criterio di `_effetti`, e
    la ragione è la stessa per cui `\\binstall\\b` non è la sottostringa «install».
    """
    for riga in corpo.splitlines():
        r = riga.strip()
        if not r or r.startswith("#"):
            continue
        for spia in GUASTA_IL_REPO:
            if spia.search(r):
                return r[:72]
    return None


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
    for nome, corpo, wd, nota in esegui:
        print(f"  • {nome}{f'   [in {wd}]' if wd else ''}")
        if nota:
            print(f"      ⚪ {nota}")
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
    for nome, corpo, wd, nota in esegui:
        dove = (radice / wd) if wd else radice
        print(f"\n─── {nome}{f'   [in {wd}]' if wd else ''}")
        if nota:
            print(f"     ⚪ {nota}")
        if not dove.is_dir():
            falliti += 1
            print(f"  🔴 working-directory inesistente: {dove}")
            continue
        p = subprocess.run(  # noqa: S602 — il corpo viene dal workflow del repo, non da input
            ["bash", "-eo", "pipefail", "-c", corpo],
            cwd=dove, text=True, capture_output=True, check=False,
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
            # Lo step distruttivo NON deve girare. La prova sta nell'esito 2
            # («nulla da eseguire»), non in un messaggio: se girasse, `exit 1`
            # darebbe 1 — cioè l'autoprova saprebbe distinguere «saltato» da
            # «eseguito e fallito», che è l'unica cosa che conta qui.
            r_depth = prova([{"name": "shallow",
                              "run": "git fetch origin main --depth=1\nexit 1"}])
        testo = buf.getvalue()

        segna("uno step verde", 0, r_verde)
        segna("uno step rosso", 1, r_rosso)
        segna("zero step (non è un verde)", 2, r_vuoto)
        segna("solo `uses:` → nulla da eseguire", 2, r_uses)
        segna("solo `${{ }}` → nulla da eseguire", 2, r_expr)
        segna("rosso seguito da verde (il verde non copre)", 1, r_dopo)
        # 2 = «nulla da eseguire», cioè SALTATO. Se lo step girasse, l'`exit 1`
        # che gli sta accanto darebbe 1: il caso sa distinguere «non eseguito»
        # da «eseguito e andato male», che senza l'`exit 1` sarebbero identici.
        segna("`--depth` non viene ESEGUITO", 2, r_depth)
        distrut = "modifica il REPO" in testo and "--depth=1" in testo
        print(f"  {'✅' if distrut else '🔴'} {'dice PERCHÉ e QUALE riga':<44} → {distrut} (atteso True)")
        ok = ok or (0 if distrut else 1)

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

        # Le righe distruttive, con le CONTROPROVE DI POLARITÀ accanto: senza il
        # caso che deve TACERE, una regex che scatta su tutto passerebbe l'esame.
        # I due `git fetch` differiscono per il solo `--depth`: è la coppia minima.
        for riga, atteso, perche in (
            ("git fetch origin main --depth=1", True, "il caso VERO di ci.yml"),
            ("git fetch origin main", False, "lo stesso comando SENZA --depth"),
            ("git fetch --unshallow origin", False, "RIPARA la storia, non la rompe"),
            ("git checkout -b prova origin/main", True, "sposta il HEAD"),
            ("git checkout --version", False, "interroga, non tocca"),
            ("git reset --hard origin/main", True, "butta il lavoro locale"),
            ("git reset HEAD~1", False, "soft: non tocca la working tree"),
            ("git clean -fd", True, "cancella i file non tracciati"),
            ("git status --porcelain", False, "sola lettura"),
            ("# git fetch --depth=1  ← perché NON lo facciamo", False,
             "COMMENTO che nomina il comando"),
        ):
            ott = _guasta_il_repo(riga) is not None
            buono = ott == atteso
            print(f"  {'✅' if buono else '🔴'} repo «{perche}»{'':<{max(0, 30 - len(perche))}} → "
                  f"{'salta' if ott else 'lascia'} (atteso {'salta' if atteso else 'lascia'})")
            if not buono:
                ok = 1

    # ── E i casi MULTI-JOB, che sono la cura del rilievo di b82df434 ──────────
    # Il verde di un job non deve coprire un job che qui non si può eseguire: senza
    # questi tre casi, «tutti i job» sarebbe una promessa invece di una misura.
    with tempfile.TemporaryDirectory() as d:
        radice = Path(d)
        import contextlib
        import io

        def prova_job(jobs: dict, job: str | None = None) -> tuple[int, str]:
            wf = yaml.safe_load(yaml.safe_dump({"jobs": jobs}))
            b = io.StringIO()
            with contextlib.redirect_stdout(b):
                e = su_piu_job(wf, job, None, False, radice)
            return e, b.getvalue()

        e1, _ = prova_job({"a": {"steps": [{"name": "v", "run": "true"}]},
                           "b": {"steps": [{"name": "r", "run": "exit 1"}]}})
        segna("due job, uno rosso", 1, e1)

        e2, t2 = prova_job({"a": {"steps": [{"name": "v", "run": "true"}]},
                            "b": {"steps": [{"name": "u", "uses": "actions/checkout@v4"}]}})
        segna("un job verde + uno NON misurabile", 0, e2)
        avvisa = "NON sono misurabili qui" in t2 and "b" in t2
        print(f"  {'✅' if avvisa else '🔴'} {'…e lo dice invece di annegarlo nel verde':<44} → "
              f"{avvisa} (atteso True)")
        if not avvisa:
            ok = 1

        e3, _ = prova_job({"a": {"steps": [{"name": "u", "uses": "actions/checkout@v4"}]},
                           "b": {"steps": []}})
        segna("tutti i job non misurabili", 2, e3)

        e4, _ = prova_job({"a": {"steps": [{"name": "v", "run": "true"}]}}, job="assente")
        segna("--job su un nome che non esiste", 2, e4)

        # working-directory: senza onorarlo, due step di `contract` girerebbero nella
        # radice e darebbero un rosso che la CI non dà. Il caso vero, non simulato:
        # il comando riesce SOLO se il cwd è quello giusto.
        (radice / "sotto").mkdir()
        (radice / "sotto" / "segno.txt").write_text("x", encoding="utf-8")
        e5, _ = prova_job({"a": {"steps": [
            {"name": "wd", "run": "test -f segno.txt", "working-directory": "sotto"}]}})
        segna("working-directory onorato", 0, e5)
        e6, _ = prova_job({"a": {"steps": [{"name": "wd", "run": "test -f segno.txt"}]}})
        segna("…e senza, lo stesso comando FALLISCE", 1, e6)
        e7, _ = prova_job({"a": {"steps": [
            {"name": "wd", "run": "true", "working-directory": "non-esiste"}]}})
        segna("working-directory inesistente → rosso", 1, e7)

        # `if:` non si valuta, ma lo step deve girare E la condizione va detta.
        e8, t8 = prova_job({"a": {"steps": [
            {"name": "cond", "run": "true", "if": "github.event_name == 'pull_request'"}]}})
        segna("step con `if:` gira comunque", 0, e8)
        dice_if = "if:" in t8 and "non valutata" in t8
        print(f"  {'✅' if dice_if else '🔴'} {'…e la condizione viene DICHIARATA':<44} → "
              f"{dice_if} (atteso True)")
        if not dice_if:
            ok = 1

    print("\n✅ il gate sa fallire." if ok == 0
          else "\n🔴 AUTOPROVA FALLITA — il gate non è affidabile.")
    return ok


def tutti_i_job(wf: object) -> list[str]:
    return list(wf.get("jobs", {}).keys()) if isinstance(wf, dict) else []


def su_piu_job(wf: object, job: str | None, solo: str | None,
               elenco: bool, radice: Path) -> int:
    """Il DEFAULT è ogni job del workflow, e i job non misurabili si DICHIARANO.

    🔴 Nasce da un rilievo di `b82df434` sulla prima stesura: il default era il solo
       `lint`, e chi lanciava senza argomenti leggeva «8 step · 0 falliti · verde»
       su UN JOB SU TRE, senza che l'output nominasse gli altri due. E `contract` è
       il job che quel giorno aveva bocciato due PR — cioè il gate avrebbe detto sì
       proprio nel caso per cui esiste.
    🔑 *È la regola di questo file applicata un piano sopra: la dichiaravo per gli
       STEP saltati e non per i JOB non eseguiti.* Il danno non era non eseguirli:
       era **credere di averli eseguiti**.
    """
    nomi = [job] if job else tutti_i_job(wf)
    if not nomi:
        print("⚪ NON MISURATO — il workflow non dichiara nessun job.")
        return 2

    esiti: dict[str, int] = {}
    for n in nomi:
        esegui, saltati = raccogli(wf, n, solo)
        print(f"\n{'=' * 4} job «{n}» {'=' * 4}")
        esiti[n] = elenca(esegui, saltati) if elenco else esegui_step(esegui, saltati, radice)

    if len(nomi) > 1 or job:
        print("\n── riepilogo ──")
        for n, e in esiti.items():
            faccia = {0: "✅ passato", 1: "🔴 FALLITO", 2: "⚪ non misurabile qui"}[e]
            print(f"  {n:<12} {faccia}")

    # Un job non misurabile in locale NON deve annegare in un verde complessivo: se
    # ce n'è anche uno solo, il verde va detto per quello che è.
    non_misurati = [n for n, e in esiti.items() if e == 2]
    if non_misurati and not any(e == 1 for e in esiti.values()):
        print(f"\n⚠️ ATTENZIONE: {len(non_misurati)} job su {len(nomi)} NON sono misurabili qui "
              f"({', '.join(non_misurati)}).")
        print("   Il verde qui sopra vale per gli altri. Chi li salta lo sappia.")

    if any(e == 1 for e in esiti.values()):
        return 1
    if all(e == 2 for e in esiti.values()):
        return 2
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--job", default=None,
                    help="un solo job (default: TUTTI quelli del workflow)")
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

    return su_piu_job(wf, a.job, a.solo, a.elenco, RADICE)


if __name__ == "__main__":
    sys.exit(main())
