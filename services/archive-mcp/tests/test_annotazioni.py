"""Ogni tool di archive si presenta per intero (S4 e S10, 05/10/2026).

Claude Code tronca descrizioni e istruzioni a 2048 caratteri: fino alla 0.72 la guida di
`search` (4.974 caratteri) e di `search_ibrida` (5.527) arrivava tagliata, e si perdevano
le spiegazioni di speaker, voice, campi e della finestra temporale. Ora le spiegazioni dei
parametri stanno nello schema, le regole in testa e nelle `instructions` del server.
E ogni tool dichiara cosa fa al mondo: le annotazioni che il client usa per i permessi.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import server  # noqa: E402

TETTO = 2048


def _tools():
    return {t.name: t for t in server.mcp._tool_manager.list_tools()}


def test_nessuna_descrizione_supera_il_tetto_di_claude_code() -> None:
    lunghe = {n: len(t.description or "") for n, t in _tools().items()
              if len(t.description or "") > TETTO}
    assert not lunghe, f"descrizioni troncate dal client: {lunghe}"


def test_le_istruzioni_del_server_ci_sono_e_stanno_nel_tetto() -> None:
    assert server.ISTRUZIONI and len(server.ISTRUZIONI) <= TETTO
    for regola in ("search_ibrida", "get_context", "speaker='human'", "saltati"):
        assert regola in server.ISTRUZIONI


def test_ogni_parametro_della_ricerca_ha_la_sua_spiegazione() -> None:
    for nome in ("search", "search_ibrida"):
        prop = _tools()[nome].parameters["properties"]
        senza = [p for p, s in prop.items() if not s.get("description")]
        assert not senza, f"{nome}: parametri senza descrizione {senza}"


def test_ogni_tool_ha_titolo_e_annotazioni() -> None:
    for nome, t in _tools().items():
        a = t.annotations
        assert a is not None and a.title and t.title, nome
        assert a.readOnlyHint is not None and a.openWorldHint is False, nome
        if not a.readOnlyHint:
            assert a.destructiveHint is not None, f"{nome}: destructiveHint implicito (default True)"


def test_scrivono_solo_i_due_tool_dei_metadati() -> None:
    scrivono = sorted(n for n, t in _tools().items() if not t.annotations.readOnlyHint)
    assert scrivono == ["set_description", "set_ruolo"]
    assert set(server.ANNOTAZIONI) == set(_tools()), "tabella e tool registrati divergono"
