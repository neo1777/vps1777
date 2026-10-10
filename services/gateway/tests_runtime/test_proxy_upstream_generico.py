"""Il proxy è generico: un upstream HTTP qualunque, non MCP, dietro lo stesso OAuth (10/10/2026).

Il 04/10 la verifica sul codice diceva «il proxy è agnostico al protocollo» e insieme
«nessun test fa passare dal proxy un upstream non MCP»: una frase vera nel codice ma non
provata. Serve alla candidatura NLnet Restack (vps1777 come gateway di autenticazione per
servizi self-hosted, MCP fra i casi d'uso): prima di dirlo, si misura.

Qui l'upstream è un echo (MockTransport) registrato come `echo`, l'OAuth è ACCESO come in
produzione, e il token è un access token vero firmato da `jwt_helpers`. Si prova che:
metodi e percorsi arbitrari passano con query e body intatti; senza Bearer o con un
soggetto non ammesso non passa niente; il Bearer non arriva all'upstream; `internal/`
resta chiuso; una risposta a pezzi arriva a pezzi.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Route

from app import jwt_helpers, proxy

_SEGRETO = "s" * 32
_PROPRIETARIO = "neo@example.invalid"


@pytest.fixture
def banco(monkeypatch):
    impostazioni = SimpleNamespace(
        effective_gateway_secret=_SEGRETO, gateway_upstreams={"echo": "echo:9000"},
        oauth_required=True, oauth_allowed_emails=[_PROPRIETARIO],
        effective_signing_secret="k" * 64, gateway_public_base="https://gw.example.invalid")
    monkeypatch.setattr(proxy, "get_settings", lambda: impostazioni)
    monkeypatch.setattr(jwt_helpers, "get_settings", lambda: impostazioni)
    monkeypatch.setattr(proxy, "audit", lambda e: None)
    visti: list[httpx.Request] = []
    vero = httpx.AsyncClient

    class _Pezzi(httpx.AsyncByteStream):
        # come l'upstream vero: il proxy legge la risposta in streaming (send(stream=True))
        def __init__(self, pezzi):
            self.pezzi = pezzi

        async def __aiter__(self):
            for p in self.pezzi:
                yield p

    def echo(req: httpx.Request) -> httpx.Response:
        visti.append(req)
        if req.url.path == "/a-pezzi":
            return httpx.Response(200, stream=_Pezzi((b"uno-", b"due-", b"tre")),
                                  headers={"content-type": "text/plain"})
        corpo = json.dumps({"metodo": req.method, "percorso": req.url.path,
                            "query": req.url.query.decode(), "corpo": req.content.decode()})
        return httpx.Response(200, stream=_Pezzi((corpo.encode(),)),
                              headers={"content-type": "application/json"})

    monkeypatch.setattr(proxy.httpx, "AsyncClient",
                        lambda **kw: vero(transport=httpx.MockTransport(echo), **kw))
    app = Starlette(routes=[Route("/{secret}/{service}/{path:path}", proxy.proxy,
                                  methods=["GET", "POST", "PUT", "DELETE", "PATCH"])])

    def chiama(metodo, percorso, *, sub=_PROPRIETARIO, bearer=True, corpo=None):
        intestazioni = {}
        if bearer:
            tok = jwt_helpers.issue(typ="access", sub=sub, aud="client-di-prova", ttl=300)
            intestazioni["authorization"] = f"Bearer {tok}"

        async def _go():
            async with vero(transport=httpx.ASGITransport(app=app), base_url="http://gw") as c:
                return await c.request(metodo, f"/{_SEGRETO}/echo/{percorso}",
                                       headers=intestazioni, content=corpo)
        return asyncio.run(_go())

    return chiama, visti


@pytest.mark.parametrize("metodo", ["GET", "POST", "PUT", "PATCH", "DELETE"])
def test_metodi_percorsi_query_e_corpo_passano_intatti(banco, metodo):
    chiama, visti = banco
    corpo = b'{"qualunque": "cosa", "non": "mcp"}' if metodo in {"POST", "PUT", "PATCH"} else None
    r = chiama(metodo, "v1/risorse/42?filtro=a&ordine=b", corpo=corpo)
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["metodo"], d["percorso"], d["query"]) == (metodo, "/v1/risorse/42", "filtro=a&ordine=b")
    assert d["corpo"] == (corpo.decode() if corpo else "")
    assert str(visti[-1].url).startswith("http://echo:9000/v1/risorse/42")


def test_senza_bearer_non_passa_niente(banco):
    chiama, visti = banco
    r = chiama("GET", "v1/risorse", bearer=False)
    assert r.status_code == 401 and r.json()["reason"] == "missing_bearer"
    assert visti == [], "l'upstream non deve vedere la richiesta"


def test_un_soggetto_non_ammesso_non_passa(banco):
    chiama, visti = banco
    r = chiama("GET", "v1/risorse", sub="altri@example.invalid")
    assert r.status_code == 401 and r.json()["reason"] == "subject_not_allowed"
    assert visti == []


def test_il_bearer_si_ferma_al_gateway(banco):
    chiama, visti = banco
    assert chiama("GET", "v1/risorse").status_code == 200
    assert "authorization" not in visti[-1].headers
    assert visti[-1].headers["host"] == "echo:9000"


def test_internal_resta_chiuso_anche_per_un_upstream_qualunque(banco):
    chiama, visti = banco
    assert chiama("GET", "internal/admin").status_code == 404
    assert visti == []


def test_una_risposta_a_pezzi_arriva_intera(banco):
    chiama, _ = banco
    r = chiama("GET", "a-pezzi")
    assert r.status_code == 200 and r.text == "uno-due-tre"
