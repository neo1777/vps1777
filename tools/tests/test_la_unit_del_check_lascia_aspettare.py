"""La unit del check giornaliero non uccide il check mentre aspetta un update.

Dalla 0.98.21 `vps1777 check` si mette in fila con l'update e lo aspetta fino a
CHECK_ATTESA_UPDATE_S. La unit aveva `TimeoutStartSec=120`: systemd avrebbe ucciso il check dopo
due minuti di attesa, la unit sarebbe risultata fallita e sarebbe partito l'avviso, proprio nel
caso che la fila cura (visto rileggendo i documenti il 26/11/2026, non in esercizio).
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("vps1777_cli_tetto", _ROOT / "tools" / "vps1777.py")
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)

MARGINE_DEL_CHECK_S = 300      # le sorveglianze, le notifiche e la domanda a GitHub, col loro tempo


def _tetto(unit: str) -> int:
    testo = (_ROOT / "systemd" / unit).read_text(encoding="utf-8")
    trovati = re.findall(r"^TimeoutStartSec=(\d+)\s*$", testo, re.M)
    assert len(trovati) == 1, f"{unit}: TimeoutStartSec va dichiarato una volta, in secondi"
    return int(trovati[0])


def test_il_tetto_della_unit_sta_sopra_l_attesa_del_check_piu_il_check():
    assert _tetto("vps1777-check-update.service") >= v.CHECK_ATTESA_UPDATE_S + MARGINE_DEL_CHECK_S


def test_le_unit_dell_update_reggono_l_attesa_di_un_check_anche_dopo_il_re_exec():
    """L'update aspetta un check fino a LOCK_ATTESA_CHECK_S, e il giro rieseguito dalla CLI nuova
    LOCK_GIRI_DOPO_REEXEC volte tanto: il tetto delle unit deve lasciarglielo fare."""
    attesa = v.LOCK_ATTESA_CHECK_S * v.LOCK_GIRI_DOPO_REEXEC
    for unit in ("vps1777-update.service", "vps1777-auto-update.service"):
        assert _tetto(unit) >= attesa + 600, unit
