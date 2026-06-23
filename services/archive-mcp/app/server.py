"""
FastMCP server — espone tool search MCP via streamable-http.

Stateless mode (FASTMCP_STATELESS_HTTP=true) per scalare.
"""
from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from . import db
from .settings import get_settings

log = logging.getLogger(__name__)

_s = get_settings()
mcp = FastMCP(
    "archive",
    host=_s.archive_http_host,
    port=_s.archive_http_port,
    stateless_http=_s.fastmcp_stateless_http,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,  # dietro gateway, rete interna
    ),
)


@mcp.tool()
def search(query: str, db_name: str = "", limit: int = 20) -> list[dict[str, Any]]:
    """
    Cerca testi in archivio FTS5.

    Args:
        query: stringa FTS5 (operatori: AND, OR, NOT, NEAR, "phrase")
        db_name: nome del DB ('' = tutti). Vedi list_databases().
        limit: max risultati (default 20)
    """
    return db.search(query, db_name, limit)


@mcp.tool()
def list_databases() -> list[str]:
    """Elenca i DB caricati nella registry."""
    return db.available_dbs()
