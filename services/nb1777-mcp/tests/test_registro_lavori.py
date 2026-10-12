"""P6 (10/10/2026): il registro dei lavori lunghi di nb1777.

`source_add_*` con attesa, `studio_download` e `studio_create_all_9` possono durare minuti, e
da claude.ai una chiamata cade verso i 30 s («MCP tool call failed»): il lavoro andava avanti
sul server, ma chi chiamava perdeva il risultato. Come `notebook_query` dalla 0.72: si aspetta
al massimo `attesa_max`, poi {stato: "in_corso", job_id}; si ritira con `lavoro_esito` o
rilanciando la stessa chiamata, che si aggancia. Al più 3 lavori insieme, e uno alla volta
per notebook: `source_add_*` ricava l'id della fonte nuova per differenza fra due liste, e
due aggiunte parallele sullo stesso notebook potrebbero scambiarsi gli id.
"""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from app import core, lavori, server


@pytest.fixture(autouse=True)
def registro_pulito(monkeypatch):
    monkeypatch.setattr(lavori, "_LAVORI", {})
    monkeypatch.setattr(lavori, "_PER_CHIAVE", {})
    monkeypatch.setattr(lavori, "_LOCK_NB", {})
    monkeypatch.setattr(lavori, "_posti", None)
    monkeypatch.setattr(server, "_check_auth_or_raise", lambda: None)


def test_un_lavoro_breve_torna_subito_il_risultato():
    async def go():
        jid = lavori.avvia("prova", ("k",), "nb", lambda: "fatto")
        return await lavori.aspetta(jid, 5)
    assert asyncio.run(go()) == "fatto"
    assert lavori._LAVORI == {} and lavori._PER_CHIAVE == {}, "ritirato, si dimentica"


def test_un_lavoro_lungo_torna_in_corso_e_si_ritira_dopo():
    via = threading.Event()

    def lento():
        via.wait(5)
        return "fine"

    async def go():
        jid = lavori.avvia("lento", ("k",), "nb", lento)
        primo = await lavori.aspetta(jid, 1)
        assert primo["stato"] == "in_corso" and primo["job_id"] == jid
        assert "lavoro_esito" in primo["nota"]
        assert lavori.avvia("lento", ("k",), "nb", lento) == jid, "la stessa chiamata si aggancia"
        via.set()
        return await lavori.aspetta(jid, 5)
    assert asyncio.run(go()) == "fine"


def test_un_errore_arriva_a_chi_ritira_e_il_lavoro_si_dimentica():
    def rotto():
        raise core.NLMError("nlm exit 1: boom")

    async def go():
        jid = lavori.avvia("rotto", ("k",), "nb", rotto)
        with pytest.raises(core.NLMError):
            await lavori.aspetta(jid, 5)
        return jid
    jid = asyncio.run(go())
    assert jid not in lavori._LAVORI


def test_un_job_id_sconosciuto_lo_dice():
    with pytest.raises(ValueError) as e:
        asyncio.run(lavori.aspetta("inventato", 1))
    assert "rilancia" in str(e.value)


def test_uno_alla_volta_per_notebook_e_tre_in_tutto():
    attivi = {"nb": 0, "max_nb": 0, "tot": 0, "max_tot": 0}
    blocco = threading.Lock()

    def lavoro(nb):
        def f():
            with blocco:
                attivi["tot"] += 1
                attivi[nb] = attivi.get(nb, 0) + 1
                attivi["max_tot"] = max(attivi["max_tot"], attivi["tot"])
                if nb == "nb":
                    attivi["max_nb"] = max(attivi["max_nb"], attivi["nb"])
            time.sleep(0.15)
            with blocco:
                attivi["tot"] -= 1
                attivi[nb] -= 1
            return nb
        return f

    async def go():
        ids = [lavori.avvia("x", ("stesso", i), "nb", lavoro("nb")) for i in range(3)]
        ids += [lavori.avvia("x", ("altri", i), f"nb{i}", lavoro(f"nb{i}")) for i in range(5)]
        return [await lavori.aspetta(j, 10) for j in ids]
    asyncio.run(go())
    assert attivi["max_nb"] == 1, "due scritture sullo stesso notebook non vanno in parallelo"
    assert attivi["max_tot"] <= lavori.POSTI


def test_source_add_url_passa_dal_registro(monkeypatch):
    monkeypatch.setattr(core, "source_add_url", lambda nb, url, **k: "src-1")
    assert asyncio.run(server.source_add_url("nb", "https://example.invalid")) == {"source_id": "src-1"}


def test_source_add_url_lento_torna_in_corso_e_lavoro_esito_lo_ritira(monkeypatch):
    via = threading.Event()

    def lento(nb, url, **k):
        via.wait(5)
        return "src-2"
    monkeypatch.setattr(core, "source_add_url", lento)

    async def go():
        primo = await server.source_add_url("nb", "https://example.invalid", attesa_max=1)
        assert primo["stato"] == "in_corso"
        via.set()
        return await server.lavoro_esito(primo["job_id"], attesa_max=5)
    assert asyncio.run(go()) == {"source_id": "src-2"}   # anche dopo il ritiro, un oggetto


def test_studio_download_passa_dal_registro_e_porta_il_link(monkeypatch, tmp_path):
    f = tmp_path / "pod.m4a"
    f.write_bytes(b"\x00" * 10)
    monkeypatch.setattr(core, "studio_download", lambda *a, **k: f)
    out = asyncio.run(server.studio_download("audio", "nb", "pod.m4a"))
    assert out["name"] == "pod.m4a" and out["bytes"] == 10 and "link" in out


def test_il_caricamento_monouso_rispetta_il_lucchetto_del_notebook():
    """Il caricamento monouso aggiunge una fonte come source_add_file: stesso lucchetto."""
    async def go():
        lock = lavori.lucchetto("nb-1")
        async with lock:
            assert lavori.lucchetto("nb-1") is lock
    asyncio.run(go())
