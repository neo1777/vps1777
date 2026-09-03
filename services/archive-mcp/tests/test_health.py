"""/health — la sonda del compose prova il MESTIERE, non la porta (vaglio 03/09).

Prima il healthcheck apriva un socket TCP: porta aperta + app rotta = «healthy»,
e su quel verde si appoggia il HEALTH-GATE dell'updater. Questi test misurano i
due versi: sano quando il registry risponde, 503 quando QUALUNQUE pezzo del
mestiere si rompe."""
from __future__ import annotations

import asyncio
import json

import pytest

# Lo step CI «stdlib-only» (uvx pytest) non ha l'SDK mcp: lì questo file SALTA
# dichiarandolo, e gira nello step «Test archive-mcp /health (deps del lock)»
# che sincronizza le dipendenze vere. Uno skip senza quel secondo step sarebbe
# un presidio che non gira mai.
pytest.importorskip("mcp", reason="serve l'SDK mcp: gira nello step con uv sync")

from app import db, server  # noqa: E402 — dopo l'importorskip, di proposito


def _chiama():
    resp = asyncio.run(server.health(None))
    return resp.status_code, json.loads(resp.body)


def test_health_ok_porta_dbs_e_revisione_mcp(monkeypatch):
    monkeypatch.setattr(db, "available_dbs", lambda: ["a", "b", "c"])
    status, body = _chiama()
    assert status == 200 and body["status"] == "ok" and body["dbs"] == 3
    # la revisione dev'essere OSSERVABILE («quale revisione parla il tuo
    # gateway?» non può avere come risposta una deduzione dal lockfile)
    assert body["mcp_protocol_max"], body
    assert body["mcp_sdk"], body


def test_health_guasto_del_registry_e_503_non_verde(monkeypatch):
    def _boom():
        raise RuntimeError("volume dati illeggibile")
    monkeypatch.setattr(db, "available_dbs", _boom)
    status, body = _chiama()
    assert status == 503 and body["status"] == "error"
    assert "illeggibile" in body["reason"]
