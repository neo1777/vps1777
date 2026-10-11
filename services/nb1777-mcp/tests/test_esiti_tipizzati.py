"""P8 (11/10/2026): ogni tool di nb1777 dichiara la forma di ciò che restituisce.

Misurato il 11/10: 23 tool su 49 senza schema d'uscita, e 4 liste di oggetti generici. Un
client che non sa la forma la indovina dal testo. Ora ogni tool ha uno schema; i modelli
stanno in `app/esiti.py`.

Due cose provate prima di scriverli, con FastMCP 1.30 vero: un TypedDict come uscita BUTTA
le chiavi non dichiarate (anche con extra="allow") e mette null nei campi NotRequired
assenti. Per i tool che passano il JSON di nlm così com'è sarebbe una perdita silenziosa.
Quindi BaseModel con extra="allow" e una base che toglie i null in uscita. E i campi che
vengono da nlm hanno tipi larghi: il server valida l'uscita contro lo schema, e un tipo
sbagliato trasformerebbe una risposta buona in un errore.
"""
from __future__ import annotations

import asyncio

import pytest

from app import core, server


def _tools() -> dict:
    return {t.name: t for t in asyncio.run(server.mcp.list_tools())}


def test_nessun_tool_resta_senza_schema_d_uscita():
    senza = [n for n, t in _tools().items() if not t.outputSchema]
    assert not senza, f"tool senza schema d'uscita: {senza}"


def test_le_liste_dicono_la_forma_dei_loro_elementi():
    t = _tools()
    for nome in ("nb_list", "source_list", "note_list", "studio_list"):
        voce = t[nome].outputSchema["properties"]["result"]["items"]
        voce = t[nome].outputSchema.get("$defs", {}).get(voce.get("$ref", "#/x/").split("/")[-1], voce)
        assert "id" in voce.get("properties", {}), nome


@pytest.fixture
def con_auth(monkeypatch):
    monkeypatch.setattr(server, "_check_auth_or_raise", lambda: None)


def _strutturato(nome: str, argomenti: dict):
    _, strutturato = asyncio.run(server.mcp.call_tool(nome, argomenti))
    return strutturato


def test_le_chiavi_di_nlm_non_dichiarate_restano(con_auth, monkeypatch):
    monkeypatch.setattr(core, "nb_get", lambda nb: {"notebook_id": nb, "title": "t",
                                                     "campo_nuovo_di_nlm": [1, 2]})
    s = _strutturato("nb_get", {"notebook_id": "nb-1"})
    assert s["campo_nuovo_di_nlm"] == [1, 2] and s["title"] == "t"


def test_niente_null_per_i_campi_assenti(con_auth, monkeypatch):
    monkeypatch.setattr(core, "nb_get", lambda nb: {"notebook_id": nb})
    s = _strutturato("nb_get", {"notebook_id": "nb-1"})
    assert s == {"notebook_id": "nb-1"}


def test_un_tipo_inatteso_da_nlm_non_rompe_la_risposta(con_auth, monkeypatch):
    monkeypatch.setattr(core, "nb_get", lambda nb: {"notebook_id": nb, "source_count": "3?",
                                                     "sources": "non una lista"})
    s = _strutturato("nb_get", {"notebook_id": "nb-1"})
    assert s["source_count"] == "3?"


def test_una_lista_tipizzata_tiene_le_chiavi_in_piu(con_auth, monkeypatch):
    monkeypatch.setattr(core, "nb_list", lambda: [{"id": "a", "title": "A", "nuovo": True}])
    s = _strutturato("nb_list", {})
    assert s["result"] == [{"id": "a", "title": "A", "nuovo": True}]
