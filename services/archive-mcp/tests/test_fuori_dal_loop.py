"""I tool di archive girano fuori dall'event loop (S1, 05/10/2026).

🔴 IL DIFETTO. FastMCP (mcp 1.30) chiama un tool `def` DENTRO l'event loop
(`func_metadata.call_fn_with_arg_validation`: `return fn(**args)`), e i 15 tool di
archive sono tutti `def`. Una ricerca lenta fermava tutto il server, `/health` compreso:
il 04/10 la sonda è rimasta muta per 311, 536 e 656 s, e dal 07/09 i client hanno visto
92 errori fra «timed out» e «connection lost».

La cura sta nel decoratore che avvolge già ogni tool per la redazione: il tool diventa
una coroutine che esegue il lavoro su un executor dedicato, con thread PERSISTENTI (la
cache delle connessioni è per thread: un thread che muore ripaga l'apertura dei DB).
"""
from __future__ import annotations

import asyncio
import inspect
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# L'SDK MCP non c'è nello step stdlib-only: questo test gira nello step «deps del lock»,
# dove è elencato (ci.yml e tools/check.sh).
pytest.importorskip("mcp")

from app import server  # noqa: E402


def test_ogni_tool_registrato_e_una_coroutine() -> None:
    tools = server.mcp._tool_manager.list_tools()
    assert len(tools) >= 15, "meno tool del previsto: il test non vede il server vero"
    sincroni = [t.name for t in tools if not inspect.iscoroutinefunction(t.fn)]
    assert not sincroni, f"tool eseguiti dentro l'event loop: {sincroni}"


def test_un_tool_lento_non_ferma_l_event_loop() -> None:
    lento = server._fuori_dal_loop(lambda: time.sleep(1.0) or "fatto")

    async def prova() -> tuple[float, str]:
        compito = asyncio.create_task(lento())
        t0 = time.monotonic()
        await asyncio.sleep(0.05)                        # il «tick» di /health
        attesa = time.monotonic() - t0
        return attesa, await compito

    attesa, esito = asyncio.run(prova())
    assert esito == "fatto"
    assert attesa < 0.5, f"l'event loop è rimasto fermo {attesa:.2f} s dietro al tool"


def test_i_thread_dell_executor_restano_vivi() -> None:
    """Un executor che ricrea i thread ripaga l'apertura dei DB (229 ms l'uno, cifrati)."""
    nomi = set()

    async def giro() -> None:
        for _ in range(6):
            nomi.add(await server._fuori_dal_loop(lambda: __import__("threading").current_thread().name)())

    asyncio.run(giro())
    assert len(nomi) <= server._THREAD_TOOL, nomi
    assert all(n.startswith("archive-tool") for n in nomi), nomi


def test_la_firma_del_tool_resta_quella_vera() -> None:
    """FastMCP costruisce lo schema dai parametri: l'involucro non deve nasconderli."""
    t = {t.name: t for t in server.mcp._tool_manager.list_tools()}["search"]
    assert {"query", "db_name", "limit", "speaker"} <= set(t.parameters["properties"])
