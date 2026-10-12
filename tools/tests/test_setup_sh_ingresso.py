#!/usr/bin/env python3
"""`setup.sh` e l'ingresso: il token di Cloudflare, i comandi del Funnel, il bot senza token.

🔴 I DIFETTI (verifica della doc del 12/10/2026):
   · con Cloudflare setup.sh chiedeva l'hostname ma NON il token, e non creava
     `secrets/cloudflared_token.txt`, che il compose dichiara come secret-file: il
     primo `up` moriva per file mancante;
   · con Tailscale non installava né accendeva il Funnel, e non lo diceva: si finiva
     con un pannello su 127.0.0.1 e il segnaposto `<PUBLIC_BASE>`;
   · col token Telegram vuoto il rimedio stampato era impreciso.

⭐ Si ESEGUE setup.sh, come in test_setup_sh_gira_davvero.py, ma su una copia dei soli
file che legge (setup.sh e .env.example) in una cartella temporanea: si prova lo
script dell'albero di lavoro, non quello di HEAD, e il repo non si tocca.
`SETUP_YES=n` risponde «no» a «Procedo ora?»: niente container.

🛡️ Il token non deve comparire nell'output: si passa un segnalino riconoscibile e si
cerca nell'uscita. Un installer che stampa un segreto lo consegna ai log e ai
transcript.

Se mancano docker / compose v2 / bcrypt il test si SALTA (setup.sh muore ai
prerequisiti): «non ho potuto guardare» non è un verde.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PWD_DI_PROVA = "Qz7mKp2wLr9xTv4B"            # passa la policy H16, valida solo nel banco
CF_SEGNALINO = "eyJ-SEGNALINO-cf-7f3a9c"      # finto: deve finire nel file, mai a schermo
TG_SEGNALINO = "123456789:" + "SegnalinoFinto-" * 2 + "x" * 8   # costruito: un token intero nel sorgente fa scattare il gate anti-leak


def _salta_se_manca_qualcosa() -> None:
    if not shutil.which("docker"):
        pytest.skip("docker non installato — setup.sh esce ai prerequisiti")
    if subprocess.run(["docker", "compose", "version"], capture_output=True).returncode != 0:
        pytest.skip("docker compose v2 non disponibile")
    if subprocess.run(["python3", "-c", "import bcrypt"], capture_output=True).returncode != 0:
        pytest.skip("bcrypt assente per python3 — setup.sh lo esige in testa")


def _esegui(**risposte: str) -> tuple[subprocess.CompletedProcess, Path, str]:
    _salta_se_manca_qualcosa()
    banco = Path(tempfile.mkdtemp(prefix="setup-ingresso-"))
    shutil.copy2(REPO / "setup.sh", banco / "setup.sh")
    shutil.copy2(REPO / ".env.example", banco / ".env.example")
    env = {**os.environ,
           "SETUP_ADMIN_EMAIL": "prova@example.invalid", "SETUP_TG_OWNER_ID": "123456789",
           "SETUP_ADMIN_PWD": PWD_DI_PROVA, "SETUP_YES": "n",
           "VPS1777_INSTALL_VERSION": "0.0.0-banco"}   # niente rete: vedi gira_davvero
    env.update({f"SETUP_{k}": v for k, v in risposte.items()})
    res = subprocess.run(["bash", "setup.sh"], cwd=banco, env=env, stdin=subprocess.DEVNULL,
                         capture_output=True, text=True, timeout=300)
    return res, banco, res.stdout + res.stderr


def _pulisci(banco: Path) -> None:
    shutil.rmtree(banco, ignore_errors=True)


def test_cloudflared_chiede_il_token_lo_scrive_600_e_non_lo_stampa():
    res, banco, out = _esegui(INGRESS_NUM="3", CF_HOSTNAME="mcp.example.invalid",
                              CF_TOKEN=CF_SEGNALINO, TG_TOKEN=TG_SEGNALINO)
    try:
        assert res.returncode == 0, out[-2500:]
        f = banco / "secrets" / "cloudflared_token.txt"
        assert f.is_file(), f"cloudflared_token.txt non creato:\n{out[-2500:]}"
        assert f.read_text() == CF_SEGNALINO
        assert stat.S_IMODE(f.stat().st_mode) == 0o600
        assert CF_SEGNALINO not in out, "il token del tunnel è finito a schermo"
        assert TG_SEGNALINO not in out, "il token del bot è finito a schermo"
        assert "(nascosto)" in out
        assert "PUBLIC_BASE=https://mcp.example.invalid" in (banco / ".env").read_text()
        # col token presente non c'è niente da ricordare in fondo
        assert "manca il token del tunnel" not in out
    finally:
        _pulisci(banco)


def test_cloudflared_senza_token_parte_lo_stesso_e_dice_come_aggiungerlo():
    res, banco, out = _esegui(INGRESS_NUM="3", CF_HOSTNAME="mcp.example.invalid")
    try:
        assert res.returncode == 0, out[-2500:]
        f = banco / "secrets" / "cloudflared_token.txt"
        # il file esiste (vuoto): senza, il compose non farebbe partire niente
        assert f.is_file() and f.read_text() == ""
        assert stat.S_IMODE(f.stat().st_mode) == 0o600
        assert "Token del tunnel vuoto" in out
        assert "rilancia ./setup.sh" in out
        assert "up -d --force-recreate cloudflared" in out
        assert "--profile ingress.cloudflared" in out
    finally:
        _pulisci(banco)


def test_tailscale_stampa_i_comandi_del_funnel_e_non_la_forma_vietata():
    res, banco, out = _esegui(INGRESS_NUM="1")
    try:
        assert res.returncode == 0, out[-2500:]
        assert "setup.sh NON installa Tailscale" in out
        assert ("sudo tailscale serve reset && sudo tailscale funnel --bg --https=443 "
                "http://127.0.0.1:8080") in out
        # la forma che installer/engine.py VIETA: serve e funnel separati → 502
        assert "funnel --bg 443" not in out
        assert "tailscale serve --bg" not in out
        assert "up -d gateway nb1777-mcp nb1777-bot" in out
        # con Tailscale niente file del tunnel: il conteggio dei secret resta quello
        assert not (banco / "secrets" / "cloudflared_token.txt").exists()
    finally:
        _pulisci(banco)


def test_tailscale_con_public_base_gia_https_non_ripete_le_istruzioni():
    # Un re-run dopo aver acceso il Funnel: il .env ha già l'URL, il promemoria tace.
    _salta_se_manca_qualcosa()
    res, banco, _ = _esegui(INGRESS_NUM="1")
    try:
        assert res.returncode == 0
        env = banco / ".env"
        env.write_text(env.read_text().replace(
            "PUBLIC_BASE=\n", "PUBLIC_BASE=https://esempio.ts.net\n"))
        assert "PUBLIC_BASE=https://esempio.ts.net" in env.read_text()
        res2 = subprocess.run(["bash", "setup.sh"], cwd=banco, stdin=subprocess.DEVNULL,
                              env={**os.environ, "SETUP_YES": "n",
                                   "VPS1777_INSTALL_VERSION": "0.0.0-banco"},
                              capture_output=True, text=True, timeout=300)
        out2 = res2.stdout + res2.stderr
        assert res2.returncode == 0, out2[-2500:]
        assert "setup.sh NON installa Tailscale" not in out2
    finally:
        _pulisci(banco)


def test_token_telegram_vuoto_indica_lo_script_di_rotazione():
    res, banco, out = _esegui(INGRESS_NUM="1", TG_TOKEN="")
    try:
        assert res.returncode == 0, out[-2500:]
        assert "./tools/rotate-secret.sh telegram_bot_token" in out
        assert "standby" in out
        # il vecchio rimedio («salvalo nel file») lasciava la Mini App senza chiave
        assert "Salvalo dopo in secrets/telegram_bot_token.txt" not in out
    finally:
        _pulisci(banco)
