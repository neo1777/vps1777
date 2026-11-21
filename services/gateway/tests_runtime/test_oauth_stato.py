"""Giro di revisione del 21/11/2026: lo stato OAuth su disco (client e refresh revocati).

Prima si scriveva con `write_text` e si rileggeva «vuoto» su qualunque errore, in silenzio: un
file troncato faceva tornare validi i refresh già ruotati. Ora la scrittura è tutto-o-niente, e
un elenco delle revoche che c'è ma non si legge chiude (valgono solo i refresh emessi dopo).
Deps del lock (oauth vero)."""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from app import oauth


@pytest.fixture
def stato(tmp_path, monkeypatch):
    monkeypatch.setattr(oauth, "get_settings",
                        lambda: SimpleNamespace(audit_log_path=str(tmp_path / "audit.log")))
    eventi: list[dict] = []
    monkeypatch.setattr(oauth, "audit", eventi.append)
    monkeypatch.setattr(oauth, "_refresh_non_prima_di", 0.0)
    return tmp_path, eventi


def test_file_assenti_sono_una_prima_installazione(stato):
    _, eventi = stato
    assert oauth._load_clients() == {} and oauth._load_revoked() == set()
    assert oauth._refresh_non_prima_di == 0.0 and eventi == []


def test_la_lista_nuda_di_prima_si_legge_ancora(stato):
    cartella, _ = stato
    (cartella / "oauth_revoked.json").write_text('["a", "b"]')
    assert oauth._load_revoked() == {"a", "b"} and oauth._refresh_non_prima_di == 0.0


def test_revoche_illeggibili_chiudono_e_lo_dicono(stato):
    cartella, eventi = stato
    (cartella / "oauth_revoked.json").write_text('["a", "b')           # troncato
    prima = time.time()
    assert oauth._load_revoked() == set()
    assert oauth._refresh_non_prima_di >= prima
    assert eventi and eventi[0]["event"] == "oauth_state_unreadable"
    assert (cartella / "oauth_revoked.json.illeggibile").exists()      # messo da parte, non perso


def test_la_soglia_sopravvive_al_salvataggio(stato, monkeypatch):
    cartella, _ = stato
    monkeypatch.setattr(oauth, "_refresh_non_prima_di", 1234.0)
    monkeypatch.setattr(oauth, "_revoked_refresh", {"x"})
    oauth._save_revoked()
    assert json.loads((cartella / "oauth_revoked.json").read_text()) == {
        "revocati": ["x"], "famiglie": [], "non_prima_di": 1234.0}
    monkeypatch.setattr(oauth, "_refresh_non_prima_di", 0.0)
    assert oauth._load_revoked() == {"x"} and oauth._refresh_non_prima_di == 1234.0
    assert [p.name for p in cartella.iterdir()] == ["oauth_revoked.json"]   # nessun .tmp


def test_client_illeggibili_non_vengono_riscritti_senza_traccia(stato):
    cartella, eventi = stato
    (cartella / "oauth_clients.json").write_text("{rotto")
    assert oauth._load_clients() == {}
    assert (cartella / "oauth_clients.json.illeggibile").read_text() == "{rotto"
    assert eventi[0]["file"] == "oauth_clients.json"


# ── la FAMIGLIA dei refresh: il riuso di uno già ruotato chiude la catena intera ──

@pytest.fixture
def banco_token(stato, monkeypatch):
    import asyncio
    import httpx
    from starlette.applications import Starlette
    from starlette.routing import Route
    from app import jwt_helpers
    cartella, eventi = stato
    impostazioni = SimpleNamespace(
        audit_log_path=str(cartella / "audit.log"), effective_signing_secret="k" * 64,
        gateway_public_base="https://gw.example.invalid", oauth_access_token_lifetime=600,
        oauth_refresh_token_lifetime=3600)
    monkeypatch.setattr(oauth, "get_settings", lambda: impostazioni)
    monkeypatch.setattr(jwt_helpers, "get_settings", lambda: impostazioni)
    monkeypatch.setattr(oauth, "_clients", {"cid": {"client_name": "prova"}})
    monkeypatch.setattr(oauth, "_revoked_refresh", set())
    monkeypatch.setattr(oauth, "_famiglie_revocate", set())
    avvisi: list = []
    monkeypatch.setattr(oauth.notifiche, "accoda", lambda *a, **k: avvisi.append(a))
    app = Starlette(routes=[Route("/token", oauth.token, methods=["POST"])])

    def rinnova(rt: str):
        async def _go():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gw") as c:
                return await c.post("/token", data={"grant_type": "refresh_token",
                                                     "refresh_token": rt, "client_id": "cid"})
        return asyncio.run(_go())
    primo = jwt_helpers.issue(typ="refresh", sub="neo@example.invalid", aud="cid", ttl=3600,
                              extra={"jti": "j0", "fam": "F1"})
    return rinnova, primo, avvisi


def test_il_riuso_di_un_refresh_ruotato_chiude_tutta_la_catena(banco_token):
    rinnova, primo, avvisi = banco_token
    r1 = rinnova(primo)
    assert r1.status_code == 200
    secondo = r1.json()["refresh_token"]
    # qualcuno ripresenta il PRIMO (già ruotato): rifiutato, e la famiglia si chiude
    assert rinnova(primo).status_code == 400
    assert "F1" in oauth._famiglie_revocate and len(avvisi) == 1
    # il secondo, che fino a ieri sarebbe rimasto valido per 30 giorni, non vale più
    r3 = rinnova(secondo)
    assert r3.status_code == 400 and r3.json()["reason"] == "revoked"


def test_la_famiglia_segue_la_rotazione_e_sopravvive_al_riavvio(banco_token):
    rinnova, primo, _ = banco_token
    from app import jwt_helpers
    secondo = rinnova(primo).json()["refresh_token"]
    assert jwt_helpers.verify(secondo, expected_typ="refresh", expected_aud="cid")["fam"] == "F1"
    rinnova(primo)                                            # riuso → revoca
    oauth._famiglie_revocate.clear()
    oauth._load_revoked()                                     # come dopo un riavvio
    assert "F1" in oauth._famiglie_revocate
