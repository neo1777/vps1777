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
        "revocati": ["x"], "non_prima_di": 1234.0}
    monkeypatch.setattr(oauth, "_refresh_non_prima_di", 0.0)
    assert oauth._load_revoked() == {"x"} and oauth._refresh_non_prima_di == 1234.0
    assert [p.name for p in cartella.iterdir()] == ["oauth_revoked.json"]   # nessun .tmp


def test_client_illeggibili_non_vengono_riscritti_senza_traccia(stato):
    cartella, eventi = stato
    (cartella / "oauth_clients.json").write_text("{rotto")
    assert oauth._load_clients() == {}
    assert (cartella / "oauth_clients.json.illeggibile").read_text() == "{rotto"
    assert eventi[0]["file"] == "oauth_clients.json"
