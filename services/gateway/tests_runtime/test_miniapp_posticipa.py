"""P18 (11/10/2026): la Mini App scrive il posticipo del promemoria dei secret."""
from __future__ import annotations

import asyncio
import json
import types

from starlette.requests import Request

from app import miniapp


def _richiesta(corpo: dict | None = None, metodo: str = "POST") -> Request:
    dati = json.dumps(corpo or {}).encode()

    async def ricevi():
        return {"type": "http.request", "body": dati, "more_body": False}

    return Request({"type": "http", "method": metodo, "path": "/app/api/secrets/posticipa",
                    "headers": [], "query_string": b""}, ricevi)


def _prepara(monkeypatch, tmp_path) -> list[dict]:
    eventi: list[dict] = []
    monkeypatch.setattr(miniapp, "_bearer_claims", lambda request: {"sub": "774"})
    monkeypatch.setattr(miniapp, "audit", lambda ev: eventi.append(ev))
    monkeypatch.setattr(miniapp, "get_settings",
                        lambda: types.SimpleNamespace(onboarding_dir=str(tmp_path)))
    return eventi


def _json(resp) -> dict:
    return json.loads(resp.body)


def test_posticipa_scrive_il_file_e_l_audit(monkeypatch, tmp_path):
    eventi = _prepara(monkeypatch, tmp_path)
    r = asyncio.run(miniapp.api_secrets_posticipa(_richiesta({"giorni": 7})))
    assert r.status_code == 200 and _json(r)["fino_a"]
    dati = json.loads((tmp_path / "secrets_posticipa.json").read_text())
    assert dati["giorni"] == 7 and dati["da"] == "774"
    assert eventi == [{"event": "secrets_posticipa", "user_id": "774", "giorni": 7}]
    s = asyncio.run(miniapp.api_secrets(_richiesta(metodo="GET")))
    assert _json(s)["posticipato_fino_a"] == dati["fino_a"]


def test_zero_giorni_annulla(monkeypatch, tmp_path):
    _prepara(monkeypatch, tmp_path)
    asyncio.run(miniapp.api_secrets_posticipa(_richiesta({"giorni": 7})))
    r = asyncio.run(miniapp.api_secrets_posticipa(_richiesta({"giorni": 0})))
    assert r.status_code == 200 and _json(r)["fino_a"] is None
    assert not (tmp_path / "secrets_posticipa.json").exists()


def test_giorni_sbagliati_sono_400(monkeypatch, tmp_path):
    _prepara(monkeypatch, tmp_path)
    r = asyncio.run(miniapp.api_secrets_posticipa(_richiesta({"giorni": 99})))
    assert r.status_code == 400 and not (tmp_path / "secrets_posticipa.json").exists()


def test_senza_login_401(monkeypatch, tmp_path):
    _prepara(monkeypatch, tmp_path)
    monkeypatch.setattr(miniapp, "_bearer_claims", lambda request: None)
    r = asyncio.run(miniapp.api_secrets_posticipa(_richiesta({"giorni": 7})))
    assert r.status_code == 401
