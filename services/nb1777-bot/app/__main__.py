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
        # Niente crash-loop e niente sleep muto: bot.run() entra nel ramo
        # standby che TIENE VIVO l'heartbeat (il container resta healthy —
        # essenziale perché il health-gate di `vps1777 update` non fallisca
        # sulle installazioni senza token Telegram).
        log.warning("TELEGRAM_BOT_TOKEN mancante — bot in standby (heartbeat attivo).")
        log.warning("Configura secrets/telegram_bot_token.txt e: docker compose restart nb1777-bot")
    elif not s.telegram_owner_id:
        log.warning("TELEGRAM_OWNER_ID=0 — bot accetterà chiunque! Configura in .env")
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
