"""
Client MCP interno — il gateway chiama i tool degli upstream sulla rete backend.

Usato dagli endpoint della Mini App (/app/api/*): a differenza del reverse
proxy (che inoltra richieste MCP di client esterni), qui è il gateway stesso il
client. Single-shot, senza sessione — come fa il bot. Il parsing della risposta
(SSE o JSON) è in miniapp_core (stdlib-only, testato).
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from .miniapp_core import extract_tool_texts, parse_mcp_payload
from .settings import get_settings

log = logging.getLogger(__name__)

# MCP streamable-http: l'Accept DEVE includere ENTRAMBI i tipi, altrimenti il
# server risponde 406 Not Acceptable (stesso quirk gestito dal bot).
_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


class MCPCallError(Exception):
    """Errore di chiamata tool MCP (rete, upstream sconosciuto, tool fallito)."""


async def call_tool(
    service: str, tool: str, args: dict[str, Any] | None = None, *,
    timeout: float = 60.0,
) -> list[str]:
    """Chiama `tool` sull'upstream `service` e ritorna i content block testuali.
    Solleva MCPCallError con messaggio user-safe in ogni caso di fallimento."""
    s = get_settings()
    upstream = s.gateway_upstreams.get(service)
    if not upstream:
        raise MCPCallError(f"servizio sconosciuto: {service}")
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": args or {}},
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=5.0)) as client:
            resp = await client.post(f"http://{upstream}/mcp", json=payload, headers=_HEADERS)
            resp.raise_for_status()
            rpc = parse_mcp_payload(resp.headers.get("content-type", ""), resp.text)
            return extract_tool_texts(rpc)
    except MCPCallError:
        raise
    except httpx.HTTPStatusError as exc:
        log.warning("mcp call %s/%s → HTTP %s", service, tool, exc.response.status_code)
        raise MCPCallError(f"upstream {service}: HTTP {exc.response.status_code}") from exc
    except httpx.RequestError as exc:
        log.warning("mcp call %s/%s → %s", service, tool, exc)
        raise MCPCallError(f"upstream {service} non raggiungibile") from exc
    except ValueError as exc:  # payload malformato o tool isError
        raise MCPCallError(str(exc)) from exc
