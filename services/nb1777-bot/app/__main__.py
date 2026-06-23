from __future__ import annotations

import asyncio
import logging
import sys

from . import bot
from .settings import get_settings


def main() -> None:
    s = get_settings()
    logging.basicConfig(
        level=s.log_level.upper(),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
    )
    log = logging.getLogger("nb1777-bot")
    log.info("vps1777-nb1777-bot starting")
    if not s.effective_token:
        log.error("TELEGRAM_BOT_TOKEN missing — exiting")
        sys.exit(1)
    if not s.telegram_owner_id:
        log.warning("TELEGRAM_OWNER_ID=0 — bot accetterà chiunque! Configura in .env")
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
