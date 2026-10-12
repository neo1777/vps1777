"""Quando PUBLIC_BASE cambia, si ricreano TUTTI i servizi che lo leggono.

🔴 IL DIFETTO (verifica della doc del 12/10/2026): `installer/engine.py` e `deploy.sh`,
dopo aver scritto l'URL del Funnel in PUBLIC_BASE, ricreavano il solo gateway. Ma
PUBLIC_BASE lo leggono anche nb1777-bot (l'URL della Mini App) e nb1777-mcp (i link
firmati di `studio_download`): restavano col valore di quando lo stack era partito,
cioè il default. Il bot rispondeva «PUBLIC_BASE non è https» a ogni /start anche col
Funnel acceso, e il reboot di prova non curava niente: un riavvio non rilegge il .env.

⭐ La lista dei servizi non si scrive qui: si LEGGE da compose.yaml. Se domani un
quarto servizio legge PUBLIC_BASE, questo test diventa rosso finché gli installer non
lo ricreano — invece di restare verde su una lista scritta a mano e invecchiata.
"""
from __future__ import annotations

import importlib.util
import re
import sys
import types
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[2]
_ENGINE = _ROOT / "installer" / "engine.py"

sys.modules.setdefault("paramiko", types.ModuleType("paramiko"))
_spec = importlib.util.spec_from_file_location("installer_engine_pb", _ENGINE)
eng = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eng)


def _chi_legge_public_base() -> set[str]:
    compose = yaml.safe_load((_ROOT / "compose.yaml").read_text(encoding="utf-8"))
    chi = set()
    for nome, servizio in (compose.get("services") or {}).items():
        env = servizio.get("environment") or {}
        valori = env.values() if isinstance(env, dict) else env
        if any("${PUBLIC_BASE" in str(v) for v in valori):
            chi.add(nome)
    return chi


def test_la_lista_dell_engine_e_quella_di_compose():
    chi = _chi_legge_public_base()
    assert chi, "compose.yaml non nomina più PUBLIC_BASE? il test va riletto"
    assert set(eng.SERVIZI_PUBLIC_BASE) == chi, (
        f"compose.yaml: {sorted(chi)} · engine.py ricrea: {sorted(eng.SERVIZI_PUBLIC_BASE)}")


def test_la_lista_di_deploy_sh_e_quella_di_compose():
    testo = (_ROOT / "deploy.sh").read_text(encoding="utf-8")
    m = re.search(r'^SERVIZI_PUBLIC_BASE="([^"]+)"', testo, re.M)
    assert m, "deploy.sh non dichiara più SERVIZI_PUBLIC_BASE"
    assert set(m.group(1).split()) == _chi_legge_public_base()


def test_nessuna_riga_scrive_public_base_e_ricrea_il_solo_gateway():
    # La forma del difetto, cercata dove si scrive PUBLIC_BASE nel .env: una riga che
    # fa `sed … PUBLIC_BASE=…` e poi `up -d gateway` e basta.
    for nome in ("installer/engine.py", "deploy.sh"):
        for n, riga in enumerate((_ROOT / nome).read_text(encoding="utf-8").splitlines(), 1):
            if "PUBLIC_BASE=" in riga and re.search(r"up -d gateway\b(?!\s+nb1777)", riga):
                raise AssertionError(f"{nome}:{n} ricrea il solo gateway dopo PUBLIC_BASE:\n{riga}")


def test_scrivi_public_base_ricrea_tutti_e_tre():
    class _Finto(eng.Deployer):
        def __init__(self):
            super().__init__("192.0.2.10", "root", "")
            self.comandi: list[str] = []

        def _sudo(self, inner: str) -> str:
            return inner

        def _run_capture(self, cmd: str) -> str:
            self.comandi.append(cmd)
            return ""

    d = _Finto()
    d._scrivi_public_base("tailscale", "https://esempio.ts.net")
    (cmd,) = d.comandi
    assert "PUBLIC_BASE=https://esempio.ts.net" in cmd
    coda = cmd.rsplit("up -d", 1)[1].split()
    assert set(coda) == _chi_legge_public_base(), coda
    # e coi file dello stack, non col solo compose.yaml (senza overlay il gateway
    # perderebbe la porta o la rete d'ingresso)
    assert "-f compose.ingress.tailscale.yaml" in cmd


def test_setup_sh_stampa_la_ricreazione_di_tutti_e_tre():
    testo = (_ROOT / "setup.sh").read_text(encoding="utf-8")
    m = re.search(r"\$COMPOSE_STACK up -d ([a-z0-9 -]+)\"", testo)
    assert m, "setup.sh non stampa più il comando per ricreare chi legge PUBLIC_BASE"
    assert set(m.group(1).split()) == _chi_legge_public_base()
