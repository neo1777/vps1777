"""cosign, il verificatore, si verifica prima di installarlo (H80, 04/10/2026).

Fino alla 0.69.1 `vps1777 update`, quando sulla macchina mancava cosign, scaricava
`cosign-linux-amd64` e lo installava in /usr/local/bin come root senza controllarne
l'impronta, e scaricava il binario amd64 anche su una macchina arm64. Il programma che
verifica la firma di ogni aggiornamento era l'unico pezzo della catena preso sulla
parola. Ora l'impronta SHA-256 di ogni architettura sta nel codice, e un binario che
non coincide non arriva a sudo.

E in CI le immagini si firmano per digest, non per tag: un tag si può spostare fra il
push e la firma, un digest no.
"""
from __future__ import annotations

import hashlib
import importlib.util
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("vps1777_cli_cosign", _ROOT / "tools" / "vps1777.py")
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)

_FINTO = b"\x7fELF un cosign finto"


@pytest.fixture
def banco(monkeypatch, tmp_path):
    """Nessun cosign sul PATH, download che scrive _FINTO, sudo registrato e non eseguito."""
    chiamate: list[list[str]] = []
    scaricati: list[str] = []
    monkeypatch.setattr(v.shutil, "which", lambda _nome: None)
    monkeypatch.setattr(v.platform, "machine", lambda: "x86_64")

    def _download(url, dest, timeout=120):
        scaricati.append(url)
        Path(dest).write_bytes(_FINTO)

    monkeypatch.setattr(v, "download", _download)
    monkeypatch.setattr(v, "sudo", lambda cmd, **kw: chiamate.append(cmd))
    return tmp_path, chiamate, scaricati


def test_un_binario_con_l_impronta_sbagliata_non_arriva_a_sudo(banco):
    repo, chiamate, _ = banco
    assert v._ensure_cosign(repo) is None
    assert chiamate == [], "sudo install chiamato su un binario non verificato"
    assert not (repo / ".cosign-dl").exists(), "il binario rifiutato resta sul disco"


def test_un_binario_con_l_impronta_giusta_si_installa(banco, monkeypatch):
    repo, chiamate, scaricati = banco
    monkeypatch.setitem(v._COSIGN_SHA256, "amd64", hashlib.sha256(_FINTO).hexdigest())
    v._ensure_cosign(repo)
    assert scaricati and scaricati[0].endswith(f"/{v._COSIGN_VERSION}/cosign-linux-amd64")
    assert chiamate and chiamate[0][:3] == ["install", "-m", "755"]


def test_su_arm64_scarica_il_binario_arm64(banco, monkeypatch):
    repo, _, scaricati = banco
    monkeypatch.setattr(v.platform, "machine", lambda: "aarch64")
    v._ensure_cosign(repo)
    assert scaricati and scaricati[0].endswith("/cosign-linux-arm64")


def test_un_architettura_senza_impronta_non_scarica_niente(banco, monkeypatch):
    repo, chiamate, scaricati = banco
    monkeypatch.setattr(v.platform, "machine", lambda: "riscv64")
    assert v._ensure_cosign(repo) is None
    assert scaricati == [] and chiamate == []


def test_ogni_impronta_e_uno_sha256():
    assert set(v._COSIGN_SHA256) == {"amd64", "arm64"}
    for arch, h in v._COSIGN_SHA256.items():
        assert re.fullmatch(r"[0-9a-f]{64}", h), arch


def test_le_immagini_si_firmano_per_digest():
    wf = (_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    firme = re.findall(r"cosign sign --yes \\\s*\n\s*(.+)", wf)
    assert firme, "nessun `cosign sign` trovato: il parser del test è rotto, non il workflow"
    for img in firme:
        assert "@${{ steps.build.outputs.digest }}" in img, f"immagine firmata per tag: {img}"
    assert "id: build" in wf
