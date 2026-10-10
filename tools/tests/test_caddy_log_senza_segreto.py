"""H78 e H79: l'access-log di Caddy non scrive il gateway_secret (01/10 e 04/10/2026).

Il segreto vive nel path del proxy MCP (/<SECRET>/<servizio>/mcp). Il gateway lo redige
nel suo log (uvicorn), ma l'access-log JSON di Caddy scriveva `request.uri` intero:
misurato con caddy:2.11, una richiesta → una riga col segreto in chiaro. Con il filtro,
la stessa richiesta scrive /***/archive/mcp.

H79: il segreto non sta solo all'inizio del path. I client OAuth lo portano anche nel
`resource` dell'autorizzazione (in query, codificato %2F, o in chiaro) e nei metadati
chiesti col path in coda (/.well-known/oauth-protected-resource/<SECRET>/…). Il filtro di
H78 era ancorato a `^/` e non li vedeva: misurato con caddy:2.11 il 04/10. I casi qui sotto
sono gli stessi provati sul Caddy vero.
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
    sost = re.sub(r"\$\{(\d+)\}", r"\\g<\1>", m.group(2))  # ${1} di Go → \g<1> di Python
    segreto = "Ab3dE" + "fGh1jK" + "lMn0pQ" + "rSt9uVwXyZ12345"
    assert pat.sub(sost, f"/{segreto}/archive/mcp") == "/***/archive/mcp"
    assert pat.sub(sost, "/health") == "/health"
    assert pat.sub(sost, "/admin/setup") == "/admin/setup"


@pytest.mark.parametrize("nome", ["Caddyfile", "Caddyfile.dns01"])
def test_il_log_di_caddy_redige_il_segreto_ovunque_nell_uri(nome: str) -> None:
    testo = (RADICE / "ingress" / nome).read_text(encoding="utf-8")
    m = re.search(r'request>uri regexp "([^"]+)" "([^"]+)"', testo)
    assert m, f"{nome}: manca il filtro su request>uri"
    pat = re.compile(m.group(1))
    sost = re.sub(r"\$\{(\d+)\}", r"\\g<\1>", m.group(2))
    s = "Ab3dE" + "fGh1jK" + "lMn0pQ" + "rSt9uVwXyZ12345"
    casi = [
        f"/.well-known/oauth-protected-resource/{s}/archive/mcp",
        f"/.well-known/oauth-authorization-server/{s}/nb1777/mcp",
        f"/oauth/authorize?client_id=x&resource=https%3A%2F%2Fexample.invalid%2F{s}%2Farchive%2Fmcp",
        f"/oauth/authorize?resource=https%3a%2f%2fexample.invalid%2f{s}%2farchive%2fmcp",
        f"/oauth/authorize?resource=https://example.invalid/{s}/nb1777/mcp",
    ]
    for uri in casi:
        assert s not in pat.sub(sost, uri), f"{nome}: il segreto resta in chiaro in {uri}"
    # quello che deve restare leggibile
    for uri in ("/health", "/admin/setup", "/oauth/token",
                "/oauth/authorize?redirect_uri=https%3A%2F%2Fexample.invalid%2Fapi%2Fmcp%2Fauth_callback"
                "&client_id=0f3c2a1b-1111-2222-3333-444455556666"):
        assert pat.sub(sost, uri) == uri, f"{nome}: redatto per sbaglio {uri}"


@pytest.mark.parametrize("nome", ["Caddyfile", "Caddyfile.dns01"])
def test_il_log_di_caddy_redige_il_gettone_dei_link_firmati(nome: str) -> None:
    """P15 (10/10/2026): il gettone sta nella query (`?t=<scade>.<firma>`) e vale 30 minuti."""
    testo = (RADICE / "ingress" / nome).read_text(encoding="utf-8")
    m = re.search(r'request>uri regexp "([^"]+)" "([^"]+)"', testo)
    pat = re.compile(m.group(1))
    sost = re.sub(r"\$\{(\d+)\}", r"\\g<\1>", m.group(2))
    firma = "135a61797855949a8d5a8580" + "deadbeef"
    uri = f"/scarica/podcast.m4a?t=1791636435.{firma}"
    fuori = pat.sub(sost, uri)
    assert firma not in fuori and "1791636435" not in fuori, fuori
    assert fuori == "/scarica/podcast.m4a?t=***"
    # un parametro che si chiama solo per caso come «t» in coda a un altro resta leggibile
    assert pat.sub(sost, "/admin/audit?event=link_scarica") == "/admin/audit?event=link_scarica"
