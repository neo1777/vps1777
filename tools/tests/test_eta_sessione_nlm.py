"""S9 (05/10/2026): `secrets-status` dà l'età vera della sessione Google.

Prima l'età era l'mtime di `cookies.json`, letto da un busybox: `nlm` riscrive quel file
anche da solo, e il numero si azzerava senza un caricamento. Ora la chiede a nb1777-mcp
(`python -m app.stato_sessione`, solo date e sonda) e ripiega sull'mtime solo se il
container non risponde. «Da ricaricare» lo dice la sonda; l'età serve quando la sonda tace.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("vps1777_cli_s9", _ROOT / "tools" / "vps1777.py")
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)


def _iso(giorni_fa: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - giorni_fa * 86400))


def _finto_run(monkeypatch, *, stato=None, exec_rc=0, mtime_giorni_fa=1):
    chiamate = []

    def run(cmd, **kw):
        chiamate.append(cmd)
        if "exec" in cmd:
            return subprocess.CompletedProcess(cmd, exec_rc, json.dumps(stato) + "\n", "")
        return subprocess.CompletedProcess(cmd, 0, f"{int(time.time() - mtime_giorni_fa * 86400)}\n", "")

    monkeypatch.setattr(v, "run", run)
    monkeypatch.setattr(v, "compose_cmd", lambda repo: ["docker", "compose"])
    return chiamate


def test_eta_dalla_nascita_della_sessione_non_dall_mtime(monkeypatch, tmp_path):
    _finto_run(monkeypatch, mtime_giorni_fa=0, stato={
        "nata_il": _iso(20), "ultimo_refresh": _iso(0),
        "sonda": {"quando": _iso(0.1), "esito": "ok"}})
    it = v.nlm_cookie_status(tmp_path)
    assert it["age_days"] == 20
    assert it["overdue"] is False              # vecchia ma viva: la sonda lo dice
    assert "nata il" in it["note"] and "ultimo refresh" in it["note"]


def test_la_sonda_che_la_da_scaduta_vince_sull_eta(monkeypatch, tmp_path):
    _finto_run(monkeypatch, stato={"nata_il": _iso(3), "ultimo_refresh": _iso(1),
                                   "sonda": {"quando": _iso(0.1), "esito": "auth_scaduta"}})
    it = v.nlm_cookie_status(tmp_path)
    assert it["overdue"] is True
    assert "/admin/nlm" in it["note"]


def test_senza_sonda_vale_la_soglia_sull_eta(monkeypatch, tmp_path):
    _finto_run(monkeypatch, stato={"nata_il": _iso(v.NLM_COOKIE_MAX_DAYS + 2),
                                   "ultimo_refresh": _iso(1), "sonda": None})
    assert v.nlm_cookie_status(tmp_path)["overdue"] is True


def test_container_muto_ripiega_sull_mtime(monkeypatch, tmp_path):
    chiamate = _finto_run(monkeypatch, exec_rc=1, stato=None, mtime_giorni_fa=3)
    it = v.nlm_cookie_status(tmp_path)
    assert it["age_days"] == 3
    assert any("busybox" in " ".join(c) or v.BUSYBOX in c for c in chiamate)
    assert "file" in it["note"]
