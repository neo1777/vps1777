from __future__ import annotations

import asyncio
import logging

from . import bot, registro
from .settings import get_settings


def main() -> None:
    s = get_settings()
    # H81: httpx a WARNING e il token mascherato in ogni riga (registro.py)
    registro.configura_log(s.log_level)
    log = logging.getLogger("nb1777-bot")
    log.info("vps1777-nb1777-bot starting")
    if not s.effective_token:
        # Niente crash-loop e niente sleep muto: bot.run() entra nel ramo
        # standby che TIENE VIVO l'heartbeat (il container resta healthy —
        # essenziale perché il health-gate di `vps1777 update` non fallisca
        # sulle installazioni senza token Telegram).
        log.warning("TELEGRAM_BOT_TOKEN mancante — bot in standby (heartbeat attivo).")
        # Non «scrivi il file e restart»: il gateway verifica la Mini App con la chiave
        # DERIVATA dal token (H54), e un token scritto a mano la lascia indietro — il bot
        # risponde e il pannello rifiuta tutti. Lo script scrive il token, rideriva la
        # chiave e riavvia bot e gateway (docs/SECRETS.md).
        log.warning("Configura il token con: tools/rotate-secret.sh telegram_bot_token "
                    "(scrive secrets/telegram_bot_token.txt, rideriva la chiave della "
                    "Mini App e riavvia bot e gateway)")
    elif not s.telegram_owner_id:
        # 🔴 Diceva «bot accetterà chiunque!», cioè l'OPPOSTO di quello che il codice fa
        # (issue #71). Il gate è fail-closed — bot.py: `if not s.telegram_owner_id or
        # user_id != s.telegram_owner_id` → con owner_id==0 la prima condizione è vera
        # per chiunque, quindi NEGA A TUTTI. È la garanzia H1 di SECURITY.md, e regge.
        # Un warning che descrive il rischio sbagliato non è un dettaglio di prosa: chi
        # legge il log in produzione crede di avere un bot APERTO e agisce di corsa —
        # o, peggio, impara a non fidarsi di un gate che invece funziona.
        # 🔴 Il consiglio era `docker compose restart nb1777-bot`, che NON rilegge il .env:
        #   il container ripartiva con la variabile vecchia e il warning tornava identico.
        #   TELEGRAM_OWNER_ID entra quando il container NASCE, quindi va ricreato — e col
        #   bot anche il gateway, che lo legge per la Mini App e per il proxy. Ricreati con
        #   gli stessi -f/--profile dello stack: un `up -d gateway` col solo compose.yaml
        #   toglie al gateway il suo ingresso (docs/TROUBLESHOOTING.md).
        log.warning("TELEGRAM_OWNER_ID=0 — il bot NEGA A TUTTI (gate fail-closed): "
                    "non risponderà a nessuno, nemmeno a te. Impostalo in .env e RICREA "
                    "bot e gateway (`docker compose restart` non rilegge il .env), con gli "
                    "stessi -f/--profile dello stack: docker compose -f compose.yaml "
                    "-f compose.ingress.<ingresso>.yaml [gli overlay delle feature] "
                    "--profile ingress.<ingresso> up -d nb1777-bot gateway — vedi "
                    "docs/TROUBLESHOOTING.md, «Ricreare il gateway dopo un cambio del .env»")
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
