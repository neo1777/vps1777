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
        # 🔴 Diceva «bot accetterà chiunque!», cioè l'OPPOSTO di quello che il codice fa
        # (issue #71). Il gate è fail-closed — bot.py: `if not s.telegram_owner_id or
        # user_id != s.telegram_owner_id` → con owner_id==0 la prima condizione è vera
        # per chiunque, quindi NEGA A TUTTI. È la garanzia H1 di SECURITY.md, e regge.
        # Un warning che descrive il rischio sbagliato non è un dettaglio di prosa: chi
        # legge il log in produzione crede di avere un bot APERTO e agisce di corsa —
        # o, peggio, impara a non fidarsi di un gate che invece funziona.
        log.warning("TELEGRAM_OWNER_ID=0 — il bot NEGA A TUTTI (gate fail-closed): "
                    "non risponderà a nessuno, nemmeno a te. Configura in .env e: "
                    "docker compose restart nb1777-bot")
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
