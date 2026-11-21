"""Un update ucciso a metà viene chiuso dal giro dopo (giro di revisione del 21/11/2026).

`update_in_progress` si scriveva allo step 10 e non si rileggeva mai: lo stack restava giù col tag
già al target, e ogni update successivo diceva «già aggiornato». Qui la CLI è il modulo vero, con
docker, health-gate e rollback sostituiti: si prova la DECISIONE, caso per caso.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("vps1777_ripresa", _ROOT / "tools" / "vps1777.py")
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)


@pytest.fixture
def banco(monkeypatch, tmp_path):
    fatti = {"tag": "0.9.0", "su": False, "sano": (True, ""), "rollback": [], "salvati": [], "avvisi": []}
    monkeypatch.setattr(v, "current_version", lambda repo: fatti["tag"])
    monkeypatch.setattr(v, "stack_running", lambda repo: fatti["su"])
    monkeypatch.setattr(v, "health_gate", lambda repo, env=None: fatti["sano"])
    monkeypatch.setattr(v, "state_save", lambda repo, st: fatti["salvati"].append(dict(st)))
    monkeypatch.setattr(v, "status_write", lambda repo, **k: None)
    monkeypatch.setattr(v, "telegram_notify", lambda repo, t, **k: fatti["avvisi"].append(t))
    monkeypatch.setattr(v, "snapshot_latest", lambda repo: tmp_path / "snap")

    def rollback(repo, st, target, previous, bundle, snap, dati, motivo):
        fatti["rollback"].append({"target": target, "previous": previous, "dati": dati, "motivo": motivo})
        return 1
    monkeypatch.setattr(v, "_rollback_routine", rollback)
    stato = {"current": "0.8.0", "previous": "0.8.0", "history": [],
             "update_in_progress": {"target": "0.9.0", "step": 10, "started_at": "2026-11-21T00:00:00Z"}}
    return fatti, stato, tmp_path


def test_senza_bandierina_non_fa_niente(banco):
    fatti, stato, repo = banco
    stato["update_in_progress"] = None
    assert v._riprendi_update_interrotto(repo, stato) is None
    assert fatti["rollback"] == [] and fatti["salvati"] == []


def test_stack_fermo_col_tag_al_target_torna_indietro_e_ripristina_i_dati(banco):
    # il caso che lasciava tutto giù: ucciso fra `down` e `up`
    fatti, stato, repo = banco
    assert v._riprendi_update_interrotto(repo, stato) == 1
    r = fatti["rollback"][0]
    assert (r["target"], r["previous"], r["dati"]) == ("0.9.0", "0.8.0", True)


def test_stack_su_e_sano_sulla_versione_nuova_si_registra_e_basta(banco):
    # ucciso dopo `up`, durante l'health-gate: l'update era arrivato in fondo
    fatti, stato, repo = banco
    fatti["su"] = True
    assert v._riprendi_update_interrotto(repo, stato) == 0
    assert fatti["rollback"] == []
    assert stato["current"] == "0.9.0" and stato["update_in_progress"] is None
    assert stato["history"][-1]["ripreso"] is True


def test_stack_su_ma_non_sano_torna_indietro_senza_toccare_i_dati(banco):
    fatti, stato, repo = banco
    fatti["su"], fatti["sano"] = True, (False, "gateway unhealthy")
    assert v._riprendi_update_interrotto(repo, stato) == 1
    assert fatti["rollback"][0]["dati"] is False      # è su: il restore butterebbe dati nuovi


def test_ucciso_prima_di_cambiare_il_tag_rimette_i_file_di_prima(banco):
    # morto mentre copiava i file (step 10): tag ancora vecchio, stack su
    fatti, stato, repo = banco
    fatti["tag"], fatti["su"] = "0.8.0", True
    assert v._riprendi_update_interrotto(repo, stato) == 1
    assert fatti["rollback"][0]["dati"] is False


def test_il_comando_di_update_guarda_la_bandierina_prima_di_dire_gia_aggiornato():
    sorgente = (_ROOT / "tools" / "vps1777.py").read_text(encoding="utf-8")
    corpo = sorgente[sorgente.index("def cmd_update("):]
    assert corpo.index("_riprendi_update_interrotto(repo, st)") < corpo.index("già aggiornato")
