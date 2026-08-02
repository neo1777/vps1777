"""Test di `/health?deep=1` sul caso ZERO backend — il ciclo su zero elementi.

Perché esiste: `if not all(checks.values())` con `checks == {}` è **True**, quindi
l'endpoint rispondeva `200 {"ok": true}` avendo sondato zero backend. E chi lo
consuma è il FAIL-CLOSED dell'update: `deep_health_ok` (tools/vps1777.py:517) esce 0
solo su status 200 ⇒ un 200 a vuoto dichiarava sana una release in cui il proxy MCP
non instrada più nulla, e il rollback non scattava.

Come ci si arriva: `GATEWAY_UPSTREAMS=archive-mcp:8002,nb1777-mcp:8003` — cioè i
prefissi `nome=` dimenticati. Il parser scartava le voci **in silenzio**.

📌 STDLIB-ONLY, come tutta questa suite (il job CI si chiama «(gateway,
stdlib-only)» e non installa starlette né pydantic). Per questo `_parse_upstreams`
viene estratto dal sorgente con l'AST ed eseguito, invece di importare il modulo:
la funzione è pura, e ciò che serve provare è il suo comportamento reale — non una
sua imitazione riscritta qui, che proverebbe solo che so riscriverla.
"""
from __future__ import annotations

import ast
from pathlib import Path

_APP = Path(__file__).resolve().parents[1] / "app"
_SETTINGS = _APP / "settings.py"
_ROUTES = _APP / "routes.py"


def _parse_upstreams_vero():
    """Estrae la funzione VERA dal sorgente e la rende eseguibile qui."""
    albero = ast.parse(_SETTINGS.read_text(encoding="utf-8"))
    for n in albero.body:
        if isinstance(n, ast.FunctionDef) and n.name == "_parse_upstreams":
            n.returns = None
            for a in n.args.args:
                a.annotation = None
            ns: dict = {"UPSTREAMS_SCARTATI": []}
            exec(compile(ast.Module(body=[n], type_ignores=[]), "<estratto>", "exec"), ns)
            return ns["_parse_upstreams"], ns["UPSTREAMS_SCARTATI"]
    raise AssertionError("_parse_upstreams non trovata in settings.py")


# ─────────────── il parser: cosa produce davvero su input reali ──────────────

def test_la_forma_corretta_produce_gli_upstream():
    parse, _ = _parse_upstreams_vero()
    out = parse("archive=archive-mcp:8002,nb1777=nb1777-mcp:8003")
    assert out == {"archive": "archive-mcp:8002", "nb1777": "nb1777-mcp:8003"}


def test_i_prefissi_dimenticati_producono_un_dict_VUOTO():
    # È esattamente l'errore di configurazione che ha originato il rilievo:
    # una virgola di elenco senza i `nome=`.
    parse, _ = _parse_upstreams_vero()
    assert parse("archive-mcp:8002,nb1777-mcp:8003") == {}


def test_le_voci_scartate_NON_spariscono_piu_in_silenzio():
    # Prima qui c'era `continue` con il commento «malformato — skip»: lo scarto
    # silenzioso è ciò che rendeva il difetto invisibile a chi diagnosticava.
    parse, scartate = _parse_upstreams_vero()
    parse("archive-mcp:8002,nb1777-mcp:8003")
    assert scartate, "una voce malformata deve lasciare una traccia leggibile"
    assert "archive-mcp:8002" in scartate


# ────────── la guardia sul fail-closed, provata sulla STRUTTURA ──────────────

def test_health_deep_non_dice_sano_con_zero_backend():
    """`if not checks:` deve precedere `if not all(checks.values())`.

    Sulla struttura e non sul comportamento perché esercitare l'endpoint vuole
    starlette, che questa suite non ha. La domanda però è strutturale: «esiste un
    cammino che restituisce 200 con `checks` vuoto?».
    """
    albero = ast.parse(_ROUTES.read_text(encoding="utf-8"))
    guardie: list[int] = []
    all_calls: list[int] = []
    for n in ast.walk(albero):
        if isinstance(n, ast.If):
            t = n.test
            # `if not checks:`
            if (isinstance(t, ast.UnaryOp) and isinstance(t.op, ast.Not)
                    and isinstance(t.operand, ast.Name) and t.operand.id == "checks"):
                guardie.append(n.lineno)
            # `if not all(checks.values()):`
            if (isinstance(t, ast.UnaryOp) and isinstance(t.op, ast.Not)
                    and isinstance(t.operand, ast.Call)
                    and isinstance(t.operand.func, ast.Name)
                    and t.operand.func.id == "all"):
                all_calls.append(n.lineno)
    assert guardie, (
        "manca `if not checks:` — `all({})` è True, quindi /health?deep=1 "
        "risponderebbe 200 avendo sondato zero backend"
    )
    # 🔴 QUI C'ERA `if all_calls:` — e un assert dentro un `if` si spegne da solo.
    # Riscrivendo `all(checks.values())` in un `any(...)` o in una comprehension la
    # lista si svuota, l'assert non viene MAI eseguito, e resta solo «esiste un
    # `if not checks:` da qualche parte» — non il suo ORDINE, che è la proprietà
    # che questo file esiste per proteggere. Trovato da un agent il 02/08: era uno
    # dei soli 2 assert condizionali del repo, e l'avevo scritto io poche ore prima.
    assert all_calls, (
        "non trovo più `if not all(...)`: se il controllo è stato riscritto in "
        "un'altra forma, questo test non può più verificare l'ordine — aggiornalo "
        "invece di lasciarlo passare a vuoto"
    )
    assert min(guardie) < min(all_calls), (
        "la guardia sul dict vuoto deve precedere il controllo `all(...)`, "
        "altrimenti il caso zero non viene mai raggiunto"
        )
