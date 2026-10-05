"""S11 (05/10/2026): una riga `proxy_tool` per ogni chiamata a un tool, a fine stream.

`proxy_request` si scrive quando partono gli header: un tool che moriva a metà, o un
client che chiudeva prima della fine (claude.ai a circa 30 s), restava un 200 senza durata.
Ora c'è il nome del tool, i millisecondi e l'esito. Gli argomenti MAI.

Gira con le deps del lock (come `test_gamba2_xff_da_destra.py`): è il proxy vero, con
starlette e httpx veri; finto è solo l'upstream (MockTransport).
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Route

from app import proxy

_SEGRETO = "s" * 32


def _chiamata(nome: str, argomenti: dict) -> bytes:
    return json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": nome, "arguments": argomenti}}).encode()


class _Corpo(httpx.AsyncByteStream):
    def __init__(self, pezzi, errore=None):
        self.pezzi, self.errore = pezzi, errore

    async def __aiter__(self):
        for p in self.pezzi:
            yield p
        if self.errore:
            raise self.errore


@pytest.fixture
def banco(monkeypatch):
    righe: list[dict] = []
    stato = {"risposta": None}
    monkeypatch.setattr(proxy, "audit", righe.append)
    monkeypatch.setattr(proxy, "get_settings", lambda: SimpleNamespace(
        effective_gateway_secret=_SEGRETO, gateway_upstreams={"nb": "nb1777:8000"},
        oauth_required=False))
    vero = httpx.AsyncClient

    def client(**kw):
        def gestisci(req):
            r = stato["risposta"]
            if isinstance(r, Exception):
                raise r
            return r
        return vero(transport=httpx.MockTransport(gestisci), **kw)

    monkeypatch.setattr(proxy.httpx, "AsyncClient", client)
    app = Starlette(routes=[Route("/{secret}/{service}/{path:path}", proxy.proxy,
                                  methods=["GET", "POST"])])
    async def _post(corpo):
        trasporto = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with vero(transport=trasporto, base_url="http://gw") as c:
            await c.post(f"/{_SEGRETO}/nb/mcp", content=corpo)

    def chiama(risposta, corpo):
        stato["risposta"] = risposta
        asyncio.run(_post(corpo))
        return [r for r in righe if r["event"] == "proxy_tool"]

    return chiama


def test_nome_durata_ed_esito_mai_gli_argomenti(banco):
    ok = httpx.Response(200, stream=_Corpo([b'data: {"result":{"isError":false}}\n\n']))
    righe = banco(ok, _chiamata("notebook_query", {"query": "testo personale"}))
    assert len(righe) == 1
    r = righe[0]
    assert (r["service"], r["tool"], r["esito"], r["status"]) == ("nb", "notebook_query", "ok", 200)
    assert isinstance(r["ms"], int)
    assert "testo personale" not in json.dumps(r)


def test_un_errore_del_tool_anche_a_cavallo_di_due_pezzi(banco):
    pezzi = [b'data: {"result":{"content":[],"is', b'Error": true}}\n\n']
    righe = banco(httpx.Response(200, stream=_Corpo(pezzi)), _chiamata("nb_list", {}))
    assert righe[0]["esito"] == "errore_tool"


def test_upstream_che_non_risponde_e_un_502_con_il_nome(banco):
    righe = banco(httpx.ConnectError("giù"), _chiamata("source_add_text", {"text": "x"}))
    assert (righe[0]["tool"], righe[0]["esito"], righe[0]["status"]) == ("source_add_text", "502", 502)


def test_lo_stream_che_scade_e_un_timeout(banco):
    lento = httpx.Response(200, stream=_Corpo([b"data: {}\n\n"], httpx.ReadTimeout("lento")))
    righe = banco(lento, _chiamata("studio_wait", {}))
    assert righe[0]["esito"] == "timeout"


def test_senza_tools_call_nessuna_riga(banco):
    corpo = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
    assert banco(httpx.Response(200, stream=_Corpo([b"{}"])), corpo) == []


def test_tool_chiamati_regge_corpi_strani():
    assert proxy.tool_chiamati(None) == []
    assert proxy.tool_chiamati(b"\xff non json") == []
    lotto = json.dumps([{"method": "tools/call", "params": {"name": "a"}},
                        {"method": "ping"}, {"method": "tools/call", "params": "x"}]).encode()
    assert proxy.tool_chiamati(lotto) == ["a", "?"]
