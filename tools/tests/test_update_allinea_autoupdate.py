"""Update e rollback riallineano il timer dell'auto-update a VPS1777_FEATURES (29/09/2026).

Residuo dell'audit della doc: l'install tratta lo stato dichiarato come AUTORITATIVO (se
`autoupdate` non c'è, il timer si spegne), ma update, rollback e auto-rollback passano da
`install_systemd_units(enable=False)`, che non toccava nessuna abilitazione. Togliere
`autoupdate` da `.env` e fare un update lasciava il timer acceso; rimetterlo non lo
riaccendeva. OPS.md lo dichiarava («rileggono a metà»). Ora il timer segue lo stato
dichiarato anche lì; le altre unit restano come sono (un operatore può averne spenta una
di proposito).
"""
from __future__ import annotations

import importlib.util
import inspect
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("vps1777_cli_allinea", _ROOT / "tools" / "vps1777.py")
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)


def _repo(env: str) -> Path:
    d = Path(tempfile.mkdtemp())
    (d / ".env").write_text(env)
    return d


def _comandi(monkeypatch, repo: Path, installato: bool = True) -> list[list[str]]:
    fatti: list[list[str]] = []
    monkeypatch.setattr(v, "sudo", lambda cmd, **k: fatti.append(list(cmd)))
    monkeypatch.setattr(v, "_timer_autoupdate_installato", lambda: installato)
    v.allinea_timer_autoupdate(repo)
    return fatti


def test_autoupdate_dichiarato_accende_il_timer(monkeypatch):
    fatti = _comandi(monkeypatch, _repo("VPS1777_FEATURES=backup,autoupdate\n"))
    assert fatti == [["systemctl", "enable", "--now", "vps1777-auto-update.timer"]], fatti


def test_autoupdate_tolto_spegne_il_timer(monkeypatch):
    fatti = _comandi(monkeypatch, _repo("VPS1777_FEATURES=backup\n"))
    assert fatti == [["systemctl", "disable", "--now", "vps1777-auto-update.timer"]], fatti


def test_default_a_chiave_assente_e_acceso(monkeypatch):
    fatti = _comandi(monkeypatch, _repo("INGRESS_PROFILE=ingress.caddy\n"))
    assert fatti == [["systemctl", "enable", "--now", "vps1777-auto-update.timer"]], fatti


def test_senza_la_unit_installata_non_tocca_niente(monkeypatch):
    assert _comandi(monkeypatch, _repo("VPS1777_FEATURES=backup\n"), installato=False) == []


def test_update_e_rollback_passano_dal_riallineamento():
    # update, rollback e auto-rollback chiamano install_systemd_units(enable=False):
    # il riallineamento deve stare nel ramo enable=False, non in uno solo dei tre chiamanti
    corpo = inspect.getsource(v.install_systemd_units)
    ramo_no = corpo.split("if enable:", 1)[1]
    assert "allinea_timer_autoupdate(repo)" in ramo_no, "il ramo enable=False non riallinea il timer"
