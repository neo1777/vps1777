"""`vps1777 secrets-status`, le strade che le prove non percorrevano (25/11/2026, QUA-04).

Prima di spezzare `cmd_secrets_status` la copertura per rami era 26 su 34: mancavano le due voci
che non sono file (cookie NotebookLM, bypass di cosign) quando sono scadute, il promemoria
posticipato, il verde pieno, e lo stato che non si riesce a scrivere.
"""
from __future__ import annotations

import importlib.util
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("vps1777_cli_secrets_status", _ROOT / "tools" / "vps1777.py")
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)


@pytest.fixture
def banco(tmp_path, monkeypatch):
    """Un repo con tutti i secret freschi; i collaboratori sono finti e scrivono in `ev`."""
    ev: list = []
    (tmp_path / "secrets").mkdir()
    (tmp_path / "onboarding").mkdir()
    for _name, fname, *_ in v._SECRET_POLICY:
        (tmp_path / "secrets" / fname).write_text("x", encoding="utf-8")
    voci = {"nlm": None, "cosign": None, "posticipo": None}
    monkeypatch.setattr(v, "nlm_cookie_status", lambda repo: voci["nlm"])
    monkeypatch.setattr(v, "cosign_bypass_status", lambda repo: voci["cosign"])
    monkeypatch.setattr(v, "posticipo_secrets", lambda repo: voci["posticipo"])
    monkeypatch.setattr(v, "onboarding_dir", lambda repo: repo / "onboarding")
    monkeypatch.setattr(v, "telegram_notify", lambda repo, testo, **kw: ev.append(("tg", testo)))
    for nome in ("log", "warn", "ok"):
        monkeypatch.setattr(v, nome, lambda t, _n=nome: ev.append((_n, str(t))))
    return SimpleNamespace(repo=tmp_path, ev=ev, voci=voci,
                           gira=lambda notify=True: v.cmd_secrets_status(tmp_path, SimpleNamespace(notify=notify)))


def test_tutti_freschi_e_verde_e_lo_stato_si_scrive(banco):
    assert banco.gira() == 0
    assert ("ok", "tutti i secret entro la soglia") in banco.ev
    assert not [e for e in banco.ev if e[0] in ("tg", "warn")]
    stato = json.loads((banco.repo / "onboarding" / "secrets_status.json").read_text())
    assert stato["mancanti"] == [] and len(stato["secrets"]) == len(v._SECRET_POLICY)


def test_le_voci_che_non_sono_file_entrano_e_se_scadute_si_dicono(banco):
    banco.voci["nlm"] = {"label": "cookie NotebookLM", "overdue": True, "age_days": 40, "max_age_days": 30}
    banco.voci["cosign"] = {"label": "bypass cosign", "overdue": True, "age_days": None, "max_age_days": 7}
    assert banco.gira() == 0
    avviso = [t for n, t in banco.ev if n == "warn"][0]
    assert "cookie NotebookLM (40g)" in avviso and "bypass cosign (Noneg)" in avviso
    assert any(n == "log" and "bypass cosign" in t and "  ??g" in t for n, t in banco.ev), "età ignota: ?? e non 0"
    assert len([e for e in banco.ev if e[0] == "tg"]) == 1


def test_il_promemoria_posticipato_non_manda_telegram(banco):
    vecchio = time.time() - 400 * 86400
    primo = banco.repo / "secrets" / v._SECRET_POLICY[0][1]
    os.utime(primo, (vecchio, vecchio))
    banco.voci["posticipo"] = "2026-12-01"
    assert banco.gira() == 0
    assert not [e for e in banco.ev if e[0] == "tg"]
    assert any(n == "log" and "posticipato" in t and "2026-12-01" in t for n, t in banco.ev)
    banco.ev.clear()
    assert banco.gira(notify=False) == 0                     # senza --notify il posticipo non si guarda
    assert not [e for e in banco.ev if e[0] == "tg" or "posticipato" in e[1]]


def test_lo_stato_che_non_si_scrive_e_un_avviso_non_un_crollo(banco, monkeypatch):
    monkeypatch.setattr(v, "onboarding_dir", lambda repo: repo / "non-esiste")
    assert banco.gira() == 0
    assert any(n == "warn" and "secrets_status.json fallita" in t for n, t in banco.ev)
