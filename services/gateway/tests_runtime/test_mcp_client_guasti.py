"""Il client MCP interno (`mcp_client.call_tool`) davanti a un upstream che si guasta.

Nato dalla rilettura di Neo del 23/11/2026 (campione della prova B, scheda C11): un revisore diceva che il
client non ha un adattatore finto; la mia prima risposta era «i test sostituiscono il client». Verificato:
i test sostituivano `call_tool` INTERO (nella Mini App), quindi i suoi rami di errore non li percorreva
nessuno. Qui l'upstream è finto (httpx.MockTransport) e sa guastarsi a comando: 500, irraggiungibile, lento,
risposta malformata, risposta che non è un oggetto, tool che dichiara errore. In ogni caso il chiamante
deve ricevere `MCPCallError` con un messaggio da mostrare, mai un'eccezione diversa (sarebbe un 500 nudo).

Gira con le deps del lock, come gli altri di `tests_runtime/`.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from app import mcp_client


@pytest.fixture
def upstream(monkeypatch):
    """Sostituisce il trasporto: `stato["fa"]` è la funzione che risponde (o solleva)."""
    stato: dict = {"fa": None, "viste": []}
    vero = httpx.AsyncClient

    def gestisci(req: httpx.Request) -> httpx.Response:
        stato["viste"].append(req)
        return stato["fa"](req)

    monkeypatch.setattr(mcp_client.httpx, "AsyncClient",
                        lambda **kw: vero(transport=httpx.MockTransport(gestisci), **kw))
    monkeypatch.setattr(mcp_client, "get_settings",
                        lambda: SimpleNamespace(gateway_upstreams={"nb1777": "nb1777-mcp:8000"}))
    return stato


def _chiama(**kw):
    return asyncio.run(mcp_client.call_tool("nb1777", "nb_list", {"a": 1}, **kw))


def _json(corpo, stato=200):
    return lambda req: httpx.Response(stato, json=corpo)


def test_risposta_buona_json_e_richiesta_ben_formata(upstream):
    upstream["fa"] = _json({"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "ciao"}]}})
    assert _chiama() == ["ciao"]
    [req] = upstream["viste"]
    assert str(req.url) == "http://nb1777-mcp:8000/mcp"
    assert "text/event-stream" in req.headers["accept"] and "application/json" in req.headers["accept"]
    assert json.loads(req.content)["params"] == {"name": "nb_list", "arguments": {"a": 1}}


def test_risposta_buona_sse(upstream):
    corpo = 'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"x"}]}}\n\n'
    upstream["fa"] = lambda req: httpx.Response(200, text=corpo, headers={"content-type": "text/event-stream"})
    assert _chiama() == ["x"]


def test_servizio_sconosciuto_non_chiama_nessuno(upstream):
    with pytest.raises(mcp_client.MCPCallError, match="sconosciuto"):
        asyncio.run(mcp_client.call_tool("altro", "x"))
    assert upstream["viste"] == []


def test_upstream_500(upstream):
    upstream["fa"] = lambda req: httpx.Response(500, text="boom interno con dettagli")
    with pytest.raises(mcp_client.MCPCallError) as e:
        _chiama()
    assert "HTTP 500" in str(e.value) and "boom" not in str(e.value)   # il corpo dell'upstream non esce


def test_upstream_irraggiungibile(upstream):
    def giu(req):
        raise httpx.ConnectError("connessione rifiutata", request=req)
    upstream["fa"] = giu
    with pytest.raises(mcp_client.MCPCallError, match="non raggiungibile"):
        _chiama()


def test_upstream_lento(upstream):
    def lento(req):
        raise httpx.ReadTimeout("scaduto", request=req)
    upstream["fa"] = lento
    with pytest.raises(mcp_client.MCPCallError, match="non raggiungibile"):
        _chiama(timeout=0.1)


@pytest.mark.parametrize("corpo", ["non è json", "", "<html>502</html>"])
def test_risposta_malformata(upstream, corpo):
    upstream["fa"] = lambda req: httpx.Response(200, text=corpo, headers={"content-type": "application/json"})
    with pytest.raises(mcp_client.MCPCallError):
        _chiama()


def test_sse_senza_dati(upstream):
    upstream["fa"] = lambda req: httpx.Response(200, text="event: ping\n\n", headers={"content-type": "text/event-stream"})
    with pytest.raises(mcp_client.MCPCallError, match="SSE"):
        _chiama()


@pytest.mark.parametrize("corpo", [[1, 2], "ok", 7, None, {"error": "stringa nuda"}, {"result": "non un oggetto"},
                                   {"result": {"content": "non una lista"}}])
def test_json_valido_ma_della_forma_sbagliata(upstream, corpo):
    """Un JSON valido che non è una risposta JSON-RPC non deve diventare AttributeError/TypeError."""
    upstream["fa"] = _json(corpo)
    try:
        esito = _chiama()
    except mcp_client.MCPCallError:
        return
    assert esito == []      # ammesso: nessun testo; non ammesso: un'eccezione di altro tipo


def test_errore_jsonrpc(upstream):
    upstream["fa"] = _json({"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "argomento sbagliato"}})
    with pytest.raises(mcp_client.MCPCallError, match="argomento sbagliato"):
        _chiama()


def test_tool_che_dichiara_errore_e_messaggio_accorciato(upstream):
    upstream["fa"] = _json({"result": {"isError": True, "content": [{"type": "text", "text": "[quota] " + "x" * 900}]}})
    with pytest.raises(mcp_client.MCPCallError) as e:
        _chiama()
    assert str(e.value).startswith("[quota]") and len(str(e.value)) <= 500
