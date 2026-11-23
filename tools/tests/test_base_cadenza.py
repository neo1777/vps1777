"""`tools/base-cadenza.py`: le basi fissate per digest non restano indietro senza che nessuno lo veda.

Dal 27/09 al 21/11/2026 Dependabot non ha mai proposto il digest nuovo di python:3.12-slim. Lo strumento
confronta il digest fissato con quello che il registro dà oggi; qui registro e storia di git sono finti.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path

import pytest

_RADICE = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("base_cadenza", _RADICE / "tools" / "base-cadenza.py")
cadenza = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cadenza)

A, B = "sha256:" + "a" * 64, "sha256:" + "b" * 64
OGGI = dt.date(2026, 11, 23)


def _repo(tmp_path, digest=A):
    for s in ("uno", "due"):
        d = tmp_path / "services" / s
        d.mkdir(parents=True)
        (d / "Dockerfile").write_text(f"FROM python:3.12-slim@{digest} AS builder\nRUN true\nFROM python:3.12-slim@{digest}\n")
    return tmp_path


def test_le_basi_vere_del_repo_si_trovano_tutte():
    trovate = cadenza.basi(_RADICE)
    nomi = {n for n, _, _ in trovate}
    assert {"python", "caddy"} <= nomi
    assert all(dove for dove in trovate.values())


def test_in_pari(tmp_path):
    rc, righe = cadenza.verdetto(cadenza.basi(_repo(tmp_path)), lambda n, t: A, lambda d, f: OGGI, oggi=OGGI)
    assert rc == 0 and "in pari (2 Dockerfile)" in righe[0]


def test_diverso_da_poco_non_e_un_allarme(tmp_path):
    rc, righe = cadenza.verdetto(cadenza.basi(_repo(tmp_path)), lambda n, t: B,
                                 lambda d, f: OGGI - dt.timedelta(days=10), oggi=OGGI)
    assert rc == 0 and "sotto la soglia" in righe[0]


def test_diverso_da_due_mesi_e_indietro(tmp_path):
    """Il caso vero: fissata il 27/09, ancora lì il 21/11."""
    rc, righe = cadenza.verdetto(cadenza.basi(_repo(tmp_path)), lambda n, t: B,
                                 lambda d, f: dt.date(2026, 9, 27), oggi=dt.date(2026, 11, 21))
    assert rc == 1 and "INDIETRO" in righe[0] and "55 giorni" in righe[0]


def test_nessuna_base_trovata_non_e_un_verde(tmp_path, capsys):
    assert cadenza.main(["--radice", str(tmp_path)]) == 2
    assert "non misurabile" in capsys.readouterr().out


def test_registro_che_non_risponde_non_e_un_verde(tmp_path, monkeypatch, capsys):
    def giu(nome, tag):
        raise OSError("rete assente")
    monkeypatch.setattr(cadenza, "digest_corrente", giu)
    assert cadenza.main(["--radice", str(_repo(tmp_path))]) == 2
    assert "rete assente" in capsys.readouterr().out


def test_un_immagine_non_ufficiale_non_si_indovina():
    with pytest.raises(ValueError):
        cadenza.digest_corrente("qualcuno/immagine", "1")


def test_rebuild_mensile_lo_lancia_e_il_non_misurato_e_rosso():
    wf = (_RADICE / ".github" / "workflows" / "rebuild-mensile.yml").read_text(encoding="utf-8")
    assert "python3 tools/base-cadenza.py > basi.txt || RC=$?" in wf
    passo = wf.split("python3 tools/base-cadenza.py > basi.txt")[1].split("- name:")[0]
    assert 'if [ "$RC" = 2 ]' in passo and "exit 1" in passo and "gh issue" in passo
