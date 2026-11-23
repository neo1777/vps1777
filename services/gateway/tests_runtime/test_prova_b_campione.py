"""I difetti veri usciti dal campione di precisione della prova B sul gateway (23/11/2026).

Due revisori automatici, leggendo il codice «pulito», hanno segnalato cose che nessuno aveva
piantato e che erano vere. Qui stanno quelle curate, ognuna col suo test. Deps del lock.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app import oauth, routes


@pytest.fixture
def stato(tmp_path, monkeypatch):
    monkeypatch.setattr(oauth, "get_settings",
                        lambda: SimpleNamespace(audit_log_path=str(tmp_path / "audit.log"),
                                                oauth_trusted_redirect_hosts=[]))
    eventi: list[dict] = []
    monkeypatch.setattr(oauth, "audit", eventi.append)
    monkeypatch.setattr(oauth, "_clients", {"c1": {"redirect_uris": ["https://claude.ai/cb"]}})
    return tmp_path, eventi


def test_la_revoca_dice_se_e_stata_salvata(stato, monkeypatch):
    _, eventi = stato
    assert oauth.revoca_client("non-esiste", by="io") is None
    monkeypatch.setattr(oauth, "_save_clients", lambda: False)     # il disco non scrive
    assert oauth.revoca_client("c1", by="io") is False, "una revoca non salvata non è «fatta»"
    assert eventi[-1]["event"] == "oauth_client_revoked" and eventi[-1]["salvata"] is False
    assert "c1" not in oauth._clients, "in memoria resta revocato comunque"


def test_la_revoca_salvata_risponde_vero_e_sta_su_disco(stato):
    cartella, eventi = stato
    assert oauth.revoca_client("c1", by="io") is True
    assert eventi[-1]["salvata"] is True
    assert "c1" not in (cartella / "oauth_clients.json").read_text()


def test_un_verifier_non_ascii_da_un_hash_e_non_un_eccezione():
    # prima: UnicodeEncodeError → 500. Ora è solo un PKCE che non combacia.
    assert oauth._b64url_sha256("verificatore-è-ñ") != oauth._b64url_sha256("verificatore-e-n")
    assert oauth._b64url_sha256("abc") == "ungWv48Bz-pBQUDeXa4iI7ADYaOWF3qctBD_YfIAFa0"   # sha256("abc")


def _richiesta(query: str, ip: str = "8.8.8.8") -> Request:
    return Request({"type": "http", "method": "GET", "path": "/health", "headers": [],
                    "query_string": query.encode(), "client": (ip, 1234)})


@pytest.mark.parametrize("query", ["deep=0", "deep=false", "deep=", "deep=no", ""])
def test_deep_spento_non_accende_la_sonda(query, monkeypatch):
    """`bool("0")` è True: `?deep=0` accendeva la sonda profonda, e da fuori dava 403."""
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(gateway_upstreams={}))
    r = asyncio.run(routes.health(_richiesta(query)))
    assert r.status_code == 200 and r.body == b'{"ok":true}'


@pytest.mark.parametrize("query", ["deep=1", "deep=true", "deep=TRUE"])
def test_deep_acceso_resta_riservato_agli_interni(query, monkeypatch):
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(gateway_upstreams={}))
    r = asyncio.run(routes.health(_richiesta(query)))
    assert r.status_code == 403
