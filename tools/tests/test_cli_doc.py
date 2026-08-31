"""docs/CLI.md resta allineata alla CLI vera — per costruzione, non per buona volontà.

Perché esiste (31/08/2026, richiesta dell'owner: «un elenco di tutti i comandi…
e teniamolo aggiornato»): una pagina di riferimento scritta una volta invecchia
in silenzio al primo comando nuovo — la stessa classe del «README ha detto 35
tool per due release». Qui il legame è un test: comando senza sezione → rosso.

Stdlib-only, ispezione del sorgente (come il resto della suite tools/)."""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_CLI = (_ROOT / "tools" / "vps1777.py").read_text(encoding="utf-8")
_DOC = (_ROOT / "docs" / "CLI.md").read_text(encoding="utf-8")

COMANDI = set(re.findall(r'sub\.add_parser\("([a-z0-9-]+)"', _CLI))
DOCUMENTATI = set(re.findall(r"^## vps1777 ([a-z0-9-]+)\s*$", _DOC, re.MULTILINE))


def test_ogni_comando_ha_la_sua_sezione():
    assert COMANDI, "sonda rotta: nessun sub.add_parser trovato in vps1777.py"
    mancanti = COMANDI - DOCUMENTATI
    assert not mancanti, (
        f"comandi senza sezione in docs/CLI.md: {sorted(mancanti)} — "
        "aggiungi `## vps1777 <comando>` con descrizione ed esempio")


def test_nessuna_sezione_fantasma():
    """Il verso opposto: una sezione su un comando rimosso è un riferimento che
    manda l'utente su un errore."""
    fantasma = DOCUMENTATI - COMANDI
    assert not fantasma, f"docs/CLI.md documenta comandi che non esistono: {sorted(fantasma)}"


def test_ogni_sezione_ha_un_esempio():
    """La richiesta era «magari pure esempi d'uso»: ogni sezione porta almeno un
    blocco di codice."""
    sezioni = re.split(r"^## vps1777 ", _DOC, flags=re.MULTILINE)[1:]
    senza = [s.splitlines()[0] for s in sezioni if "```" not in s]
    assert not senza, f"sezioni senza esempio: {senza}"


def test_i_sottocomandi_di_memoria_sono_documentati():
    """`memoria` ha azioni proprie (add_subparsers annidato): la doc le nomina."""
    azioni = set(re.findall(r'azioni\.add_parser\("([a-z0-9-]+)"', _CLI))
    assert azioni, "sonda rotta: azioni di `memoria` non trovate"
    sezione = _DOC.split("## vps1777 memoria", 1)[1].split("\n## ", 1)[0]
    mancano = [a for a in azioni if f"memoria {a}" not in sezione]
    assert not mancano, f"azioni di `memoria` non documentate: {mancano}"


def test_lhelp_rimanda_alla_doc_e_viceversa():
    """Chi ha in mano la CLI trova la pagina; chi legge la pagina trova `help`."""
    assert "docs/CLI.md" in _CLI, "l'epilog della CLI deve nominare docs/CLI.md"
    assert "vps1777 help" in _DOC
