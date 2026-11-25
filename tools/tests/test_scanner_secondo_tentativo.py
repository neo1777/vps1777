"""Lo scanner dei segreti guarda due volte prima di dire rosso (25/11/2026).

trufflehog segnala anche ciò che non riesce a verificare: se la verifica remota fallisce per un momento
storto della rete, stringhe innocue escono come «non verificabili» e il controllo arrossisce da solo.
Qui `docker` è finto: conta le chiamate e risponde come gli si dice.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
FINITO = '{"level":"info-0","msg":"finished scanning"}'


def _gira(tmp_path: Path, esiti: list[int], specie: str = "verified") -> tuple[int, str, int]:
    """Lancia `scanner.sh segreti` con un docker finto che esce, chiamata dopo chiamata, con `esiti`."""
    finti = tmp_path / "bin"
    finti.mkdir()
    conta = tmp_path / "chiamate"
    conta.write_text("")
    docker = finti / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        f"echo x >> '{conta}'\n"
        f"n=$(wc -l < '{conta}')\n"
        f"esiti=({' '.join(map(str, esiti))})\n"
        'rc="${esiti[$((n - 1))]:-0}"\n'
        'specie=($SPECIE); if [ "$rc" -eq 183 ]; then echo "Found ${specie[$((n - 1))]:-${specie[0]}} result"; echo "Detector Type: Github"; echo "File: x.yml";'
        ' echo "Verification issue: i/o timeout"; fi\n'
        f"echo '{FINITO}'\n"
        'exit "$rc"\n')
    docker.chmod(0o755)
    cartella = tmp_path / "src"
    cartella.mkdir()
    r = subprocess.run(["bash", str(_ROOT / "tools" / "scanner.sh"), "segreti", str(cartella)],
                       capture_output=True, text=True, timeout=60,
                       env={**os.environ, "PATH": f"{finti}:{os.environ['PATH']}", "SCANNER_PAUSA_S": "0", "SPECIE": specie})
    return r.returncode, r.stdout + r.stderr, len(conta.read_text().splitlines())


def test_un_risultato_che_al_secondo_sguardo_non_c_e_non_e_rosso(tmp_path):
    rc, detto, chiamate = _gira(tmp_path, [183, 0], specie="unverified")
    assert (rc, chiamate) == (0, 2), detto
    assert "riguardo una volta" in detto


def test_un_risultato_verificato_e_rosso_subito_senza_riguardare(tmp_path):
    rc, detto, chiamate = _gira(tmp_path, [183, 183])
    assert (rc, chiamate) == (1, 1), detto
    assert "riguardo" not in detto


def test_un_verificato_al_primo_sguardo_non_diventa_non_misurato_se_poi_la_rete_cede(tmp_path):
    # il secondo giro, se ci fosse, direbbe «unverified»: non deve nemmeno partire
    rc, detto, chiamate = _gira(tmp_path, [183, 183], specie="verified unverified")
    assert (rc, chiamate) == (1, 1), detto
    assert "non ho potuto verificare" not in detto


def test_un_incerto_che_al_secondo_sguardo_si_verifica_e_rosso(tmp_path):
    rc, detto, chiamate = _gira(tmp_path, [183, 183], specie="unverified verified")
    assert (rc, chiamate) == (1, 2), detto


def test_risultati_mai_verificati_sono_non_misurato_col_motivo(tmp_path):
    rc, detto, chiamate = _gira(tmp_path, [183, 183], specie="unverified")
    assert (rc, chiamate) == (2, 2), detto
    assert "non ho potuto verificare" in detto and "i/o timeout" in detto


def test_il_pulito_non_si_guarda_due_volte(tmp_path):
    rc, detto, chiamate = _gira(tmp_path, [0])
    assert (rc, chiamate) == (0, 1), detto
    assert "riguardo" not in detto


@pytest.mark.parametrize("guasto", [125, 124, 1])
def test_un_guasto_al_secondo_sguardo_e_non_misurato_e_non_verde(tmp_path, guasto):
    rc, detto, chiamate = _gira(tmp_path, [183, guasto], specie="unverified")
    assert (rc, chiamate) == (2, 2), detto
