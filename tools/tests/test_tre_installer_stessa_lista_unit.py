"""I TRE INSTALLER ABILITANO LE STESSE UNIT — e qui la lista si ESEGUE, non si legge.

🔓 PERCHÉ ESISTE. `security/confronta-installer.py` confronta i tre installer per
   **nomi che compaiono nel testo**, e lo dichiara: *«un verde qui è "i nomi
   concordano", NON "i tre installer fanno la stessa cosa"»*. Resta scoperto
   l'oggetto su cui la divergenza è già avvenuta **due volte**:

     `ENABLE_UNITS` / `enable_units` — la lista delle unit che vengono ABILITATE.

   Non è una stringa: è il risultato di un **calcolo condizionale**, scritto tre
   volte in due linguaggi (`setup.sh:356-363`, `deploy.sh:848-849`,
   `installer/engine.py:603-606`). Tre testi possono contenere gli stessi nomi e
   abilitarne insiemi diversi — che è esattamente ciò che è successo:

     · fix #13 (`6c764bc`): `secrets-check.timer` aggiunto a deploy.sh ed
       engine.py, **saltato in setup.sh** → chi installava con setup.sh restava
       senza il controllo delle scadenze secret, in silenzio.
     · RECIDIVA: `auto-update.timer` rifece lo stesso identico percorso.

   Il commento a `setup.sh:350-355` racconta la cura («da qui in poi setup.sh legge
   la STESSA fonte di verità») — **e nessuno la verifica**. Un difetto che si è
   ripetuto due volte non è coperto dal commento che lo racconta: è coperto da una
   prova che lo rifà fallire.

🔑 COME: i tre calcoli vengono **estratti dai file veri ed eseguiti**, non ricopiati
   qui. Una copia proverebbe se stessa — è il criterio di
   `tools/tests/test-install-version-shell.sh`, da cui questo file prende il metodo.

⚠️ COSA NON FA, dichiarato perché non lo si scopra come se fosse un bug:
   verifica la lista che i tre CALCOLANO, non che `systemctl enable` vada a buon
   fine. È il confronto fra tre intenzioni espresse in tre modi — che è
   precisamente il punto in cui sono divergute.
   *L'esito sulla macchina lo prende `prova-8` e il collaudo, non un test statico.*

   ✅ E ciò che invece È coperto, perché dirlo scoperto sarebbe un altro errore:
      **che le unit esistano sul disco** lo verifica già il ledger —
      `tools/verify-features.py:145-147` (`kind == "systemd_unit"` → `p.exists()`),
      eseguito in CI da `.github/workflows/verify-features.yml:31`. Tutte e quattro
      le unit di questa lista sono dichiarate in `features.yaml`.
      🔑 *La prima stesura scriveva «né che le unit esistano sul disco»: un limite
      **più largo del vero**, che fa sembrare aperto un fronte chiuso. È l'immagine
      speculare del difetto per cui un limite dichiarato si legge come gestito — e
      passa più facilmente, perché ha la forma della prudenza.* (rilievo di
      `b82df434`, riverificato prima di accettarlo.)
"""

from __future__ import annotations

import ast
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parents[2]

# I due scenari che contano: la feature `autoupdate` è l'unica che muove la lista,
# ed è quella su cui la recidiva è avvenuta. `none` non è un caso di fantasia:
# `engine.py:547` lo tratta esplicitamente come «nessuna feature».
SCENARI = [
    pytest.param("backup,autoupdate", True, id="autoupdate-ON (default)"),
    pytest.param("backup", False, id="autoupdate-OFF"),
]


def _blocco_shell(percorso: Path, primo: str, ultimo: str) -> str:
    """Le righe dal primo match all'ultimo, ESTRATTE dal file vero."""
    testo = percorso.read_text(encoding="utf-8", errors="replace").splitlines()
    inizio = next((i for i, r in enumerate(testo) if primo in r), None)
    assert inizio is not None, f"{percorso.name}: non trovo «{primo}» — il file è cambiato"
    fine = next((i for i, r in enumerate(testo[inizio:], inizio) if ultimo in r), None)
    assert fine is not None, f"{percorso.name}: non trovo «{ultimo}» dopo l'inizio"
    return textwrap.dedent("\n".join(testo[inizio:fine + 1]))


def _esegui_shell(blocco: str, features: str) -> set[str]:
    """Esegue il blocco con FEATURES imposto e restituisce l'insieme calcolato."""
    script = f'FEATURES="{features}"\n{blocco}\nprintf "%s" "$ENABLE_UNITS"'
    esito = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert esito.returncode == 0, f"il blocco non gira: {esito.stderr[:200]}"
    return set(esito.stdout.split())


def _lista_setup(features: str) -> set[str]:
    # `setup.sh` ricava FEATURES da .env con un `sed`; la riga successiva applica il
    # default. Sovrascrivo FEATURES DOPO il blocco di lettura, così provo il calcolo
    # senza dover fabbricare un .env — e senza toccare quello vero.
    blocco = _blocco_shell(RADICE / "setup.sh", 'ENABLE_UNITS="vps1777-check-update.timer', "esac")
    blocco = re.sub(r'^\s*FEATURES=.*$', "", blocco, flags=re.M)
    return _esegui_shell(blocco, features)


def _lista_deploy(features: str) -> set[str]:
    blocco = _blocco_shell(RADICE / "deploy.sh", 'ENABLE_UNITS="vps1777-check-update.timer',
                           "autoupdate")
    return _esegui_shell(blocco, features)


def _lista_engine(features: str) -> set[str]:
    """Il calcolo di `engine.py`, estratto con l'AST ed eseguito.

    L'AST e non una regex: `enable_units` è costruito da un `Assign` seguito da un
    `AugAssign` dentro un `If`, e riconoscere quella forma con un'espressione
    regolare significa reimplementare il parser di Python — male.
    """
    albero = ast.parse((RADICE / "installer" / "engine.py").read_text(encoding="utf-8"))
    metodo = next((n for n in ast.walk(albero)
                   if isinstance(n, ast.FunctionDef) and n.name == "step_selfupdate_setup"), None)
    assert metodo is not None, "engine.py: manca `step_selfupdate_setup` — il file è cambiato"

    def assegna(nodo: ast.AST) -> bool:
        """Chi ASSEGNA `enable_units`, non chi lo NOMINA.

        🔴 Il primo giro filtrava su `"enable_units" in ast.unparse(nodo)` e prendeva
           anche `script = f"…{enable_units}…"` — che **usa** la variabile e tira
           dentro `REMOTE_DIR`: `NameError` in exec. *Un filtro sul testo non
           distingue chi scrive da chi legge; il target dell'assegnamento sì.*
        """
        for n in ast.walk(nodo):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store) and n.id == "enable_units":
                return True
        return False

    righe = [ast.unparse(n) for n in metodo.body
             if isinstance(n, (ast.Assign, ast.AugAssign, ast.If)) and assegna(n)]
    assert righe, "engine.py: nessuna riga costruisce `enable_units`"

    # `self._features()` è l'unica dipendenza esterna del calcolo: la sostituisco con
    # lo scenario, che è esattamente ciò che il test vuole variare.
    class _Finto:
        def _features(self) -> list[str]:
            return [f.strip() for f in features.split(",") if f.strip() and f.strip() != "none"]

    spazio: dict = {"self": _Finto()}
    exec("\n".join(righe), spazio)  # noqa: S102 — codice estratto dal repo, non da input
    return set(str(spazio["enable_units"]).split())


TRE = {"setup.sh": _lista_setup, "deploy.sh": _lista_deploy, "installer/engine.py": _lista_engine}


@pytest.mark.parametrize("features, con_autoupdate", SCENARI)
def test_i_tre_installer_abilitano_le_STESSE_unit(features: str, con_autoupdate: bool) -> None:
    liste = {nome: fn(features) for nome, fn in TRE.items()}
    distinte = {frozenset(v) for v in liste.values()}
    assert len(distinte) == 1, (
        f"i tre installer abilitano insiemi DIVERSI con VPS1777_FEATURES={features}:\n"
        + "\n".join(f"  {n:<22} {sorted(v)}" for n, v in liste.items())
        + "\n  ⇒ è il difetto del fix #13 (secrets-check.timer) e la sua recidiva\n"
          "    (auto-update.timer): una unit aggiunta a due installer su tre."
    )
    # Polarità: senza questo, tre liste identiche e VUOTE passerebbero.
    comune = next(iter(distinte))
    assert "vps1777-check-update.timer" in comune, "nessuno abilita check-update.timer: sospetto"
    assert ("vps1777-auto-update.timer" in comune) is con_autoupdate, (
        f"auto-update.timer {'manca' if con_autoupdate else 'è presente'} "
        f"con FEATURES={features}: la condizione non è quella dichiarata"
    )


def test_la_lista_NON_e_ricopiata_qui() -> None:
    """Il test non deve contenere la risposta che verifica.

    Se un giorno qualcuno «semplifica» sostituendo l'estrazione con una lista
    scritta a mano, questo test lo dice: da quel momento proverebbe se stesso.

    🔴 E AL PRIMO GIRO QUESTO TEST HA TROVATO SÉ STESSO: cercavo la lista scritta
       per intero, e scrivendola nell'`assert` l'ho messa nel file che ispeziono.
       *Un presidio che nomina ciò che vieta si autoaccusa* — è la stessa classe
       per cui `grep "la frase sbagliata"` su un documento che la cita dà sempre 1.
       ⇒ la stringa cercata si **compone a runtime** e non compare mai per intero
       nel sorgente. È l'unica cura che non dipende da chi la rilegge.
    """
    mio = Path(__file__).read_text(encoding="utf-8")
    codice = "\n".join(r for r in mio.splitlines() if not r.strip().startswith("#"))
    # `check-update.timer` compare nelle asserzioni di polarità ed è voluto; ciò che
    # NON deve comparire è la lista COMPLETA, cioè la risposta che il test verifica.
    risposta = " ".join(("vps1777-update.path", "vps1777-" + "secrets-check.timer"))
    assert risposta not in codice, (
        "la lista attesa è ricopiata dentro il test: da qui in poi proverebbe se stessa"
    )
