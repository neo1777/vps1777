"""Entry point esempio MCP plugin."""
from __future__ import annotations

import logging
import os
import sys

from fastmcp import FastMCP

logging.basicConfig(level="INFO", stream=sys.stdout)

mcp = FastMCP("example")


@mcp.tool()
def hello(name: str = "world") -> str:
    """Saluta. Tool di esempio."""
    return f"Hello, {name}! (from vps1777 example plugin)"


@mcp.tool()
def echo(payload: dict) -> dict:
    """Echo del payload ricevuto. Utile per debug."""
    return {"received": payload}


def main() -> None:
    host = os.environ.get("PLUGIN_HOST", "0.0.0.0")
    port = int(os.environ.get("PLUGIN_PORT", "8010"))
    stateless = os.environ.get("FASTMCP_STATELESS_HTTP", "true").lower() == "true"
    log = logging.getLogger("example-mcp")
    log.info("example-mcp starting on %s:%s", host, port)
    mcp.run(transport="streamable-http", host=host, port=port, stateless_http=stateless)


if __name__ == "__main__":
    main()
