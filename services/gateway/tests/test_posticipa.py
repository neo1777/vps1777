"""P18 (11/10/2026): il posticipo del promemoria dei secret, le parti pure (stdlib)."""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import miniapp_core as mc  # noqa: E402

ORA = dt.datetime(2026, 10, 11, 12, 0, tzinfo=dt.timezone.utc)


def test_un_posticipo_di_sette_giorni():
    d = mc.nuovo_posticipo(7, ORA, "774")
    assert d["fino_a"] == "2026-10-18T12:00:00+00:00" and d["da"] == "774" and d["giorni"] == 7


@pytest.mark.parametrize("giorni", [-1, 31, "7", None, 2.5])
def test_giorni_fuori_dai_limiti_o_non_interi(giorni):
    with pytest.raises(ValueError):
        mc.nuovo_posticipo(giorni, ORA, "774")


def test_posticipo_attivo():
    assert mc.posticipo_attivo({"fino_a": "2026-10-18T12:00:00+00:00"}, ORA) == "2026-10-18T12:00:00+00:00"
    assert mc.posticipo_attivo({"fino_a": "2026-10-10T12:00:00+00:00"}, ORA) is None
    assert mc.posticipo_attivo({}, ORA) is None and mc.posticipo_attivo({"fino_a": "boh"}, ORA) is None


def test_la_pagina_apre_la_vista_e_ha_il_bottone():
    pagina = (Path(__file__).resolve().parents[1] / "app" / "miniapp.py").read_text(encoding="utf-8")
    assert "URLSearchParams(location.search).get('vista')" in pagina
    assert "/app/api/secrets/posticipa" in pagina
