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
        # Niente crash-loop: dormiamo in attesa che il token venga
        # configurato (secrets/telegram_bot_token.txt) + restart del container.
        log.warning("TELEGRAM_BOT_TOKEN mancante — bot in standby.")
        log.warning("Configura secrets/telegram_bot_token.txt e: docker compose restart nb1777-bot")
        try:
            import time
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return
    if not s.telegram_owner_id:
        log.warning("TELEGRAM_OWNER_ID=0 — bot accetterà chiunque! Configura in .env")
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
