"""Il `check` giornaliero e l'update si mettono in fila sullo stesso lucchetto.

Misurato il 26/11/2026 alle 01:52Z: il timer del check è scattato mentre un update stava
scambiando i container. Il check ha visto il gateway giù, ha mandato «il servizio non
risponde» su Telegram e ha scritto `irraggiungibile_da` nello stato; l'update, che lo
stato l'aveva letto prima, un minuto dopo l'ha riscritto col suo. Risultato: un allarme
falso senza il suo «risponde di nuovo», `last_check` fermo al giorno prima, e il pannello
che diceva «non raggiungibile» fino al check dopo.

La cura: il check aspetta l'update in corso e tiene il lucchetto mentre gira; chi trova il
lucchetto in mano a un check lo aspetta invece di uscire con «riprova dopo». Che sia un check
lo dice un secondo flock (`var/check.lock`), non il testo del file; e se il check non finisce
entro l'attesa, l'intent del pulsante NON si cancella (rilettura di Sagoma del 26/11: un
check lento, il giorno in cui la rete va male, avrebbe fatto perdere il click in silenzio).
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


def _fra(secondi: float, gesto) -> threading.Thread:
    t = threading.Thread(target=lambda: (time.sleep(secondi), gesto()))
    t.start()
    return t


def _tieni(repo: Path, nome: str):
    """Un flock tenuto a mano su un file di var/, come lo terrebbe un altro processo."""
    (repo / "var").mkdir(exist_ok=True)
    fh = open(repo / "var" / nome, "a+")
    v.fcntl.flock(fh, v.fcntl.LOCK_EX | v.fcntl.LOCK_NB)
    return fh


@pytest.fixture(autouse=True)
def _tetti_corti(monkeypatch):
    monkeypatch.setattr(v, "LOCK_SGUARDI_S", 0.3)
    monkeypatch.setattr(v, "LOCK_ATTESA_CHECK_S", 3.0)


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
    assert time.monotonic() - t0 < 1.5
    assert _testo(tmp_path) == prima
    primo.close()


def test_un_update_aspetta_il_check_che_sta_finendo(tmp_path):
    del_check = v._lock_del_check(tmp_path)
    assert _testo(tmp_path).startswith("check ")
    t = _fra(0.6, del_check.close)                 # oltre LOCK_SGUARDI_S: ha aspettato davvero
    lock = v.acquire_lock(tmp_path)
    t.join()
    assert lock is not None and _testo(tmp_path).startswith("update ")
    lock.close()


def test_un_check_che_non_finisce_non_e_un_update_in_corso(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "LOCK_ATTESA_CHECK_S", 0.5)
    del_check = v._lock_del_check(tmp_path)
    with pytest.raises(v.CheckInCorso):
        v.acquire_lock(tmp_path)
    assert _testo(tmp_path).startswith("check ")
    del_check.close()


def test_chi_tiene_il_lucchetto_lo_dice_il_secondo_flock_non_il_nome_scritto(tmp_path):
    """La finestra vista da Sagoma: il check ha già la fila ma nel file c'è ancora «update»
    di prima, e `check.lock` arriva un istante dopo. Chi guarda non deve credere al nome."""
    v.acquire_lock(tmp_path).close()               # lascia scritto «update …»
    fila = _tieni(tmp_path, "update.lock")
    assert _testo(tmp_path).startswith("update ")
    presi = []
    t1 = _fra(0.1, lambda: presi.append(_tieni(tmp_path, "check.lock")))
    t2 = _fra(0.8, lambda: (fila.close(), presi[0].close()))
    lock = v.acquire_lock(tmp_path)
    t1.join()
    t2.join()
    assert lock is not None                        # ha aspettato il check, non è uscito a 0.3 s
    lock.close()


def test_se_dopo_il_check_arriva_prima_un_altro_update_si_esce_subito(tmp_path):
    fila = _tieni(tmp_path, "update.lock")         # resta tenuta: ora è «un update»
    chi = _tieni(tmp_path, "check.lock")
    t = _fra(0.5, chi.close)
    t0 = time.monotonic()
    assert v.acquire_lock(tmp_path) is None
    assert 0.4 < time.monotonic() - t0 < 1.5
    t.join()
    fila.close()


def test_il_click_del_pulsante_non_si_perde_se_il_check_e_lento(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(v, "LOCK_ATTESA_CHECK_S", 0.5)
    intent = tmp_path / "update_pending_update.json"
    intent.write_text("{}")
    del_check = v._lock_del_check(tmp_path)
    with pytest.raises(SystemExit) as e:
        v._update_lock(tmp_path, SimpleNamespace(from_intent=str(intent)))
    assert e.value.code == v.ESITO_LOCK_OCCUPATO
    assert intent.exists(), "l'intent va tenuto: la path unit rilancia l'update da sola"
    errore = capsys.readouterr().err
    assert "controllo giornaliero" in errore and "update già in corso" not in errore
    del_check.close()


def test_contro_un_update_vero_l_intent_si_consuma_come_prima(tmp_path, capsys):
    intent = tmp_path / "update_pending_update.json"
    intent.write_text("{}")
    primo = v.acquire_lock(tmp_path)
    with pytest.raises(SystemExit) as e:
        v._update_lock(tmp_path, SimpleNamespace(from_intent=str(intent)))
    assert e.value.code == v.ESITO_LOCK_OCCUPATO and not intent.exists()
    assert "update già in corso" in capsys.readouterr().err
    primo.close()


def test_rollback_e_bootstrap_dicono_il_motivo_vero(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(v, "LOCK_ATTESA_CHECK_S", 0.5)
    del_check = v._lock_del_check(tmp_path)
    with pytest.raises(SystemExit) as e:
        v._lock_o_riprova_dopo(tmp_path, "update/rollback già in corso (lock attivo)")
    assert e.value.code == v.ESITO_LOCK_OCCUPATO
    assert "controllo giornaliero" in capsys.readouterr().err
    del_check.close()
    primo = v.acquire_lock(tmp_path)
    with pytest.raises(SystemExit) as e:
        v._lock_o_riprova_dopo(tmp_path, "update/rollback già in corso (lock attivo)")
    assert e.value.code == v.ESITO_LOCK_OCCUPATO
    assert "update/rollback già in corso" in capsys.readouterr().err
    primo.close()
    libero = v._lock_o_riprova_dopo(tmp_path, "non serve")
    assert libero is not None
    libero.close()


def test_il_check_aspetta_l_update_in_corso(tmp_path, monkeypatch, capsys):
    vero = v._flock_entro
    monkeypatch.setattr(v, "_flock_entro", lambda fh, scadenza, passo: vero(fh, scadenza, 0.05))
    update = v.acquire_lock(tmp_path)
    t = _fra(0.3, update.close)
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
    monkeypatch.setattr(v, "LOCK_ATTESA_CHECK_S", 0.3)
    durante = []

    def finto(repo, args):
        try:
            durante.append(v.acquire_lock(repo))
        except v.CheckInCorso:
            durante.append("check in corso")
        return 7

    monkeypatch.setattr(v, "cmd_check", finto)
    assert v.cmd_check_in_fila(tmp_path, SimpleNamespace(notify=False)) == 7
    assert durante == ["check in corso"]
    dopo = v.acquire_lock(tmp_path)
    assert dopo is not None
    dopo.close()
    assert not v._un_check_tiene_il_lucchetto(tmp_path / "var")


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
