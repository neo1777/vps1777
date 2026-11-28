"""Quattro buchi del verificatore del ledger, visti da Arianna rileggendo un articolo (27/11/2026).

1. Una voce `opt-in` o `removed` non diceva che cosa c'è al posto suo: il declassamento di
   Watchtower a «opt-in, non supportato», rifatto oggi, avrebbe dato verde.
2. Un rinvio a giudizio (`follow_up.manuale`) senza `rivedi_dopo` dava verde e non tornava più
   davanti a nessuno.
3. Un `follow_up` scritto come testo faceva cadere il verificatore con un AttributeError invece
   di un rosso che dice che cosa correggere; una data scritta male, lo stesso più in là.

(Il quarto, i conti per origine in SECURITY.md, sta in test_check_findings_origine.py.)
Il verificatore vuole PyYAML: si lancia come processo, come in test_ledger_condizione_o_data.py.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parents[2]


def _verifica(tmp_path: Path, voce: str) -> subprocess.CompletedProcess:
    ledger = tmp_path / "features.yaml"
    ledger.write_text(f"""_meta: {{baseline_completo: false}}
features:
  - id: prova.voce
    nome: "prova"
    cosa: "prova"
    dove: []
    verify: {{manual: "prova"}}
{voce}
""", encoding="utf-8")
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


@pytest.mark.parametrize("stato", ["opt-in", "removed"])
def test_una_voce_non_accesa_dice_che_cosa_c_e_al_posto_suo(tmp_path, stato):
    r = _verifica(tmp_path, f'    status: {stato}\n    decisione: "declassata il 10/06"')
    assert r.returncode != 0, r.stdout
    assert f"'{stato}' senza 'al_posto_suo'" in r.stdout, r.stdout
    r = _verifica(tmp_path, f'    status: {stato}\n    decisione: "declassata il 10/06"\n'
                            '    al_posto_suo: "   "')
    assert r.returncode != 0 and "senza 'al_posto_suo'" in r.stdout, r.stdout
    r = _verifica(tmp_path, f'    status: {stato}\n    decisione: "declassata il 10/06"\n'
                            '    al_posto_suo: "l\'aggiornamento gestito dalla CLI"')
    assert r.returncode == 0, r.stdout


def test_una_voce_accesa_di_default_non_deve_dirlo(tmp_path):
    r = _verifica(tmp_path, "    status: active-default")
    assert r.returncode == 0 and "al_posto_suo" not in r.stdout, r.stdout


def test_un_rinvio_a_giudizio_senza_data_e_rosso(tmp_path):
    base = '    status: deferred\n    decisione: "rinviata"\n    follow_up:\n      manuale:\n        cosa: "quando il ritmo sarà regolare"\n'
    r = _verifica(tmp_path, base)
    assert r.returncode != 0, r.stdout
    assert "follow_up.manuale senza rivedi_dopo" in r.stdout, r.stdout
    r = _verifica(tmp_path, base + '        rivedi_dopo: "2020-01-01"\n')
    assert r.returncode == 0, r.stdout
    assert "[RIVEDI] prova.voce: rinvio-a-giudizio scaduto il 2020-01-01" in r.stdout, r.stdout


def test_un_follow_up_scritto_come_testo_e_un_rosso_che_dice_cosa_correggere(tmp_path):
    r = _verifica(tmp_path, '    status: deferred\n    decisione: "rinviata"\n    follow_up: "timer sicuro"')
    assert r.returncode != 0
    assert "Traceback" not in r.stdout + r.stderr, r.stderr
    assert "follow_up deve essere una mappa" in r.stdout and "timer sicuro" in r.stdout, r.stdout


def test_un_manuale_scritto_come_testo_e_una_data_scritta_male_non_fanno_cadere(tmp_path):
    r = _verifica(tmp_path, '    status: deferred\n    decisione: "rinviata"\n    follow_up:\n      manuale: "poi"')
    assert r.returncode != 0 and "Traceback" not in r.stdout + r.stderr, r.stderr
    assert "follow_up.manuale deve essere una mappa" in r.stdout, r.stdout
    r = _verifica(tmp_path, '    status: deferred\n    decisione: "rinviata"\n    follow_up:\n      manuale:\n        cosa: "x"\n        rivedi_dopo: "fra un mese"')
    assert r.returncode != 0 and "Traceback" not in r.stdout + r.stderr, r.stderr
    assert "non è una data AAAA-MM-GG" in r.stdout, r.stdout
    r = _verifica(tmp_path, '    status: deferred\n    decisione: "rinviata"\n    follow_up:\n      verify: {path_exists: non/esiste}\n      rivedi_dopo: "31/12/2026"')
    assert r.returncode != 0 and "Traceback" not in r.stdout + r.stderr, r.stderr
    assert "follow_up.rivedi_dopo «31/12/2026» non è una data" in r.stdout, r.stdout


def test_un_difetto_di_forma_e_un_rosso_solo_non_due(tmp_path):
    """Un `manuale` scritto come testo o una data scritta male non aggiungono anche il rosso
    «senza rivedi_dopo»: chi legge crederebbe a due difetti (nota di Sagoma)."""
    for voce in ('    status: deferred\n    decisione: "rinviata"\n    follow_up:\n      manuale: "poi"',
                 '    status: deferred\n    decisione: "rinviata"\n    follow_up:\n      manuale:\n'
                 '        cosa: "x"\n        rivedi_dopo: "fra un mese"'):
        r = _verifica(tmp_path, voce)
        assert r.returncode != 0 and "Traceback" not in r.stdout + r.stderr, r.stderr
        assert r.stdout.count("prova.voce:") == 1, r.stdout
