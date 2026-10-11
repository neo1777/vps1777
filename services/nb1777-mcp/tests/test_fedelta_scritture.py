"""P20 (11/10/2026): la fedeltà delle scritture su NotebookLM.

- `source_replace`: NotebookLM non modifica una fonte; si aggiunge la nuova e POI si toglie
  la vecchia. Un errore nell'aggiunta lascia la vecchia intatta, uno nella cancellazione
  lascia due fonti e lo dice. L'id cambia sempre. Due tempi, come le cancellazioni.
- `source_drive_stato` / `source_sync_drive`: le fonti Drive si riallineano sul posto (stesso
  id). La freschezza viene da `source list --drive`, perché `source stale` di nlm 0.15.4 non
  la controlla e non segnala mai niente.
Si mockano i confini nlm.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app import core, server


@pytest.fixture
def registro(monkeypatch):
    passi: list[tuple] = []
    monkeypatch.setattr(core, "source_list",
                        lambda nb: [{"id": "vecchia", "title": "Appunti"}, {"id": "altra"}])
    monkeypatch.setattr(core, "source_add_text",
                        lambda nb, text, title, **k: passi.append(("testo", title)) or "nuova")
    monkeypatch.setattr(core, "source_add_url",
                        lambda nb, url, title=None, **k: passi.append(("url", url, title)) or "nuova")
    monkeypatch.setattr(core, "source_delete", lambda nb, sid: passi.append(("via", sid)))
    return passi


def test_prima_si_aggiunge_poi_si_toglie(registro):
    out = core.source_replace("nb", "vecchia", text="testo nuovo")
    assert registro == [("testo", "Appunti"), ("via", "vecchia")]
    assert out["source_id"] == "nuova" and out["sostituita"] == "vecchia"
    assert out["id_cambiato"] is True and out["vecchia_cancellata"] is True


def test_l_url_tiene_il_titolo_della_pagina_se_non_se_ne_da_uno(registro):
    core.source_replace("nb", "vecchia", url="https://example.invalid/a")
    assert registro[0] == ("url", "https://example.invalid/a", None)


def test_se_l_aggiunta_fallisce_la_vecchia_resta(registro, monkeypatch):
    def rotta(*a, **k):
        raise core.NLMError("add fallita")

    monkeypatch.setattr(core, "source_add_text", rotta)
    with pytest.raises(core.NLMError):
        core.source_replace("nb", "vecchia", text="x")
    assert ("via", "vecchia") not in registro


def test_se_la_cancellazione_fallisce_si_dice(registro, monkeypatch):
    def rotta(nb, sid):
        raise core.NLMError("delete ko")

    monkeypatch.setattr(core, "source_delete", rotta)
    out = core.source_replace("nb", "vecchia", text="x")
    assert out["vecchia_cancellata"] is False and "tutte e due" in out["avviso"]


@pytest.mark.parametrize("kw", [{}, {"text": "a", "url": "https://example.invalid"}])
def test_testo_oppure_url(registro, kw):
    with pytest.raises(ValueError):
        core.source_replace("nb", "vecchia", **kw)


def test_una_fonte_che_non_c_e(registro):
    with pytest.raises(core.NLMError):
        core.source_replace("nb", "inesistente", text="x")


def test_lo_stato_drive_usa_list_drive_e_tiene_solo_le_fonti_drive(monkeypatch):
    visti: list = []

    def finto(args, **k):
        visti.append(args)
        return [{"id": "d1", "title": "Doc", "type": "google_doc", "is_fresh": False},
                {"id": "d2", "title": "Foglio", "type": "google_sheet", "is_fresh": True},
                {"id": "p1", "title": "pdf caricato", "type": "pdf", "is_fresh": None}]

    monkeypatch.setattr(core, "_run_json", finto)
    out = core.source_drive_stato("nb")
    assert visti == [["source", "list", "nb", "--drive"]]
    assert [(f["source_id"], f["indietro"]) for f in out] == [("d1", True), ("d2", False)]


def test_il_sync_passa_gli_id_e_legge_il_conto(monkeypatch):
    visti: list = []

    def finto(args, **k):
        visti.append(args)
        return SimpleNamespace(stdout="✓ Synced 2 source(s)\n", stderr="", returncode=0)

    monkeypatch.setattr(core, "_run", finto)
    out = core.source_sync_drive("nb", ["d1", " d2 ", ""])
    assert visti == [["source", "sync", "nb", "--source-ids", "d1,d2", "--confirm"]]
    assert out == {"chieste": 2, "sincronizzate": 2, "source_ids": ["d1", "d2"]}
    assert core.source_sync_drive("nb", []) == {"chieste": 0, "sincronizzate": 0}


# ── i tool: due tempi per la sostituzione, il default «tutte le indietro» per il sync ──

def _chiama(fn, *a, **kw):
    return asyncio.run(fn(*a, **kw))


@pytest.fixture
def senza_auth(monkeypatch):
    monkeypatch.setattr(server, "_check_auth_or_raise", lambda: None)


def test_la_sostituzione_vuole_il_gettone(registro, senza_auth):
    primo = _chiama(server.source_replace, "nb", "vecchia", text="nuovo")
    assert primo["anteprima"]["title"] == "Appunti" and primo["conferma"]
    assert registro == [], "senza gettone non si tocca niente"
    secondo = _chiama(server.source_replace, "nb", "vecchia", text="nuovo",
                      conferma=primo["conferma"], attesa_max=5)
    assert secondo["source_id"] == "nuova" and secondo["id_cambiato"] is True
    assert registro[-1] == ("via", "vecchia")


def test_un_gettone_di_un_altra_fonte_non_vale(registro, senza_auth):
    primo = _chiama(server.source_replace, "nb", "vecchia", text="nuovo")
    with pytest.raises(ValueError):
        _chiama(server.source_replace, "nb", "altra", text="nuovo", conferma=primo["conferma"])


def test_il_sync_senza_id_prende_quelle_indietro(monkeypatch, senza_auth):
    monkeypatch.setattr(core, "source_drive_stato", lambda nb: [
        {"source_id": "d1", "indietro": True}, {"source_id": "d2", "indietro": False}])
    chiesti: list = []
    monkeypatch.setattr(core, "source_sync_drive",
                        lambda nb, ids: chiesti.append(ids) or {"chieste": len(ids),
                                                                "sincronizzate": len(ids)})
    out = _chiama(server.source_sync_drive, "nb", attesa_max=5)
    assert chiesti == [["d1"]] and out["sincronizzate"] == 1


def test_il_sync_senza_niente_da_fare_non_chiama_nlm(monkeypatch, senza_auth):
    monkeypatch.setattr(core, "source_drive_stato", lambda nb: [{"source_id": "d2",
                                                                 "indietro": False}])
    monkeypatch.setattr(core, "source_sync_drive", lambda *a: pytest.fail("non doveva"))
    assert _chiama(server.source_sync_drive, "nb")["chieste"] == 0
