"""Il client verso nb1777-mcp (`nlm_client`) davanti a un servizio che si guasta.

Stessa classe di `test_mcp_client_guasti.py` (scheda C11 del campione della prova B, 23/11/2026): le pagine
`/admin/nlm` e l'onboarding chiamano `status()`, `artifacts()` e `upload()`, che promettono `None` (o un
motivo) quando non sanno. Con un JSON valido della forma sbagliata la promessa saltava: `.get` su una lista
dava AttributeError, cioè un 500 sulla pagina di amministrazione. Il servizio qui è finto e si guasta a comando.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app import nlm_client

FORME_SBAGLIATE = [[1, 2], "ok", 7, None]


@pytest.fixture
def servizio(monkeypatch):
    stato: dict = {"fa": None, "viste": []}
    vero = httpx.AsyncClient

    def gestisci(req: httpx.Request) -> httpx.Response:
        stato["viste"].append(req)
        return stato["fa"](req)

    monkeypatch.setattr(nlm_client.httpx, "AsyncClient",
                        lambda **kw: vero(transport=httpx.MockTransport(gestisci), **kw))
    monkeypatch.setattr(nlm_client, "get_settings", lambda: SimpleNamespace(
        nlm_internal_base="http://nb1777-mcp:8000/", effective_gateway_secret="s" * 32))
    return stato


def _json(corpo, codice=200):
    return lambda req: httpx.Response(codice, json=corpo)


def _giu(req):
    raise httpx.ConnectError("rifiutata", request=req)


def _lento(req):
    raise httpx.ReadTimeout("scaduto", request=req)


def _testo(testo, codice=200):
    return lambda req: httpx.Response(codice, text=testo)


def test_status_buono_porta_il_segreto_interno(servizio):
    servizio["fa"] = _json({"ok": True, "has_cookies": True, "pending": False})
    assert asyncio.run(nlm_client.status())["ok"] is True
    [req] = servizio["viste"]
    assert str(req.url) == "http://nb1777-mcp:8000/internal/nlm/status"
    assert req.headers["x-vps1777-internal"] == "s" * 32


@pytest.mark.parametrize("guasto", [_giu, _lento, _json({}, 500), _json({}, 401), _testo("non json"), _testo("")]
                         + [_json(f) for f in FORME_SBAGLIATE])
def test_status_guasto_e_non_so(servizio, guasto):
    servizio["fa"] = guasto
    assert asyncio.run(nlm_client.status()) is None


def test_artifacts_buono(servizio):
    servizio["fa"] = _json({"artifacts": [{"name": "a.mp3", "bytes": 3, "mtime": 1}]})
    assert asyncio.run(nlm_client.artifacts()) == [{"name": "a.mp3", "bytes": 3, "mtime": 1}]


@pytest.mark.parametrize("guasto", [_giu, _lento, _json({}, 500), _testo("<html>")]
                         + [_json(f) for f in FORME_SBAGLIATE]
                         + [_json({"artifacts": "non una lista"}), _json({"artifacts": ["non un oggetto"]})])
def test_artifacts_guasto_e_non_so_mai_lista_vuota(servizio, guasto):
    """`None` e non `[]`: una lista vuota direbbe «non ne hai» quando il vero è «non lo so»."""
    servizio["fa"] = guasto
    assert asyncio.run(nlm_client.artifacts()) is None


def test_upload_buono(servizio):
    servizio["fa"] = _json({"files": 4})
    assert asyncio.run(nlm_client.upload(b"x")) == (4, None)


@pytest.mark.parametrize("guasto", [_giu, _lento, _testo("non json")] + [_json(f) for f in FORME_SBAGLIATE]
                         + [_json({"files": "tanti"}), _json({"files": None})])
def test_upload_guasto_da_un_motivo(servizio, guasto):
    servizio["fa"] = guasto
    n, motivo = asyncio.run(nlm_client.upload(b"x"))
    assert n is None and isinstance(motivo, str) and motivo


@pytest.mark.parametrize("risposta", [_json({"reason": "tar non valido"}, 400), _testo("boom", 500)]
                         + [_json(f, 400) for f in FORME_SBAGLIATE])
def test_upload_rifiutato_da_un_motivo(servizio, risposta):
    servizio["fa"] = risposta
    n, motivo = asyncio.run(nlm_client.upload(b"x"))
    assert n is None and isinstance(motivo, str)
