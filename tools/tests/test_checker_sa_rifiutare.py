"""Il CONTROLLORE del registro deve saper dire di no — e questi test lo dimostrano.

🔴 IL DIFETTO (voce `7b54e2ac`, dall'audio del round-3). Tutto il loop di sicurezza si
appoggia su `security/check_findings.py`, e **nessuno protegge `check_findings.py`**:
«la fiducia nel check verde presuppone l'inviolabilità del controllore». Basterebbe una
modifica che gli faccia accettare evidenze vuote — o un `return 0` in cima a `main()` —
per svuotare l'intero registro senza che nulla diventi rosso.

📏 VERIFICATO da `abdd732a` il 27/07, ed è vero nella metà che conta:
    (a) la CI usa `on: pull_request` (non `pull_request_target`) → una PR da fork non
        eredita i segreti. **Questa metà è a posto.**
    (b) `gh api …/branches/main/protection` → **404, branch non protetto**. `CODEOWNERS`
        dice `/security/ @neo1777` ma senza «Require review from Code Owners» non è un
        cancello: è un suggerimento su chi assegnare come reviewer.

🖐️ COSA FA QUESTO FILE, e cosa NO. Abilitare le branch protection è una scelta di
configurazione del repo e non è mia: resta per Neo. Questo è **difesa in profondità** —
chi addomesticasse il checker deve addomesticare anche questi test, che stanno in un
altro file e in un'altra cartella. Non lo rende impossibile: lo rende **rumoroso**.

⭐ IL METODO: non costruisco un registro finto «valido» (fragile: il checker fa 15+
controlli incrociati col CHANGELOG e coi file veri). **Parto dal registro VERO, che oggi
passa, e lo manometto** — è esattamente lo scenario della voce, e la baseline è reale.

🔑 E questi stessi test sono il presidio contro il checker permissivo: **se qualcuno gli
mette un `return 0` in cima, i casi che si aspettano un rosso cadono tutti insieme.**
"""
from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import shutil
import tempfile
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="check_findings.py stesso richiede PyYAML")

_ROOT = Path(__file__).resolve().parents[2]
_CHECKER = _ROOT / "security" / "check_findings.py"


def _carica():
    spec = importlib.util.spec_from_file_location("cf_sotto_test", _CHECKER)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _esegui(registro: dict | None) -> tuple[int, str]:
    """Lancia il checker su un registro dato (None = quello vero). Torna (exit, output)."""
    m = _carica()
    tmp = None
    if registro is not None:
        tmp = Path(tempfile.mkdtemp()) / "findings.yml"
        tmp.write_text(yaml.safe_dump(registro, allow_unicode=True, sort_keys=False),
                       encoding="utf-8")
        m.REGISTRY = tmp
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = m.main()
    finally:
        if tmp:
            shutil.rmtree(tmp.parent, ignore_errors=True)
    return rc, buf.getvalue()


def _registro_vero() -> dict:
    return yaml.safe_load((_ROOT / "security" / "findings.yml").read_text(encoding="utf-8"))


def _prima_chiusa_con_evidenza(reg: dict) -> dict:
    for v in reg["findings"]:
        if v.get("status") == "closed" and v.get("evidence"):
            return v
    pytest.skip("nessuna voce `closed` con evidenza: il registro è cambiato forma")
    raise AssertionError


# ── la baseline: senza questa, tutti i rossi qui sotto non provano niente ─────

def test_il_registro_vero_passa():
    """Il caso di controllo, e viene per primo apposta.

    Se il registro vero fosse già rosso, un test che si aspetta un rosso dopo una
    manomissione passerebbe **per la ragione sbagliata** — e l'intero file direbbe
    «il checker sa rifiutare» senza averlo dimostrato.
    """
    rc, out = _esegui(None)
    assert rc == 0, f"il registro VERO non passa: la baseline non regge.\n{out[-600:]}"


# ── le manomissioni: il checker deve accorgersene ─────────────────────────────

def test_evidenza_TOLTA_da_una_voce_chiusa():
    """«Chiuso» senza prova è la forma più comoda di bugia in un registro."""
    reg = copy.deepcopy(_registro_vero())
    v = _prima_chiusa_con_evidenza(reg)
    v["evidence"] = []
    rc, out = _esegui(reg)
    assert rc != 0, (
        f"una voce `closed` con evidenza VUOTA è passata: il checker accetta una "
        f"chiusura non provata.\n{out[-400:]}")


def test_evidenza_che_punta_a_un_file_INESISTENTE():
    reg = copy.deepcopy(_registro_vero())
    v = _prima_chiusa_con_evidenza(reg)
    v["evidence"] = [{"file": "services/gateway/app/questo_file_non_esiste_1777.py",
                      "contains": ["qualcosa"]}]
    rc, out = _esegui(reg)
    assert rc != 0, (
        f"un'evidenza che punta a un file inesistente è passata: il registro potrebbe "
        f"citare qualunque cosa.\n{out[-400:]}")


def test_evidenza_che_cita_una_stringa_ASSENTE_dal_file():
    """Il caso più insidioso: il file esiste, la riga no.

    Un'evidenza così **si legge come verificata** — c'è un percorso vero — e passerebbe
    qualunque controllo che si fermi all'esistenza del file.
    """
    reg = copy.deepcopy(_registro_vero())
    v = _prima_chiusa_con_evidenza(reg)
    v["evidence"] = [{"file": "README.md",
                      "contains": ["QUESTA-STRINGA-NON-ESISTE-IN-NESSUN-FILE-1777"]}]
    rc, out = _esegui(reg)
    assert rc != 0, (
        f"un'evidenza che cita una stringa ASSENTE dal file è passata: il checker "
        f"controlla che il file esista e non che dica quello che gli si attribuisce."
        f"\n{out[-400:]}")


def test_id_DUPLICATO():
    """Due voci con lo stesso id: una delle due sparisce da ogni conteggio."""
    reg = copy.deepcopy(_registro_vero())
    reg["findings"].append(copy.deepcopy(reg["findings"][0]))
    rc, out = _esegui(reg)
    assert rc != 0, f"un id duplicato è passato.\n{out[-400:]}"


def test_uno_STATUS_inventato():
    reg = copy.deepcopy(_registro_vero())
    reg["findings"][0]["status"] = "risolto_secondo_me"
    rc, out = _esegui(reg)
    assert rc != 0, (
        f"uno status fuori vocabolario è passato: chi scrive può inventare una parola "
        f"che *sembra* una chiusura.\n{out[-400:]}")


# ── e il presidio contro il controllore ADDOMESTICATO ─────────────────────────

def test_il_checker_non_ha_una_scorciatoia_verso_lo_zero():
    """`main()` non deve poter uscire 0 prima di aver controllato qualcosa.

    🔑 Gli altri test di questo file coprono già il caso in modo indiretto — un
    `return 0` in cima li fa cadere tutti. Questo lo dice **esplicitamente**, perché
    un rosso che nomina la causa vale più di cinque rossi che la implicano: chi legge
    «cinque manomissioni non rilevate» cerca il bug nelle manomissioni.
    """
    import ast
    albero = ast.parse(_CHECKER.read_text(encoding="utf-8"))
    main = next((n for n in ast.walk(albero)
                 if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
    assert main is not None, "`main()` non esiste più: il checker ha cambiato forma"
    # il primo statement non può essere un `return 0` nudo
    primo = main.body[0]
    if isinstance(primo, ast.Return) and isinstance(primo.value, ast.Constant):
        assert primo.value.value != 0, (
            "`main()` comincia con `return 0`: il controllore è stato addomesticato")
    # e da qualche parte deve restituire non-zero, o non può rifiutare niente
    ritorni = [n for n in ast.walk(main) if isinstance(n, ast.Return)]
    valori = {n.value.value for n in ritorni
              if isinstance(n.value, ast.Constant) and isinstance(n.value.value, int)}
    assert valori - {0}, (
        f"`main()` non ha nessun `return` diverso da zero: qualunque registro passerebbe. "
        f"Valori trovati: {sorted(valori)}")
