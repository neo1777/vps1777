"""
Telegram bot — owner-only, MVP con 4 comandi.

In F8 estendiamo a tutti i ~60 del vecchio nb1777/bot.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
from functools import wraps
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from .settings import get_settings

log = logging.getLogger(__name__)


# ───── helpers ─────

def auth_pending() -> bool:
    s = get_settings()
    # nlm 0.7.x: l'auth è il profilo profiles/default/cookies.json (non auth.json)
    cookies = Path(s.nlm_home) / "profiles" / "default" / "cookies.json"
    return (Path(s.nlm_home) / "AUTH_PENDING.flag").exists() or not cookies.exists()


def owner_only(
    fn: Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]],
) -> Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]:
    @wraps(fn)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        s = get_settings()
        user_id = update.effective_user.id if update.effective_user else 0
        if s.telegram_owner_id and user_id != s.telegram_owner_id:
            if update.effective_message:
                await update.effective_message.reply_text("Bot privato.")
            return
        await fn(update, ctx)
    return wrapper


async def _mcp_call(tool: str, args: dict[str, Any] | None = None) -> Any:
    """Chiama un tool MCP via streamable-http. MVP: single-shot, no session."""
    s = get_settings()
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": args or {}},
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(s.nb1777_mcp_url, json=payload)
        resp.raise_for_status()
        return resp.json()


# ───── comandi ─────

@owner_only
async def cmd_start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if not msg:
        return
    if auth_pending():
        s = get_settings()
        link = f"{s.gateway_public_base}/admin/nlm" if s.gateway_public_base else "/admin/nlm"
        await msg.reply_text(
            "Ciao. Sono il bot nb1777 — ma sono ancora bloccato.\n\n"
            "⚠️ *Auth NotebookLM mancante*\n\n"
            "Cosa fare:\n"
            f"1. Apri *{link}* sul browser\n"
            "2. Login con email + password admin\n"
            "3. Sul PC: `nlm login`, poi `tar czf nlm-profile.tgz profiles/default`\n"
            "4. Carica il `.tgz` — riparto automaticamente",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    await msg.reply_text(
        "Ciao. Sono il bot nb1777 — ponte tra te e NotebookLM.\n"
        "Scrivi /aiuto per l'elenco comandi."
    )


@owner_only
async def cmd_aiuto(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if not msg:
        return
    await msg.reply_text(
        "*Comandi nb1777*\n\n"
        "/lista — elenca i tuoi notebook\n"
        "/chiedi `<id> <domanda>` — domanda RAG su un notebook\n"
        "/aiuto — questo messaggio\n"
        "\n_MVP. La versione completa con tutti i comandi arriva in F8._",
        parse_mode=ParseMode.MARKDOWN,
    )


@owner_only
async def cmd_lista(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if not msg:
        return
    try:
        result = await _mcp_call("nb_list")
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        await msg.reply_text(f"Errore MCP: {exc}")
        return
    content = result.get("result", {}).get("content", [])
    if not content:
        await msg.reply_text("Nessun notebook (o auth mancante — /start).")
        return
    # Mostra primi 20 notebook (titolo + id)
    body = result.get("result", {}).get("content", [{}])[0].get("text", "")
    try:
        nb = json.loads(body) if isinstance(body, str) else body
    except json.JSONDecodeError:
        nb = []
    if not nb:
        await msg.reply_text(body[:3500] or "Risposta vuota.")
        return
    out = "\n".join(
        f"• `{n.get('id', '?')}` {n.get('title', '(senza titolo)')}"
        for n in nb[:30]
    )
    await msg.reply_text(out, parse_mode=ParseMode.MARKDOWN)


@owner_only
async def cmd_chiedi(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if not msg:
        return
    args = ctx.args or []
    if len(args) < 2:
        await msg.reply_text("Uso: /chiedi <id_notebook> <domanda>")
        return
    nb_id = args[0]
    question = " ".join(args[1:])
    try:
        result = await _mcp_call("notebook_query", {"notebook_id": nb_id, "question": question})
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        await msg.reply_text(f"Errore MCP: {exc}")
        return
    content = result.get("result", {}).get("content", [])
    text = content[0].get("text", "") if content else ""
    await msg.reply_text(text[:4000] or "Risposta vuota.")


# ───── runner ─────

def build_app() -> Application:
    s = get_settings()
    if not s.effective_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN mancante — non posso partire")
    app = Application.builder().token(s.effective_token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("aiuto", cmd_aiuto))
    app.add_handler(CommandHandler("lista", cmd_lista))
    app.add_handler(CommandHandler("chiedi", cmd_chiedi))
    return app


async def run() -> None:
    app = build_app()
    log.info("bot starting")
    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        # blocca fino a SIGTERM
        try:
            await asyncio.Event().wait()
        finally:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()
