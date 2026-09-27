"""Smoke-test del rendering della state card — offline, senza nlm."""
from __future__ import annotations

from app.statecard import CARD_TITLE, nlm_installato, render_card


def test_render_card_contiene_versione_data_e_rimando_a_doctor() -> None:
    md = render_card("1.2.3", date="2026-07-05")
    assert "1.2.3" in md
    assert "2026-07-05" in md
    # il pin è quello INSTALLATO, non un numero scritto a mano (era «0.7.7» fisso)
    assert f"nlm pin: {nlm_installato()}" in md
    assert f"pinnati a nlm {nlm_installato()}" in md
    # il principio anti-staleness: la card rimanda alla verità viva
    assert "doctor" in md
    # i tre fatti che erano ricordi stale
    assert "cross_notebook_query" in md
    assert "archive1777" in md and "nasce vuoto" in md
    assert "nb_get" in md


def test_render_card_nlm_pin_override() -> None:
    assert "nlm pin: 0.8.0" in render_card("2.0.0", nlm_pin="0.8.0", date="2026-01-01")


def test_card_title_stabile() -> None:
    # l'upsert idempotente dipende da un titolo stabile
    assert CARD_TITLE == "vps1777-state-card"


def test_doctor_version_e_una_riga_sola(monkeypatch) -> None:
    """Dalla 0.9 `nlm --version` stampa anche «You are on the latest version.»."""
    import subprocess

    from app import core

    def finto(args, **kw):
        if args == ["--version"]:
            return subprocess.CompletedProcess(args, 0, "nlm version 0.12.0\nYou are on the latest version.\n", "")
        raise RuntimeError("niente rete nel test")

    monkeypatch.setattr(core, "_run", finto)
    monkeypatch.setattr(core, "_run_json", lambda *a, **k: [])
    assert core.doctor()["version"] == "nlm version 0.12.0"
