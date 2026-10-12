"""Ogni causa di rifiuto che /app/auth dichiara ha la sua frase nella pagina (12/10/2026).

Il server dice il perché nel campo `error` (401: `init_data_expired` / `invalid_init_data`;
503: `owner_not_configured` / `bot_token_not_configured`), la pagina lo trasforma in
`auth_<codice>` e `err()` lo traduce. Un codice nuovo lato server senza la sua voce in
`err()` ricadrebbe nella frase generica: il difetto che questo lavoro ha tolto (una frase
sola per cause con rimedi opposti) tornerebbe di lato. Le risposte di prova vere stanno in
tests_runtime/test_miniapp_auth_risposte.py; qui la sola COPERTURA, stdlib-only come la
cartella: `miniapp.py` importa starlette, quindi si legge con l'AST.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

_MINIAPP = Path(__file__).resolve().parents[1] / "app" / "miniapp.py"


def _albero() -> ast.Module:
    return ast.parse(_MINIAPP.read_text(encoding="utf-8"))


def _codici_di_auth() -> set[str]:
    """I valori di `error` che miniapp_auth può restituire con 401 o 503."""
    for n in ast.walk(_albero()):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "miniapp_auth":
            codici: set[str] = set()
            for c in ast.walk(n):
                if not (isinstance(c, ast.Call) and getattr(c.func, "id", "") == "JSONResponse"):
                    continue
                stato = next((k.value for k in c.keywords if k.arg == "status_code"), None)
                if not (isinstance(stato, ast.Constant) and stato.value in (401, 503)):
                    continue
                for costante in ast.walk(c.args[0]):
                    if isinstance(costante, ast.Constant) and isinstance(costante.value, str) \
                            and costante.value != "error":
                        codici.add(costante.value)
            return codici
    raise AssertionError("miniapp_auth non trovata in miniapp.py")


def _pagina() -> str:
    for n in ast.walk(_albero()):
        if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "_PAGE" for t in n.targets):
            return n.value.value
    raise AssertionError("_PAGE non trovata in miniapp.py")


def test_le_quattro_cause_ci_sono():
    assert _codici_di_auth() == {"init_data_expired", "invalid_init_data",
                                 "owner_not_configured", "bot_token_not_configured"}


def test_ogni_causa_ha_la_sua_frase():
    pagina = _pagina()
    voci = set(re.findall(r"m==='auth_([a-z_]+)'", pagina))
    mancano = _codici_di_auth() - voci
    assert not mancano, f"cause di /app/auth senza frase in err(): {sorted(mancano)}"


def test_la_pagina_legge_la_causa_dal_corpo():
    """Senza leggere `error` dal corpo, le voci sopra sarebbero codice morto."""
    assert "'auth_'+((d && d.error) || r.status)" in _pagina()


def test_scaduta_e_firma_hanno_rimedi_diversi():
    pagina = _pagina()

    def frase(codice: str) -> str:
        m = re.search(rf"m==='auth_{codice}'\) return (.+?);\n", pagina, re.S)
        assert m, codice
        return m.group(1)

    assert "rotate-secret.sh" in frase("invalid_init_data")
    assert "rotate-secret.sh" not in frase("init_data_expired")
    assert "TELEGRAM_OWNER_ID" in frase("owner_not_configured")
    assert "telegram_webapp_secret" in frase("bot_token_not_configured")
