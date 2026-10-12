"""L'URL finale dell'installer grafico è quello PUBBLICO — `installer/engine.py`.

🔴 IL DIFETTO (verifica della doc del 12/10/2026): `result["URL"]` si impostava solo nel
ramo Tailscale; con Caddy o Cloudflare `collect_result` ripiegava su
`http://<IP>:8080`. Con quegli ingressi la 8080 sta su 127.0.0.1 (compose.onboarding),
quindi la schermata finale mostrava un URL irraggiungibile, e gli URL connector per
claude.ai — che la UI costruisce SOPRA quell'URL — non funzionavano. Per Cloudflare,
in più, l'installer non conosceva nemmeno l'hostname: il token del tunnel non lo
contiene, e il pannello non lo chiedeva.

⭐ Cosa tengono fermo questi test: caddy → https://<dominio>, cloudflared →
https://<hostname del tunnel>, tailscale → niente qui (l'URL nasce dopo, dal Funnel);
la UI manda l'hostname; un nome malformato è un errore detto prima di toccare la VPS.

📌 `paramiko` è stubbato come in test_installer_funnel.py: è la sola dipendenza esterna
dell'installer e in CI non c'è.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_ENGINE = _ROOT / "installer" / "engine.py"
_UI = _ROOT / "installer" / "ui.html"

_paramiko = sys.modules.setdefault("paramiko", types.ModuleType("paramiko"))
if not hasattr(_paramiko, "AuthenticationException"):
    # run() la nomina nel suo `except`: senza, lo stub non arriva al ramo DeployError.
    _paramiko.AuthenticationException = type("AuthenticationException", (Exception,), {})
_spec = importlib.util.spec_from_file_location("installer_engine_url", _ENGINE)
eng = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eng)


# ───────────────────────── _public_base, la funzione pura ─────────────────────────

def test_caddy_da_il_dominio_in_https():
    assert eng._public_base({"caddy_domain": "vps.example.invalid"}, "caddy") == \
        "https://vps.example.invalid"


def test_cloudflared_da_l_hostname_del_tunnel_in_https():
    assert eng._public_base({"cf_token": "eyJ-finto", "cf_hostname": "mcp.example.invalid"},
                            "cloudflared") == "https://mcp.example.invalid"


def test_cloudflared_senza_hostname_non_inventa_niente():
    # Senza hostname l'URL pubblico NON si conosce: "" (la schermata ripiega e avvisa),
    # non un https:// costruito dal nulla.
    assert eng._public_base({"cf_token": "eyJ-finto"}, "cloudflared") == ""


def test_tailscale_qui_non_lo_sa_ancora():
    # L'URL *.ts.net nasce in step_tailscale_host: il dominio di Caddy, se il form lo
    # avesse ancora compilato, non deve diventare l'URL di un'installazione Tailscale.
    assert eng._public_base({"caddy_domain": "vps.example.invalid"}, "tailscale") == ""


@pytest.mark.parametrize("scritto", [
    "https://vps.example.invalid", "https://vps.example.invalid/", "  vps.example.invalid  ",
    "http://vps.example.invalid", "HTTPS://vps.example.invalid",
])
def test_il_nome_si_accetta_come_lo_si_copia_dal_browser(scritto):
    assert eng._public_base({"caddy_domain": scritto}, "caddy") == "https://vps.example.invalid"


@pytest.mark.parametrize("scritto", [
    "vps.example.invalid/admin", "vps example.invalid", "vps.example.invalid:8443",
    "localhost", "vps.example.invalid;rm", "-vps.example.invalid",
])
def test_un_nome_malformato_e_un_errore_che_dice_cosa_fare(scritto):
    with pytest.raises(eng.DeployError) as e:
        eng._public_base({"cf_hostname": scritto}, "cloudflared")
    assert "non valido" in str(e.value) and "rilancia" in str(e.value)


# ───────────── step_config → collect_result: l'URL che arriva alla schermata ─────────────

class _Finto(eng.Deployer):
    """Un Deployer senza SSH: registra gli script invece di eseguirli."""

    def __init__(self):
        super().__init__("192.0.2.10", "root", "")
        self.script = ""

    def _sudo_stdin(self) -> str:
        return "bash -s"

    def _sudo(self, inner: str) -> str:
        return inner

    def _stream(self, cmd, label="", stdin_script=None):
        self.script = stdin_script or ""
        yield "CONFIG_OK"

    def _run_capture(self, cmd: str) -> str:
        return "segreto-finto"


def _referto(params: dict) -> dict:
    d = _Finto()
    list(d.step_config(params))
    righe = list(d.collect_result())
    risultato = dict(r[len("RESULT_"):].split("=", 1) for r in righe if r.startswith("RESULT_"))
    return {"risultato": risultato, "script": d.script}


def test_con_caddy_la_schermata_mostra_https_e_non_l_ip():
    r = _referto({"ingress_num": "2", "caddy_domain": "https://vps.example.invalid/",
                  "caddy_email": "prova@example.invalid"})
    assert r["risultato"]["URL"] == "https://vps.example.invalid"
    assert r["risultato"]["SETUP_URL"] == "https://vps.example.invalid/admin/setup"
    assert "192.0.2.10" not in r["risultato"]["URL"]
    # e il .env riceve gli stessi valori, normalizzati (Caddy chiede il cert per il NOME)
    assert "set_kv PUBLIC_BASE https://vps.example.invalid" in r["script"]
    assert "set_kv CADDY_DOMAIN vps.example.invalid" in r["script"]


def test_con_cloudflared_la_schermata_mostra_l_hostname_del_tunnel():
    r = _referto({"ingress_num": "3", "cf_token": "eyJ-finto-abcdef",
                  "cf_hostname": "mcp.example.invalid"})
    assert r["risultato"]["URL"] == "https://mcp.example.invalid"
    assert "set_kv PUBLIC_BASE https://mcp.example.invalid" in r["script"]


def test_con_cloudflared_senza_hostname_resta_il_ripiego_dichiarato():
    # La UI, davanti a un URL http, mostra l'avviso che chiede di sostituire la base.
    r = _referto({"ingress_num": "3", "cf_token": "eyJ-finto-abcdef"})
    assert r["risultato"]["URL"] == "http://192.0.2.10:8080"


def test_con_tailscale_step_config_non_fissa_l_url():
    d = _Finto()
    list(d.step_config({"ingress_num": "1", "ts_authkey": "tskey-auth-finta"}))
    assert "URL" not in d.result, "l'URL Tailscale lo fissa step_tailscale_host, dal Funnel"


def test_il_nome_malformato_ferma_run_prima_di_connettersi():
    connessioni = []
    vecchio = eng.Deployer.connect
    eng.Deployer.connect = lambda self: connessioni.append(1)
    try:
        righe = list(eng.run({"ip": "192.0.2.10", "ingress_num": "2",
                              "caddy_domain": "vps.example.invalid/admin"}))
    finally:
        eng.Deployer.connect = vecchio
    assert not connessioni, "un dominio malformato si dice prima di toccare la VPS"
    assert righe[-1] == "__EXIT__1"
    assert any("non valido" in r for r in righe)


# ─────────────────────────── la UI manda l'hostname ───────────────────────────

def test_la_ui_chiede_e_manda_l_hostname_del_tunnel():
    ui = _UI.read_text(encoding="utf-8")
    assert 'id="cf_hostname"' in ui, "il pannello non chiede l'hostname del tunnel"
    assert "cf_hostname:$('cf_hostname')" in ui, "il pannello non manda cf_hostname all'engine"
