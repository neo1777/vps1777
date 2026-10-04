"""Due silenzi del timer giornaliero (W5, 04/10/2026).

① Il backup notturno che si ferma. H59 avvisa quando la copertura SCENDE, ma la potatura
la fa backup.sh stesso: se il backup non gira più, non pota più, i file restano e la
copertura resta al massimo. Un backup morto aveva l'aspetto di uno sano. Ora si guarda
anche l'età dell'ultima copia, come per il livello archivio.

② Il disco. C'era una guardia sugli upload, ma niente che guardasse lo spazio ogni giorno:
il disco si riempie anche di backup, log e immagini, e a disco pieno il primo a fallire è
proprio il backup.
"""
from __future__ import annotations

import importlib.util
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("vps1777_cli_w5", _ROOT / "tools" / "vps1777.py")
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)


def _backup(repo: Path, giorni_fa: int) -> None:
    d = repo / "backups"
    d.mkdir(exist_ok=True)
    giorno = (datetime.now(timezone.utc) - timedelta(days=giorni_fa)).strftime("%Y-%m-%d")
    (d / f"vps1777-{giorno}-030000.tar.age").write_bytes(b"x")


def test_il_notturno_fermo_si_arma_oltre_due_giorni_e_si_disarma(tmp_path):
    st: dict = {}
    v._sorveglia_backup_notturno(tmp_path, st, notifica=False)          # nessun backup ancora
    assert "notturno_fermo_da" not in st
    for n in range(3, 10):                                              # sette giorni, l'ultimo 3 giorni fa
        _backup(tmp_path, n)
    assert v.copertura_backup(tmp_path)[0] == 7, "la copertura è piena: H59 da solo tacerebbe"
    v._sorveglia_backup_notturno(tmp_path, st, notifica=False)
    assert st.get("notturno_fermo_da"), "tre giorni senza backup: deve armarsi"
    _backup(tmp_path, 0)
    v._sorveglia_backup_notturno(tmp_path, st, notifica=False)
    assert "notturno_fermo_da" not in st, "è tornato: si disarma"


def test_due_giorni_non_sono_ancora_un_guasto(tmp_path):
    st: dict = {}
    _backup(tmp_path, 2)
    v._sorveglia_backup_notturno(tmp_path, st, notifica=False)
    assert "notturno_fermo_da" not in st


def test_la_notifica_parte_una_volta_sola(tmp_path, monkeypatch):
    mandati: list[str] = []
    monkeypatch.setattr(v, "telegram_notify", lambda _repo, testo: mandati.append(testo))
    st: dict = {}
    _backup(tmp_path, 5)
    v._sorveglia_backup_notturno(tmp_path, st, notifica=True)
    v._sorveglia_backup_notturno(tmp_path, st, notifica=True)
    assert len(mandati) == 1 and "5 giorni" in mandati[0]


_Uso = namedtuple("_Uso", "total used free")


def test_il_disco_quasi_pieno_si_arma_e_si_disarma(tmp_path, monkeypatch):
    mandati: list[str] = []
    monkeypatch.setattr(v, "telegram_notify", lambda _repo, testo: mandati.append(testo))
    libero = {"f": 50}
    monkeypatch.setattr(v.shutil, "disk_usage", lambda _p: _Uso(100 * 1024**3, 0, libero["f"] * 1024**3))
    st: dict = {}
    v._sorveglia_disco(tmp_path, st, notifica=True)
    assert "disco_pieno_da" not in st and mandati == []
    libero["f"] = 8
    v._sorveglia_disco(tmp_path, st, notifica=True)
    v._sorveglia_disco(tmp_path, st, notifica=True)
    assert st.get("disco_pieno_da") and len(mandati) == 1 and "8%" in mandati[0]
    libero["f"] = 30
    v._sorveglia_disco(tmp_path, st, notifica=True)
    assert "disco_pieno_da" not in st and len(mandati) == 2 and mandati[1].startswith("🟢")


def test_un_disco_non_leggibile_non_e_un_disco_pieno(tmp_path, monkeypatch):
    def _rotto(_p):
        raise PermissionError("negato")
    monkeypatch.setattr(v.shutil, "disk_usage", _rotto)
    st: dict = {}
    v._sorveglia_disco(tmp_path, st, notifica=False)
    assert "disco_pieno_da" not in st


def test_il_check_giornaliero_chiama_le_due_sorveglianze():
    testo = (_ROOT / "tools" / "vps1777.py").read_text(encoding="utf-8")
    corpo = testo.split("def cmd_check(", 1)[1].split("\ndef ", 1)[0]
    assert "_sorveglia_backup_notturno(repo, st," in corpo
    assert "_sorveglia_disco(repo, st," in corpo
