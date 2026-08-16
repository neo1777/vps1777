"""Un presidio che nessuno esegue non fallisce mai: ogni autoprova dev'essere in CI.

🔴 MISURATO, ed è già successo qui: `gate-locale.py` è nato con la sua autoprova e non
era agganciato a niente (rilievo di `71d540e6` sulla #93). È rimasto scollegato **cinque
giorni con la CI 7/7 verde** — e i sette verdi non lo vedevano, perché *un presidio che
nessuno esegue non fallisce mai*. Fu agganciato a mano, e a mano resta la garanzia: oggi
i quattro presìdi autoprovanti del repo sono in `ci.yml` perché qualcuno se n'è ricordato
quattro volte.

⭐ **Questo test toglie la garanzia dalla memoria e la mette in un comando.** È la stessa
forma già adottata in `ci.yml`: l'elenco degli script da passare a shellcheck era scritto
a mano e invecchiava in silenzio (tre volte — `tools/prove-empiriche/`, `tools/tests/`,
`deploy.sh`), finché non è diventato un glob da `git ls-files`. *Un elenco scritto a mano
invecchia; chi lo allarga guarda ciò che sta aggiungendo, non ciò che manca.*

🪦 **PERCHÉ QUESTO FILE NON SCRIVE MAI IL FLAG PER INTERO, ed è una cicatrice, non un
vezzo.** La prima stesura lo nominava una dozzina di volte — e sarebbe stata trovata dal
proprio gate come «presidio scoperto»: *la lapide scritta con le parole del morto*. Il
repo ha già pagato tre volte questa forma (un `grep` che trovava la citazione dentro il
commento che la descriveva). ⚠️ E la cura sbagliata sarebbe **aggiungersi all'elenco
delle eccezioni**: allargare un presidio per far passare una riga di documentazione.
*Parafrasare costa nulla e non tocca il presidio.*

⚠️ IL VERSO DELL'ERRORE, dichiarato: se un file **nomina** il flag senza implementarlo,
questo test lo segnala come scoperto. È rumore visibile, non un silenzio — e il verso
sicuro: *meglio un falso positivo che si vede che un presidio scollegato che nessuno
guarda.* Si chiude agganciandolo o parafrasando la citazione.

Stile stdlib-only: la CI esegue `tools/tests/` con `uvx pytest` senza dipendenze.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# composto, non scritto: vedi 🪦 nel docstring.
FLAG = "--auto" + "prova"


def _basename(s: str) -> str:
    """Il nome nudo: via le virgolette, via il path, via i prefissi di variabile.

    Confrontare i PATH sembrava più preciso ed era più fragile: lo stesso file si
    scrive `tools/x.py`, `./tools/x.py`, `$GITHUB_WORKSPACE/tools/x.py` o `x.py` dopo
    un `cd`. *Un identificatore che cambia forma a seconda di come lo scrivi non
    identifica: separa.*
    """
    return s.strip("\"'").rsplit("/", 1)[-1]


def _file_tracciati() -> list[Path]:
    """I file dal REGISTRO di git, non da una passeggiata sul filesystem.

    `git ls-files` non può dimenticare un file che è nel repo — una `rglob` sì, e in
    più raccoglie artefatti non versionati. Se git non risponde questo test FALLISCE
    invece di misurare un insieme vuoto: *uno zero da strumento muto non è una misura.*
    """
    res = subprocess.run(
        ["git", "-C", str(REPO), "ls-files"],
        capture_output=True, text=True, check=True,
    )
    return [REPO / r for r in res.stdout.splitlines() if r]


def _dichiarano_autoprova() -> set[str]:
    trovati = set()
    for f in _file_tracciati():
        # i workflow sono il posto dove si ESEGUE, non dove si dichiara; i .md parlano.
        if f.suffix == ".md" or ".github" in f.parts:
            continue
        try:
            testo = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if FLAG in testo:
            trovati.add(str(f.relative_to(REPO)))
    return trovati


def _eseguiti_in_ci() -> set[str]:
    """Solo le righe che ESEGUONO: un commento che nomina il flag non lo lancia.

    Il criterio è la riga di comando dentro un `run:`, non la presenza della stringa nel
    file — altrimenti basterebbe *parlare* di un presidio perché risultasse presidiato,
    che è il difetto opposto a quello curato qui.
    """
    eseguiti = set()
    wf = REPO / ".github" / "workflows"
    for f in sorted(wf.glob("*.yml")):
        for riga in f.read_text(encoding="utf-8").splitlines():
            nuda = riga.strip()
            if not nuda or nuda.startswith("#") or FLAG not in nuda:
                continue
            # 🔴 NON PIÙ «adiacente», e NON per path (rilievo di abdd732a, misurato su
            #    otto forme di comando: **5 su 8 davano un falso scoperto**).
            #      python3 tools/x.py --verbose <flag>   il flag non è attaccato al file
            #      python3 "tools/x.py" <flag>           virgolette
            #      python3 ./tools/x.py <flag>           cattura «./tools/x.py»
            #      cd tools && python3 x.py <flag>       cattura «x.py»
            #      python3 $GITHUB_WORKSPACE/tools/x.py  prefisso di variabile
            #    Le ultime tre catturavano QUALCOSA che poi non combaciava col dichiarato.
            # ⭐ E il punto non è il verso dell'errore — quello è sicuro, e l'avevo
            #    dichiarato. È che **il rosso sarebbe arrivato su un presidio VERO**, e chi
            #    lo vede cerca la via corta per rifarlo verde: aggiungere un'eccezione,
            #    cioè proprio la cura che il docstring qui sopra chiama sbagliata.
            #    *Un falso positivo su un caso vero insegna a disinnescare il presidio.*
            for m in re.finditer(r"[\w./${}\"'-]*\.(?:py|sh)", nuda):
                eseguiti.add(_basename(m.group(0)))
    return eseguiti


def test_ogni_autoprova_dichiarata_e_eseguita_in_ci() -> None:
    dichiarate = _dichiarano_autoprova()
    assert dichiarate, (
        "nessun file dichiara un'autoprova: o il repo è cambiato molto, o questa sonda "
        "guarda l'insieme sbagliato. Uno zero non è un verde."
    )
    eseguite = _eseguiti_in_ci()          # già ridotti a nome nudo
    # ⚠️ IL PREZZO DEL BASENAME, dichiarato invece di subìto: se due file dichiarassero
    #    un'autoprova con lo STESSO nome in cartelle diverse, agganciarne uno solo
    #    farebbe passare anche l'altro — un falso VERDE, cioè il verso pericoloso.
    #    Oggi non succede; il giorno che succede questo test lo dice, invece di tacere.
    per_nome: dict[str, list[str]] = {}
    for d in dichiarate:
        per_nome.setdefault(_basename(d), []).append(d)
    ambigui = {n: v for n, v in per_nome.items() if len(v) > 1}
    assert not ambigui, (
        "due presìdi con lo stesso nome in cartelle diverse: "
        + "; ".join(f"{n} → {', '.join(v)}" for n, v in ambigui.items())
        + ". Il confronto per nome nudo non li distingue e potrebbe darne uno per "
        "coperto senza esserlo: rinominane uno, o insegna a questo test i path."
    )
    scoperte = sorted(d for n, v in per_nome.items() if n not in eseguite for d in v)
    assert not scoperte, (
        "presìdi con un'autoprova che NESSUN workflow esegue: "
        + ", ".join(scoperte)
        + ". Un presidio che nessuno esegue non fallisce mai — è successo a "
        "gate-locale.py per cinque giorni con la CI verde. Agganciala in "
        ".github/workflows/ci.yml, oppure — se la stringa è solo una citazione — "
        "parafrasala: mai allargare un'eccezione."
    )


def test_questo_file_non_si_segnala_da_se() -> None:
    """La lapide non deve contenere le parole del morto — e lo si verifica, non si spera."""
    mio = Path(__file__).read_text(encoding="utf-8")
    assert FLAG not in mio, (
        "questo file nomina il flag per intero: si segnalerebbe da sé come presidio "
        "scoperto. Componi la stringa invece di scriverla, o parafrasa."
    )


def test_la_sonda_sa_dire_di_no() -> None:
    """L'autoprova di questa autoprova: un presidio che non sa fallire darebbe verde.

    Il caso che deve scattare è «dichiarato ma non eseguito» — costruito senza toccare
    il repo, perché il gruppo di controllo dev'essere identico al caso vero tranne
    nella proprietà misurata.
    """
    dichiarate = {"tools/finto-presidio.py", "tools/gate-locale.py"}
    eseguite = {"gate-locale.py"}          # nomi nudi, come li estrae _eseguiti_in_ci
    per_nome = {_basename(d): d for d in dichiarate}
    scoperte = sorted(v for n, v in per_nome.items() if n not in eseguite)
    assert scoperte == ["tools/finto-presidio.py"]


def test_le_forme_di_comando_che_prima_davano_falso_scoperto() -> None:
    """Le otto forme misurate da abdd732a: cinque davano un falso rosso.

    Non è un test del regex per sé — è il caso vero che il rilievo ha prodotto, e
    l'unico modo di sapere che non torna. *Un falso positivo su un presidio VERO
    insegna ad aggiungere un'eccezione, cioè a disinnescare il gate.*
    """
    righe = [
        "python3 tools/x.py " + FLAG,
        "python3 tools/x.py --verbose " + FLAG,
        'python3 "tools/x.py" ' + FLAG,
        "python3 ./tools/x.py " + FLAG,
        "cd tools && python3 x.py " + FLAG,
        "python3 $GITHUB_WORKSPACE/tools/x.py " + FLAG,
        "python3 ${GITHUB_WORKSPACE}/tools/x.py " + FLAG,
        "bash tools/x.sh " + FLAG,
    ]
    for riga in righe:
        trovati = {_basename(m.group(0))
                   for m in re.finditer(r"[\w./${}\"'-]*\.(?:py|sh)", riga)}
        assert "x.py" in trovati or "x.sh" in trovati, f"non riconosciuta: {riga}"
