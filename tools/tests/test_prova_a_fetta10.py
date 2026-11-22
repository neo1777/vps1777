"""CI e guardiani dopo la rilettura col catalogo di requisiti (decima fetta).

Il filo è lo stesso delle prove empiriche: un guardiano che salta qualcosa e chiude verde.
"""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github" / "workflows"


# ── i workflow ─────────────────────────────────────────────────────────────────

def test_ogni_job_ha_un_tempo_massimo() -> None:
    senza = []
    for f in sorted(WF.glob("*.yml")):
        dati = yaml.safe_load(f.read_text(encoding="utf-8"))
        for nome, job in (dati.get("jobs") or {}).items():
            if "runs-on" in job and "timeout-minutes" not in job:
                senza.append(f"{f.name}:{nome}")
    assert not senza, f"job senza timeout-minutes (un passo appeso gira fino al tetto di GitHub, sei ore): {senza}"


def test_pytest_e_pyyaml_hanno_una_versione_e_la_stessa_in_ci_e_in_locale() -> None:
    versioni: dict[str, set[str]] = {"pytest": set(), "pyyaml": set()}
    for f in (WF / "ci.yml", ROOT / "tools" / "check.sh"):
        for riga in f.read_text(encoding="utf-8").splitlines():
            codice = riga.split("#", 1)[0] if riga.lstrip().startswith("#") else riga
            if riga.lstrip().startswith("#"):
                continue
            assert not re.search(r"uvx pytest(\s|$)", codice), f"{f.name}: pytest senza versione: {riga.strip()[:80]}"
            assert not re.search(r"--with (pytest|pyyaml)(\s|$)", codice), f"{f.name}: senza versione: {riga.strip()[:80]}"
            versioni["pytest"].update(re.findall(r"pytest(?:@|==)([0-9.]+)", codice))
            versioni["pyyaml"].update(re.findall(r"pyyaml==([0-9.]+)", codice))
    assert len(versioni["pytest"]) == 1 and len(versioni["pyyaml"]) == 1, versioni


def test_la_cadenza_non_misurata_non_e_un_verde_mensile() -> None:
    testo = (WF / "rebuild-mensile.yml").read_text(encoding="utf-8")
    riga = next(r for r in testo.splitlines() if '"$RC" = 2' in r)
    assert "exit 1" in riga and "exit 0" not in riga


def test_la_release_pubblicata_viene_riletta() -> None:
    testo = (WF / "release.yml").read_text(encoding="utf-8")
    dopo = testo[testo.index("softprops/action-gh-release"):]
    assert "gh release view" in dopo
    for allegato in ("SHA256SUMS.sig", "SHA256SUMS.pem", "vps1777-runtime-v$VERSIONE.tar.gz"):
        assert allegato in dopo[dopo.index("gh release view"):]


# ── il gate anti-leak ──────────────────────────────────────────────────────────

def _repo_finto(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    (r / "security").mkdir(parents=True)
    shutil.copy(ROOT / "security" / "check_no_leaks.py", r / "security" / "check_no_leaks.py")
    (r / "leggimi.md").write_text("niente da nascondere\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=r, check=True)
    return r


def test_un_file_che_non_si_legge_non_e_pulito(tmp_path: Path) -> None:
    if os.geteuid() == 0:
        pytest.skip("root legge tutto: il caso non si costruisce")
    r = _repo_finto(tmp_path)
    chiuso = r / "chiuso.txt"
    chiuso.write_text("x\n", encoding="utf-8")
    chiuso.chmod(0)
    try:
        p = subprocess.run([sys.executable, "security/check_no_leaks.py"], cwd=r, capture_output=True, text=True,
                           check=False)
    finally:
        chiuso.chmod(0o600)
    assert p.returncode == 2, p.stdout + p.stderr
    assert "chiuso.txt" in p.stdout and "✓ gate anti-leak" not in p.stdout


def test_il_repo_finto_sano_passa_e_conta_i_binari(tmp_path: Path) -> None:
    r = _repo_finto(tmp_path)
    (r / "immagine.bin").write_bytes(b"\x00\x01\x02" * 10)
    p = subprocess.run([sys.executable, "security/check_no_leaks.py"], cwd=r, capture_output=True, text=True, check=False)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "1 file binari" in p.stdout


# ── il confronto dei tre installatori ──────────────────────────────────────────

def test_un_asse_che_non_trova_niente_non_e_concordano(monkeypatch) -> None:
    spec = importlib.util.spec_from_file_location("confronta_a10", ROOT / "security" / "confronta-installer.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.confronta()[0] == 0, "sul repo vero i tre concordano"
    monkeypatch.setattr(m, "estrai", lambda testo, pattern: set())
    esito, righe = m.confronta()
    assert esito == 2, righe


def test_le_liste_dei_servizi_nei_workflow_sono_quelle_delle_immagini() -> None:
    """L'elenco è ripetuto a mano in cinque punti di quattro workflow: tutti devono nominare
    esattamente i servizi che hanno un Dockerfile (è già successo che uno restasse fuori)."""
    attesi = sorted(p.parent.name for p in (ROOT / "services").glob("*/Dockerfile"))
    trovate = 0
    for f in sorted(WF.glob("*.yml")):
        for riga in f.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s+service: \[(.+)\]\s*$", riga) or re.match(r"\s+for (?:s|svc) in (.+); do\s*$", riga)
            if not m:
                continue
            nomi = sorted(x.strip() for x in re.split(r"[,\s]+", m.group(1)) if x.strip())
            if "gateway" not in nomi:
                continue
            trovate += 1
            assert nomi == attesi, f"{f.name}: {nomi} ≠ {attesi}"
    assert trovate == 5, f"mi aspettavo 5 liste di servizi nei workflow, ne ho trovate {trovate}"


def test_il_nome_del_tag_ha_una_forma_prima_di_entrare_nei_passi() -> None:
    testo = (WF / "release.yml").read_text(encoding="utf-8")
    i = testo.index('VERSION="${GITHUB_REF_NAME#v}"')
    j = testo.index('echo "VERSION=$VERSION" >> "$GITHUB_OUTPUT"')
    assert "=~" in testo[i:j] and "exit 1" in testo[i:j]


def test_un_immagine_non_trovata_non_e_uno_scan_riuscito() -> None:
    testo = (WF / "trivy.yml").read_text(encoding="utf-8")
    ramo = testo[testo.index("*NAME_UNKNOWN*)"):testo.index('echo "::error::NON HO POTUTO VERIFICARE')]
    assert "exit 1" in ramo
