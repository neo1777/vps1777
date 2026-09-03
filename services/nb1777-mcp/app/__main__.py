from __future__ import annotations

import logging
import sys

from . import auth
from . import server
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
    # Il bind VERO è quello del costruttore FastMCP (server.HOST/PORT, da env
    # NB1777_HOST/NB1777_PORT): loggare settings.nb1777_host qui stampava
    # 0.0.0.0 mentre il server bindava 127.0.0.1 — due default diversi per lo
    # stesso fatto, e il log mentiva (misurato al banco /health, 03/09).
    log.info("listen=%s:%s transport=%s", server.HOST, server.PORT, s.nb1777_transport)

    # Setup HOME per nlm (cerca auth.json in ~/.notebooklm-mcp-cli/)
    auth.ensure_nlm_home_in_env()

    # FastMCP run senza ridichiarare host/port — già nel costruttore.
    mcp.run(transport=s.nb1777_transport)


if __name__ == "__main__":
    main()
