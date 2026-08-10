"""Il version-floor deve NEGARE quando non sa confrontare, non lasciar passare.

La garanzia (`SECURITY.md`): *«Anti-downgrade: dal pulsante il target non può essere una
versione più vecchia di quella in esecuzione (version-floor SemVer)»*.

Il difetto che questi test proteggono non era un controllo mancante: era un controllo che
**si spegne da solo** quando il dato è illeggibile.

    version_key("dev") == version_key("") == version_key("qualsiasi-cosa") == ((0,0,0), 1, ())

`version_key` mappa al MINIMO ogni stringa non numerica — la scelta giusta per ORDINARE, la
peggiore per DECIDERE. Con `VPS1777_TAG` non semver, `version_key(target) < version_key(cur)`
è **sempre falso**: il floor non scatta mai, e non lo dice.

🔑 LA REGOLA GENERALE, ed è il motivo per cui questo file esiste invece di una riga in più:
   quasi ogni guardia normalizza il dato mancante in un valore neutro, e ciò che decide se
   è sicura o no è **in quale ramo cade quel neutro rispetto al VERBO che la garanzia usa**.
   Una guardia che promette «RIFIUTO» deve negare quando non sa; una che promette «SEGNALO»
   deve tacere (`copertura_max` fa così, ed è corretto: senza storico non c'è regressione).
   Qui il verbo è «non può», quindi il caso illeggibile appartiene al ramo che nega.

📌 E non è una regola importata da fuori: `consume_intent`, ~800 righe sopra nello stesso
   file, valida già il target con `valid_semver` prima di usarlo. La cura allinea due punti
   dello stesso file che trattavano una versione in due modi diversi.

Solo stdlib. Nessun docker, nessuna rete: `floor_blocca` è una funzione pura.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("vps1777_cli", _ROOT / "tools" / "vps1777.py")
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)


@pytest.mark.parametrize("cur", ["dev", "", "latest", "main", "0.41", "v0.41.2-dirty", "  "])
def test_una_corrente_non_confrontabile_blocca(cur):
    """Il caso che il floor lasciava passare: `cur` non è un semver.

    Con la versione in esecuzione illeggibile un gateway compromesso poteva far scrivere
    un intent verso QUALUNQUE release — anche la più vecchia con vuln note — e il
    confronto non lo fermava, perché `version_key(cur)` era il minimo assoluto.
    """
    assert v.floor_blocca("0.1.0", cur), (
        f"cur={cur!r} non è semver: il floor deve NEGARE (non sa confrontare), invece passa"
    )


def test_il_downgrade_vero_resta_bloccato():
    """Controprova sul caso che già funzionava: non deve essersi rotto."""
    assert v.floor_blocca("0.1.0", "0.41.2")
    assert v.floor_blocca("0.41.1", "0.41.2")


def test_un_upgrade_passa():
    """E la controprova di polarità: un gate che dice sempre «no» non protegge niente."""
    assert not v.floor_blocca("0.42.0", "0.41.2")
    assert not v.floor_blocca("1.0.0", "0.41.2")


def test_la_stessa_versione_non_e_un_downgrade():
    """Uguale non è minore: il ramo «già aggiornato» sta prima, ma se ci si arriva
    la guardia non deve inventare un rifiuto."""
    assert not v.floor_blocca("0.41.2", "0.41.2")


def test_il_floor_usa_la_funzione_e_non_il_confronto_nudo():
    """Il chiamante deve passare da `floor_blocca`.

    Senza questo, la funzione potrebbe restare corretta mentre `cmd_update` torna al
    confronto diretto — la cura viva in un posto che nessuno esegue.

    ⚠️ SI CHIEDE ALL'AST, NON AL TESTO. Qui c'era un `in sorgente` su una stringa
    esatta, e bastavano DUE PARENTESI per farlo gridare: riscrivendo la riga come
    `if (args.from_intent) and floor_blocca(...)` — stesso identico senso — il test
    diventava rosso (misurato il 10/08 riformattando e ripristinando).
    ⭐ *Un falso positivo su una riformattazione innocua non protegge: insegna a
    disattivare il presidio.* E il difetto è quello che abbiamo curato cinque volte
    oggi in altri file: **un insieme definito da una stringa, dove la stringa ha una
    grammatica che il confronto ignora.**
    Con l'AST il test regge alla FORMA e cade solo sulla SOSTANZA: se qualcuno toglie
    la condizione `from_intent`, o chiama un'altra funzione, o confronta a mano.
    """
    import ast

    albero = ast.parse((_ROOT / "tools" / "vps1777.py").read_text())

    def _nomi(nodo):
        return {n.id for n in ast.walk(nodo) if isinstance(n, ast.Name)} | {
            n.attr for n in ast.walk(nodo) if isinstance(n, ast.Attribute)
        }

    guardie = [
        n for n in ast.walk(albero)
        if isinstance(n, ast.If)
        and "floor_blocca" in _nomi(n.test)
        and "from_intent" in _nomi(n.test)
    ]
    assert guardie, (
        "nessun `if` che testi INSIEME `from_intent` e `floor_blocca`: o il "
        "version-floor è tornato al confronto nudo, o non è più agganciato al "
        "percorso del pulsante. (Chiesto all'AST: una riformattazione non basta "
        "a far fallire questo test, e non basta a farlo passare.)"
    )
