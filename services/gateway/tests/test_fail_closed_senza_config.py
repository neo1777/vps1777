"""«In assenza di configurazione il gateway nega, non apre» — la frase, provata.

Perché esiste (27/08/2026, lavoro a80025f1 sulle garanzie senza ancora): la
postura fail-closed è dichiarata in `docs/ARCHITECTURE.md` da mesi, e nessun
test la teneva per il caso più semplice di tutti — il segreto NON configurato.
Il ramo che la mantiene è `proxy.py`:

    expected = s.effective_gateway_secret
    if not expected or not _constant_eq(secret, expected):
        → 404

e il pezzo che conta è `not expected` PRIMA del confronto: senza quella metà,
`_constant_eq("", "")` su un gateway non configurato sarebbe **True** — il
segreto vuoto «combacerebbe» con l'URL senza segreto, e l'assenza di
configurazione diventerebbe un lasciapassare. È esattamente la classe che il
repo chiama «un default che degrada in silenzio verso l'aperto».

📌 STDLIB-ONLY come tutta la suite: `proxy.py` importa starlette, quindi non si
importa — si estrae con l'AST ciò che serve (`_constant_eq`, che è pura) e si
verifica sulla STRUTTURA che il ramo `not expected` esista e preceda l'uso
degli upstream, col metodo di `test_health_deep_zero.py`.
"""
from __future__ import annotations

import ast
from pathlib import Path

_PROXY = Path(__file__).resolve().parents[1] / "app" / "proxy.py"


def _constant_eq_vera():
    albero = ast.parse(_PROXY.read_text(encoding="utf-8"))
    for n in ast.walk(albero):
        if isinstance(n, ast.FunctionDef) and n.name == "_constant_eq":
            n.returns = None
            for a in n.args.args:
                a.annotation = None
            ns: dict = {}
            exec(compile(ast.Module(body=[n], type_ignores=[]), "<estratto>", "exec"), ns)
            return ns["_constant_eq"]
    raise AssertionError("_constant_eq non trovata in proxy.py")


def test_il_confronto_da_solo_NON_basta_sul_vuoto():
    """La ragione per cui `not expected` deve esistere: due vuoti combaciano.

    Non è un difetto di `_constant_eq` — confrontare due stringhe uguali E
    vere è il suo mestiere — è la prova che il fail-closed non può essere
    delegato al confronto: serve il ramo esplicito sul non-configurato.
    """
    eq = _constant_eq_vera()
    assert eq("", "") is True, (
        "se questo diventa False, _constant_eq ha cambiato natura: "
        "aggiorna il commento del ramo in proxy.py, non solo questo test")
    assert eq("a", "b") is False
    assert eq("x", "x") is True


def test_il_ramo_not_expected_esiste_e_viene_prima_degli_upstream():
    """Sulla STRUTTURA: dentro `proxy()`, `not expected` sta in un test di
    ramo che ritorna, e compare PRIMA del primo uso di `gateway_upstreams`.
    """
    src = _PROXY.read_text(encoding="utf-8")
    albero = ast.parse(src)
    fn = next((n for n in ast.walk(albero)
               if isinstance(n, ast.AsyncFunctionDef) and n.name == "proxy"), None)
    assert fn is not None, "la funzione async proxy() non c'è più: la garanzia va ri-ancorata"

    riga_guardia = None
    riga_upstreams = None
    for n in ast.walk(fn):
        if isinstance(n, ast.If) and riga_guardia is None:
            # cerco `not expected` fra gli operandi del test dell'if
            for sub in ast.walk(n.test):
                if (isinstance(sub, ast.UnaryOp) and isinstance(sub.op, ast.Not)
                        and isinstance(sub.operand, ast.Name)
                        and sub.operand.id == "expected"):
                    riga_guardia = n.lineno
        if (isinstance(n, ast.Attribute) and n.attr == "gateway_upstreams"
                and riga_upstreams is None):
            riga_upstreams = n.lineno
    assert riga_guardia is not None, (
        "il ramo `not expected` è sparito da proxy(): senza, un gateway non "
        "configurato smette di negare — la garanzia fail-closed cade")
    assert riga_upstreams is not None, "proxy() non usa più gateway_upstreams?"
    assert riga_guardia < riga_upstreams, (
        f"la guardia sul secret (r.{riga_guardia}) deve precedere l'uso degli "
        f"upstream (r.{riga_upstreams}): negare DOPO aver instradato non è negare")
