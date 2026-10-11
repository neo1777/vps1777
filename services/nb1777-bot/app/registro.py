"""Il log del bot, senza il token (H81, 11/10/2026).

python-telegram-bot parla con Telegram via httpx, e httpx scrive a INFO ogni richiesta con
l'URL intero, che contiene il token: `https://api.telegram.org/bot<id>:<token>/…`. Col
livello del bot a INFO, il token finiva nel log del container ogni 10 secondi. Due difese:
httpx e httpcore a WARNING (le richieste riuscite non si scrivono più), e un filtro sul
gestore che maschera `bot<id>:<token>` in qualunque riga, compreso il testo di
un'eccezione (un errore di rete può riportare l'URL).
"""
from __future__ import annotations

import logging
import re
import sys
from typing import TextIO

_TOKEN = re.compile(r"bot\d{5,}:[A-Za-z0-9_-]{20,}")
_RUMOROSI = ("httpx", "httpcore")


class MascheraToken(logging.Filter):
    """Riscrive il messaggio e il traceback della riga con il token mascherato."""

    def filter(self, record: logging.LogRecord) -> bool:
        testo = record.getMessage()
        if _TOKEN.search(testo):
            record.msg = _TOKEN.sub("bot<redatto>", testo)
            record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text and _TOKEN.search(record.exc_text):
            record.exc_text = _TOKEN.sub("bot<redatto>", record.exc_text)
        return True


def configura_log(livello: str, *, stream: TextIO | None = None) -> None:
    logging.basicConfig(
        level=livello.upper(),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=stream or sys.stdout,
        force=True,
    )
    for h in logging.root.handlers:
        h.addFilter(MascheraToken())
    for nome in _RUMOROSI:
        logging.getLogger(nome).setLevel(logging.WARNING)
