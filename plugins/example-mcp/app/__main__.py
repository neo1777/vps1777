"""Entry point esempio MCP plugin."""
from __future__ import annotations

import logging
import os
import sys

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

logging.basicConfig(level="INFO", stream=sys.stdout)

_HOST = os.environ.get("PLUGIN_HOST", "0.0.0.0")
_PORT = int(os.environ.get("PLUGIN_PORT", "8010"))
_STATELESS = os.environ.get("FASTMCP_STATELESS_HTTP", "true").lower() == "true"

mcp = FastMCP(
    "example",
    host=_HOST,
    port=_PORT,
    stateless_http=_STATELESS,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


@mcp.tool()
def hello(name: str = "world") -> str:
    """Saluta. Tool di esempio."""
    return f"Hello, {name}! (from vps1777 example plugin)"


@mcp.tool()
def echo(payload: dict) -> dict:
    """Echo del payload ricevuto. Utile per debug."""
    return {"received": payload}


def main() -> None:
    log = logging.getLogger("example-mcp")
    log.info("example-mcp starting on %s:%s", _HOST, _PORT)
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
