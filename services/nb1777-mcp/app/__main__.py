from __future__ import annotations

import logging
import sys

from . import auth
from .server import mcp
from .settings import get_settings


def main() -> None:
    s = get_settings()
    logging.basicConfig(
        level=s.log_level.upper(),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
    )
    log = logging.getLogger("nb1777-mcp")
    log.info("vps1777-nb1777-mcp starting")
    log.info("listen=%s:%s transport=%s", s.nb1777_host, s.nb1777_port, s.nb1777_transport)

    # Setup HOME per nlm (cerca auth.json in ~/.notebooklm-mcp-cli/)
    auth.ensure_nlm_home_in_env()

    mcp.run(
        transport=s.nb1777_transport,
        host=s.nb1777_host,
        port=s.nb1777_port,
        stateless_http=s.fastmcp_stateless_http,
    )


if __name__ == "__main__":
    main()
