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
        dati = r.json()
        # una risposta che non è un oggetto è «non so»: vale la stessa prudenza del guasto di rete
        return not (isinstance(dati, dict) and bool(dati.get("ok")))
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
            # Solo il TIPO dell'errore: il testo intero può portare un indirizzo col token del
            # bot (gli errori di rete lo citano), e nel log quel pezzo viene mascherato, qui no.
            await update.effective_message.reply_text(
                f"Errore interno ({type(ctx.error).__name__}): il dettaglio è nei log del bot.")
    except Exception as exc:  # noqa: BLE001 — non far fallire l'error handler
        log.warning("non sono riuscito ad avvisare dell'errore (%s)", type(exc).__name__)


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


def _fonti_notifiche(s) -> list[tuple[str, str]]:
    """Le code da prelevare: nb1777-mcp (canonico, sonda, promemoria) e il gateway (i
    connettori OAuth autorizzati). Una base vuota spegne la sua coda."""
    fonti = [("nb1777-mcp", s.nlm_internal_base), ("gateway", s.gateway_internal_base)]
    return [(nome, f"{base.rstrip('/')}/internal/notifications") for nome, base in fonti if base]


async def _preleva(nome: str, url: str, segreto: str) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
            r = await client.get(url, headers={"x-vps1777-internal": segreto})
        if r.status_code != 200:
            log.warning("notifiche: %s ha risposto %s", nome, r.status_code)
            return []
        corpo = r.json()
    except (httpx.RequestError, ValueError) as exc:
        log.warning("notifiche: %s irraggiungibile (%s)", nome, exc)
        return []
    # La forma si controlla: una risposta che non è {"items": [...]} faceva sollevare
    # AttributeError, che non era catturato e uccideva il ciclo delle notifiche per sempre
    # (col battito ancora acceso, quindi container «healthy»).
    items = corpo.get("items", []) if isinstance(corpo, dict) else None
    if not isinstance(items, list):
        log.warning("notifiche: %s ha risposto con una forma inattesa (%s): scartata",
                    nome, type(corpo).__name__)
        return []
    buone = [x for x in items[:_PRELIEVO_MAX] if isinstance(x, dict)]
    if len(buone) != len(items):
        log.warning("notifiche: %s, %d elementi scartati su %d (non oggetti, o oltre il tetto di %d)",
                    nome, len(items) - len(buone), len(items), _PRELIEVO_MAX)
    return buone


async def _notify_loop(app: Application) -> None:
    """Preleva periodicamente le notifiche da nb1777-mcp e dal gateway e le manda
    all'owner. Fail-safe: se un server non risponde, logga e riprova al giro dopo."""
    s = get_settings()
    # Il prelievo SVUOTA la coda sul server: una notifica che Telegram non accetta (timeout,
    # flood) andava persa, e la sonda della sessione avvisa una volta sola. Quelle non
    # consegnate restano qui e si riprovano ai giri dopo (21/11/2026).
    in_sospeso: list[dict] = []
    while True:
        await asyncio.sleep(60)
        owner = get_settings().telegram_owner_id
        if not owner:
            continue
        # Un giro che solleva NON deve chiudere il ciclo: è l'unico che porta i promemoria,
        # e se muore nessuno se ne accorge. Si logga e si riprova al giro dopo.
        try:
            da_mandare, in_sospeso = in_sospeso, []
            for nome, url in _fonti_notifiche(s):
                da_mandare.extend(await _preleva(nome, url, s.effective_gateway_secret))
            in_sospeso = await _consegna(app, owner, da_mandare)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — qualunque errore di un giro: il ciclo resta vivo
            log.exception("giro delle notifiche fallito: riprovo fra un minuto")


_TENTATIVI_MAX = 30          # mezz'ora di giri: oltre, la notifica si lascia andare e lo si dice
_SOSPESE_MAX = 50
_PRELIEVO_MAX = 200         # notifiche accettate da una coda in un solo giro


async def _consegna(app: Application, owner: int, items: list[dict]) -> list[dict]:
    """Manda le notifiche; torna quelle NON consegnate, da riprovare al giro dopo."""
    restano: list[dict] = []
    for item in items:
        try:
            await _send_notification(app, owner, item)
        except Exception as exc:  # noqa: BLE001 — una notifica rotta non ferma il loop
            tentativi = int(item.get("_tentativi", 0)) + 1
            if tentativi >= _TENTATIVI_MAX:
                log.warning("notifica PERSA dopo %d tentativi (%s): %s",
                            tentativi, item.get("kind"), exc)
                continue
            log.warning("notifica non inviata (%s), riprovo: %s", item.get("kind"), exc)
            restano.append({**item, "_tentativi": tentativi})
    if len(restano) > _SOSPESE_MAX:
        log.warning("notifiche in sospeso oltre il tetto: %d PERSE (ne tengo %d)",
                    len(restano) - _SOSPESE_MAX, _SOSPESE_MAX)
    return restano[-_SOSPESE_MAX:]


async def cmd_ack(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Tap su «✓ Fatto»: registra l'ack presso nb1777-mcp e conferma. Owner-only
    anche qui — solo Neo può segnare che le superfici cloud sono aggiornate."""
    q = update.callback_query
    if q is None:
        return
    s = get_settings()
    # stessa regola di `owner_only`, fail-closed: chi non si sa chi è non passa (prima un
    # mittente assente rendeva falsa la condizione e l'ack passava).
    if not s.telegram_owner_id or not q.from_user or q.from_user.id != s.telegram_owner_id:
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
    # Il battito parte PRIMA di parlare con Telegram (21/11/2026). `initialize` chiama
    # `get_me`: con Telegram irraggiungibile o il token rifiutato sollevava, il processo
    # usciva e il container ripartiva in ciclo SENZA battito: unhealthy, e l'health-gate
    # faceva fallire (e tornare indietro) ogni `vps1777 update`. È lo stesso esito che il
    # ramo «senza token» qui sopra evita apposta. Ora si riprova con calma, a battito acceso.
    heartbeat = asyncio.create_task(_heartbeat_loop())
    attesa = 5.0
    while True:
        try:
            await app.initialize()
            break
        except Exception as exc:  # noqa: BLE001 — rete, timeout, token rifiutato
            log.warning("Telegram non risponde all'avvio (%s): riprovo fra %.0f s",
                        type(exc).__name__, attesa)
            await asyncio.sleep(attesa)
            attesa = min(attesa * 2, 300.0)
    notify: asyncio.Task | None = None
    try:
        await app.start()
        await _install_menu_button(app)
        await app.updater.start_polling()
        notify = asyncio.create_task(_notify_loop(app))
        await asyncio.Event().wait()          # blocca fino a SIGTERM
    finally:
        heartbeat.cancel()
        if notify is not None:
            notify.cancel()
        if app.updater is not None and app.updater.running:
            await app.updater.stop()
        if app.running:
            await app.stop()
        await app.shutdown()
