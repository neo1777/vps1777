"""Entry point archive-mcp: avvia FastMCP streamable-http."""
from __future__ import annotations

import logging
import sys

from .server import mcp
from .settings import get_settings


def main() -> None:
    s = get_settings()
    logging.basicConfig(
        level=s.log_level.upper(),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
    )
    log = logging.getLogger("archive-mcp")
    log.info("vps1777-archive-mcp starting")
    log.info("listen=%s:%s stateless=%s", s.archive_http_host, s.archive_http_port, s.fastmcp_stateless_http)

    # host/port/stateless sono già nel costruttore FastMCP (server.py)
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
