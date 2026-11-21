"""Due presìdi che davano verde senza aver guardato niente (giro di revisione del 21/11/2026).

- `lock-salti.py`: due lock senza la chiave `package` (un cambio di formato di uv.lock) davano
  «0 → 0, nessun attraversamento» ed esito 0, contro il suo stesso contratto «non ho guardato = 2».
- `verify-features.py`: senza `_meta` il ledger valeva «in semina» e ogni «non dichiarato»
  diventava un avviso; con zero voci il verdetto era «quadrano».
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_lock_senza_pacchetti_non_e_un_verde(tmp_path: Path) -> None:
    prima, dopo = tmp_path / "prima.lock", tmp_path / "dopo.lock"
    prima.write_text('[[packages]]\nname = "x"\nversion = "1.0"\n', encoding="utf-8")
    dopo.write_text('[[packages]]\nname = "x"\nversion = "9.0"\n', encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "lock-salti.py"), str(prima), str(dopo)],
                       capture_output=True, text=True, check=False)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "NON MISURATO" in r.stderr


def test_lock_veri_si_leggono_ancora(tmp_path: Path) -> None:
    prima, dopo = tmp_path / "prima.lock", tmp_path / "dopo.lock"
    for f in (prima, dopo):
        f.write_text('[[package]]\nname = "x"\nversion = "1.0"\n', encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "lock-salti.py"), str(prima), str(dopo)],
                       capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stdout + r.stderr


def test_un_ledger_senza_voci_non_quadra(tmp_path: Path) -> None:
    pytest.importorskip("yaml")
    ledger = tmp_path / "features.yaml"
    ledger.write_text("features: []\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "verify-features.py"),
                        "--ledger", str(ledger), "--repo", str(ROOT)],
                       capture_output=True, text=True, check=False)
    assert r.returncode != 0, "zero voci nel ledger e il verdetto è verde"


def test_senza_meta_il_ledger_e_severo() -> None:
    sorgente = (ROOT / "tools" / "verify-features.py").read_text(encoding="utf-8")
    assert '.get("baseline_completo", True)' in sorgente, \
        "il default di `baseline_completo` è tornato permissivo"
