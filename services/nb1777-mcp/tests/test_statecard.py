"""Smoke-test del rendering della state card — offline, senza nlm."""
from __future__ import annotations

from app.statecard import CARD_TITLE, render_card


def test_render_card_contiene_versione_data_e_rimando_a_doctor() -> None:
    md = render_card("1.2.3", date="2026-07-05")
    assert "1.2.3" in md
    assert "2026-07-05" in md
    assert "nlm pin: 0.7.7" in md
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
