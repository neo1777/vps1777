"""H78: l'access-log di Caddy non scrive il gateway_secret (01/10/2026).

Il segreto vive nel path del proxy MCP (/<SECRET>/<servizio>/mcp). Il gateway lo redige
nel suo log (uvicorn), ma l'access-log JSON di Caddy scriveva `request.uri` intero:
misurato con caddy:2.11, una richiesta → una riga col segreto in chiaro. Con il filtro,
la stessa richiesta scrive /***/archive/mcp.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("nome", ["Caddyfile", "Caddyfile.dns01"])
def test_il_log_di_caddy_redige_il_primo_segmento(nome: str) -> None:
    testo = (RADICE / "ingress" / nome).read_text(encoding="utf-8")
    blocco = re.search(r"^\s*log \{.*?^\s*\}\s*$", testo, re.M | re.S)
    assert blocco, f"{nome}: blocco log non trovato"
    b = blocco.group(0)
    assert "format filter" in b and "wrap json" in b, f"{nome}: il log deve passare dal filtro"
    m = re.search(r'request>uri regexp "([^"]+)" "([^"]+)"', b)
    assert m, f"{nome}: manca il filtro su request>uri"
    pat = re.compile(m.group(1))
    segreto = "Ab3dE" + "fGh1jK" + "lMn0pQ" + "rSt9uVwXyZ12345"
    assert pat.sub(m.group(2), f"/{segreto}/archive/mcp") == "/***/archive/mcp"
    assert pat.sub(m.group(2), "/health") == "/health"
    assert pat.sub(m.group(2), "/admin/setup") == "/admin/setup"
