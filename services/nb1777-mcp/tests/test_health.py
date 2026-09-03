"""/health — sonda del compose: settings + volume dati, MAI NotebookLM (vaglio 03/09).

Un health che chiama un servizio esterno riavvia il container per i guasti
degli altri; uno che apre solo il socket fa passare per sana un'app rotta."""
from __future__ import annotations

import asyncio
import json

from app import server


def _chiama():
    resp = asyncio.run(server.health(None))
    return resp.status_code, json.loads(resp.body)


def test_health_ok_con_volume_presente(monkeypatch, tmp_path):
    class _S:
        nlm_home = str(tmp_path)
    monkeypatch.setattr(server, "get_settings", lambda: _S())
    status, body = _chiama()
    assert status == 200 and body["status"] == "ok"
    assert body["mcp_protocol_max"] and body["mcp_sdk"]


def test_health_volume_assente_e_503(monkeypatch, tmp_path):
    class _S:
        nlm_home = str(tmp_path / "non-c-e")
    monkeypatch.setattr(server, "get_settings", lambda: _S())
    status, body = _chiama()
    assert status == 503 and "nlm_home" in body["reason"]
