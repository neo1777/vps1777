"""`fetch_bundle`: che cosa accetta e che cosa rifiuta chi scarica il pacchetto di una release (25/11/2026).

Prima di spezzarla (QUA-04) nessuna prova la chiamava: la percorrevano solo gli update veri. È la
funzione che decide se un pacchetto è autentico e intero, quindi ogni rifiuto ha la sua prova:
allegato mancante, impronta che non torna, firma richiesta e assente o non valida, tarball che
esce dalla radice. I collaboratori (scaricamento, cosign) sono finti e scrivono in `ev`.
"""
from __future__ import annotations

import gzip
import hashlib
import importlib.util
import io
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("vps1777_cli_fetch_bundle", _ROOT / "tools" / "vps1777.py")
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)

VER = "9.9.9"
NOME = f"vps1777-runtime-v{VER}.tar.gz"


def _tarball(*extra: tarfile.TarInfo) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz, tarfile.open(fileobj=gz, mode="w") as t:
        i = tarfile.TarInfo("VERSION")
        i.size = 6
        t.addfile(i, io.BytesIO(b"9.9.9\n"))
        for e in extra:
            t.addfile(e, io.BytesIO(b"x" * e.size))
    return buf.getvalue()


@pytest.fixture
def banco(tmp_path, monkeypatch):
    b = SimpleNamespace(repo=tmp_path, ev=[], cosign="/usr/bin/cosign", installabile=None, rc=0)
    b.dati = _tarball()
    b.remoto = {NOME: b.dati, "SHA256SUMS": f"{hashlib.sha256(b.dati).hexdigest()}  {NOME}\n".encode(),
                "SHA256SUMS.sig": b"sig", "SHA256SUMS.pem": b"pem"}
    monkeypatch.setattr(v, "staging_dir", lambda _repo, _ver: tmp_path / "stage")
    monkeypatch.setattr(v, "download", lambda url, dest: Path(dest).write_bytes(b.remoto[url]))
    monkeypatch.setattr(v.shutil, "which", lambda _n: b.cosign)
    monkeypatch.setattr(v, "_ensure_cosign", lambda _repo: b.installabile)
    monkeypatch.setattr(v, "run", lambda cmd, **_k: (b.ev.append(("cosign", cmd[1])),
                                                     SimpleNamespace(returncode=b.rc, stderr="firma storta"))[1])
    monkeypatch.setattr(v, "reclaim_ownership", lambda *_a: b.ev.append("reclaim"))
    for nome in ("log", "ok", "warn"):
        monkeypatch.setattr(v, nome, lambda t, _n=nome: b.ev.append((_n, str(t))))
    b.gira = lambda richiesta=True: v.fetch_bundle(
        tmp_path, {"tag_name": "v" + VER, "assets": [{"name": k, "browser_download_url": k} for k in b.remoto]},
        richiesta)
    return b


def test_un_pacchetto_integro_e_firmato_si_estrae(banco):
    (banco.repo / "stage" / "bundle").mkdir(parents=True)
    (banco.repo / "stage" / "bundle" / "avanzo").write_text("di un tentativo prima", encoding="utf-8")
    bundle = banco.gira()
    assert bundle == banco.repo / "stage" / "bundle" and (bundle / "VERSION").read_text() == "9.9.9\n"
    assert not (bundle / "avanzo").exists(), "la cartella si rifà da capo"
    assert ("ok", "sha256 del bundle verificato") in banco.ev and ("ok", "firma cosign verificata") in banco.ev
    assert ("cosign", "verify-blob") in banco.ev and banco.ev[-1] == "reclaim"


@pytest.mark.parametrize("manca", [NOME, "SHA256SUMS"])
def test_senza_un_allegato_obbligatorio_non_si_scarica_niente(banco, manca):
    del banco.remoto[manca]
    with pytest.raises(RuntimeError, match=f"asset '{manca}' assente"):
        banco.gira()


@pytest.mark.parametrize("sums", ["0" * 64 + "  " + NOME + "\n", "", "abc  altro.tar.gz\n"])
def test_l_impronta_che_non_torna_ferma_prima_della_firma(banco, sums):
    banco.remoto["SHA256SUMS"] = sums.encode()
    with pytest.raises(RuntimeError, match="sha256 mismatch"):
        banco.gira()
    assert not [e for e in banco.ev if e[0] == "cosign"] and not (banco.repo / "stage" / "bundle").exists()


def test_firma_richiesta_e_cosign_assente_e_non_installabile(banco):
    banco.cosign = None
    with pytest.raises(RuntimeError, match="cosign è assente e non installabile"):
        banco.gira()
    banco.installabile = "/opt/cosign"                         # installato al volo: la verifica si fa
    assert banco.gira().is_dir() and ("ok", "firma cosign verificata") in banco.ev


def test_firma_richiesta_e_la_release_non_l_ha(banco):
    del banco.remoto["SHA256SUMS.sig"]
    with pytest.raises(RuntimeError, match="la release non ha firma"):
        banco.gira()


def test_una_firma_che_non_verifica_ferma_l_estrazione(banco):
    banco.rc = 1
    with pytest.raises(RuntimeError, match="cosign verify-blob fallita"):
        banco.gira()
    assert not (banco.repo / "stage" / "bundle").exists()


def test_senza_firma_e_senza_obbligo_si_estrae_ma_lo_si_dice(banco):
    del banco.remoto["SHA256SUMS.pem"]
    assert banco.gira(richiesta=False).is_dir()
    assert any(n == "warn" and "NON verificata" in t for n, t in [e for e in banco.ev if isinstance(e, tuple)])


def test_un_tarball_che_esce_dalla_radice_e_rifiutato(banco):
    fuori = tarfile.TarInfo("../fuori.txt")
    fuori.size = 1
    banco.dati = _tarball(fuori)
    banco.remoto[NOME] = banco.dati
    banco.remoto["SHA256SUMS"] = f"{hashlib.sha256(banco.dati).hexdigest()}  {NOME}\n".encode()
    with pytest.raises(RuntimeError, match="path traversal"):
        banco.gira()
    assert not (banco.repo / "stage" / "fuori.txt").exists()
