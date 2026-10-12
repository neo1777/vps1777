"""/app/auth dice PERCHÉ rifiuta (12/10/2026): una causa per ogni 401 e ogni 503.

Prima la pagina vedeva solo lo status: il 401 era sempre «sessione scaduta» — anche quando
la firma non tornava perché la chiave della Mini App era rimasta quella del token vecchio,
dove riaprire il pannello non serve a niente — e il 503 nominava insieme due cause con
rimedi diversi. Qui, col miniapp vero e una initData firmata davvero:
① firma giusta ma auth_date oltre le 12h → 401 `init_data_expired`;
② firma che non torna (hash alterato, chiave di un altro token, auth_date assente)
  → 401 `invalid_init_data`;
③ proprietario assente → 503 `owner_not_configured`; chiave assente → 503
  `bot_token_not_configured`;
e nessuna risposta porta altro che il codice (niente id, niente chiave, niente dettaglio).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
import types
from urllib.parse import urlencode

from starlette.requests import Request

from app import miniapp
from app.ratelimit import RateLimiter

CHIAVE = hmac.new(b"WebAppData", b"123:token-di-prova", hashlib.sha256).hexdigest()
CHIAVE_VECCHIA = hmac.new(b"WebAppData", b"123:token-vecchio", hashlib.sha256).hexdigest()
OWNER = 774


def _init_data(*, chiave: str = CHIAVE, eta_s: float = 60, auth_date: bool = True,
               user_id: int = OWNER) -> str:
    campi = {"user": json.dumps({"id": user_id, "username": "prova"}), "query_id": "q1"}
    if auth_date:
        campi["auth_date"] = str(int(time.time() - eta_s))
    check = "\n".join(f"{k}={v}" for k, v in sorted(campi.items()))
    campi["hash"] = hmac.new(bytes.fromhex(chiave), check.encode(), hashlib.sha256).hexdigest()
    return urlencode(campi)


def _richiesta(init_data: str) -> Request:
    dati = json.dumps({"init_data": init_data}).encode()

    async def ricevi():
        return {"type": "http.request", "body": dati, "more_body": False}

    return Request({"type": "http", "method": "POST", "path": "/app/auth", "headers": [],
                    "query_string": b"", "client": ("203.0.113.7", 40000)}, ricevi)


def _prepara(monkeypatch, *, chiave: str = CHIAVE, owner: int = OWNER) -> list[dict]:
    eventi: list[dict] = []
    monkeypatch.setattr(miniapp, "audit", lambda ev: eventi.append(ev))
    monkeypatch.setattr(miniapp, "_AUTH_LIMIT", RateLimiter(max_calls=100, window_s=300))
    monkeypatch.setattr(miniapp, "issue", lambda **kw: "jwt-finto")
    monkeypatch.setattr(miniapp, "get_settings", lambda: types.SimpleNamespace(
        effective_bot_token="", effective_webapp_secret=chiave,
        miniapp_auth_configurata=bool(chiave), telegram_owner_id=owner,
        oauth_miniapp_token_lifetime=3600))
    return eventi


def _auth(init_data: str):
    r = asyncio.run(miniapp.miniapp_auth(_richiesta(init_data)))
    return r.status_code, json.loads(r.body)


def test_fresca_e_del_proprietario_entra(monkeypatch):
    _prepara(monkeypatch)
    stato, corpo = _auth(_init_data())
    assert stato == 200 and corpo["access_token"] == "jwt-finto"


def test_firma_giusta_ma_vecchia_e_scaduta(monkeypatch):
    eventi = _prepara(monkeypatch)
    assert _auth(_init_data(eta_s=13 * 3600)) == (401, {"error": "init_data_expired"})
    assert eventi == [{"event": "miniapp_auth_fail", "ip": "203.0.113.7", "reason": "scaduta"}]


def test_hash_alterato_non_e_una_scadenza(monkeypatch):
    eventi = _prepara(monkeypatch)
    alterata = _init_data().replace("query_id=q1", "query_id=q2")
    assert _auth(alterata) == (401, {"error": "invalid_init_data"})
    assert eventi[-1]["reason"] == "firma"


def test_chiave_del_token_vecchio_non_si_legge_come_scaduta(monkeypatch):
    """Il caso che il messaggio unico nascondeva: token cambiato, chiave non riderivata.
    Anche con auth_date VECCHIA la causa è la firma, non l'età — riaprire non basterebbe."""
    _prepara(monkeypatch, chiave=CHIAVE_VECCHIA)
    assert _auth(_init_data()) == (401, {"error": "invalid_init_data"})
    assert _auth(_init_data(eta_s=13 * 3600)) == (401, {"error": "invalid_init_data"})


def test_senza_auth_date_e_firma_non_scadenza(monkeypatch):
    _prepara(monkeypatch)
    assert _auth(_init_data(auth_date=False)) == (401, {"error": "invalid_init_data"})


def test_proprietario_assente_503_con_la_sua_causa(monkeypatch):
    _prepara(monkeypatch, owner=0)
    assert _auth(_init_data()) == (503, {"error": "owner_not_configured"})


def test_chiave_assente_503_con_la_sua_causa(monkeypatch):
    _prepara(monkeypatch, chiave="")
    assert _auth(_init_data()) == (503, {"error": "bot_token_not_configured"})
