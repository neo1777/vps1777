"""P8 (11/10/2026): ogni errore di un tool di nb1777 porta un codice stabile fra quadre.

Fino alla 0.81 un errore arrivava al client come testo libero («nlm exit 1: …», «Auth
NotebookLM mancante…», «query_id … sconosciuto»), e chi lo riceve (il bot, la Mini App, un
modello) doveva indovinare dal testo se era la sessione Google, la rete o un argomento
sbagliato. Ora il testo comincia, dopo il prefisso di FastMCP («Error executing tool X: »),
con uno dei codici di `server.CODICI_ERRORE`. Il messaggio di prima resta, dopo il codice.

Le chiamate passano da `mcp.call_tool`, come quelle di un client; le funzioni del modulo
restano quelle di prima (chi le chiama in Python vede le eccezioni originali).
"""
from __future__ import annotations

import asyncio
import re

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from app import core, server


def _chiama(nome: str, argomenti: dict | None = None):
    return asyncio.run(server.mcp.call_tool(nome, argomenti or {}))


def _codice(exc: BaseException) -> str:
    m = re.search(r"Error executing tool \w+: \[([a-z_]+)\] ", str(exc))
    assert m, f"nessun codice in {exc!s:.200}"
    return m.group(1)


@pytest.fixture
def con_auth(monkeypatch):
    monkeypatch.setattr(server, "_check_auth_or_raise", lambda: None)


def test_auth_assente(monkeypatch):
    def nega():
        raise server.AuthAssente("Auth NotebookLM mancante.")
    monkeypatch.setattr(server, "_check_auth_or_raise", nega)
    with pytest.raises(ToolError) as e:
        _chiama("nb_list")
    assert _codice(e.value) == "auth_assente" and "Auth NotebookLM mancante" in str(e.value)


@pytest.mark.parametrize("errore, codice", [
    (core.NLMAuthError(core.MSG_AUTH_SCADUTA), "auth_scaduta"),
    (core.NLMError("timeout 60.0s su: nlm notebook list --json"), "timeout"),
    (core.NLMError("nlm exit 1: Could not reach NotebookLM (network)"), "rete"),
    (core.NLMError("nlm exit 1: You have reached your daily quota"), "quota"),
    (core.NLMError("nlm exit 2: qualcosa d'altro"), "nlm"),
    (RuntimeError("guasto inatteso"), "interno"),
])
def test_gli_errori_di_nlm_e_gli_altri(con_auth, monkeypatch, errore, codice):
    def solleva():
        raise errore
    monkeypatch.setattr(core, "nb_list", solleva)
    with pytest.raises(ToolError) as e:
        _chiama("nb_list")
    assert _codice(e.value) == codice


def test_un_argomento_sbagliato(con_auth, monkeypatch):
    monkeypatch.setattr(core, "nb_get", lambda nb: {"id": nb, "title": "t"})
    with pytest.raises(ToolError) as e:
        _chiama("nb_delete", {"notebook_id": "nb-1", "conferma": "gettone-inventato"})
    assert _codice(e.value) == "argomento"


def test_i_codici_sono_un_vocabolario_chiuso_e_documentato():
    assert set(server.CODICI_ERRORE) == {"auth_assente", "auth_scaduta", "rete", "timeout",
                                         "quota", "argomento", "nlm", "interno"}
    assert "[auth_scaduta]" in server.ISTRUZIONI_ERRORI


def test_la_funzione_del_modulo_resta_quella_di_prima(con_auth, monkeypatch):
    """I test e il codice interno che chiamano `server.nb_delete` in Python vedono
    l'eccezione originale: il codice si aggiunge solo sulla strada di MCP."""
    monkeypatch.setattr(core, "nb_get", lambda nb: {"id": nb, "title": "t"})
    with pytest.raises(ValueError):
        asyncio.run(server.nb_delete("nb-1", conferma="gettone-inventato"))


# ── 12/10/2026: un valore sbagliato del client è [argomento], anche se lo rifiuta core ──
# Prima questi controlli di `core` alzavano un NLMError nudo, e il client leggeva [nlm]
# («un errore di NotebookLM») per un argomento sbagliato suo. Ora alzano
# `core.ArgomentoNonValido`. In ogni caso nlm NON si chiama: `_run` qui fallisce il test.

@pytest.fixture
def senza_nlm(con_auth, monkeypatch, tmp_path):
    def vietato(*a, **k):
        raise AssertionError(f"nlm non andava chiamato: {a!r}")
    monkeypatch.setattr(core, "_run", vietato)
    monkeypatch.setattr(core, "_run_ricerca", vietato)
    monkeypatch.setenv("NLM_ARTIFACTS", str(tmp_path))
    # il registro dei lavori lunghi (studio_download, source_replace) parte pulito
    from app import lavori
    monkeypatch.setattr(lavori, "_LAVORI", {})
    monkeypatch.setattr(lavori, "_PER_CHIAVE", {})
    monkeypatch.setattr(lavori, "_LOCK_NB", {})
    monkeypatch.setattr(lavori, "_posti", None)


@pytest.mark.parametrize("nome, argomenti, nel_testo", [
    ("research_start", {"notebook_id": "nb-1", "query": "q", "source": "biblioteca"},
     "source 'biblioteca'"),
    ("research_start", {"notebook_id": "nb-1", "query": "q", "mode": "lentissimo"},
     "mode 'lentissimo'"),
    ("research_start", {"notebook_id": "nb-1", "query": "q", "source": "drive", "mode": "deep"},
     "solo sul web"),
    ("studio_create_report", {"notebook_id": "nb-1", "format": "Create Your Own"},
     "richiede `prompt`"),
    ("studio_download", {"kind": "podcast", "notebook_id": "nb-1", "output_path": "x.m4a"},
     "tipo non riconosciuto 'podcast'"),
    ("studio_download", {"kind": "audio", "notebook_id": "nb-1", "output_path": "..."},
     "non si ricava un nome file valido"),
    ("note_save", {"notebook_id": "nb-1", "note_id": "nota-1"},
     "serve content, title o tutti e due"),
])
def test_un_valore_rifiutato_da_core_e_un_argomento(senza_nlm, nome, argomenti, nel_testo):
    with pytest.raises(ToolError) as e:
        _chiama(nome, argomenti)
    assert _codice(e.value) == "argomento", str(e.value)
    assert nel_testo in str(e.value)


def test_source_replace_su_una_fonte_che_non_ce_piu_e_un_argomento(senza_nlm, monkeypatch):
    """Il primo tempo controlla già la fonte (ValueError in server); qui la fonte sparisce
    fra l'anteprima e la conferma, e a dirlo è `core.source_replace`."""
    monkeypatch.setattr(core, "source_list", lambda nb: [{"id": "un-altra-fonte"}])
    gettone = server._gettoni.gettone("source_replace", "nb-1", "fonte-1")
    with pytest.raises(ToolError) as e:
        _chiama("source_replace", {"notebook_id": "nb-1", "source_id": "fonte-1",
                                   "text": "nuovo", "conferma": gettone})
    assert _codice(e.value) == "argomento", str(e.value)
    assert "non è nel notebook nb-1" in str(e.value)


def test_l_argomento_rifiutato_resta_un_nlmerror_per_chi_lo_prende_cosi():
    """Le rotte interne degli artefatti (404) e il censimento prendono `core.NLMError`:
    devono continuare a prenderlo. Ed è un ValueError, come gli altri argomenti."""
    exc = core.ArgomentoNonValido("x")
    assert isinstance(exc, core.NLMError) and isinstance(exc, ValueError)
    assert server.codice_errore(exc) == "argomento"
    assert server.codice_errore(core.NLMError("nlm exit 1: Notebook not found")) == "nlm"


# ── 12/10/2026: l'attesa scaduta è [timeout], il guasto del server è [interno] ────────────

def test_l_attesa_scaduta_di_studio_wait_e_un_timeout(monkeypatch):
    """Il tool MCP studio_wait restituisce al tetto (non alza); alza chi chiama core senza
    `restituisci_al_tetto` (studio_create_all_9 con wait). Il testo resta quello di prima."""
    monkeypatch.setattr(core, "studio_status", lambda nb, aid: {"status": "in_progress"})
    with pytest.raises(core.AttesaScaduta) as e:
        core.studio_wait("nb-1", "art-1", poll_interval=0, timeout=0)
    assert str(e.value).startswith("studio_wait timeout 0s su art-1")
    assert isinstance(e.value, core.NLMError) and isinstance(e.value, TimeoutError)
    assert server.codice_errore(e.value) == "timeout"


def test_l_attesa_scaduta_arriva_al_client_come_timeout(con_auth, monkeypatch):
    def scade(*a, **k):
        raise core.AttesaScaduta("studio_wait timeout 25.0s su art-1; ultimo stato: {}")
    monkeypatch.setattr(core, "studio_wait", scade)
    with pytest.raises(ToolError) as e:
        _chiama("studio_wait", {"notebook_id": "nb-1", "artifact_id": "art-1"})
    assert _codice(e.value) == "timeout"


def test_la_directory_artefatti_non_scrivibile_e_un_guasto_interno(con_auth, monkeypatch,
                                                                   tmp_path):
    monkeypatch.setenv("NLM_ARTIFACTS", str(tmp_path))
    monkeypatch.setattr(core.os, "access", lambda p, m: False)
    with pytest.raises(core.GuastoDelServer) as e:
        core.artifacts_dir()
    assert isinstance(e.value, core.NLMError), "le rotte interne lo prendono come NLMError"
    assert server.codice_errore(e.value) == "interno"
    with pytest.raises(ToolError) as e:
        _chiama("studio_download", {"kind": "audio", "notebook_id": "nb-guasto",
                                    "output_path": "x.m4a"})
    assert _codice(e.value) == "interno" and "NON è scrivibile" in str(e.value)
