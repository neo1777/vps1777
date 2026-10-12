"""
Telegram bot — owner-only, un comando solo: /start, che risponde col bottone del pannello.

Dal 12/10/2026 (scelta di Neo `2026-10-12-soglia-comandi-bot`) il bot non fa più domande ai
notebook in chat: /aiuto, /pannello, /lista e /chiedi sono stati tolti. Tutto passa dalla
Mini App (il bottone «Pannello» accanto al campo di testo, o quello che manda /start), che
parla solo col gateway: i titoli dei notebook e le risposte non passano più dai server di
Telegram. Restano il trasporto delle notifiche e il bottone «✓ Fatto» del promemoria cloud.
"""
from __future__ import annotations

import asyncio
import logging
import os
from functools import wraps
from pathlib import Path
from typing import Awaitable, Callable

import httpx
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Update,
    WebAppInfo,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from .settings import get_settings

log = logging.getLogger(__name__)


# ───── helpers ─────

async def auth_pending() -> bool:
    """
    C'è un profilo NotebookLM valido? Lo chiede a nb1777-mcp (H6): il bot non
    monta più il volume coi cookie Google — non deve poterli leggere.
    Fail-safe: se nb1777-mcp non risponde, si assume auth pendente (si mostra la
    guida invece di far partire un comando che fallirebbe comunque).
    """
    s = get_settings()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
            r = await client.get(
                f"{s.nlm_internal_base.rstrip('/')}/internal/nlm/status",
                headers={"x-vps1777-internal": s.effective_gateway_secret},
            )
        if r.status_code != 200:
            log.warning("stato nlm: nb1777-mcp ha risposto %s", r.status_code)
            return True
        return not bool(r.json().get("ok"))
    except (httpx.RequestError, ValueError) as exc:
        log.warning("stato nlm: nb1777-mcp irraggiungibile (%s)", exc)
        return True


def owner_only(
    fn: Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]],
) -> Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]:
    @wraps(fn)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        s = get_settings()
        user_id = update.effective_user.id if update.effective_user else 0
        # FAIL-CLOSED: senza owner configurato (owner_id==0) si NEGA a tutti, non
        # si apre a tutti. Prima `if owner_id and ...` corto-circuitava su 0 →
        # il bot rispondeva a chiunque. Un bot owner-only senza owner non deve
        # funzionare per nessuno finché TELEGRAM_OWNER_ID non è impostato.
        if not s.telegram_owner_id or user_id != s.telegram_owner_id:
            if update.effective_message:
                await update.effective_message.reply_text("Bot privato.")
            return
        await fn(update, ctx)
    return wrapper


# ───── comandi ─────

def _miniapp_url() -> str | None:
    """URL della Mini App, solo se il gateway è su https (requisito Telegram per
    i bottoni web_app). In dev (http) → None: niente bottone, niente errori."""
    base = get_settings().gateway_public_base
    return f"{base}/app" if base.startswith("https://") else None


# I comandi del bot: uno. Un test lo controlla contro i gestori registrati.
COMANDI = ("start",)


@owner_only
async def cmd_start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if not msg:
        return
    if await auth_pending():
        s = get_settings()
        link = f"{s.gateway_public_base}/admin/nlm" if s.gateway_public_base else "/admin/nlm"
        await msg.reply_text(
            "Ciao. Sono il bot nb1777 — ma sono ancora bloccato.\n\n"
            "⚠️ *Auth NotebookLM mancante*\n\n"
            "Cosa fare:\n"
            f"1. Apri *{link}* sul browser\n"
            "2. Login con email + password admin\n"
            "3. Sul PC: `nlm login`, poi `cd ~/.notebooklm-mcp-cli && tar czf nlm-profile.tgz profiles/default`\n"
            "4. Carica il `.tgz` — riparto automaticamente",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    url = _miniapp_url()
    if not url:
        await msg.reply_text(
            "Ciao. Sono il bot nb1777. Il pannello richiede il gateway su HTTPS pubblico "
            "(PUBLIC_BASE nel .env non è https): impostalo, ricrea il bot "
            "(`docker compose … up -d nb1777-bot`: il bot legge PUBLIC_BASE solo all'avvio) "
            "e riprova /start.")
        return
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🎛 Apri il pannello", web_app=WebAppInfo(url=url))]])
    await msg.reply_text(
        "Ciao. Sono il bot nb1777: notebook, archivio, secret e aggiornamenti stanno nel "
        "pannello (anche dal bottone «Pannello» accanto al campo di testo). Qui ti arrivano "
        "i promemoria.", reply_markup=kb)


# ───── error handler globale ─────
# Senza questo, un'eccezione in un handler viene solo loggata e l'utente resta
# in silenzio (è successo con /lista, oggi tolto). Qui rispondiamo sempre qualcosa.

async def _on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("errore handler", exc_info=ctx.error)
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text(f"Errore interno: {ctx.error}")
    except Exception:  # noqa: BLE001 — non far fallire l'error handler
        pass


# ───── heartbeat (healthcheck del container) ─────
# Il bot è long-poll puro, nessuna porta esposta: l'unica prova di vita
# osservabile da fuori è un file toccato periodicamente. Il healthcheck in
# compose verifica che il mtime sia recente (<90s) — serve anche al
# health-gate di `vps1777 update`.

HEARTBEAT_FILE = Path(os.environ.get("BOT_HEARTBEAT_FILE", "/tmp/nb1777-bot.heartbeat"))


async def _heartbeat_loop() -> None:
    while True:
        try:
            HEARTBEAT_FILE.touch()
        except OSError:  # path non scrivibile: logga, non uccidere il bot
            log.warning("heartbeat non scrivibile: %s", HEARTBEAT_FILE)
        await asyncio.sleep(30)


# ───── notifiche push (issue #30 ③) ─────
# Il bot ha rootfs read-only e nessun token verso nb1777-mcp: lo stato e la
# logica stanno nel server. Qui si fa solo trasporto — preleva le notifiche
# pronte e le manda a Neo, e rimanda l'ack del bottone. Il poll È il tick del
# promemoria cloud: niente scheduler (sul VPS non c'è cron).

async def _send_notification(app: Application, owner: int, item: dict) -> None:
    text = item.get("text") or ""
    if item.get("kind") == "cloud" and item.get("ack_version"):
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(
            "✓ Fatto (aggiornate)", callback_data=f"ack:{item['ack_version']}")]])
        await app.bot.send_message(chat_id=owner, text=text, reply_markup=kb)
    else:
        await app.bot.send_message(chat_id=owner, text=text)


async def _notify_loop(app: Application) -> None:
    """Preleva periodicamente le notifiche da nb1777-mcp e le manda all'owner.
    Fail-safe: se il server non risponde, logga e riprova al giro dopo."""
    s = get_settings()
    url = f"{s.nlm_internal_base.rstrip('/')}/internal/notifications"
    while True:
        await asyncio.sleep(60)
        owner = get_settings().telegram_owner_id
        if not owner:
            continue
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
                r = await client.get(url, headers={"x-vps1777-internal": s.effective_gateway_secret})
            if r.status_code != 200:
                log.warning("notifiche: nb1777-mcp ha risposto %s", r.status_code)
                continue
            items = r.json().get("items", [])
        except (httpx.RequestError, ValueError) as exc:
            log.warning("notifiche: nb1777-mcp irraggiungibile (%s)", exc)
            continue
        for item in items:
            try:
                await _send_notification(app, owner, item)
            except Exception as exc:  # noqa: BLE001 — una notifica rotta non ferma il loop
                log.warning("notifica non inviata (%s): %s", item.get("kind"), exc)


async def cmd_ack(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Tap su «✓ Fatto»: registra l'ack presso nb1777-mcp e conferma. Owner-only
    anche qui — solo Neo può segnare che le superfici cloud sono aggiornate."""
    q = update.callback_query
    if q is None:
        return
    s = get_settings()
    if not s.telegram_owner_id or (q.from_user and q.from_user.id != s.telegram_owner_id):
        await q.answer("non autorizzato")
        return
    version = (q.data or "").split(":", 1)[1] if ":" in (q.data or "") else ""
    ok = False
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
            r = await client.post(
                f"{s.nlm_internal_base.rstrip('/')}/internal/canonico/ack",
                headers={"x-vps1777-internal": s.effective_gateway_secret},
                json={"version": version},
            )
        ok = r.status_code == 200
    except httpx.RequestError as exc:
        log.warning("ack: nb1777-mcp irraggiungibile (%s)", exc)
    await q.answer("segnato ✓" if ok else "errore, riprova")
    if ok:
        try:
            await q.edit_message_text(f"✓ Superfici cloud segnate aggiornate a {version}.")
        except Exception as exc:  # noqa: BLE001 — cosmetico, l'ack è già registrato
            log.warning("edit ack fallito: %s", exc)


# ───── runner ─────

def build_app() -> Application:
    s = get_settings()
    if not s.effective_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN mancante — non posso partire")
    app = Application.builder().token(s.effective_token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(cmd_ack, pattern=r"^ack:"))
    app.add_error_handler(_on_error)
    return app


async def _install_menu_button(app: Application) -> None:
    """Imposta il bottone-menu del bot come launcher della Mini App (accanto al
    campo di testo). Best-effort: se il gateway non è https o Telegram rifiuta,
    logga e prosegue — /start manda comunque il bottone del pannello."""
    url = _miniapp_url()
    owner = get_settings().telegram_owner_id
    if not url or not owner:
        return
    try:
        # chat_id=owner: il bottone-menu della Mini App va SOLO all'owner. Senza
        # chat_id era il default globale → visibile a qualunque utente del bot.
        await app.bot.set_chat_menu_button(
            chat_id=owner,
            menu_button=MenuButtonWebApp(text="Pannello", web_app=WebAppInfo(url=url)),
        )
        log.info("menu button Mini App impostato per l'owner → %s", url)
    except Exception as exc:  # noqa: BLE001 — cosmetico, non deve bloccare l'avvio
        log.warning("set_chat_menu_button fallito: %s", exc)


async def run() -> None:
    # Senza token il bot NON muore: resta idle col heartbeat attivo. Un
    # crash-loop renderebbe il container unhealthy e farebbe fallire (e
    # rollbackare) ogni `vps1777 update` sulle installazioni senza Telegram.
    if not get_settings().effective_token:
        log.warning("TELEGRAM_BOT_TOKEN mancante — bot in idle (configuralo e riavvia)")
        await _heartbeat_loop()
        return
    app = build_app()
    log.info("bot starting")
    async with app:
        await app.initialize()
        await app.start()
        await _install_menu_button(app)
        await app.updater.start_polling()
        heartbeat = asyncio.create_task(_heartbeat_loop())
        notify = asyncio.create_task(_notify_loop(app))
        # blocca fino a SIGTERM
        try:
            await asyncio.Event().wait()
        finally:
            heartbeat.cancel()
            notify.cancel()
            await app.updater.stop()
            await app.stop()
            await app.shutdown()
