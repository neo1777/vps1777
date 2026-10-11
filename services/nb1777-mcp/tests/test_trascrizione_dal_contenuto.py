"""P17 (11/10/2026): la trascrizione prende il testo indicizzato della fonte.

`transcribe_document` chiedeva la trascrizione con una domanda: la risposta ha un tetto
di lunghezza e passa da un LLM, quindi su un podcast di un'ora può accorciare o
riassumere. Ora il testo viene da `source content` (ciò che NotebookLM ha indicizzato:
per un audio la trascrizione, per un PDF-immagine il testo letto); la domanda resta il
ripiego quando il contenuto è vuoto o la chiamata fallisce. Si mockano i confini nlm.
"""
from __future__ import annotations

import pytest

from app import core


@pytest.fixture()
def scratch(monkeypatch):
    domande: list[str] = []
    monkeypatch.setattr(core, "nb_create", lambda title: "nb-p17")
    monkeypatch.setattr(core, "source_add_file", lambda *a, **k: "sid-p17")
    monkeypatch.setattr(core, "nb_delete", lambda nb_id: None)

    def domanda(nb, q, **k):
        domande.append(q)
        return {"answer": "RISPOSTA ALLA DOMANDA"}

    monkeypatch.setattr(core, "notebook_query", domanda)
    return domande


def test_il_testo_viene_dal_contenuto_della_fonte(monkeypatch, scratch):
    visti: list[str] = []

    def contenuto(sid):
        visti.append(sid)
        return {"content": "  la trascrizione intera  ", "source_type": "audio",
                "char_count": 24}

    monkeypatch.setattr(core, "source_contenuto", contenuto)
    out = core.transcribe_document("/tmp/podcast.m4a")
    assert visti == ["sid-p17"]
    assert out["text"] == "la trascrizione intera" and out["chars"] == 22
    assert out["metodo"] == "contenuto" and out["fonte_tipo"] == "audio"
    assert scratch == [], "col contenuto pieno nessuna domanda"


def test_contenuto_vuoto_si_torna_alla_domanda(monkeypatch, scratch):
    monkeypatch.setattr(core, "source_contenuto", lambda sid: {"content": "   "})
    out = core.transcribe_document("/tmp/x.pdf")
    assert out["metodo"] == "domanda" and out["text"] == "RISPOSTA ALLA DOMANDA"
    assert scratch == [core._TRANSCRIBE_PROMPT]


def test_un_errore_del_contenuto_ripiega_sulla_domanda(monkeypatch, scratch):
    def rotto(sid):
        raise core.NLMError("rpc cambiata")

    monkeypatch.setattr(core, "source_contenuto", rotto)
    out = core.transcribe_document("/tmp/x.pdf")
    assert out["metodo"] == "domanda" and out["text"]


def test_una_sessione_scaduta_non_ripiega(monkeypatch, scratch):
    """Con l'auth scaduta anche la domanda fallirebbe: si dice subito, e lo scratch si
    cancella lo stesso (il finally)."""
    def scaduta(sid):
        raise core.NLMAuthError("auth scaduta")

    monkeypatch.setattr(core, "source_contenuto", scaduta)
    with pytest.raises(core.NLMAuthError):
        core.transcribe_document("/tmp/x.pdf")
    assert scratch == []


def test_la_verifica_resta_una_domanda(monkeypatch, scratch):
    monkeypatch.setattr(core, "source_contenuto", lambda sid: {"content": "testo"})
    out = core.transcribe_document("/tmp/x.pdf", verify=True)
    assert out["metodo"] == "contenuto"
    assert scratch == [core._VERIFY_PROMPT] and out["verification"]


def test_source_contenuto_vuole_un_oggetto(monkeypatch):
    monkeypatch.setattr(core, "_run_json", lambda args, **k: ["non", "un", "oggetto"])
    with pytest.raises(core.NLMError):
        core.source_contenuto("sid")


def test_source_contenuto_chiede_il_json_di_source_content(monkeypatch):
    visti: list = []

    def finto(args, **k):
        visti.append(args)
        return {"content": "x"}

    monkeypatch.setattr(core, "_run_json", finto)
    assert core.source_contenuto("sid-1") == {"content": "x"}
    assert visti == [["source", "content", "sid-1"]]
