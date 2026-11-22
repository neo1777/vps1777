"""I file dichiarativi (compose, plugin d'esempio) dopo la rilettura col catalogo di requisiti.

Tre cose tenute qui:
  · il controllo di salute di cloudflared non dipende da una shell che l'immagine non ha;
  · ogni servizio di ogni compose, plugin compresi, ha un tetto ai log (l'ancora non
    attraversa i file, e i due plugin ne erano rimasti senza);
  · il bot d'esempio risponde solo al proprietario e non ripiega in silenzio su un altro token.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = sorted(ROOT.glob("compose*.yaml")) + sorted(ROOT.glob("plugins/*/compose*.yaml"))


def _servizi():
    for f in COMPOSE:
        dati = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        for nome, s in (dati.get("services") or {}).items():
            yield f, nome, s or {}


def test_ci_sono_compose_da_guardare() -> None:
    assert len(COMPOSE) >= 10 and any("plugins" in str(f) for f in COMPOSE)


def test_ogni_servizio_ha_un_tetto_ai_log() -> None:
    """Per NOME di servizio: basta che uno dei file che lo definiscono porti il tetto (gli
    overlay di build o di immagine si sommano al file che lo dichiara)."""
    col_tetto: set[str] = set()
    tutti: dict[str, str] = {}
    for f, nome, s in _servizi():
        tutti.setdefault(nome, str(f.relative_to(ROOT)))
        opzioni = (s.get("logging") or {}).get("options") or {}
        if opzioni.get("max-size") and opzioni.get("max-file"):
            col_tetto.add(nome)
    senza = {n: dove for n, dove in tutti.items() if n not in col_tetto}
    assert not senza, f"servizi senza tetto ai log (json-file cresce fino a disco pieno): {senza}"


def test_il_controllo_di_salute_di_cloudflared_non_vuole_una_shell() -> None:
    dati = yaml.safe_load((ROOT / "compose.ingress.cloudflared.yaml").read_text(encoding="utf-8"))
    s = dati["services"]["cloudflared"]
    prova = s["healthcheck"]["test"]
    assert prova[0] == "CMD", "CMD-SHELL vuole /bin/sh, che l'immagine di cloudflared non ha"
    assert prova[1] == "cloudflared" and prova[-1] == "ready"
    dove = prova[prova.index("--metrics") + 1]
    assert dove.startswith("127.0.0.1:"), "l'endpoint delle metriche resta sul loopback"
    comando = s["command"]
    assert comando[comando.index("--metrics") + 1] == dove, \
        "il tunnel deve aprire le metriche allo stesso indirizzo a cui il controllo le chiede"


# ── il bot d'esempio ───────────────────────────────────────────────────────────

@pytest.fixture()
def bot(monkeypatch):
    telegram = types.ModuleType("telegram")
    telegram.Update = object
    ext = types.ModuleType("telegram.ext")
    ext.Application = ext.CommandHandler = object
    ext.ContextTypes = types.SimpleNamespace(DEFAULT_TYPE=object)
    monkeypatch.setitem(sys.modules, "telegram", telegram)
    monkeypatch.setitem(sys.modules, "telegram.ext", ext)
    spec = importlib.util.spec_from_file_location("example_bot_main", ROOT / "plugins/example-bot/app/__main__.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_il_bot_risponde_solo_al_proprietario(bot) -> None:
    assert bot.autorizzato(42, 42)
    assert not bot.autorizzato(7, 42)
    assert not bot.autorizzato(None, 42)
    assert not bot.autorizzato(0, 0), "senza proprietario impostato non risponde a nessuno"


def test_owner_id_scritto_male_vale_nessuno(bot, monkeypatch) -> None:
    monkeypatch.setenv("OWNER_ID", "non-un-numero")
    assert bot._owner_id() == 0


def test_un_file_del_token_indicato_e_assente_non_ripiega_sull_ambiente(bot, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_FILE", str(tmp_path / "non-c-e.txt"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "un-altro-token")
    assert bot._read_token() == ""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN_FILE")
    assert bot._read_token() == "un-altro-token"


def test_env_example_non_promette_piu_un_audit_senza_limite() -> None:
    testo = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "cresce senza" not in testo
