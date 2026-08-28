"""Entry point archive-mcp: avvia FastMCP streamable-http."""
from __future__ import annotations

import logging
import sys
import threading

from . import db
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

    # Riscaldamento del memo di describe(): senza, la PRIMA describe dopo un
    # riavvio paga la scansione completa (74,6 s misurati il 28/08/2026) in
    # faccia al primo client, che riceve un timeout. Un thread daemon la paga
    # qui, in avvio, senza bloccare né il server né l'healthcheck.
    threading.Thread(target=db.describe, name="describe-warmup", daemon=True).start()

    # host/port/stateless sono già nel costruttore FastMCP (server.py)
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
