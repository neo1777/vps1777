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


def test_list_databases_espone_il_ruolo_nelle_schede() -> None:
    """#278 — il campo su cui si INSTRADA deve stare nella scheda che il client
    legge per scegliere. Se `ruolo` esistesse solo in describe_databases, chi usa
    le schede continuerebbe a dedurre il DB dalla prosa, che è la #278 stessa."""
    fn = getattr(server, "list_databases")
    sorgente = inspect.getsource(fn)
    assert '"ruolo"' in sorgente, "le schede non portano il ruolo"
    assert "#278" in (fn.__doc__ or "")


def test_set_ruolo_dichiara_il_vocabolario_e_il_default() -> None:
    """Il docstring è l'unica cosa che un LLM legge prima di chiamare il tool: se
    non porta le quattro parole, chi lo usa deve indovinarle — e il tool
    esisterebbe per togliere gli indovinelli."""
    sig, doc = _firma("set_ruolo")
    assert list(sig.parameters) == ["db_name", "ruolo"]
    for parola in ("primario", "fotografia", "riscontro", "riservato"):
        assert parola in doc, f"il docstring non dichiara '{parola}'"
    assert "non dichiarato" in doc, "il default onesto non è dichiarato a chi chiama"
    assert "#278" in doc


def test_describe_dichiara_che_il_ruolo_NON_cambia_i_default() -> None:
    """La cura A è additiva, e la cosa va detta dove qualcuno potrebbe assumere il
    contrario. Un campo `ruolo` in vista fa credere che il default sia diventato
    «cerca sui primari» — se lo diventerà (cura B) sarà un cambio di CONTRATTO,
    con il suo CHANGELOG e il protocollo dello zero aggiornato. Fino ad allora
    l'unica difesa contro quell'assunzione è la riga che la smentisce."""
    _, doc = _firma("describe_databases")
    assert "#278" in doc
    assert "tutti i DB" in doc and "cura B" in doc


def test_archive_stats_dichiara_il_costo() -> None:
    _, doc = _firma("archive_stats")
    assert "memoizzate" in doc and "#269" in doc
