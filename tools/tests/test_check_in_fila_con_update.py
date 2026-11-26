"""Il `check` giornaliero e l'update si mettono in fila sullo stesso lucchetto.

Misurato il 26/11/2026 alle 01:52Z: il timer del check è scattato mentre un update stava
scambiando i container. Il check ha visto il gateway giù, ha mandato «il servizio non
risponde» su Telegram e ha scritto `irraggiungibile_da` nello stato; l'update, che lo
stato l'aveva letto prima, un minuto dopo l'ha riscritto col suo. Risultato: un allarme
falso senza il suo «risponde di nuovo», `last_check` fermo al giorno prima, e il pannello
che diceva «non raggiungibile» fino al check dopo.

La cura: il check aspetta l'update in corso e tiene il lucchetto mentre gira; chi trova il
lucchetto in mano a un check lo aspetta (dura secondi) invece di uscire con «riprova dopo».
"""
from __future__ import annotations

import importlib.util
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("vps1777_cli_fila", _ROOT / "tools" / "vps1777.py")
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)


def _testo(repo: Path) -> str:
    return (repo / "var" / "update.lock").read_text()


def _rilascia_fra(lock, secondi: float) -> threading.Thread:
    t = threading.Thread(target=lambda: (time.sleep(secondi), lock.close()))
    t.start()
    return t


def test_il_lucchetto_libero_si_prende_e_dice_chi_lo_tiene(tmp_path):
    lock = v.acquire_lock(tmp_path)
    assert lock is not None and _testo(tmp_path).startswith("update ")
    lock.close()
    lock = v.acquire_lock(tmp_path)
    assert _testo(tmp_path).startswith("update ") and _testo(tmp_path).count("\n") == 1
    lock.close()


def test_un_update_non_aspetta_un_altro_update_e_non_ne_cancella_il_nome(tmp_path):
    primo = v.acquire_lock(tmp_path)
    prima = _testo(tmp_path)
    t0 = time.monotonic()
    assert v.acquire_lock(tmp_path) is None
    assert time.monotonic() - t0 < 1.0
    assert _testo(tmp_path) == prima
    primo.close()


def test_un_update_aspetta_il_check_che_sta_finendo(tmp_path):
    del_check = v._lock_del_check(tmp_path)
    assert _testo(tmp_path).startswith("check ")
    t = _rilascia_fra(del_check, 0.3)
    lock = v.acquire_lock(tmp_path)
    t.join()
    assert lock is not None and _testo(tmp_path).startswith("update ")
    lock.close()


def test_un_check_che_non_finisce_non_tiene_fermo_l_update_per_sempre(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "LOCK_ATTESA_CHECK_S", 0.2)
    del_check = v._lock_del_check(tmp_path)
    assert v.acquire_lock(tmp_path) is None
    assert _testo(tmp_path).startswith("check ")
    del_check.close()


def test_il_check_aspetta_l_update_in_corso(tmp_path, monkeypatch, capsys):
    vero = v._flock_entro
    monkeypatch.setattr(v, "_flock_entro", lambda fh, scadenza, passo: vero(fh, scadenza, 0.05))
    update = v.acquire_lock(tmp_path)
    t = _rilascia_fra(update, 0.3)
    lock = v._lock_del_check(tmp_path)
    t.join()
    assert lock is not None and _testo(tmp_path).startswith("check ")
    assert "aspetto: un update è in corso" in capsys.readouterr().out
    lock.close()


def test_un_update_piantato_non_spegne_il_check(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(v, "CHECK_ATTESA_UPDATE_S", 0.2)
    update = v.acquire_lock(tmp_path)
    prima = _testo(tmp_path)
    assert v._lock_del_check(tmp_path) is None
    assert _testo(tmp_path) == prima
    uscita = capsys.readouterr()
    assert "il check gira lo stesso" in uscita.out + uscita.err
    visto = []
    monkeypatch.setattr(v, "cmd_check", lambda repo, args: visto.append("girato") or 0)
    assert v.cmd_check_in_fila(tmp_path, SimpleNamespace(notify=False)) == 0
    assert visto == ["girato"]
    update.close()


def test_il_check_tiene_il_lucchetto_mentre_gira_e_lo_lascia_dopo(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "LOCK_ATTESA_CHECK_S", 0.1)
    durante = []

    def finto(repo, args):
        durante.append(v.acquire_lock(repo))
        return 7

    monkeypatch.setattr(v, "cmd_check", finto)
    assert v.cmd_check_in_fila(tmp_path, SimpleNamespace(notify=False)) == 7
    assert durante == [None]
    dopo = v.acquire_lock(tmp_path)
    assert dopo is not None
    dopo.close()


def test_il_check_lascia_il_lucchetto_anche_se_cade(tmp_path, monkeypatch):
    def cade(repo, args):
        raise RuntimeError("guasto")

    monkeypatch.setattr(v, "cmd_check", cade)
    with pytest.raises(RuntimeError):
        v.cmd_check_in_fila(tmp_path, SimpleNamespace(notify=False))
    dopo = v.acquire_lock(tmp_path)
    assert dopo is not None
    dopo.close()


def test_la_cli_lancia_il_check_in_fila():
    """Il cablaggio: `vps1777 check` passa dal lucchetto, non dal corpo nudo."""
    import inspect
    assert '"check": cmd_check_in_fila' in inspect.getsource(v.main)
