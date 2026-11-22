"""Due scelte del proprietario del 22/11/2026, tenute da test.

1. I backup che restano solo sulla macchina non proteggono dalla sua perdita: portarli fuori è
   un gesto a mano, e sulla macchina di riferimento l'ultima copia fuori aveva tre mesi. Il
   pull lascia la data sulla macchina e il controllo giornaliero avvisa quando invecchia.
2. Gli installatori accettavano qualunque chiave SSH a ogni corsa. Ora la prima si accetta e
   si ricorda; una chiave cambiata ferma l'installazione finché chi installa non conferma.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _carica(nome: str, file: Path):
    spec = importlib.util.spec_from_file_location(nome, file)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nome] = mod
    spec.loader.exec_module(mod)
    return mod


v = _carica("vps1777_copia_fuori", ROOT / "tools" / "vps1777.py")
sys.modules.setdefault("paramiko", types.ModuleType("paramiko"))
eng = _carica("installer_engine_chiave", ROOT / "installer" / "engine.py")


def _repo(tmp_path: Path, giorni_marca: int | None, con_backup: bool = True) -> Path:
    b = tmp_path / "backups"
    b.mkdir()
    if con_backup:
        oggi = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        (b / f"vps1777-{oggi}-030000.tar.age").write_bytes(b"x")
    if giorni_marca is not None:
        quando = datetime.now(timezone.utc) - timedelta(days=giorni_marca, minutes=5)
        (b / v.FUORI_MARCA).write_text(quando.strftime("%Y-%m-%dT%H:%M:%SZ") + "\n", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def mandati(monkeypatch):
    lista: list[str] = []
    monkeypatch.setattr(v, "telegram_notify", lambda repo, testo, **k: lista.append(testo) or True)
    return lista


def test_una_copia_fresca_non_fa_rumore(tmp_path, mandati) -> None:
    st: dict = {}
    v._sorveglia_copia_fuori(_repo(tmp_path, 1), st, notifica=True)
    assert st == {} and mandati == []


def test_una_copia_vecchia_avvisa_una_volta_sola_e_poi_dice_quando_torna(tmp_path, mandati) -> None:
    repo = _repo(tmp_path, v.FUORI_MAX_GIORNI + 2)
    st: dict = {}
    v._sorveglia_copia_fuori(repo, st, notifica=True)
    v._sorveglia_copia_fuori(repo, st, notifica=True)
    assert st.get("fuori_vecchia_da") and len(mandati) == 1, mandati
    (repo / "backups" / v.FUORI_MARCA).write_text(
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), encoding="utf-8")
    v._sorveglia_copia_fuori(repo, st, notifica=True)
    assert "fuori_vecchia_da" not in st and len(mandati) == 2


def test_backup_mai_usciti_lo_dice_una_volta(tmp_path, mandati) -> None:
    repo = _repo(tmp_path, None)
    st: dict = {}
    v._sorveglia_copia_fuori(repo, st, notifica=True)
    v._sorveglia_copia_fuori(repo, st, notifica=True)
    assert st.get("fuori_mai_da") and len(mandati) == 1
    assert "solo sulla macchina" in mandati[0]


def test_senza_backup_non_c_e_niente_da_dire(tmp_path, mandati) -> None:
    st: dict = {}
    v._sorveglia_copia_fuori(_repo(tmp_path, None, con_backup=False), st, notifica=True)
    assert st == {} and mandati == []


def test_una_marca_illeggibile_vale_come_nessuna(tmp_path) -> None:
    repo = _repo(tmp_path, None)
    (repo / "backups" / v.FUORI_MARCA).write_text("ieri, credo\n", encoding="utf-8")
    assert v.eta_copia_fuori(repo) is None


def test_il_pull_registra_la_data_sulla_macchina() -> None:
    testo = (ROOT / "tools" / "backup-pull.sh").read_text("utf-8")
    assert f"backups/{v.FUORI_MARCA}" in testo
    assert "date -u +%Y-%m-%dT%H:%M:%SZ" in testo, "il formato deve essere quello che il controllo sa leggere"


def test_il_controllo_giornaliero_chiama_la_sorveglianza() -> None:
    testo = (ROOT / "tools" / "vps1777.py").read_text("utf-8")
    assert testo.count("_sorveglia_copia_fuori(repo, st,") == 1


# ── la chiave della macchina ───────────────────────────────────────────────────

def test_deploy_non_dimentica_piu_la_chiave_a_ogni_corsa() -> None:
    testo = (ROOT / "deploy.sh").read_text("utf-8")
    i = testo.index('ssh-keygen -f "$HOME/.ssh/known_hosts" -R "$VPS_IP"')
    prima = testo[max(0, i - 700):i]
    assert "REMOTE HOST IDENTIFICATION HAS CHANGED" in prima, "la voce si toglie solo dopo aver visto la chiave cambiata"
    assert "VPS1777_NUOVA_CHIAVE_HOST" in prima and "confirm " in prima, "e solo con una conferma"
    assert testo.count('-R "$VPS_IP"') == 1


def test_l_installer_tiene_un_elenco_di_chiavi_e_sa_dimenticarne_una(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    noti = eng.chiavi_note_path()
    assert noti.exists() and oct(noti.stat().st_mode & 0o777) == "0o600"
    noti.write_text("192.0.2.10 ssh-ed25519 AAAAfinta1\n192.0.2.11,altro ssh-ed25519 AAAAfinta2\n"
                    "192.0.2.100 ssh-ed25519 AAAAfinta3\n", encoding="utf-8")
    eng.dimentica_chiave_nota(noti, "192.0.2.10")
    rimaste = noti.read_text("utf-8")
    assert "AAAAfinta1" not in rimaste
    assert "AAAAfinta2" in rimaste and "AAAAfinta3" in rimaste, "192.0.2.100 non è 192.0.2.10"


class _ChiaveCambiata(Exception):
    pass


def _paramiko_finto(monkeypatch, esiti: list):
    """Un paramiko il cui connect() dà, in ordine, gli esiti della lista (eccezione o None)."""
    class Client:
        def load_host_keys(self, _f): pass
        def set_missing_host_key_policy(self, _p): pass
        def close(self): pass
        def connect(self, **_k):
            e = esiti.pop(0)
            if e is not None:
                raise e
    finto = types.SimpleNamespace(SSHClient=Client, AutoAddPolicy=lambda: None,
                                  BadHostKeyException=_ChiaveCambiata)
    monkeypatch.setattr(eng, "paramiko", finto)


def test_una_chiave_cambiata_ferma_l_installazione(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _paramiko_finto(monkeypatch, [_ChiaveCambiata()])
    d = eng.Deployer("192.0.2.10", "root", "x")
    with pytest.raises(eng.DeployError, match="DIVERSA"):
        d.connect()
    assert d.client is None


def test_con_la_conferma_la_chiave_vecchia_si_dimentica_e_si_riprova(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    noti = eng.chiavi_note_path()
    noti.write_text("192.0.2.10 ssh-ed25519 AAAAvecchia\n", encoding="utf-8")
    _paramiko_finto(monkeypatch, [_ChiaveCambiata(), None])
    d = eng.Deployer("192.0.2.10", "root", "x", nuova_chiave_host=True)
    d.connect()
    assert d.client is not None
    assert "AAAAvecchia" not in noti.read_text("utf-8")
