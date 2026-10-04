"""Un init solo per container (04/10/2026).

Fino alla 0.69.0 ogni servizio di base aveva due init: `init: true` nel compose mette
docker-init come PID 1, e l'ENTRYPOINT dell'immagine lancia tini come suo figlio. Il
tini figlio lo diceva a ogni avvio («Tini is not running as PID 1 and isn't registered
as a child subreaper»): un avviso inutile nel log, e un processo in più per niente.

La regola: se l'immagine parte già da tini, il compose non aggiunge l'init; se il
servizio sovrascrive l'entrypoint (indice-notturno), tini non c'è più e l'init serve.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

RADICE = Path(__file__).resolve().parents[2]


def _entrypoint_con_tini(servizio: str) -> bool:
    dockerfile = RADICE / "services" / servizio / "Dockerfile"
    righe = re.findall(r"^ENTRYPOINT\s+(\[.*\])\s*$", dockerfile.read_text(encoding="utf-8"), re.M)
    assert righe, f"{dockerfile}: nessun ENTRYPOINT in forma JSON — il parser del test è rotto"
    return json.loads(righe[-1])[0] == "tini"


def test_nessun_servizio_ha_due_init_e_nessuno_resta_senza() -> None:
    d = yaml.safe_load((RADICE / "compose.yaml").read_text(encoding="utf-8"))
    visti = 0
    for nome, s in d["services"].items():
        m = re.search(r"/vps1777-([a-z0-9-]+):", s.get("image", ""))
        if not m:
            continue
        visti += 1
        tini = "entrypoint" not in s and _entrypoint_con_tini(m.group(1))
        if tini:
            assert not s.get("init"), f"{nome}: tini è già PID 1 nell'immagine, `init: true` ne mette un secondo"
        else:
            assert s.get("init") is True, f"{nome}: entrypoint senza tini e niente `init: true` — nessuno raccoglie gli zombie"
    assert visti >= 6, "meno di 6 servizi riconosciuti: il parser del test è rotto, non il compose"
