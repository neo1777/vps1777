"""P11 (05/10/2026): `/admin/salute` — un verde vecchio non è un verde.

La pagina legge `onboarding/salute.json` (scritto da `vps1777 check`, una volta al
giorno). Il rischio dichiarato nel dossier è «un verde vecchio»: se il timer smette di
girare, le righe restano ok per sempre. Qui ogni riga ha l'età della sua misura, e oltre
la soglia diventa «vecchia» qualunque stato dica. Stdlib-only, come test_admin_core.
"""
from __future__ import annotations

import calendar
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import admin_core  # noqa: E402

_ORA = calendar.timegm(time.strptime("2026-10-05T20:00:00Z", "%Y-%m-%dT%H:%M:%SZ"))


def test_una_misura_recente_tiene_il_suo_stato():
    r = admin_core.righe_salute({"righe": [
        {"voce": "disco", "stato": "ok", "dettaglio": "libero 70%",
         "misurato_il": "2026-10-05T03:00:00Z"}]}, now=_ORA)
    assert r[0]["stato"] == "ok" and r[0]["ore"] == 17 and r[0]["vecchia"] is False


def test_una_misura_oltre_la_soglia_e_vecchia_anche_se_verde():
    r = admin_core.righe_salute({"righe": [
        {"voce": "disco", "stato": "ok", "dettaglio": "", "misurato_il": "2026-10-03T03:00:00Z"}]},
        now=_ORA)
    assert r[0]["vecchia"] is True and r[0]["ore"] > admin_core.SALUTE_VECCHIA_ORE


def test_senza_data_o_con_uno_stato_ignoto_non_e_verde():
    r = admin_core.righe_salute({"righe": [
        {"voce": "a", "stato": "ok", "misurato_il": None},
        {"voce": "b", "stato": "inventato", "misurato_il": "2026-10-05T19:00:00Z"}]}, now=_ORA)
    assert r[0]["vecchia"] is True
    assert r[1]["stato"] == "non_misurato"


def test_file_assente_o_rotto_da_lista_vuota():
    assert admin_core.righe_salute({}) == []
    assert admin_core.righe_salute({"righe": "non una lista"}) == []
