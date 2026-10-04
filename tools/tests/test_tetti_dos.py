"""I tetti contro il DoS (OWASP API4, 04/10/2026).

Prima di questa data nessun servizio di base aveva un tetto di processi, di CPU o di
memoria: un processo impazzito poteva prendersi la VPS intera. I tetti di processi e di
CPU stanno su tutti (la CPU rallenta, non uccide). La memoria solo dove il picco è
misurato: un tetto a occhio uccide il servizio nel mezzo di una chiamata, e questo test
NON chiede un mem_limit dove il compose dichiara che manca la misura.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

RADICE = Path(__file__).resolve().parents[2]


def test_ogni_servizio_ha_il_tetto_di_processi_e_di_cpu() -> None:
    d = yaml.safe_load((RADICE / "compose.yaml").read_text(encoding="utf-8"))
    for nome, s in d["services"].items():
        assert isinstance(s.get("pids_limit"), int) and 0 < s["pids_limit"] <= 1024, nome
        assert s.get("cpus") is not None and 0 < float(s["cpus"]) <= 4, nome
    b = yaml.safe_load((RADICE / "compose.ops.backup.yaml").read_text(encoding="utf-8"))
    assert b["services"]["backup"].get("pids_limit"), "backup senza tetto di processi"


def test_un_servizio_senza_tetto_di_memoria_dice_perche() -> None:
    testo = (RADICE / "compose.yaml").read_text(encoding="utf-8")
    d = yaml.safe_load(testo)
    for nome, s in d["services"].items():
        if s.get("mem_limit") is None:
            blocco = re.split(r"\n  [a-z0-9-]+:\n|\n[a-z]", testo.split(f"\n  {nome}:\n", 1)[1], maxsplit=1)[0]
            assert "# mem_limit: non ancora" in blocco, (
                f"{nome}: niente mem_limit e niente perché — o la misura, o la riga che dice cosa manca")


def test_il_gateway_passa_il_limite_di_concorrenza_a_uvicorn() -> None:
    main = (RADICE / "services/gateway/app/__main__.py").read_text(encoding="utf-8")
    assert "limit_concurrency=s.gateway_limit_concurrency" in main
