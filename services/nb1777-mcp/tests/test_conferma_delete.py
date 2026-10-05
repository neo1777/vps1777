"""Le tre cancellazioni di nb1777 chiedono conferma in due tempi (05/10/2026, Neo).

Un notebook, una fonte o un artefatto cancellati su NotebookLM non tornano. Prima
bastava una chiamata: un id sbagliato, o un modello che aveva capito male, e la cosa
spariva. Ora, come fa notebooklm-py, la prima chiamata non cancella: dice cosa
sparirebbe e dà un gettone legato a QUELL'azione e a QUEGLI id, valido 5 minuti; solo la
seconda, con quel gettone, cancella. Le chiamate interne (statecard, pulizia dell'OCR)
passano da `core` e non cambiano.
"""
from __future__ import annotations

import asyncio

import pytest

from app import conferma, core, server


def test_il_gettone_vale_solo_per_la_sua_azione_e_i_suoi_id():
    g = conferma.gettone("nb_delete", "nb-1")
    assert conferma.verifica(g, "nb_delete", "nb-1") is None
    assert "non vale" in conferma.verifica(g, "nb_delete", "nb-2")
    assert "non vale" in conferma.verifica(g, "source_delete", "nb-1")
    assert "non vale" in conferma.verifica("rotto", "nb_delete", "nb-1")


def test_il_gettone_scade():
    g = conferma.gettone("nb_delete", "nb-1", ora=1000)
    assert conferma.verifica(g, "nb_delete", "nb-1", ora=1000 + conferma.DURATA_S - 1) is None
    assert "scaduto" in conferma.verifica(g, "nb_delete", "nb-1", ora=1000 + conferma.DURATA_S + 1)


@pytest.fixture
def finto(monkeypatch):
    cancellati: list[tuple] = []
    monkeypatch.setattr(core, "nb_get", lambda nb: {"id": nb, "title": "Prova", "sources": [1, 2]})
    monkeypatch.setattr(core, "nb_delete", lambda nb: cancellati.append(("nb", nb)))
    monkeypatch.setattr(core, "source_list", lambda nb: [{"id": "s1", "title": "Fonte uno"}])
    monkeypatch.setattr(core, "source_delete", lambda nb, s: cancellati.append(("src", s)))
    monkeypatch.setattr(core, "studio_list",
                        lambda nb, verbose=False: [{"id": "a1", "type": "audio", "label": "Podcast"}])
    monkeypatch.setattr(core, "studio_delete", lambda nb, a: cancellati.append(("art", a)))
    return cancellati


def _chiama(fn, *a, **kw):
    return asyncio.run(fn(*a, **kw))


@pytest.mark.parametrize("tool, args, cosa", [
    ("nb_delete", ("nb-1",), ("nb", "nb-1")),
    ("source_delete", ("nb-1", "s1"), ("src", "s1")),
    ("studio_delete", ("nb-1", "a1"), ("art", "a1")),
])
def test_prima_l_anteprima_poi_col_gettone_la_cancellazione(finto, tool, args, cosa):
    fn = getattr(server, tool)
    primo = _chiama(fn, *args)
    assert finto == [], "la prima chiamata non deve cancellare niente"
    assert primo["cancellato"] is False and primo["conferma"] and primo["anteprima"]
    secondo = _chiama(fn, *args, conferma=primo["conferma"])
    assert secondo["cancellato"] is True
    assert finto == [cosa]


def test_un_gettone_di_un_altro_id_non_cancella(finto):
    g = _chiama(server.nb_delete, "nb-1")["conferma"]
    with pytest.raises(ValueError, match="non vale"):
        _chiama(server.nb_delete, "nb-2", conferma=g)
    assert finto == []


def test_l_anteprima_dice_cosa_sparirebbe(finto):
    a = _chiama(server.source_delete, "nb-1", "s1")["anteprima"]
    assert a.get("title") == "Fonte uno"
    assert _chiama(server.studio_delete, "nb-1", "a1")["anteprima"]["label"] == "Podcast"
    assert _chiama(server.nb_delete, "nb-1")["anteprima"]["title"] == "Prova"
