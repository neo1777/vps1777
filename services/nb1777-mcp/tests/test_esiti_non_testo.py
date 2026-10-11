"""I tool di nb1777 che rispondevano una stringa ora dicono cosa hanno fatto (11/10/2026).

Diciassette tool davano «ok», un id nudo o il JSON di nlm COME TESTO: `source_get_content`
restituiva un dizionario serializzato dentro una stringa, e chi chiamava doveva indovinare
la forma. Qui: ogni tool ha uno schema d'uscita con proprietà vere, e le forme si
chiamano davvero (confini nlm finti).
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app import core, server

DICIASSETTE = ["nb_create", "nb_rename", "nb_describe", "source_get_content", "source_rename",
               "studio_create_audio", "studio_create_video", "studio_create_slides",
               "studio_create_mindmap", "studio_create_infographic", "studio_create_data_table",
               "studio_create_report", "studio_create_quiz", "studio_create_flashcards",
               "studio_rename", "studio_export_to_docs", "studio_export_to_sheets"]


def _tools():
    return {t.name: t for t in server.mcp._tool_manager.list_tools()}


def test_nessun_tool_risponde_col_solo_testo():
    for nome, t in _tools().items():
        props = (t.output_schema or {}).get("properties", {})
        solo_testo = set(props) == {"result"} and props["result"].get("type") == "string"
        assert t.output_schema and not solo_testo, f"{nome}: nessuna forma, o solo una stringa"


@pytest.mark.parametrize("nome", DICIASSETTE)
def test_i_diciassette_hanno_proprieta_vere(nome):
    props = _tools()[nome].output_schema.get("properties", {})
    assert props and "result" not in props, props


def _chiama(fn, *a, **kw):
    return asyncio.run(fn(*a, **kw))


@pytest.fixture
def finto(monkeypatch):
    monkeypatch.setattr(server, "_check_auth_or_raise", lambda: None)
    monkeypatch.setattr(core, "nb_create", lambda title: "nb-nuovo")
    monkeypatch.setattr(core, "nb_rename", lambda nb, t: None)
    monkeypatch.setattr(core, "source_rename", lambda nb, s, t: None)
    monkeypatch.setattr(core, "studio_rename", lambda nb, a, t: None)
    monkeypatch.setattr(core, "studio_create_audio", lambda nb, **k: "art-1")
    monkeypatch.setattr(core, "studio_export_to_docs",
                        lambda nb, a, title=None: "https://docs.google.com/document/d/x")


def test_le_forme(finto):
    assert _chiama(server.nb_create, "Prova") == {"notebook_id": "nb-nuovo", "title": "Prova"}
    assert _chiama(server.nb_rename, "nb", "Nuovo")["rinominato"] is True
    assert _chiama(server.source_rename, "nb", "s1", "T") == {"id": "s1", "title": "T",
                                                              "rinominato": True}
    assert _chiama(server.studio_rename, "nb", "a1", "T")["id"] == "a1"
    assert _chiama(server.studio_create_audio, "nb") == {"artifact_id": "art-1",
                                                         "notebook_id": "nb", "tipo": "audio"}
    assert _chiama(server.studio_export_to_docs, "nb", "a1")["url"].startswith("https://")


def test_il_json_di_nlm_diventa_un_oggetto(monkeypatch, finto):
    d = {"content": "testo", "title": "t", "source_type": "audio", "char_count": 5}
    monkeypatch.setattr(core, "source_get_content", lambda nb, s: json.dumps(d))
    assert _chiama(server.source_get_content, "nb", "s1") == d
    monkeypatch.setattr(core, "nb_describe",
                        lambda nb: json.dumps({"summary": "S", "suggested_topics": ["a"]}))
    assert _chiama(server.nb_describe, "nb")["summary"] == "S"


def test_se_nlm_non_da_json_il_testo_resta(monkeypatch, finto):
    monkeypatch.setattr(core, "source_get_content", lambda nb, s: "testo nudo")
    assert _chiama(server.source_get_content, "nb", "s1") == {"content": "testo nudo"}
    monkeypatch.setattr(core, "nb_describe", lambda nb: "[1, 2]")
    assert _chiama(server.nb_describe, "nb") == {"testo": "[1, 2]"}
