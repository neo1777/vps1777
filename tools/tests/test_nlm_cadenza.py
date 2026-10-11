"""La cadenza di nlm (P9, 11/10/2026): il pin non resta indietro di più di un mese senza che si sappia.

Dependabot ignora i minor di notebooklm-mcp-cli di proposito (dependabot.yml): sotto la 1.0
un minor può rompere come un major, e il salto si fa a mano. Il prezzo era un pin fermo: la
0.12.0 è rimasta in produzione mentre upstream arrivava alla 0.15.4 (cinque rilasci in dieci
giorni). `tools/nlm-cadenza.py` misura il ritardo; rebuild-mensile.yml lo lancia una volta
al mese e apre una issue se il pin è indietro da più di 30 giorni.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path

import pytest

_RADICE = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("nlm_cadenza", _RADICE / "tools" / "nlm-cadenza.py")
cadenza = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cadenza)  # type: ignore[union-attr]


def _pypi(rilasci: dict[str, str]) -> dict:
    return {"releases": {v: [{"upload_time": f"{d}T10:00:00"}] for v, d in rilasci.items()}}


RILASCI = {"0.12.0": "2026-09-24", "0.13.0": "2026-09-28", "0.15.0": "2026-10-01",
           "0.15.4": "2026-10-06", "0.16.0rc1": "2026-10-20"}


def test_pin_letto_dal_pyproject_vero():
    assert cadenza.pin_attuale(_RADICE / "services" / "nb1777-mcp" / "pyproject.toml")


def test_in_pari():
    v = cadenza.verdetto("0.15.4", _pypi(RILASCI), oggi=dt.date(2026, 12, 1))
    assert v["indietro"] is False and v["ultima"] == "0.15.4" and v["giorni"] == 0


def test_indietro_da_meno_di_un_mese_non_suona():
    v = cadenza.verdetto("0.12.0", _pypi(RILASCI), oggi=dt.date(2026, 10, 11))
    assert v["indietro"] is False and v["giorni"] == 13 and v["ultima"] == "0.15.4"


def test_indietro_da_piu_di_un_mese_suona_e_conta_dal_primo_rilascio_saltato():
    v = cadenza.verdetto("0.12.0", _pypi(RILASCI), oggi=dt.date(2026, 11, 3))
    assert v["indietro"] is True and v["giorni"] == 36
    assert v["dal"] == "2026-09-28" and "0.15.4" in v["messaggio"]


def test_le_prerelease_non_contano():
    v = cadenza.verdetto("0.15.4", _pypi(RILASCI), oggi=dt.date(2027, 1, 1))
    assert v["indietro"] is False


def test_un_rilascio_ritirato_senza_file_non_conta():
    pypi = _pypi(RILASCI)
    pypi["releases"]["0.15.5"] = []
    assert cadenza.verdetto("0.15.4", pypi, oggi=dt.date(2027, 1, 1))["indietro"] is False


def test_main_codici_di_uscita(tmp_path, capsys):
    pp = tmp_path / "pyproject.toml"
    pp.write_text('dependencies = [\n    "notebooklm-mcp-cli==0.12.0",  # pin\n]\n')
    js = tmp_path / "pypi.json"
    js.write_text(json.dumps(_pypi(RILASCI)))
    assert cadenza.main(["--pyproject", str(pp), "--pypi-json", str(js), "--oggi", "2026-11-03"]) == 1
    assert "0.12.0" in capsys.readouterr().out
    assert cadenza.main(["--pyproject", str(pp), "--pypi-json", str(js), "--oggi", "2026-10-11"]) == 0
    assert cadenza.main(["--pyproject", str(pp), "--pypi-json", str(tmp_path / "manca.json"),
                         "--oggi", "2026-10-11"]) == 2
    with pytest.raises(SystemExit):
        cadenza.main(["--oggi", "ieri"])


def test_rebuild_mensile_lo_lancia_e_l_uscita_1_non_ferma_il_passo():
    """Actions esegue i passi con `bash -e`: un `python3 …; RC=$?` si fermerebbe proprio
    quando c'è da aprire la issue."""
    wf = (_RADICE / ".github" / "workflows" / "rebuild-mensile.yml").read_text(encoding="utf-8")
    assert "python3 tools/nlm-cadenza.py > nlm.txt || RC=$?" in wf
