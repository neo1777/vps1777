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
    path = os.environ.get("TELEGRAM_BOT_TOKEN_FILE", "")
    if path and Path(path).is_file():
        return Path(path).read_text(encoding="utf-8").strip()
    return os.environ.get("TELEGRAM_BOT_TOKEN", "")


async def cmd_start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg:
        await msg.reply_text("Ciao da example-bot (plugin vps1777).")


async def run() -> None:
    token = _read_token()
    if not token:
        log.error("TOKEN mancante — exiting")
        sys.exit(1)
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        try:
            await asyncio.Event().wait()
        finally:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
