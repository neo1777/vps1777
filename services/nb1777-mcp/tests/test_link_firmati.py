"""P15 (10/10/2026): un link firmato per scaricare un artefatto da claude.ai.

Prima `studio_download` diceva «scaricalo dal pannello»: chi chiamava da claude.ai (o dal
telefono) doveva entrare in /admin con la password. Ora ritorna anche un link valido 30
minuti, riusabile, verso la rotta pubblica del gateway `/scarica/<nome>?t=<gettone>`.

La chiave sta SOLO qui (nata col processo, come il gettone di conferma): il gateway non la
conosce e passa nome e gettone a `/internal/nlm/link`, che verifica la firma PRIMA di
guardare se il file esiste. Un gateway_secret trapelato non basta a forgiare un link.
"""
from __future__ import annotations

import asyncio

import pytest
from starlette.requests import Request

from app import core, link_firmati, server


def test_il_gettone_vale_per_il_suo_nome_e_scade():
    t = link_firmati.gettone("audio.m4a", ora=1000)
    assert link_firmati.verifica(t, "audio.m4a", ora=1000) is None
    assert link_firmati.verifica(t, "audio.m4a", ora=1000 + link_firmati.DURATA_S - 1) is None
    assert "scaduto" in link_firmati.verifica(t, "audio.m4a", ora=1000 + link_firmati.DURATA_S + 1)
    assert "non vale" in link_firmati.verifica(t, "altro.m4a", ora=1000)
    assert "non vale" in link_firmati.verifica("rotto", "audio.m4a", ora=1000)
    scade, firma = t.split(".", 1)
    forgiato = f"{int(scade) + 86400}.{firma}"
    assert "non vale" in link_firmati.verifica(forgiato, "audio.m4a", ora=1000), \
        "allungare la scadenza senza la chiave non deve funzionare"


def test_la_durata_e_trenta_minuti():
    assert link_firmati.DURATA_S == 30 * 60


def test_il_link_con_la_base_pubblica_e_senza(monkeypatch):
    monkeypatch.setattr(link_firmati, "_base", lambda: "https://vps.example.invalid/")
    link = link_firmati.link("podcast prova.m4a", ora=1000)
    assert link["url"].startswith("https://vps.example.invalid/scarica/podcast%20prova.m4a?t=")
    assert link["scade_il"] == "1970-01-01T00:46:40Z"
    monkeypatch.setattr(link_firmati, "_base", lambda: "")
    assert link_firmati.link("a.m4a", ora=1000)["url"].startswith("/scarica/a.m4a?t=")


def _richiesta(nome: str, t: str) -> Request:
    from urllib.parse import urlencode
    return Request({"type": "http", "method": "GET", "path": "/internal/nlm/link",
                    "headers": [], "query_string": urlencode({"name": nome, "t": t}).encode()})


@pytest.fixture
def artefatto(monkeypatch, tmp_path):
    monkeypatch.setenv("NLM_ARTIFACTS", str(tmp_path))
    (tmp_path / "audio.m4a").write_bytes(b"\x00" * 32)
    monkeypatch.setattr(server, "_internal_ok", lambda request: True)
    return tmp_path


def test_l_endpoint_interno_serve_solo_con_un_gettone_valido(artefatto):
    buono = asyncio.run(server.internal_nlm_link(_richiesta("audio.m4a", link_firmati.gettone("audio.m4a"))))
    assert buono.status_code == 200
    cattivo = asyncio.run(server.internal_nlm_link(_richiesta("audio.m4a", "1.abc")))
    assert cattivo.status_code == 403


def test_senza_gettone_valido_non_dice_se_il_file_esiste(artefatto):
    """Il gettone si verifica PRIMA del file: un nome inventato e uno vero danno la stessa
    risposta, o l'endpoint diventa un oracolo su cosa c'è nel container."""
    vero = asyncio.run(server.internal_nlm_link(_richiesta("audio.m4a", "1.abc")))
    finto = asyncio.run(server.internal_nlm_link(_richiesta("inventato.m4a", "1.abc")))
    assert vero.status_code == finto.status_code == 403
    assert vero.body == finto.body


def test_gettone_valido_su_un_file_sparito(artefatto):
    r = asyncio.run(server.internal_nlm_link(_richiesta("sparito.m4a", link_firmati.gettone("sparito.m4a"))))
    assert r.status_code == 404


def test_senza_segreto_interno_niente(monkeypatch, artefatto):
    monkeypatch.setattr(server, "_internal_ok", lambda request: False)
    r = asyncio.run(server.internal_nlm_link(_richiesta("audio.m4a", link_firmati.gettone("audio.m4a"))))
    assert r.status_code == 403


def test_studio_download_porta_il_link(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "_check_auth_or_raise", lambda: None)
    f = tmp_path / "pod.m4a"
    f.write_bytes(b"\x00" * 10)
    monkeypatch.setattr(core, "studio_download", lambda *a, **k: f)
    monkeypatch.setattr(link_firmati, "_base", lambda: "https://vps.example.invalid")
    out = asyncio.run(server.studio_download("audio", "nb-1", "pod.m4a"))
    assert out["download_url"] == "/admin/nlm/artifact/pod.m4a"
    assert out["link"]["url"].startswith("https://vps.example.invalid/scarica/pod.m4a?t=")
    assert out["link"]["scade_il"]
