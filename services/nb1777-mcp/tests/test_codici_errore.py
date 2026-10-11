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
