"""Un update che trova il lock di un altro update non è FALLITO: è un «riprova dopo».

Misurato il 27/09/2026 alle 01:48, alla prima installazione della 0.58.0: il timer
dell'auto-update è passato da `weekly` a `daily`, e con `Persistent=true` il
`daemon-reload` fatto DALL'update lo ha fatto scattare subito (l'ultimo giro era di
cinque giorni prima). Il giro ha trovato il lock dell'update in corso, è uscito con 1,
e `OnFailure=` ha mandato all'owner su Telegram «auto-update fallito», mentre l'update
stava riuscendo. Un falso allarme è il modo in cui un canale d'allarme smette di essere
letto.

La cura: il lock occupato esce con 75 (EX_TEMPFAIL di sysexits.h, «riprova più
tardi»), e le unit che lanciano un update lo contano come successo
(`SuccessExitStatus=75`). A mano il messaggio resta, e il codice resta non-zero.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("vps1777_cli", _ROOT / "tools" / "vps1777.py")
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)


def test_update_col_lock_occupato_esce_con_75(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "acquire_lock", lambda repo: None)
    with pytest.raises(SystemExit) as e:
        v.cmd_update(tmp_path, SimpleNamespace(from_intent=None, version=None))
    assert e.value.code == v.ESITO_LOCK_OCCUPATO == 75


@pytest.mark.parametrize("unit", ["vps1777-auto-update.service", "vps1777-update.service"])
def test_le_unit_dell_update_contano_75_come_successo(unit):
    testo = (_ROOT / "systemd" / unit).read_text()
    assert re.search(r"^SuccessExitStatus=.*\b75\b", testo, re.M), (
        f"{unit}: senza SuccessExitStatus=75 un lock occupato accende OnFailure "
        f"e manda un falso allarme")
