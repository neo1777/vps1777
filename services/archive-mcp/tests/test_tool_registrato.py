"""Un tool DEFINITO non è un tool REGISTRATO — e la differenza non lascia traccia.

🔓 PERCHÉ ESISTE. Nella prima versione della PR #89 avevo scritto `verifica()`,
   l'avevo testata, e la CI era verde. **Aveva zero chiamanti**: `server.py` non
   era fra i file toccati, quindi da fuori quella funzione non esisteva.
   Trovato da `71d540e6` con una sonda banale — `git grep "verifica("` — e la
   classe è quella che avevo diagnosticato io stessa poche ore prima:
   **«esiste» ≠ «chiamato», «versionato» ≠ «in esecuzione»**. *Si salta perché
   non lascia traccia in nessun commit: il codice c'è, i test passano, e la
   funzione è irraggiungibile.*

🔑 La domanda che lo prende: **«se lo tolgo adesso, qualcuno se ne accorgerebbe?»**
   Questo file è quella domanda resa eseguibile.

⚠️ È un'analisi AST del sorgente, non un'introspezione del server MCP vivo
   (`mcp` non è disponibile nel job stdlib-only). Vede la FORMA della
   registrazione — decoratore + chiamata — non che il server la esponga davvero
   a runtime. *Un verde qui dice «è cablato nel sorgente», non «risponde».*
"""
from __future__ import annotations

import ast
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "app" / "server.py"


def _tool_registrati(sorgente: str) -> dict[str, ast.FunctionDef]:
    """I nomi delle funzioni decorate con `@mcp.tool()`."""
    albero = ast.parse(sorgente)
    out: dict[str, ast.FunctionDef] = {}
    for nodo in albero.body:
        if not isinstance(nodo, ast.FunctionDef):
            continue
        for dec in nodo.decorator_list:
            f = dec.func if isinstance(dec, ast.Call) else dec
            if isinstance(f, ast.Attribute) and f.attr == "tool":
                out[nodo.name] = nodo
    return out


def test_check_integrity_e_REGISTRATO_non_solo_definito():
    tools = _tool_registrati(SERVER.read_text(encoding="utf-8"))
    assert "check_integrity" in tools, (
        "check_integrity non è fra i tool registrati: la funzione può esistere in "
        "db.py e restare IRRAGGIUNGIBILE da fuori. È il difetto che questo file esiste "
        f"per prendere. Tool trovati: {sorted(tools)}"
    )


def test_check_integrity_CHIAMA_davvero_la_logica():
    """Registrato e vuoto sarebbe peggio di assente: risponderebbe, senza guardare."""
    tools = _tool_registrati(SERVER.read_text(encoding="utf-8"))
    corpo = ast.dump(tools["check_integrity"])
    assert "integrita_archivi" in corpo, (
        "check_integrity è registrato ma non chiama db.integrita_archivi: "
        "un tool che risponde senza misurare è un verde che mente."
    )


def test_la_sonda_SA_DIRE_DI_NO():
    """Controprova: su un sorgente senza il tool, il test deve fallire.

    Senza questa, `_tool_registrati` potrebbe restituire tutto e il verde sopra
    non distinguerebbe un tool cablato da uno assente.
    """
    finto = (
        "from x import mcp\n"
        "@mcp.tool()\n"
        "def altro_tool() -> int:\n"
        "    return 1\n"
    )
    tools = _tool_registrati(finto)
    assert "altro_tool" in tools          # sa vedere
    assert "check_integrity" not in tools  # e sa NON vedere ciò che non c'è


DB_PY = Path(__file__).resolve().parents[1] / "app" / "db.py"


def test_ogni_db_punto_X_chiamata_dai_tool_ESISTE_in_db() -> None:
    """Il verso che mancava — e che il 27/08/2026 è costato un tool morto.

    I due test sopra guardano REGISTRAZIONE e CHIAMATA: `check_integrity` era
    registrato, chiamava `db.integrita_archivi`, ed erano verdi — ma la funzione
    non era MAI stata scritta. In produzione: `AttributeError` alla prima
    chiamata vera (fase USO). Qui si chiude il triangolo: ogni `db.X(...)`
    dentro un tool registrato deve avere `def X` (o un riesporto) in db.py.
    Il perimetro è DERIVATO dai tool stessi, non elencato a mano: un tool nuovo
    entra da solo nel controllo.
    """
    tools = _tool_registrati(SERVER.read_text(encoding="utf-8"))
    chiamate: set[str] = set()
    for fn in tools.values():
        for n in ast.walk(fn):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and isinstance(n.func.value, ast.Name) and n.func.value.id == "db"):
                chiamate.add(n.func.attr)
    assert chiamate, "nessuna chiamata db.* nei tool: la sonda è rotta, non il codice"
    albero = ast.parse(DB_PY.read_text(encoding="utf-8"))
    definiti = {n.name for n in albero.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for n in albero.body:            # anche i nomi riesportati (from .x import y)
        if isinstance(n, ast.ImportFrom):
            definiti.update(a.asname or a.name for a in n.names)
    mancanti = sorted(chiamate - definiti)
    assert not mancanti, (
        f"chiamate dai tool ma NON definite in db.py: {mancanti} — è l'AttributeError "
        "del 27/08/2026 (check_integrity nato morto: registrato+chiamato+mai scritto).")


def test_integrita_archivi_DELEGA_alla_logica_pura() -> None:
    """Esistere non basta: un adattatore con corpo vuoto sarebbe il verde peggiore."""
    albero = ast.parse(DB_PY.read_text(encoding="utf-8"))
    fn = next((n for n in albero.body
               if isinstance(n, ast.FunctionDef) and n.name == "integrita_archivi"), None)
    assert fn is not None, "integrita_archivi non definita in db.py"
    assert "verifica" in ast.dump(fn), (
        "integrita_archivi non delega a integrita.verifica: "
        "un adattatore che non adatta è il corpo vuoto con un altro nome.")
