"""Ogni container che un overlay AGGIUNGE ha un tetto ai log (giro di revisione del 21/11/2026).

L'ancora `x-logging` (10 MB × 5) vive in `compose.yaml` e le ancore YAML non attraversano i
file: Caddy, cloudflared, backup e Portainer partivano con `json-file` senza limite. Caddy
scrive una riga per richiesta: chi martella la 443 riempiva il disco, e con lui cadevano
backup e gateway. La doc diceva già «json-file con rotazione».
"""
from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
ROOT = Path(__file__).resolve().parents[2]
OVERLAY = sorted(p for p in ROOT.glob("compose.*.yaml")
                 if p.name not in ("compose.build.yaml", "compose.dev.yaml"))


def test_ci_sono_overlay_da_guardare() -> None:
    assert len(OVERLAY) >= 5, "non trovo gli overlay: un controllo su zero file non è un verde"


def test_i_servizi_nuovi_hanno_il_tetto() -> None:
    # per NOME di servizio, su tutti gli overlay: `compose.ops.caddy-dns01.yaml` ritocca il
    # `caddy` di `compose.ingress.caddy.yaml` (cambia l'immagine), e il tetto gli arriva da lì
    nuovi: dict[str, list[str]] = {}
    col_tetto: set[str] = set()
    for percorso in OVERLAY:
        servizi = (yaml.safe_load(percorso.read_text(encoding="utf-8")) or {}).get("services") or {}
        for nome, s in servizi.items():
            if "image" in s:
                nuovi.setdefault(nome, []).append(percorso.name)
            opzioni = (s.get("logging") or {}).get("options") or {}
            if opzioni.get("max-size") and opzioni.get("max-file"):
                col_tetto.add(nome)
    assert {"caddy", "cloudflared", "backup", "portainer"} <= set(nuovi), nuovi
    senza = {n: f for n, f in nuovi.items() if n not in col_tetto}
    assert not senza, f"servizi degli overlay senza `logging.options.max-size/max-file`: {senza}"
