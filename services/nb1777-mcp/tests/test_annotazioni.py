"""Ogni tool di nb1777 dichiara cosa fa al mondo (S10, 05/10/2026).

Le annotazioni (`readOnlyHint`, `destructiveHint`, `openWorldHint`) sono ciò che il client
usa per raggruppare e chiedere i permessi. Fino alla 0.72 nessuno dei 39 tool le aveva.
`destructiveHint` va scritto anche quando è False: il default della spec è True.
"""
from __future__ import annotations

from app import canonical, server

TETTO = 2048


def _tools():
    return {t.name: t for t in server.mcp._tool_manager.list_tools()}


def test_ogni_tool_ha_titolo_e_annotazioni() -> None:
    tools = _tools()
    assert len(tools) == 40
    assert set(server.ANNOTAZIONI) == set(tools), "tabella e tool registrati divergono"
    for nome, t in tools.items():
        a = t.annotations
        assert a is not None and a.title and t.title, nome
        assert a.readOnlyHint is not None and a.openWorldHint is not None, nome
        if not a.readOnlyHint:
            assert a.destructiveHint is not None, f"{nome}: destructiveHint implicito (default True)"


def test_distruttivi_sono_solo_le_tre_cancellazioni() -> None:
    distruttivi = sorted(n for n, t in _tools().items() if t.annotations.destructiveHint)
    assert distruttivi == ["nb_delete", "source_delete", "studio_delete"]


def test_chi_scrive_non_si_spaccia_per_sola_lettura() -> None:
    """Due casi che sembrano letture e non lo sono (verifica del 05/10)."""
    t = _tools()
    assert t["memoria_check"].annotations.readOnlyHint is False, "manda un ping Telegram"
    assert t["studio_download"].annotations.readOnlyHint is False, "scrive un file sul volume"


def test_descrizioni_e_istruzioni_nel_tetto() -> None:
    lunghe = {n: len(t.description or "") for n, t in _tools().items()
              if len(t.description or "") > TETTO}
    assert not lunghe, lunghe
    assert len(canonical.declaration_text()) <= TETTO
