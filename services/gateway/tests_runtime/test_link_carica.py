"""P15, seconda metà (10/10/2026): la rotta pubblica /carica/<gettone> del gateway.

Deps del lock: gateway vero, nb1777-mcp finto (MockTransport). Il gateway non ha il registro
dei gettoni: passa il file a nb1777 in streaming e ne riporta la risposta. Si prova la
pagina (CSP con nonce), il passaggio del corpo con nome e lunghezza, il rifiuto leggibile,
il tetto per IP e che /carica prende il tetto alto degli upload (quello vero lo mette nb1777).
"""
from __future__ import annotations

import asyncio

import httpx
from starlette.applications import Starlette
from starlette.routing import Route

from app import carica, nlm_client
from app.asgi_security import body_cap_for
from app.ratelimit import RateLimiter


def _app():
    return Starlette(routes=[Route("/carica/{t}", carica.carica, methods=["GET", "PUT", "POST"])])


def _banco(monkeypatch, risposta=(200, {"source_id": "s1", "nome": "doc.pdf", "bytes": 6})):
    visti = []
    audit = []
    vero = httpx.AsyncClient

    def nb1777(req: httpx.Request) -> httpx.Response:
        visti.append((req.method, req.url.path, dict(req.url.params), req.headers.get("content-length"),
                      req.read()))
        return httpx.Response(risposta[0], json=risposta[1])

    monkeypatch.setattr(nlm_client, "_base_and_headers",
                        lambda: ("http://nb1777:8003", {"x-vps1777-internal": "s"}))
    monkeypatch.setattr(nlm_client.httpx, "AsyncClient",
                        lambda **kw: vero(transport=httpx.MockTransport(nb1777), **kw))
    monkeypatch.setattr(carica, "audit", audit.append)
    monkeypatch.setattr(carica, "_LIMITE", RateLimiter(max_calls=20, window_s=300))

    def chiama(metodo, percorso, corpo=None):
        async def _go():
            async with vero(transport=httpx.ASGITransport(app=_app(), client=("203.0.113.9", 1)),
                            base_url="http://gw") as c:
                return await c.request(metodo, percorso, content=corpo)
        return asyncio.run(_go())
    return chiama, visti, audit


def test_la_pagina_ha_la_csp_col_nonce(monkeypatch):
    chiama, visti, _ = _banco(monkeypatch)
    r = chiama("GET", "/carica/abc")
    assert r.status_code == 200 and "Carica una fonte" in r.text
    csp = r.headers["content-security-policy"]
    nonce = csp.split("'nonce-")[1].split("'")[0]
    assert f'nonce="{nonce}"' in r.text and "default-src 'none'" in csp
    assert r.headers["cache-control"] == "no-store"
    assert visti == [], "la pagina non tocca nb1777 (e non consuma il link)"


def test_il_file_passa_a_nb1777_col_nome_e_la_lunghezza(monkeypatch):
    chiama, visti, audit = _banco(monkeypatch)
    r = chiama("PUT", "/carica/abc?nome=relazione%20finale.pdf", corpo=b"%PDF-1")
    assert r.status_code == 200 and r.json()["source_id"] == "s1"
    metodo, percorso, params, lunghezza, corpo = visti[0]
    assert (metodo, percorso) == ("PUT", "/internal/nlm/carica")
    assert params == {"t": "abc", "nome": "relazione finale.pdf"}
    assert lunghezza == "6" and corpo == b"%PDF-1"
    assert audit[0]["event"] == "link_carica" and audit[0]["esito"] == "ok"


def test_un_rifiuto_di_nb1777_torna_leggibile(monkeypatch):
    chiama, _, audit = _banco(monkeypatch, risposta=(403, {
        "error": "link_non_valido", "reason": "il link di caricamento non vale (già usato…)"}))
    r = chiama("POST", "/carica/abc?nome=a.txt", corpo=b"x")
    assert r.status_code == 403 and "già usato" in r.json()["reason"]
    assert audit[0]["esito"] == "rifiutato"


def test_il_ritmo_per_ip_ha_un_tetto(monkeypatch):
    chiama, visti, _ = _banco(monkeypatch)
    monkeypatch.setattr(carica, "_LIMITE", RateLimiter(max_calls=2, window_s=300))
    stati = [chiama("PUT", "/carica/abc", corpo=b"x").status_code for _ in range(3)]
    assert stati == [200, 200, 429] and len(visti) == 2


def test_carica_prende_il_tetto_degli_upload():
    assert body_cap_for("/carica/abc", default=1, upload=2) == 2
    assert body_cap_for("/caricatore", default=1, upload=2) == 1
