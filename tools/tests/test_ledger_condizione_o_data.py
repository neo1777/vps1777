"""Un rinvio con una condizione verificabile ha anche una data: «condizione O data».

Lezione dei gemelli dei rinvii (curatrice dei rimandi, F1-Gbis, 27/09/2026; il gemello è
todo_or_die): un rinvio che aspetta SOLO una condizione non scatta mai se la condizione
non si avvera. È successo con Graphiti, promesso «dopo il test» cinque volte, e il test è
stato abolito. Quindi una `deferred` con `follow_up.verify` deve portare anche
`follow_up.rivedi_dopo`: la macchina la chiude quando la condizione diventa vera
([PROMUOVI]), e la rimette davanti quando la data passa ([RIVEDI]), qualunque delle due
arrivi prima.

Il verificatore vuole PyYAML e questa suite gira senza dipendenze: lo si lancia come
processo con `uv run --with pyyaml`, così in CI gira davvero invece di saltare.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parents[2]


def _verifica(tmp_path: Path, follow_up: str) -> subprocess.CompletedProcess:
    ledger = tmp_path / "features.yaml"
    ledger.write_text(f"""_meta: {{baseline_completo: false}}
features:
  - id: prova.rinvio
    nome: "prova"
    cosa: "prova"
    dove: []
    status: deferred
    since: "rinviato"
    decisione: "prova"
    verify: {{manual: "prova"}}
    follow_up:
{follow_up}
""")
    try:
        import yaml  # noqa: F401
        cmd = [sys.executable]
    except ImportError:
        if not shutil.which("uv"):
            pytest.skip("né PyYAML né uv: il verificatore non si può lanciare")
        cmd = ["uv", "run", "--no-project", "--with", "pyyaml", "python"]
    return subprocess.run([*cmd, str(RADICE / "tools" / "verify-features.py"),
                           "--ledger", str(ledger), "--repo", str(RADICE)],
                          capture_output=True, text=True, timeout=300)


def test_condizione_senza_data_e_un_rinvio_che_puo_non_scattare(tmp_path):
    r = _verifica(tmp_path, "      verify: {path_exists: non/esiste/ancora}")
    assert r.returncode != 0, r.stdout
    assert "senza data" in r.stdout, r.stdout


def test_condizione_con_data_passata_rimette_il_rinvio_davanti(tmp_path):
    r = _verifica(tmp_path, "      verify: {path_exists: non/esiste/ancora}\n"
                            "      rivedi_dopo: \"2020-01-01\"")
    assert r.returncode == 0, r.stdout
    assert "[RIVEDI] prova.rinvio" in r.stdout, r.stdout


def test_condizione_con_data_futura_tace(tmp_path):
    r = _verifica(tmp_path, "      verify: {path_exists: non/esiste/ancora}\n"
                            "      rivedi_dopo: \"2099-01-01\"")
    assert r.returncode == 0 and "prova.rinvio" not in r.stdout, r.stdout
