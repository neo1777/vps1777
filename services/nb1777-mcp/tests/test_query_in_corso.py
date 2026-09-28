"""notebook_query non tiene il client appeso oltre `attesa_max` (28/09/2026).

Da una chat su claude.ai `notebook_query` falliva sempre attorno ai 30 secondi, anche su
un notebook da cinque fonti, mentre `nb_list` rispondeva. Sul server la chiamata non
falliva: veniva chiusa dal client (nessun errore nel log, sessione terminata a 29-30 s),
mentre NotebookLM quel giorno rispondeva in 19-124 s. Da Claude Code la stessa query
di 2 minuti tornava intera: il limite era del client, non del server.

Ora la query aspetta al massimo `attesa_max` (default 25 s): se NotebookLM non ha ancora
risposto, torna `{stato: "in_corso", query_id}` e la query continua sul server;
`notebook_query_esito(query_id)` la ritira. Chi può aspettare (il bot, la Mini App)
passa un `attesa_max` lungo e riceve la risposta come prima.
"""
from __future__ import annotations

import asyncio
import threading

import pytest

from app import core, server


@pytest.fixture(autouse=True)
def _senza_auth(monkeypatch):
    monkeypatch.setattr(server, "_check_auth_or_raise", lambda: None)
    server._QUERY_IN_CORSO.clear()


def test_risposta_veloce_arriva_come_prima(monkeypatch):
    monkeypatch.setattr(core, "notebook_query", lambda nb, q, **k: {"answer": "ok"})
    r = asyncio.run(server.notebook_query("nb", "domanda"))
    assert r == {"answer": "ok"}


def test_risposta_lenta_da_un_query_id_e_poi_l_esito(monkeypatch):
    via = threading.Event()

    def lenta(nb, q, **k):
        via.wait(5)
        return {"answer": "arrivata"}
    monkeypatch.setattr(core, "notebook_query", lenta)

    async def giro():
        primo = await server.notebook_query("nb", "domanda", attesa_max=0.2)
        assert primo["stato"] == "in_corso" and primo["query_id"], primo
        ancora = await server.notebook_query_esito(primo["query_id"], attesa_max=0.1)
        assert ancora["stato"] == "in_corso", ancora
        via.set()
        return await server.notebook_query_esito(primo["query_id"], attesa_max=5)
    assert asyncio.run(giro()) == {"answer": "arrivata"}


def test_l_errore_della_query_arriva_all_esito(monkeypatch):
    def rotta(nb, q, **k):
        import time
        time.sleep(0.3)
        raise core.NLMError("nlm exit 1: NOT_FOUND")
    monkeypatch.setattr(core, "notebook_query", rotta)

    async def giro():
        primo = await server.notebook_query("nb", "domanda", attesa_max=0.05)
        return await server.notebook_query_esito(primo["query_id"], attesa_max=5)
    with pytest.raises(core.NLMError):
        asyncio.run(giro())


def test_query_id_sconosciuto_e_un_errore_parlante():
    with pytest.raises(ValueError, match="query_id"):
        asyncio.run(server.notebook_query_esito("non-esiste"))


def test_attesa_max_fuori_misura_e_limitata(monkeypatch):
    monkeypatch.setattr(core, "notebook_query", lambda nb, q, **k: {"answer": "ok"})
    # 0 o negativo non vuol dire «non aspettare mai»: si aspetta almeno 1 s
    assert asyncio.run(server.notebook_query("nb", "d", attesa_max=0)) == {"answer": "ok"}
