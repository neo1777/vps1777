"""I consigli che il bot scrive all'avvio funzionano davvero (12/10/2026).

Con TELEGRAM_OWNER_ID=0 il warning diceva `docker compose restart nb1777-bot`: un restart
NON rilegge il .env (la variabile entra quando il container nasce), quindi il bot ripartiva
con lo 0 e lo stesso warning. Ora chiede di RICREARE bot e gateway con i -f/--profile dello
stack. Senza token il consiglio era «scrivi il file e restart», che lascia indietro la chiave
derivata della Mini App: ora è `tools/rotate-secret.sh telegram_bot_token`.

Stdlib: `bot` (python-telegram-bot) e `settings` (pydantic-settings) sono sostituiti da
moduli finti in sys.modules solo per la durata del test; `main()` gira davvero.
"""
from __future__ import annotations

import importlib
import io
import logging
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app  # noqa: E402


def _avvia(monkeypatch, *, token: str, owner: int) -> str:
    async def run_finto() -> None:
        return None

    bot_finto = types.ModuleType("app.bot")
    bot_finto.run = run_finto
    settings_finto = types.ModuleType("app.settings")
    settings_finto.get_settings = lambda: types.SimpleNamespace(
        effective_token=token, telegram_owner_id=owner, log_level="INFO")
    monkeypatch.setitem(sys.modules, "app.bot", bot_finto)
    monkeypatch.setattr(app, "bot", bot_finto, raising=False)
    monkeypatch.setitem(sys.modules, "app.settings", settings_finto)
    monkeypatch.setattr(app, "settings", settings_finto, raising=False)
    monkeypatch.delitem(sys.modules, "app.__main__", raising=False)
    principale = importlib.import_module("app.__main__")

    buf = io.StringIO()
    vero = principale.registro.configura_log
    monkeypatch.setattr(principale.registro, "configura_log",
                        lambda livello: vero(livello, stream=buf))
    try:
        principale.main()
    finally:
        for h in list(logging.root.handlers):
            logging.root.removeHandler(h)
    return buf.getvalue()


def test_senza_owner_chiede_di_ricreare_non_di_riavviare(monkeypatch):
    log = _avvia(monkeypatch, token="123:tok", owner=0)
    assert "TELEGRAM_OWNER_ID=0" in log
    assert "up -d nb1777-bot gateway" in log
    assert "--profile ingress." in log
    # nominato solo per dire che NON basta
    assert "docker compose restart nb1777-bot" not in log
    assert "non rilegge il .env" in log


def test_senza_token_manda_allo_script_che_rideriva_la_chiave(monkeypatch):
    log = _avvia(monkeypatch, token="", owner=4242)
    assert "standby" in log
    assert "tools/rotate-secret.sh telegram_bot_token" in log
    assert "docker compose restart" not in log


def test_configurato_non_consiglia_niente(monkeypatch):
    log = _avvia(monkeypatch, token="123:tok", owner=4242)
    assert "WARNING" not in log
