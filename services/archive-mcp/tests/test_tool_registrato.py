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
