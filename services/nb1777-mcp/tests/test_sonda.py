"""nb1777 si accorge da solo che la sessione Google è morta (S7-S8, 05/10/2026).

🔴 I DUE FATTI. Il 02/10 la sessione è morta e ce ne siamo accorti 12,7 ore dopo l'ultimo
successo, a metà di un lavoro. Il 21/07 l'errore diceva di lanciare `nlm login` «nel
terminale», e a Neo è stato suggerito di farlo sul PC, dove sarebbe riuscito senza
sbloccare niente: il login vive sul PC, ma il profilo che conta è quello caricato sulla VPS.

Le cure: ① un errore di autenticazione si riconosce (quattro forme, la rete esclusa) e dice
cosa fare, cioè ricaricare il profilo da /admin/nlm; ② una sonda rada, ogni qualche ora,
prova una chiamata vera, registra solo l'esito e avvisa su Telegram al primo
«auth_scaduta», una volta, e di nuovo quando torna.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from app import core, memoria, sonda


@pytest.fixture(autouse=True)
def _isola(tmp_path, monkeypatch):
    monkeypatch.setattr(sonda, "_dir_stato", lambda: tmp_path)
    memoria._outbox.clear()
    yield
    memoria._outbox.clear()


@pytest.mark.parametrize("testo", [
    "Error: Authentication expired. Run `nlm login` in your terminal to re-authenticate.",
    "RPC Error 16: request had invalid authentication credentials",
    "Credentials have expired, please log in again",
    "Your authentication is no longer valid",
])
def test_le_quattro_forme_dell_auth_scaduta(testo: str) -> None:
    assert core.classifica_errore(testo) == "auth_scaduta"


def test_la_rete_non_e_un_auth_scaduta() -> None:
    """«Could not reach NotebookLM» ha la stessa intestazione ma è un problema di rete."""
    assert core.classifica_errore(
        "Error: Authentication expired? Could not reach NotebookLM (timeout)") == "rete"
    assert core.classifica_errore("Could not retrieve studio status") == "altro"


def test_run_solleva_un_errore_parlante(monkeypatch) -> None:
    falso = subprocess.CompletedProcess(
        ["nlm"], 1, stdout="",
        stderr="Error: Authentication expired. Run `nlm login` in your terminal to re-authenticate.")
    monkeypatch.setattr(core.subprocess, "run", lambda *a, **k: falso)
    with pytest.raises(core.NLMAuthError) as e:
        core._run(["notebook", "list"])
    msg = str(e.value)
    assert "/admin/nlm" in msg
    assert "your terminal" not in msg, "l'invito a fare login QUI è l'errore del 21/07"


def _con_esito(monkeypatch, esito: str) -> None:
    def nb_list():
        if esito == "ok":
            return [{"id": "x"}]
        if esito == "auth_scaduta":
            raise core.NLMAuthError("sessione scaduta")
        raise core.NLMError("nlm exit 1: Could not reach NotebookLM")
    monkeypatch.setattr(core, "nb_list", nb_list)


def test_la_sonda_avvisa_una_volta_e_di_nuovo_al_ritorno(monkeypatch) -> None:
    _con_esito(monkeypatch, "ok")
    assert sonda.sonda_una_volta()["esito"] == "ok"
    assert memoria.drain(include_reminder=False) == [], "il primo ok non è una notizia"
    _con_esito(monkeypatch, "auth_scaduta")
    sonda.sonda_una_volta()
    sonda.sonda_una_volta()
    avvisi = memoria.drain(include_reminder=False)
    assert len(avvisi) == 1 and "/admin/nlm" in avvisi[0]["text"]
    _con_esito(monkeypatch, "ok")
    sonda.sonda_una_volta()
    tornata = memoria.drain(include_reminder=False)
    assert len(tornata) == 1 and tornata[0]["text"].startswith("🟢")


def test_la_rete_non_fa_suonare_l_allarme_dell_auth(monkeypatch) -> None:
    _con_esito(monkeypatch, "rete")
    assert sonda.sonda_una_volta()["esito"] == "rete"
    assert memoria.drain(include_reminder=False) == []


def test_il_registro_tiene_solo_l_esito_e_resta_corto(monkeypatch, tmp_path) -> None:
    _con_esito(monkeypatch, "ok")
    monkeypatch.setattr(sonda, "_RIGHE_MAX", 5)
    for _ in range(8):
        sonda.sonda_una_volta()
    righe = (tmp_path / "sonda-nlm.jsonl").read_text().splitlines()
    assert len(righe) == 5
    ultima = json.loads(righe[-1])
    # dal 05/10 anche la quota usata, un numero: nessun contenuto entra nel registro
    assert set(ultima) <= {"quando", "esito", "quota_usata"}
    assert isinstance(ultima.get("quota_usata", 0.0), (int, float))
    assert sonda.ultimo()["esito"] == "ok"


def test_senza_registro_ultimo_e_none() -> None:
    assert sonda.ultimo() is None


def test_studio_wait_al_tetto_restituisce_lo_stato(monkeypatch) -> None:
    """Da claude.ai una chiamata oltre ~30 s cade: il tool risponde prima, con lo stato."""
    monkeypatch.setattr(core, "studio_status", lambda nb, a: {"status": "in_progress"})
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    r = core.studio_wait("nb", "art", poll_interval=0.0, timeout=0.0,
                         restituisci_al_tetto=True)
    assert r["in_corso"] is True and r["status"] == "in_progress"
    with pytest.raises(core.NLMError):
        core.studio_wait("nb", "art", poll_interval=0.0, timeout=0.0)
