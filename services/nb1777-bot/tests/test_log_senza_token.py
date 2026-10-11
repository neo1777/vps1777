"""Il token del bot non finisce nei log (H81, 11/10/2026).

python-telegram-bot parla con Telegram via httpx, e httpx scrive a INFO ogni richiesta con
l'URL intero: `https://api.telegram.org/bot<id>:<token>/getUpdates`. Col livello del bot a
INFO, il token finiva nel log del container ogni 10 secondi (trovato dal vivo l'11/10).
Due difese: il logger di httpx (e httpcore) a WARNING, e un filtro sul gestore del log che
maschera `bot<id>:<token>` in qualunque riga, anche nel testo di un'eccezione.

Stdlib: `configura_log` non importa python-telegram-bot.
"""
from __future__ import annotations

import io
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import registro  # noqa: E402

FINTO = "bot1234567890:AAE0finto_finto-finto_finto_finto_fint"


def _log_in(buf: io.StringIO) -> None:
    for h in list(logging.root.handlers):
        logging.root.removeHandler(h)
    registro.configura_log("INFO", stream=buf)


def test_httpx_non_scrive_le_richieste_a_info():
    buf = io.StringIO()
    _log_in(buf)
    logging.getLogger("httpx").info('HTTP Request: POST https://api.telegram.org/%s/getUpdates "200"', FINTO)
    logging.getLogger("httpcore").info("connect %s", FINTO)
    assert buf.getvalue() == ""
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING


def test_il_token_si_maschera_anche_negli_altri_log():
    buf = io.StringIO()
    _log_in(buf)
    logging.getLogger("telegram.ext").warning("NetworkError su https://api.telegram.org/%s/getMe", FINTO)
    try:
        raise RuntimeError(f"connessione caduta: https://api.telegram.org/{FINTO}/send")
    except RuntimeError:
        logging.getLogger("nb1777-bot").exception("errore handler")
    out = buf.getvalue()
    assert "AAE0finto" not in out and "1234567890:" not in out
    assert out.count("bot<redatto>") == 2


def test_i_log_del_bot_restano():
    buf = io.StringIO()
    _log_in(buf)
    logging.getLogger("nb1777-bot").info("bot starting")
    assert "bot starting" in buf.getvalue()
