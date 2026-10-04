"""Il campanello delle «cose da fare» (riga c-20261004-il-campanello-anche-su-telegram-la-spint).

Un messaggio a Neo per giro: suona quando il conto cambia, tace quando è uguale.
Porta solo numeri e un link a claude.ai: niente testo libero da fuori.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("vps1777_campanello", _ROOT / "tools" / "vps1777.py")
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)

URL = "https://claude.ai/artifact/esempio"


def _args(**kw) -> argparse.Namespace:
    base = {"pagine": 3, "decisioni": 114, "rossi": 0, "url": URL, "quando": "", "prova": False}
    base.update(kw)
    return argparse.Namespace(**base)


@pytest.fixture
def spia(monkeypatch):
    mandati: list[str] = []
    monkeypatch.setattr(v, "telegram_notify", lambda repo, testo: mandati.append(testo))
    return mandati


def test_suona_al_primo_giro_e_tace_con_lo_stesso_conto(tmp_path, spia) -> None:
    assert v.cmd_campanello(tmp_path, _args()) == 0
    assert len(spia) == 1 and "3 pagine · 114 decisioni" in spia[0] and URL in spia[0]
    assert v.cmd_campanello(tmp_path, _args()) == 0
    assert len(spia) == 1, "lo stesso conto ha suonato due volte"


def test_risuona_se_il_conto_cambia(tmp_path, spia) -> None:
    v.cmd_campanello(tmp_path, _args())
    v.cmd_campanello(tmp_path, _args(decisioni=113, rossi=2))
    assert len(spia) == 2 and "2 rossi" in spia[1]


def test_porta_solo_un_link_di_claude_ai(tmp_path, spia) -> None:
    with pytest.raises(SystemExit):
        v.cmd_campanello(tmp_path, _args(url="https://example.invalid/altro"))
    with pytest.raises(SystemExit):
        v.cmd_campanello(tmp_path, _args(pagine=-1))
    assert spia == []


def test_la_prova_non_manda_e_non_segna(tmp_path, spia, capsys) -> None:
    v.cmd_campanello(tmp_path, _args(prova=True))
    assert spia == [] and "114 decisioni" in capsys.readouterr().out
    v.cmd_campanello(tmp_path, _args())
    assert len(spia) == 1, "la prova aveva segnato il conto come già suonato"
