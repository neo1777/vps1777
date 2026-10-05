"""La quota di Gemini Notebook (05/10/2026): `usage_get` e il campo `quota` di `doctor`.

Quando nb1777 smette di rispondere le cause più comuni sono due, e si curano in modo
opposto: la sessione Google scaduta (si ricarica il profilo) e la quota esaurita (si
aspetta l'azzeramento). `nlm usage` le distingue già nella 0.12; qui diventa un tool, e
`doctor` lo porta con sé senza fallire se la quota non si legge.
"""
from __future__ import annotations

import asyncio
import json
import subprocess

from app import core, server

_USO = {"windows": [{"window": "rolling", "percent_used": 12.5, "percent_remaining": 87.5,
                     "resets_at": "2026-10-05T23:00:00+00:00"}], "tier": "pro"}


def test_usage_get_chiama_nlm_usage_in_json(monkeypatch):
    visti = []

    def finto_run(args, **kw):
        visti.append(args)
        return subprocess.CompletedProcess(args, 0, json.dumps(_USO), "")

    monkeypatch.setattr(core, "_run", finto_run)
    assert core.usage_get() == _USO
    assert visti == [["usage", "--json"]]


def test_doctor_porta_la_quota_e_non_cade_se_manca(monkeypatch):
    monkeypatch.setattr(core, "doctor", lambda: {"version": "nlm 0.12.0"})
    monkeypatch.setattr(core, "usage_get", lambda: _USO)
    assert asyncio.run(server.doctor())["quota"] == _USO

    def rotto():
        raise core.NLMError("usage non disponibile")

    monkeypatch.setattr(core, "usage_get", rotto)
    d = asyncio.run(server.doctor())
    assert d["version"] == "nlm 0.12.0" and "usage non disponibile" in d["quota"]["errore"]
