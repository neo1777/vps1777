"""Un tool che fallisce lascia una riga nel log del container (28/09/2026).

Una chat su claude.ai ha visto `notebook_query` fallire per qualche minuto, anche su un
notebook da cinque fonti, mentre `nb_list` e `studio_list` rispondevano. Sulla VPS non
restava niente: il 200 del gateway non dice nulla (la risposta MCP è in streaming) e
nb1777-mcp non scriveva gli errori dei tool. Un'ora dopo la query rispondeva di nuovo, e
la causa non si poteva più leggere da nessuna parte. Ora ogni fallimento lascia nome del
tool, durata ed errore (già ripulito dai contenuti, H41, e troncato).
"""
from __future__ import annotations

import asyncio
import logging

import pytest

from app import core, server


def test_il_fallimento_di_un_tool_si_scrive_nel_log(monkeypatch, caplog):
    monkeypatch.setattr(server, "_check_auth_or_raise", lambda: None)

    def notebook_query(*_a, **_k):
        raise core.NLMError("nlm exit 1: " + "x" * 2000)

    with caplog.at_level(logging.WARNING), pytest.raises(core.NLMError):
        asyncio.run(server._aio(notebook_query, "nb", "domanda"))
    righe = [r.getMessage() for r in caplog.records]
    assert any("notebook_query" in r and "NLMError" in r and "nlm exit 1" in r
               for r in righe), righe
    assert all(len(r) < 600 for r in righe), "l'errore va troncato"


def test_anche_l_auth_mancante_si_scrive(monkeypatch, caplog):
    def _nega():
        raise RuntimeError("Auth NotebookLM mancante.")
    monkeypatch.setattr(server, "_check_auth_or_raise", _nega)
    with caplog.at_level(logging.WARNING), pytest.raises(RuntimeError):
        asyncio.run(server._aio(lambda: None))
    assert any("Auth NotebookLM mancante" in r.getMessage() for r in caplog.records)


# La chat che ha segnalato il guasto ha chiesto di distinguere le chiamate riuscite da
# quelle fallite. Gli esiti sono tre: il suo «MCP tool call failed» era il terzo — il
# client che chiude a ~30 s — e il log di prima non lo vedeva, perché non è un'eccezione
# del tool ma un CancelledError.
def test_tre_esiti_tre_righe(monkeypatch, caplog):
    monkeypatch.setattr(server, "_check_auth_or_raise", lambda: None)

    def nb_list():
        return []

    async def interrotta():
        t = asyncio.create_task(server._aio(__import__("time").sleep, 2))
        await asyncio.sleep(0.1)
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t

    with caplog.at_level(logging.INFO):
        asyncio.run(server._aio(nb_list))
        asyncio.run(interrotta())
    righe = [r.getMessage() for r in caplog.records]
    assert any(r.startswith("tool nb_list ok in") for r in righe), righe
    assert any("tool sleep interrotto dopo" in r and "il client ha chiuso" in r
               for r in righe), righe
