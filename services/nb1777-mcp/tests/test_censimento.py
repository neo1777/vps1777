"""P14 (11/10/2026): i lavori in blocco su nb1777 senza ssh.

Il censimento del 21/09 (sessione 63d7d7a0) è passato da `ssh + docker exec nlm`: 2.662
chiamate in fila, 2 h 53 min. Ora ci sono tre tool:
  · `source_describe(source_id)`: il riassunto con le parole chiave di una fonte (nlm 0.15);
  · `nb_export(notebook_id)`: un notebook in un file JSON (fonti, e a scelta testi e riassunti);
  · `censimento()`: lo stesso su tutti i notebook.
I due ultimi sono lavori lunghi (P6: `in_corso` + `lavoro_esito`) e restituiscono un link
firmato al file (P15). Un errore su una fonte non ferma il lavoro: si conta e si scrive.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app import core, server


def test_source_describe_chiede_a_nlm_il_json(monkeypatch):
    chiamate = []
    monkeypatch.setattr(core, "_run_json", lambda args, **k: chiamate.append(args) or
                        {"summary": "s", "keywords": ["a"]})
    assert core.source_describe("src-1") == {"summary": "s", "keywords": ["a"]}
    assert chiamate == [["source", "describe", "src-1"]]


@pytest.fixture
def finto(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "artifacts_dir", lambda: tmp_path)
    monkeypatch.setattr(core, "nb_list", lambda: [{"id": "nb-1", "title": "Uno"},
                                                  {"id": "nb-2", "title": "Due"}])
    fonti = {"nb-1": [{"id": "s1", "title": "Fonte 1", "type": "pdf"},
                      {"id": "s2", "title": "Fonte 2", "type": "web"}],
             "nb-2": [{"id": "s3", "title": "Fonte 3", "type": "text"}]}
    monkeypatch.setattr(core, "source_list", lambda nb: fonti[nb])

    def contenuto(nb, sid):
        if sid == "s2":
            raise core.NLMError("nlm exit 1: fonte illeggibile")
        return f"testo di {sid}"
    monkeypatch.setattr(core, "source_get_content", contenuto)
    monkeypatch.setattr(core, "source_describe", lambda sid: {"summary": f"rias {sid}"})
    return tmp_path


def test_censisci_scrive_un_file_e_conta(finto):
    r = core.censisci(None, descrizioni=False, contenuti=False)
    dati = json.loads((finto / r["name"]).read_text())
    assert [n["id"] for n in dati["notebooks"]] == ["nb-1", "nb-2"]
    assert [f["id"] for f in dati["notebooks"][0]["sources"]] == ["s1", "s2"]
    assert "contenuto" not in dati["notebooks"][0]["sources"][0]
    assert r["notebooks"] == 2 and r["fonti"] == 3 and r["errori"] == 0
    assert r["bytes"] == (finto / r["name"]).stat().st_size


def test_un_errore_su_una_fonte_non_ferma_il_lavoro(finto):
    r = core.censisci(["nb-1"], descrizioni=True, contenuti=True)
    dati = json.loads((finto / r["name"]).read_text())
    s1, s2 = dati["notebooks"][0]["sources"]
    assert s1["contenuto"] == "testo di s1" and s1["descrizione"] == {"summary": "rias s1"}
    assert "fonte illeggibile" in s2["errore"] and "contenuto" not in s2
    assert r["errori"] == 1 and r["notebooks"] == 1


def test_nb_export_e_censimento_tornano_un_link(finto, monkeypatch):
    monkeypatch.setattr(server, "_check_auth_or_raise", lambda: None)
    r = asyncio.run(server.nb_export("nb-2", attesa_max=10))
    assert r["fonti"] == 1 and r["link"] and r["name"].startswith("export-")
    r = asyncio.run(server.censimento(attesa_max=10))
    assert r["notebooks"] == 2 and r["name"].startswith("censimento-")


def test_i_tre_tool_sono_registrati_e_leggono():
    nomi = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    for nome in ("source_describe", "nb_export", "censimento"):
        assert nome in nomi and nomi[nome].outputSchema, nome
    assert nomi["source_describe"].annotations.readOnlyHint is True
