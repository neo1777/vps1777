"""Il bot preleva gli avvisi da due code: nb1777-mcp (canonico, sonda, promemoria) e il
gateway (i connettori OAuth appena autorizzati, H84). Il gateway non parla con Telegram:
è il bot che legge la sua coda, con lo stesso segreto che usa per nb1777-mcp.

Importa python-telegram-bot: salta nello step stdlib e gira in quello con le deps del lock.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

pytest.importorskip("telegram")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import bot  # noqa: E402


def test_le_code_sono_due_e_una_base_vuota_spegne_la_sua():
    s = types.SimpleNamespace(nlm_internal_base="http://nb1777-mcp:8003/",
                              gateway_internal_base="http://gateway:8080")
    assert bot._fonti_notifiche(s) == [
        ("nb1777-mcp", "http://nb1777-mcp:8003/internal/notifications"),
        ("gateway", "http://gateway:8080/internal/notifications"),
    ]
    s.gateway_internal_base = ""
    assert [n for n, _ in bot._fonti_notifiche(s)] == ["nb1777-mcp"]


async def test_una_coda_che_non_risponde_non_ferma_le_altre(monkeypatch):
    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            assert headers == {"x-vps1777-internal": "s3"}
            if "gateway" in url:
                raise bot.httpx.ConnectError("giù")
            return types.SimpleNamespace(status_code=200,
                                         json=lambda: {"items": [{"kind": "x", "text": "t"}, 7]})

    monkeypatch.setattr(bot.httpx, "AsyncClient", _Client)
    assert await bot._preleva("gateway", "http://gateway:8080/internal/notifications", "s3") == []
    assert await bot._preleva("nb1777-mcp", "http://nb1777-mcp:8003/internal/notifications",
                              "s3") == [{"kind": "x", "text": "t"}]


@pytest.mark.anyio
async def test_una_notifica_non_consegnata_si_riprova_e_non_si_perde(monkeypatch):
    # giro di revisione del 21/11: il prelievo svuota la coda sul server, quindi un invio
    # fallito (timeout, flood) perdeva l'avviso; la sonda della sessione avvisa una volta sola
    inviati: list[str] = []
    guasto = {"acceso": True}

    async def manda(app, owner, item):
        if guasto["acceso"] and item["kind"] == "sessione":
            raise TimeoutError("Telegram non risponde")
        inviati.append(item["kind"])

    monkeypatch.setattr(bot, "_send_notification", manda)
    restano = await bot._consegna(None, 1, [{"kind": "sessione"}, {"kind": "oauth"}])
    assert inviati == ["oauth"] and [r["kind"] for r in restano] == ["sessione"]
    assert restano[0]["_tentativi"] == 1
    guasto["acceso"] = False
    assert await bot._consegna(None, 1, restano) == [] and inviati == ["oauth", "sessione"]


@pytest.mark.anyio
async def test_dopo_troppi_tentativi_la_notifica_si_lascia_andare(monkeypatch):
    async def manda(app, owner, item):
        raise TimeoutError("sempre giù")

    monkeypatch.setattr(bot, "_send_notification", manda)
    quasi = [{"kind": "x", "_tentativi": bot._TENTATIVI_MAX - 1}]
    assert await bot._consegna(None, 1, quasi) == []


# ── dalla rilettura col catalogo (22/11/2026) ──────────────────────────────────

def _client_che_risponde(corpo):
    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            return types.SimpleNamespace(status_code=200, json=lambda: corpo)
    return _Client


@pytest.mark.anyio
async def test_una_risposta_di_forma_sbagliata_non_uccide_il_prelievo(monkeypatch):
    """Una lista al posto dell'oggetto faceva sollevare AttributeError: il ciclo moriva per
    sempre e il container restava «healthy»."""
    for corpo in ([1, 2, 3], "testo", None, {"items": "non-una-lista"}):
        monkeypatch.setattr(bot.httpx, "AsyncClient", _client_che_risponde(corpo))
        assert await bot._preleva("gateway", "http://gateway:8080/internal/notifications", "s") == []


@pytest.mark.anyio
async def test_un_giro_che_solleva_non_chiude_il_ciclo_delle_notifiche(monkeypatch):
    giri = {"n": 0}

    async def _dormi(_s):
        giri["n"] += 1
        if giri["n"] > 3:
            raise bot.asyncio.CancelledError

    async def _preleva_rotto(*a, **k):
        raise RuntimeError("imprevisto")

    monkeypatch.setattr(bot.asyncio, "sleep", _dormi)
    monkeypatch.setattr(bot, "_preleva", _preleva_rotto)
    monkeypatch.setattr(bot, "get_settings", lambda: types.SimpleNamespace(
        telegram_owner_id=1, nlm_internal_base="http://nb1777-mcp:8003",
        gateway_internal_base="", effective_gateway_secret="s"))
    with pytest.raises(bot.asyncio.CancelledError):
        await bot._notify_loop(None)
    assert giri["n"] == 4, "il ciclo è arrivato al quarto giro nonostante tre giri falliti"


@pytest.mark.anyio
async def test_l_ack_senza_mittente_non_passa():
    risposte = []

    async def _answer(testo):
        risposte.append(testo)

    q = types.SimpleNamespace(from_user=None, data="ack:v2.6", answer=_answer)
    vecchio = bot.get_settings
    bot.get_settings = lambda: types.SimpleNamespace(telegram_owner_id=1)
    try:
        await bot.cmd_ack(types.SimpleNamespace(callback_query=q), None)
    finally:
        bot.get_settings = vecchio
    assert risposte == ["non autorizzato"]


@pytest.mark.parametrize("risposta, atteso", [
    ({"ok": True}, False), ({"ok": False}, True), ({}, True),
    ([1, 2], True), ("ok", True), (None, True), (7, True),          # JSON valido, forma sbagliata: «non so»
])
def test_lo_stato_di_nlm_con_una_risposta_della_forma_sbagliata_e_prudente(monkeypatch, risposta, atteso):
    """`auth_pending` promette: se non so, mostro la guida. Con una lista al posto dell'oggetto
    sollevava AttributeError dentro il comando (23/11/2026, stessa classe del client del gateway)."""
    import asyncio

    import httpx
    vero = httpx.AsyncClient
    monkeypatch.setattr(bot.httpx, "AsyncClient", lambda **kw: vero(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=risposta)), **kw))
    monkeypatch.setattr(bot, "get_settings", lambda: types.SimpleNamespace(
        nlm_internal_base="http://nb1777-mcp:8003", effective_gateway_secret="s" * 32))
    assert asyncio.run(bot.auth_pending()) is atteso
