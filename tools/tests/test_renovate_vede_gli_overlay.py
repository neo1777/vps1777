"""Renovate vede ogni compose con immagini di terzi (01/10/2026).

Dependabot non li vedeva: la sua regex ammette un solo segmento dopo «compose.» e i nostri
overlay sono compose.ingress.*.yaml e compose.ops.*.yaml. Caddy è rimasto a 2.8 e
cloudflared a una versione che non leggeva il token. Questo test tiene la copertura
FALSIFICABILE: un overlay nuovo con un'immagine di terzi che il pattern di Renovate non
prende fa diventare rossa la CI, invece di invecchiare in silenzio.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]
CONF = json.loads((RADICE / ".github" / "renovate.json").read_text(encoding="utf-8"))


def _pattern() -> re.Pattern[str]:
    (p,) = CONF["docker-compose"]["managerFilePatterns"]
    assert p.startswith("/") and p.endswith("/"), "pattern Renovate in forma /regex/"
    return re.compile(p[1:-1])


def _immagini_di_terzi(f: Path) -> list[str]:
    return [m.group(1) for m in re.finditer(r"^\s*image:\s*(\S+)", f.read_text(), re.M)
            # né le nostre (variabili) né quelle di build locale (vps1777/*:dev)
            if "${" not in m.group(1) and not m.group(1).startswith("vps1777/")]


def test_ogni_compose_con_immagini_di_terzi_e_coperto() -> None:
    pat = _pattern()
    scoperti = [f.name for f in sorted(RADICE.glob("compose*.y*ml"))
                if _immagini_di_terzi(f) and not pat.search(f.name)]
    assert not scoperti, f"Renovate non vede {scoperti}: allarga managerFilePatterns"
    coperti = [f.name for f in RADICE.glob("compose*.y*ml") if pat.search(f.name)]
    assert len(coperti) >= 4, coperti


def test_renovate_fa_solo_quello() -> None:
    assert CONF["enabledManagers"] == ["docker-compose"], "il resto è di Dependabot"
    nostre = [r for r in CONF["packageRules"] if "ghcr.io/neo1777/**" in r.get("matchPackageNames", [])]
    assert nostre and nostre[0]["enabled"] is False, "le immagini vps1777-* le versiona il rilascio"
    assert CONF["pinDigests"] is True


def test_dependabot_non_dichiara_piu_il_compose_che_non_vedeva() -> None:
    testo = (RADICE / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    assert "package-ecosystem: docker-compose" not in testo
