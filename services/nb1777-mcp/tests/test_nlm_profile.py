"""
Il profilo NotebookLM è l'unico segreto che nb1777-mcp possiede da solo (H6):
qui si verifica che l'upload non fidato non possa uscire dalla sua cartella e
che un tar malformato NON distrugga il profilo già buono.
"""
from __future__ import annotations

import io
import tarfile

import pytest

from app.nlm_profile import install_profile, profile_status


def _targz(files: dict[str, bytes], *, symlink: tuple[str, str] | None = None) -> bytes:
    """tar.gz in memoria: {nome: contenuto} (+ eventuale symlink)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        if symlink:
            link_name, target = symlink
            info = tarfile.TarInfo(link_name)
            info.type = tarfile.SYMTYPE
            info.linkname = target
            tar.addfile(info)
    return buf.getvalue()


VALID = {"profiles/default/cookies.json": b'{"c":1}',
         "profiles/default/metadata.json": b"{}"}


# ───── stato ─────

def test_status_vuoto(tmp_path):
    assert profile_status(tmp_path) == {"ok": False, "has_cookies": False, "pending": False}


def test_status_ok_con_cookies(tmp_path):
    install_profile(_targz(VALID), tmp_path)
    st = profile_status(tmp_path)
    assert st["ok"] is True and st["has_cookies"] is True and st["pending"] is False


def test_status_pending_flag_invalida_il_profilo(tmp_path):
    install_profile(_targz(VALID), tmp_path)
    (tmp_path / "AUTH_PENDING.flag").touch()
    st = profile_status(tmp_path)
    assert st["has_cookies"] is True
    assert st["pending"] is True
    assert st["ok"] is False          # ok = cookies presenti E non pendente


# ───── installazione ─────

def test_install_scrive_il_profilo_e_toglie_il_flag(tmp_path):
    (tmp_path / "AUTH_PENDING.flag").touch()
    n = install_profile(_targz(VALID), tmp_path)
    assert n == 2
    assert (tmp_path / "profiles/default/cookies.json").read_bytes() == b'{"c":1}'
    assert not (tmp_path / "AUTH_PENDING.flag").exists()   # profilo valido → non più pendente
    assert (tmp_path / "profiles/default/cookies.json").stat().st_mode & 0o777 == 0o600


def test_install_ignora_ciò_che_non_sta_sotto_profiles(tmp_path):
    n = install_profile(_targz({**VALID, "altro/x.txt": b"x"}), tmp_path)
    assert n == 2                                  # solo i 2 di profiles/
    assert not (tmp_path / "altro").exists()


def test_install_ignora_i_symlink(tmp_path):
    # un symlink dentro il tar non deve materializzarsi (no symlink attack)
    blob = _targz(VALID, symlink=("profiles/default/evil", "/etc/passwd"))
    install_profile(blob, tmp_path)
    assert not (tmp_path / "profiles/default/evil").exists()


# ───── il tar non fidato non esce dalla cartella ─────

def test_install_rifiuta_path_traversal(tmp_path):
    with pytest.raises(ValueError, match="non sicuro"):
        install_profile(_targz({"profiles/../../evil.txt": b"x"}), tmp_path)
    assert not (tmp_path.parent / "evil.txt").exists()


def test_install_non_scrive_fuori_con_path_assoluto(tmp_path):
    # tarfile normalizza già il leading "/", quindi il membro non finisce sotto
    # `profiles/` e viene scartato dal filtro: l'upload fallisce e NIENTE viene
    # scritto fuori dalla cartella. (Il guard startswith("/") resta come 2ª rete.)
    with pytest.raises(ValueError):
        install_profile(_targz({"/etc/evil.txt": b"x"}), tmp_path)
    assert not (tmp_path / "etc").exists()
    assert not (tmp_path.parent / "etc").exists()


# ───── un upload sbagliato NON distrugge il profilo buono ─────

def test_tar_senza_cookies_non_tocca_il_profilo_esistente(tmp_path):
    install_profile(_targz(VALID), tmp_path)                    # profilo buono
    with pytest.raises(ValueError, match="cookies.json"):
        install_profile(_targz({"profiles/default/altro.json": b"{}"}), tmp_path)
    # il profilo di prima è ancora lì, intatto
    assert (tmp_path / "profiles/default/cookies.json").read_bytes() == b'{"c":1}'
    assert profile_status(tmp_path)["ok"] is True


def test_tar_corrotto_non_tocca_il_profilo_esistente(tmp_path):
    install_profile(_targz(VALID), tmp_path)
    with pytest.raises(ValueError, match="tar.gz valido"):
        install_profile(b"non sono un tar", tmp_path)
    assert profile_status(tmp_path)["ok"] is True


def test_file_vuoto(tmp_path):
    with pytest.raises(ValueError, match="vuoto"):
        install_profile(b"", tmp_path)


def test_nessuna_staging_residua(tmp_path):
    install_profile(_targz(VALID), tmp_path)
    with pytest.raises(ValueError):
        install_profile(b"rotto", tmp_path)
    assert not (tmp_path / ".upload-staging").exists()
    assert not (tmp_path / ".profiles-prev").exists()
