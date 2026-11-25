"""`Deployer._stream`: che cosa esce da un canale SSH, riga per riga (25/11/2026).

Misurato prima di spezzarla (QUA-04): le prove coprivano il comando che non finisce e l'errore del
canale. Restavano senza prova la cosa che fa sempre (ricomporre le righe dai pezzi che arrivano), la
coda letta a comando finito, lo script dato per stdin (la via dei segreti: mai in argv) e l'uscita
diversa da zero. Il canale è finto e segue un copione: bytes, oppure `None` per «niente di pronto».
"""
from __future__ import annotations

import importlib.util
import socket
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.modules.setdefault("paramiko", types.ModuleType("paramiko"))
_spec = importlib.util.spec_from_file_location("installer_engine_stream", ROOT / "installer" / "engine.py")
eng = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eng)


class _Canale:
    def __init__(self, copione: list, coda: list | None = None, rc: int = 0):
        self.copione, self.coda, self.rc = list(copione), list(coda or []), rc
        self.fatti: list = []

    def set_combine_stderr(self, v): self.fatti.append(("stderr_insieme", v))
    def exec_command(self, cmd): self.fatti.append(("exec", cmd))
    def sendall(self, dati): self.fatti.append(("sendall", dati))
    def shutdown_write(self): self.fatti.append(("chiudi_scrittura",))
    def settimeout(self, t): self.fatti.append(("timeout", t))
    def close(self): self.fatti.append(("close",))
    def exit_status_ready(self): return not self.copione
    def recv_exit_status(self): return self.rc

    def recv(self, _n):
        da = self.copione if self.copione else self.coda
        pezzo = da.pop(0) if da else None
        if pezzo is None:
            raise socket.timeout()
        return pezzo


def _gira(canale: _Canale, monkeypatch, *args, **kw) -> list[str]:
    monkeypatch.setattr(eng.time, "sleep", lambda _s: None)
    d = eng.Deployer("192.0.2.10", "root", "")
    d.client = types.SimpleNamespace(get_transport=lambda: types.SimpleNamespace(open_session=lambda: canale))
    return list(d._stream(*args, **kw))


def test_le_righe_si_ricompongono_dai_pezzi(monkeypatch):
    canale = _Canale([b"prima\nsec", None, b"onda\r\nter", b"za\n"])
    assert _gira(canale, monkeypatch, "comando") == ["prima", "seconda", "terza"]


def test_l_ultima_riga_senza_a_capo_esce_lo_stesso(monkeypatch):
    assert _gira(_Canale([b"uno\ndue"]), monkeypatch, "comando") == ["uno", "due"]


def test_cio_che_arriva_dopo_la_fine_del_comando_non_si_perde(monkeypatch):
    # un giro a vuoto (None) a comando finito: è lì che si legge la coda, fino al pezzo vuoto
    canale = _Canale([b"uno\nmez"], coda=[None, b"za\nulti", b"ma\r\n", b"", b"oltre la fine\n"])
    assert _gira(canale, monkeypatch, "comando") == ["uno", "mezza", "ultima"]


def test_la_coda_che_finisce_per_attesa_e_non_per_pezzo_vuoto_esce_lo_stesso(monkeypatch):
    canale = _Canale([b"uno\n"], coda=[None, b"resto senza a capo"])
    assert _gira(canale, monkeypatch, "comando") == ["uno", "resto senza a capo"]


def test_i_byte_che_non_sono_utf8_non_fermano_la_lettura(monkeypatch):
    assert _gira(_Canale([b"\xff ok\n"]), monkeypatch, "comando") == ["� ok"]


def test_un_comando_muto_che_riesce_non_rende_niente(monkeypatch):
    assert _gira(_Canale([]), monkeypatch, "true") == []


def test_lo_script_va_per_stdin_prima_del_non_bloccante_e_la_scrittura_si_chiude(monkeypatch):
    canale = _Canale([b"fatto\n"])
    assert _gira(canale, monkeypatch, "bash -s", "config", "export PAROLA='é'\n") == ["fatto"]
    assert canale.fatti == [("stderr_insieme", True), ("exec", "bash -s"),
                            ("sendall", "export PAROLA='é'\n".encode()), ("chiudi_scrittura",), ("timeout", 0.0)]
    # il segreto non è mai nel comando: argv è leggibile da tutta la macchina
    assert "PAROLA" not in canale.fatti[1][1]


def test_senza_script_non_si_scrive_niente_sul_canale(monkeypatch):
    canale = _Canale([b"x\n"])
    _gira(canale, monkeypatch, "true")
    assert canale.fatti == [("stderr_insieme", True), ("exec", "true"), ("timeout", 0.0)]


@pytest.mark.parametrize("etichetta, atteso", [("build", "build fallito (exit 3)"), ("", "comando fallito (exit 3)")])
def test_un_uscita_diversa_da_zero_e_un_errore_dopo_aver_reso_le_righe(monkeypatch, etichetta, atteso):
    canale = _Canale([b"errore: disco pieno\n"], rc=3)
    d = eng.Deployer("192.0.2.10", "root", "")
    d.client = types.SimpleNamespace(get_transport=lambda: types.SimpleNamespace(open_session=lambda: canale))
    monkeypatch.setattr(eng.time, "sleep", lambda _s: None)
    viste = []
    with pytest.raises(eng.DeployError, match=atteso.replace("(", r"\(").replace(")", r"\)")):
        for riga in d._stream("make", etichetta):
            viste.append(riga)
    assert viste == ["errore: disco pieno"]


def test_il_tetto_nomina_il_comando_se_manca_l_etichetta(monkeypatch):
    monkeypatch.setattr(eng, "CMD_TIMEOUT_S", 0)
    canale = _Canale([None] * 5 + [b"mai letta\n"])
    canale.exit_status_ready = lambda: False
    with pytest.raises(eng.DeployError, match="«" + "x" * 40 + "»"):
        _gira(canale, monkeypatch, "x" * 60)
    assert ("close",) in canale.fatti


def test_un_pezzo_vuoto_a_comando_in_corso_non_e_la_fine(monkeypatch):
    assert _gira(_Canale([b"uno\n", b"", b"due\n"]), monkeypatch, "comando") == ["uno", "due"]
