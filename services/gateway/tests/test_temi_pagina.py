"""/admin/temi: il proprietario vede prima i temi da guardare, e il suo marchio vince sempre
(mappa dei temi, 07/11/2026). Stdlib-only, come test_admin_core."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import admin_core  # noqa: E402

_MAPPA = {"temi": [{"id": 0, "scambi": 50}, {"id": 1, "scambi": 3, "da_guardare": True},
                   {"id": 2, "scambi": 9}, "rotto", {"id": 3, "scambi": 1, "da_guardare": True}]}


def test_prima_i_da_guardare_poi_i_riservati_poi_i_liberi():
    t = admin_core.temi_da_mostrare(_MAPPA, {"2": "riservato"})
    assert [x["id"] for x in t] == [1, 3, 2, 0]


def test_il_marchio_del_proprietario_vince():
    assert admin_core.stato_del_tema({"id": 1, "da_guardare": True}, {"1": "libero"}) == "libero"
    assert admin_core.stato_del_tema({"id": 0}, {"0": "riservato"}) == "riservato"
    assert admin_core.stato_del_tema({"id": 0}, {"0": "inventato"}) == "libero"
    assert admin_core.stato_del_tema({"id": 1, "da_guardare": True}, {}) == "da_guardare"


def test_mappa_assente_o_rotta_da_lista_vuota():
    assert admin_core.temi_da_mostrare({}, {}) == []
    assert admin_core.temi_da_mostrare({"temi": "no"}, {}) == []


def test_la_pagina_controlla_chi_e_e_cosa_scrive():
    src = (Path(__file__).resolve().parents[1] / "app" / "admin.py").read_text(encoding="utf-8")
    corpo = src[src.index("async def temi_view"):src.index("async def secrets_view")]
    assert corpo.index("_require_admin(request)") < corpo.index("_scrivi_marchi(marchi)")
    assert 'stato not in ("libero", "riservato")' in corpo and "tema.isdigit()" in corpo
    assert 'audit({"event": "temi_marchio"' in corpo
    # tutto ciò che viene dal file passa da escape: le parole stanno nei messaggi dell'archivio
    assert re.search(r'parole = html\.escape\(', corpo)
