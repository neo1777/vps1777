"""La superficie MCP dichiara le igiene della ricerca (#268/#270/#272/#274).

Guardie di contratto sul livello SERVER (firme e docstring): il lavoro vero è
provato dai test di comportamento in test_ricerca_igiene.py; qui si tiene ciò
che un client MCP VEDE — i parametri nuovi e le regole d'uso dichiarate.

Importa l'SDK MCP, che nello step CI stdlib-only non c'è: `importorskip` +
lo step dedicato «deps del lock» in ci.yml che esegue questo file per nome —
uno skip senza quel secondo step sarebbe un presidio che non gira mai
(stesso patto di test_health.py).
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import server  # noqa: E402


def _firma(nome: str):
    fn = getattr(server, nome)
    return inspect.signature(fn), (fn.__doc__ or "")


def test_get_context_e_conversation_hanno_max_chars() -> None:
    for nome in ("get_context", "get_conversation"):
        sig, doc = _firma(nome)
        assert "max_chars" in sig.parameters, f"{nome} senza max_chars (#268)"
        assert sig.parameters["max_chars"].default == 0
        assert "#268" in doc


def test_list_databases_offre_le_schede() -> None:
    sig, doc = _firma("list_databases")
    assert "schede" in sig.parameters and sig.parameters["schede"].default is False
    assert "#274" in doc and "describe_databases" in doc


def test_search_dichiara_dedup_e_concorrenza() -> None:
    _, doc = _firma("search")
    assert "anche_in" in doc, "il dedup #272 va dichiarato a chi legge i risultati"
    assert "2 ricerche" in doc, "il limite di concorrenza #270 va dichiarato"


def test_archive_stats_dichiara_il_costo() -> None:
    _, doc = _firma("archive_stats")
    assert "memoizzate" in doc and "#269" in doc
