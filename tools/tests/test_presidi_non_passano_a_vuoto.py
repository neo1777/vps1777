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


def _verify_features(ledger: Path, repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "tools" / "verify-features.py"),
                           "--ledger", str(ledger), "--repo", str(repo)],
                          capture_output=True, text=True, check=False)


@pytest.mark.parametrize("testo", ["", "- una\n- due\n", "features: 3\n", "features: [ciao]\n",
                                   "features: [\n"])
def test_un_ledger_storto_esce_2_e_dice_perche(tmp_path: Path, testo: str) -> None:
    """Un file vuoto, una lista al posto della mappa, `features` che non è una lista, una voce
    che non è una mappa, un YAML rotto: prima alcuni facevano crollare lo strumento con un
    errore Python (rilievo di Sagoma, 25/11). Ora esce 2, «non ho potuto guardare», e lo dice."""
    ledger = tmp_path / "features.yaml"
    ledger.write_text(testo, encoding="utf-8")
    r = _verify_features(ledger, ROOT)
    assert r.returncode == 2, (r.returncode, r.stderr[-400:])
    assert "Traceback" not in r.stderr, r.stderr[-400:]
    assert "ERRORE: " in r.stderr


def test_senza_la_cli_le_voci_dei_comandi_sono_rosse_senza_crollare(tmp_path: Path) -> None:
    """Un repo senza `tools/vps1777.py`: ogni voce `cli_command` è un fallimento che lo nomina,
    non un FileNotFoundError che ferma il referto a metà."""
    r = _verify_features(ROOT / "features.yaml", tmp_path)
    assert r.returncode == 1, (r.returncode, r.stderr[-400:])
    assert "Traceback" not in r.stdout + r.stderr
    assert "tools/vps1777.py MANCA" in r.stdout + r.stderr


def test_la_semina_di_tools_script_finisce_il_31_gennaio() -> None:
    """DER-03: una semina ha una data di fine, e il controllo la legge (scelta di Neo
    2026-11-25-soglia-tools-script-semina). L'ultimo giorno i non dichiarati sono avvisi; dal
    giorno dopo sono fallimenti duri e l'esito è 1."""
    def gira(oggi: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(ROOT / "tools" / "verify-features.py"),
                               "--repo", str(ROOT), "--oggi", oggi],
                              capture_output=True, text=True, check=False)
    ultimo, dopo = gira("2027-01-31"), gira("2027-02-01")
    assert "in semina fino al 2027-01-31" in ultimo.stdout + ultimo.stderr
    assert "✗ [NON DICHIARATO] tools_script" not in ultimo.stdout + ultimo.stderr
    assert dopo.returncode == 1
    assert "✗ [NON DICHIARATO] tools_script" in dopo.stdout + dopo.stderr
