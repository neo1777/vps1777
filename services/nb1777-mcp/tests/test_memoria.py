# Issue #30 ②③ — verdetto, ping drift (rate-limit), promemoria cloud + ack.
# Stato su file temporaneo; canonico e cloud-ack monkeypatchati (niente nlm).
from __future__ import annotations

import pytest

from app import canonical, memoria

CANON_24 = {"version": "v2.4", "major": 2, "minor": 4,
            "date": "2026-07-13", "note": "regola CANONICO"}


@pytest.fixture(autouse=True)
def _isola(tmp_path, monkeypatch):
    monkeypatch.setattr(memoria, "_state_path", lambda: tmp_path / "memoria.json")
    memoria._outbox.clear()
    yield
    memoria._outbox.clear()


def _canon(monkeypatch, canon):
    monkeypatch.setattr(canonical, "get_canonical", lambda **k: canon)


def _ack_src(monkeypatch, tup):
    monkeypatch.setattr(canonical, "get_cloud_ack", lambda **k: tup)


# ── parse + verdetto ─────────────────────────────────────────────────────────

def test_parse_version_varie_forme() -> None:
    assert memoria.parse_version("v2.4") == (2, 4)
    assert memoria.parse_version("2.4") == (2, 4)
    assert memoria.parse_version("Memoria 1777 (v2.4 · 2026-07-13)") == (2, 4)
    assert memoria.parse_version("niente qui") is None


def test_compare_stale(monkeypatch) -> None:
    _canon(monkeypatch, CANON_24)
    v = memoria.compare("v2.2")
    assert v["stale"] is True and v["canonico"] == "v2.4"
    assert "indietro di 2 minor" in v["delta"]
    assert v["note"] == "regola CANONICO"


def test_compare_allineato(monkeypatch) -> None:
    _canon(monkeypatch, CANON_24)
    assert memoria.compare("v2.4")["stale"] is False


def test_compare_canonico_assente(monkeypatch) -> None:
    _canon(monkeypatch, None)
    v = memoria.compare("v2.2")
    assert v["stale"] is None and "fallback" in v["nota"]


def test_compare_versione_non_riconosciuta(monkeypatch) -> None:
    _canon(monkeypatch, CANON_24)
    assert memoria.compare("boh")["stale"] is None


# ── ping drift + rate-limit ──────────────────────────────────────────────────

def test_note_drift_ratelimit_una_al_giorno(monkeypatch) -> None:
    assert memoria.note_drift("v2.2", "v2.4") is True   # prima volta → accoda
    assert memoria.note_drift("v2.2", "v2.4") is False  # stesso giorno → no
    assert len(memoria._outbox) == 1
    assert memoria._outbox[0]["kind"] == "drift"


# ── ack + promemoria cloud ───────────────────────────────────────────────────

def test_ack_bottone_e_fonte_prende_il_max(monkeypatch) -> None:
    _ack_src(monkeypatch, None)
    assert memoria._effective_ack() is None
    memoria.set_ack("v2.4")
    assert memoria._effective_ack() == (2, 4)
    _ack_src(monkeypatch, (2, 5))          # fonte cloud-ack più alta vince
    assert memoria._effective_ack() == (2, 5)


def test_promemoria_dovuto_e_poi_ratelimit(monkeypatch) -> None:
    _canon(monkeypatch, CANON_24)
    _ack_src(monkeypatch, None)
    rem = memoria.maybe_cloud_reminder()   # nessun ack → dovuto
    assert rem and rem["kind"] == "cloud" and rem["ack_version"] == "v2.4"
    assert memoria.maybe_cloud_reminder() is None   # intervallo non passato


def test_promemoria_spento_dopo_ack(monkeypatch) -> None:
    _canon(monkeypatch, CANON_24)
    _ack_src(monkeypatch, None)
    memoria.set_ack("v2.4")
    assert memoria.maybe_cloud_reminder() is None


def test_promemoria_spento_da_fonte_cloud_ack(monkeypatch) -> None:
    _canon(monkeypatch, CANON_24)
    _ack_src(monkeypatch, (2, 4))          # cloud-ack v2.4 nel notebook
    assert memoria.maybe_cloud_reminder() is None


def test_drain_svuota_e_include_promemoria(monkeypatch) -> None:
    _canon(monkeypatch, CANON_24)
    _ack_src(monkeypatch, None)
    memoria.note_drift("v2.2", "v2.4")
    items = memoria.drain()
    kinds = [i["kind"] for i in items]
    assert "drift" in kinds and "cloud" in kinds
    assert memoria._outbox == []           # coda svuotata
