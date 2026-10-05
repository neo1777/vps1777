"""S9: l'età vera della sessione Google, non l'mtime del file dei cookie.

L'mtime di `cookies.json` cambia anche quando `nlm` riscrive il file per conto suo, e
così l'età si azzerava senza che nessuno avesse ricaricato il profilo. Google dà a SID
una scadenza di 400 giorni dal login: la scadenza meno 400 giorni è la nascita della
sessione (il 05/10/2026 combaciava al secondo col login del 02/10). Mai i valori.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from app.nlm_profile import COOKIES_REL, eta_sessione

_NATA = datetime(2026, 10, 2, 10, 19, 7, tzinfo=timezone.utc)
_SCADE = _NATA.timestamp() + 400 * 86400


def _scrivi(tmp_path, cookies, mtime=None):
    p = tmp_path / COOKIES_REL
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(cookies))
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


def test_nascita_da_sid_meno_400_giorni_e_ultimo_refresh_dal_file(tmp_path):
    rifatto = datetime(2026, 10, 5, 0, 34, tzinfo=timezone.utc).timestamp()
    _scrivi(tmp_path, [
        {"name": "__Secure-1PSIDTS", "value": "segreto-a", "expires": _SCADE - 200 * 86400},
        {"name": "SID", "value": "segreto-b", "expires": _SCADE},
        {"name": "SID", "value": "segreto-c", "expires": _SCADE - 5},
    ], mtime=rifatto)
    eta = eta_sessione(tmp_path)
    assert eta == {"nata_il": "2026-10-02T10:19:07Z", "ultimo_refresh": "2026-10-05T00:34:00Z"}
    assert "segreto" not in json.dumps(eta)


def test_senza_sid_vale_secure_1psid(tmp_path):
    _scrivi(tmp_path, [{"name": "__Secure-1PSID", "value": "x", "expires": _SCADE}])
    assert eta_sessione(tmp_path)["nata_il"] == "2026-10-02T10:19:07Z"


def test_niente_profilo_o_file_illeggibile_da_none(tmp_path):
    assert eta_sessione(tmp_path) is None
    _scrivi(tmp_path, "non è una lista")
    assert eta_sessione(tmp_path) is None


def test_nessun_sid_lascia_solo_l_ultimo_refresh(tmp_path):
    _scrivi(tmp_path, [{"name": "NID", "value": "x", "expires": _SCADE}], mtime=0)
    assert eta_sessione(tmp_path) == {"nata_il": None, "ultimo_refresh": "1970-01-01T00:00:00Z"}


def test_la_riga_per_secrets_status_ha_solo_date_e_sonda(tmp_path, monkeypatch, capsys):
    """`python -m app.stato_sessione` è ciò che legge la CLI dell'host: una riga JSON."""
    from types import SimpleNamespace

    from app import sonda, stato_sessione
    monkeypatch.setattr(stato_sessione, "get_settings",
                        lambda: SimpleNamespace(nlm_home=str(tmp_path)))
    monkeypatch.setattr(sonda, "ultimo", lambda: {"quando": "2026-10-05T17:12:13Z", "esito": "ok"})
    assert stato_sessione.main() == 1                       # niente profilo
    assert json.loads(capsys.readouterr().out) is None
    _scrivi(tmp_path, [{"name": "SID", "value": "segreto", "expires": _SCADE}])
    assert stato_sessione.main() == 0
    riga = capsys.readouterr().out
    assert "segreto" not in riga
    assert json.loads(riga)["nata_il"] == "2026-10-02T10:19:07Z"
    assert json.loads(riga)["sonda"]["esito"] == "ok"
