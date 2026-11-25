"""Entry point esempio bot Telegram plugin."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(level="INFO", stream=sys.stdout)
log = logging.getLogger("example-bot")


def _read_token() -> str:
    """Il token dal file indicato, oppure dall'ambiente SOLO se nessun file è stato indicato.

    Se `TELEGRAM_BOT_TOKEN_FILE` è impostato e il file non c'è, non si ripiega in silenzio
    sulla variabile d'ambiente: una configurazione sbagliata deve fermare il bot, non farlo
    partire con un altro token.
    """
    path = os.environ.get("TELEGRAM_BOT_TOKEN_FILE", "")
    if path:
        try:
            return Path(path).read_text(encoding="utf-8").strip()
        except OSError as e:
            log.error("TELEGRAM_BOT_TOKEN_FILE=%s non si legge (%s)", path, type(e).__name__)
            return ""
    return os.environ.get("TELEGRAM_BOT_TOKEN", "")


# Il battito: il healthcheck del compose guarda l'età di questo file. Un bot non ha una porta da
# interrogare; un file toccato dal ciclo di eventi dice che il processo c'è E che il ciclo gira.
HEARTBEAT_FILE = Path(os.environ.get("BOT_HEARTBEAT_FILE", "/tmp/example-bot.heartbeat"))
HEARTBEAT_OGNI_S = 30


async def _batti() -> None:
    while True:
        try:
            HEARTBEAT_FILE.touch()
        except OSError as e:
            log.warning("battito non scritto (%s): il container risulterà non sano", type(e).__name__)
        await asyncio.sleep(HEARTBEAT_OGNI_S)


def _owner_id() -> int:
    """L'unico utente a cui il bot risponde. 0 = nessuno (chiuso finché non lo imposti)."""
    try:
        return int(os.environ.get("OWNER_ID", "0") or "0")
    except ValueError:
        return 0


def autorizzato(user_id: int | None, owner: int) -> bool:
    """Un bot che gira sulla tua macchina non risponde a chiunque lo trovi: solo al proprietario."""
    return bool(owner) and user_id == owner


async def cmd_start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    utente = update.effective_user
    if not autorizzato(utente.id if utente else None, _owner_id()):
        log.info("messaggio ignorato: non viene dal proprietario")
        return
    if msg:
        await msg.reply_text("Ciao da example-bot (plugin vps1777).")


async def run() -> None:
    token = _read_token()
    if not token:
        log.error("TOKEN mancante — exiting")
        sys.exit(1)
    if not _owner_id():
        log.warning("OWNER_ID non impostato: il bot parte ma non risponde a nessuno")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        battito = asyncio.create_task(_batti())
        try:
            await asyncio.Event().wait()
        finally:
            battito.cancel()
            await app.updater.stop()
            await app.stop()
            await app.shutdown()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
