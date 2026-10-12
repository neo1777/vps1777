"""Il bot ha un comando solo: /start (12/10/2026, scelta di Neo `2026-10-12-soglia-comandi-bot`).

/aiuto, /pannello, /lista e /chiedi sono tolti: le domande ai notebook passano dalla Mini App,
che non le fa transitare dai server di Telegram. /start risponde col bottone del pannello.

Importa python-telegram-bot: salta nello step stdlib e gira in quello con le deps del lock
(ci.yml e tools/check.sh lo nominano). Update e contesto sono finti e minimi.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("telegram")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from telegram.ext import CallbackQueryHandler, CommandHandler  # noqa: E402

from app import bot  # noqa: E402
from app.settings import get_settings  # noqa: E402

NEO = 4242


class _Msg:
    chat_id = 1

    def __init__(self) -> None:
        self.inviati: list[tuple[str, dict]] = []

    async def reply_text(self, text: str, **k) -> "_Msg":
        self.inviati.append((text, k))
        return self


class _Utente:
    def __init__(self, uid: int) -> None:
        self.id = uid


class _Update:
    def __init__(self, msg: _Msg, uid: int = NEO) -> None:
        self.effective_message = msg
        self.effective_user = _Utente(uid)
        self.callback_query = None


@pytest.fixture(autouse=True)
def proprietario(monkeypatch):
    monkeypatch.setenv("TELEGRAM_OWNER_ID", str(NEO))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:finto")
    monkeypatch.setenv("GATEWAY_PUBLIC_BASE", "https://vps.example.invalid")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_i_gestori_sono_start_e_l_ack():
    app = bot.build_app()
    gestori = [h for gruppo in app.handlers.values() for h in gruppo]
    comandi = sorted(c for h in gestori if isinstance(h, CommandHandler) for c in h.commands)
    assert comandi == list(bot.COMANDI) == ["start"]
    assert [h.pattern.pattern for h in gestori if isinstance(h, CallbackQueryHandler)] == [r"^ack:"]


async def test_start_manda_il_bottone_del_pannello(monkeypatch):
    async def pronta() -> bool:
        return False

    monkeypatch.setattr(bot, "auth_pending", pronta)
    msg = _Msg()
    await bot.cmd_start(_Update(msg), None)
    (testo, k), = msg.inviati
    bottone = k["reply_markup"].inline_keyboard[0][0]
    assert bottone.web_app.url == "https://vps.example.invalid/app"
    assert "pannello" in testo


async def test_senza_https_lo_dice(monkeypatch):
    async def pronta() -> bool:
        return False

    monkeypatch.setattr(bot, "auth_pending", pronta)
    monkeypatch.setenv("GATEWAY_PUBLIC_BASE", "http://gateway:8080")
    get_settings.cache_clear()
    msg = _Msg()
    await bot.cmd_start(_Update(msg), None)
    assert "HTTPS" in msg.inviati[0][0] and "reply_markup" not in msg.inviati[0][1]


async def test_con_l_auth_mancante_spiega_cosa_fare(monkeypatch):
    async def manca() -> bool:
        return True

    monkeypatch.setattr(bot, "auth_pending", manca)
    msg = _Msg()
    await bot.cmd_start(_Update(msg), None)
    assert "Auth NotebookLM mancante" in msg.inviati[0][0]


async def test_un_estraneo_no(monkeypatch):
    msg = _Msg()
    await bot.cmd_start(_Update(msg, uid=99), None)
    assert msg.inviati == [("Bot privato.", {})]
