#!/usr/bin/env python3
"""Ogni `tools/tests/test_*.py` deve avere almeno una funzione `test_*`, o non gira.

PERCHÉ ESISTE — e il difetto non è ipotetico: era in produzione stamattina.

La CI esegue i test di questa cartella con **una riga sola** (`.github/workflows/ci.yml`,
job «Test CLI vps1777»):

    uvx pytest tools/tests/ -v

`pytest` esegue le **funzioni** `test_*`. Un file che si chiama `test_qualcosa.py` ma
contiene solo `def main()` + `if __name__ == "__main__"` viene **raccolto** — il nome
combacia — e **non esegue niente**. Nessun errore, nessun warning: verde.

MISURATO IL 09/08 su `origin/main` (`f774921`), sabotando un presidio appena mergiato:

    python3 tools/tests/test_sudo_whitelist_copre_la_cli.py   →  exit 1   (rotto, e lo dice)
    uvx pytest tools/tests/                                   →  250 passed, exit 0

Tre file su ventuno erano in questo stato, ed erano **esattamente i tre nati quel giorno**
(#131, #132, #135), mergiati tutti e tre con la CI verde e revisionati tutti e tre
*provandoli*: `python3 <file>`, nei due versi negativi. Funzionavano sempre.
⭐ **Erano stati eseguiti nel modo in cui non sarebbero mai stati eseguiti.** «Provato, non
letto» non basta: bisogna provarlo **col comando che lo eseguirà davvero**.

## Perché un test della CLASSE e non tre ganci e via

I tre ganci curano l'istanza. Il buco gemello per i file `.sh` era già stato curato il
03/08 — *«5 file .sh, 1 eseguito, TRE mai eseguiti da nessuno ⇒ non una voce in più nella
lista: VIA la lista»*, da cui `tools/esegui-test-bash.sh`. Quella cura ha coperto gli
`.sh` e non ha visto che i `.py` senza `test_*` hanno lo stesso destino: **la classe è la
stessa, l'istanza no.** Chi scrive il quarto presidio non deve ricordarsi di niente.

## Il gancio, per chi lo vedrà fallire

Tre righe in fondo al file, prima di `if __name__ == "__main__"`:

    def test_presidio_gira_anche_in_ci() -> None:
        assert main() == 0

Il `if __name__` resta: serve a eseguirlo a mano con l'output leggibile. Le due strade
non si escludono — è che finora ce n'era **una sola**, ed era quella che la CI non prende.

Stile: stdlib-only. Uso:  python3 tools/tests/test_ogni_presidio_ha_il_gancio_pytest.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CARTELLA = ROOT / "tools" / "tests"

# La riga della CI che esegue questa cartella. Se cambia, questo test parla di un comando
# che non esiste più: lo si verifica invece di assumerlo (vedi `la_ci_usa_ancora_pytest`).
CI = ROOT / ".github" / "workflows" / "ci.yml"
# ⚠️ La riga NON deve essere un commento, e questa cautela me l'ha insegnata il collaudo
# di questo stesso file. La prima versione cercava `pytest tools/tests/` in tutto il
# ci.yml: ho tolto il comando vero per provare il ramo «la premessa è caduta», e il test
# è passato lo stesso — perché quella stringa compare in DUE COMMENTI del ci.yml, che la
# raccontano. **Misuravo la prosa al posto del programma, dentro il presidio che avrebbe
# dovuto accorgersene.** (Terza volta in un giorno per la stessa famiglia: un test che
# falliva sul commento che nomina la stringa, un collaudo di rientri che eseguiva una
# riga di prosa, e questa.) ⇒ si guarda la riga NUDA, senza `#` davanti.
_ATTESO_IN_CI = re.compile(r"^\s*[^#\n]*pytest\s+tools/tests/", re.M)

_DEF_TEST = re.compile(r"^(?:async\s+)?def\s+test_\w*\s*\(", re.M)


def file_di_test() -> list[Path]:
    """I `test_*.py` della cartella. Lista SCOPERTA, mai enumerata a mano."""
    return sorted(CARTELLA.glob("test_*.py"))


def senza_gancio(file: list[Path]) -> list[Path]:
    return [p for p in file if not _DEF_TEST.search(p.read_text(encoding="utf-8"))]


def la_ci_usa_ancora_pytest() -> bool:
    """La premessa di questo test è ancora vera?

    Se un domani la CI eseguisse i `.py` uno per uno (come fa per i `.sh`), la mancanza
    di `test_*` smetterebbe di essere un difetto e questo presidio starebbe chiedendo una
    cosa inutile — cioè sarebbe RUMORE, che è il modo in cui un presidio si disattiva
    senza che nessuno lo tocchi.
    """
    return bool(CI.is_file() and _ATTESO_IN_CI.search(CI.read_text(encoding="utf-8")))


def main() -> int:
    if not CARTELLA.is_dir():
        print(f"✗ {CARTELLA} non esiste: la sonda non sta guardando il repo giusto")
        return 1

    if not la_ci_usa_ancora_pytest():
        # Non è un verde e non è un rosso sul codice: è questo test che non sa più
        # se la sua domanda ha senso. Fallisce, perché tacere qui lo renderebbe
        # indistinguibile da «tutto a posto».
        print("✗ non trovo `pytest tools/tests/` in .github/workflows/ci.yml.\n"
              "      La premessa di questo presidio è che la CI esegua la cartella con\n"
              "      pytest. Se l'hai cambiata, aggiorna o togli questo file: così com'è\n"
              "      sta controllando una regola che forse non vale più.")
        return 1

    file = file_di_test()
    if not file:
        # Zero file trovati non è «tutti a posto»: è la sonda che guarda nel posto
        # sbagliato. È il difetto che questo stesso presidio esiste per prendere.
        print(f"✗ nessun `test_*.py` in {CARTELLA.relative_to(ROOT)}: NON è un verde,\n"
              "      è una sonda cieca (glob a vuoto).")
        return 1

    orfani = senza_gancio(file)
    print(f"{len(file)} file `test_*.py` · {len(file) - len(orfani)} con un gancio pytest")
    if orfani:
        print(f"\n✗ {len(orfani)} file che pytest RACCOGLIE E NON ESEGUE:")
        for p in orfani:
            print(f"      {p.relative_to(ROOT)}")
        print("\n  Aggiungi in fondo, prima di `if __name__ == \"__main__\"`:\n"
              "      def test_presidio_gira_anche_in_ci() -> None:\n"
              "          assert main() == 0\n"
              "  Finché manca, quel file è verde perché non viene eseguito — non perché\n"
              "  la proprietà che controlla sia vera.")
        return 1
    print("✓ ogni presidio di tools/tests ha un gancio: la CI li esegue davvero")
    return 0


def test_presidio_gira_anche_in_ci() -> None:
    """E questo file rispetta la regola che impone — altrimenti sarebbe il primo orfano."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
