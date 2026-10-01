"""`tools/fatti-nei-doc.py`: i numeri ripetuti nei doc sono quelli che il codice conta.

Il presidio ha la sua autoprova (in CI, nel job `lint`); questo file lo esegue col
comando che lo eseguirà davvero — pytest su `tools/tests/` — e fissa le tre proprietà
che la sua esistenza promette:

  1. il repo vero passa (se no il presidio è rosso su main, o i doc sono andati);
  2. un documento con un numero sbagliato, in una COPIA del repo, fallisce, e l'errore
     nomina il file e la riga giusti;
  3. una riga storica — con una data o una versione — col numero vecchio NON fa scattare.

E una quarta, quando c'è docker: la definizione di «container di default», contata dal
presidio leggendo i compose per righe, coincide con ciò che `docker compose config
--services` risponde sugli stessi file e profili. Senza docker si salta, e lo dice.

Stdlib-only (più pytest): la CI esegue questa cartella con `uvx pytest`.
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("fatti_nei_doc", RADICE / "tools" / "fatti-nei-doc.py")
fd = importlib.util.module_from_spec(_spec)
sys.modules["fatti_nei_doc"] = fd   # @dataclass cerca il modulo in sys.modules
_spec.loader.exec_module(fd)


@pytest.fixture
def copia(tmp_path: Path) -> Path:
    fd.copia_minima(RADICE, tmp_path)
    return tmp_path


def _riga_di(p: Path, testo: str) -> int:
    return next(i for i, r in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
                if testo in r)


def test_il_repo_vero_passa():
    e = fd.controlla(RADICE)
    assert not e.errori, "\n".join(e.errori)
    # e ha guardato davvero: un presidio che confronta zero numeri non è un verde
    assert e.viste >= len(fd.FRASI)


def test_un_numero_sbagliato_fallisce_con_la_riga_giusta(copia: Path):
    n = fd.conta(copia)[0]["archive_tool"]
    p = copia / "docs" / "en" / "ARCHIVE.md"
    vecchio = f"`archive-mcp` exposes **{n} tools**"
    t = p.read_text(encoding="utf-8")
    assert vecchio in t
    p.write_text(t.replace(vecchio, f"`archive-mcp` exposes **{n + 2} tools**"), encoding="utf-8")
    riga = _riga_di(p, f"exposes **{n + 2} tools**")

    e = fd.controlla(copia)
    assert len(e.errori) == 1, e.errori
    assert e.errori[0].startswith(f"docs/en/ARCHIVE.md:{riga} "), e.errori[0]
    assert f"dice {n + 2}" in e.errori[0] and f"ne conta {n}" in e.errori[0]


def test_il_registro_cambia_e_le_frasi_fuori_tabella_diventano_rosse(copia: Path):
    """Il caso H50: una voce passa da closed a partial e le frasi che contano le chiuse
    (REVIEW.md, ARCHITECTURE IT/EN) devono accorgersene."""
    p = copia / "security" / "findings.yml"
    t = p.read_text(encoding="utf-8")
    assert "    status: closed\n" in t
    p.write_text(t.replace("    status: closed\n", "    status: partial\n", 1), encoding="utf-8")
    e = fd.controlla(copia)
    file_rossi = {x.split(":", 1)[0] for x in e.errori}
    assert {"REVIEW.md", "docs/ARCHITECTURE.md", "docs/en/ARCHITECTURE.md"} <= file_rossi, e.errori


@pytest.mark.parametrize("storica", [
    "Il 24/09/2026 `nb1777` ne espone **{n}** (contati quel giorno).",
    "In v0.63.2 `nb1777` ne espone **{n}**.",
    "Al 2026-09-24 `nb1777` ne espone **{n}**.",
])
def test_una_riga_storica_col_numero_vecchio_non_scatta(copia: Path, storica: str):
    n = fd.conta(copia)[0]["nb1777_tool"] - 1
    p = copia / "docs" / "INSTALL.md"
    with p.open("a", encoding="utf-8") as f:
        f.write("\n" + storica.format(n=n) + "\n")
    e = fd.controlla(copia)
    assert not e.errori, e.errori
    assert e.saltate >= 1


def test_il_changelog_non_si_legge():
    assert all(not f.file.startswith(("CHANGELOG", "docs/roadmap/")) for f in fd.FRASI)


def test_la_definizione_di_container_di_default_combacia_con_docker():
    if shutil.which("docker") is None or subprocess.run(
            ["docker", "info"], capture_output=True).returncode != 0:
        pytest.skip("docker non disponibile: la definizione non è confrontata con compose")
    feat = set(fd._letterale(RADICE, "DEFAULT_FEATURES"))
    ops = fd._letterale(RADICE, "OPS_COMPOSE_FEATURES")
    argv = ["docker", "compose", "--env-file", "/dev/null", "-f", "compose.yaml",
            "-f", "compose.ingress.tailscale.yaml", "--profile", "ingress.tailscale"]
    for f in sorted(feat & set(ops)):
        stem, profilo = ops[f]
        argv += ["-f", f"compose.{stem}.yaml"] + (["--profile", profilo] if profilo else [])
    r = subprocess.run([*argv, "config", "--services"], cwd=RADICE, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert set(r.stdout.split()) == fd.container_default(RADICE)


def test_autoprova_gira_anche_in_pytest():
    assert fd._autoprova() == 0
