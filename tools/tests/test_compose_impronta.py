"""Il plugin docker-compose si installa solo se l'impronta combacia (giro di revisione del 21/11/2026).

I due installer lo scaricano da GitHub e lo installano da root: senza impronta ci si fidava del
trasporto, la stessa classe di H80 (cosign). Qui si tiene che: le impronte ci sono per le due
architetture, sono le STESSE nei due installer, e l'installazione viene dopo la verifica.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = (ROOT / "deploy.sh").read_text(encoding="utf-8")
ENGINE = (ROOT / "installer" / "engine.py").read_text(encoding="utf-8")


def _impronte_deploy() -> dict[str, str]:
    return {a.lower(): h for a, h in re.findall(r'^COMPOSE_SHA256_(X86_64|AARCH64)="([0-9a-f]{64})"', DEPLOY, re.M)}


def _impronte_engine() -> dict[str, str]:
    return dict(re.findall(r'"(x86_64|aarch64)":\s*"([0-9a-f]{64})"', ENGINE))


def test_le_impronte_ci_sono_e_sono_le_stesse_nei_due_installer() -> None:
    d, e = _impronte_deploy(), _impronte_engine()
    assert set(d) == set(e) == {"x86_64", "aarch64"}
    assert d == e, "deploy.sh e installer/engine.py dichiarano impronte diverse"
    assert re.search(r'^COMPOSE_VERSION="(v[\d.]+)"', DEPLOY, re.M).group(1) == \
        re.search(r'^COMPOSE_VERSION = "(v[\d.]+)"', ENGINE, re.M).group(1)


def test_si_installa_solo_dopo_la_verifica() -> None:
    for nome, testo in (("deploy.sh", DEPLOY), ("installer/engine.py", ENGINE)):
        i = testo.index("compose/releases/download/")
        blocco = testo[i:i + 900]
        assert "sha256sum -c" in blocco, f"{nome}: il binario non viene verificato"
        assert blocco.index("sha256sum -c") < blocco.index("install -m 0755"), \
            f"{nome}: l'installazione precede la verifica"
        assert "-o /usr/local/lib/docker/cli-plugins/docker-compose" not in testo, \
            f"{nome}: il download scrive ancora direttamente nella cartella dei plugin"


def test_un_architettura_senza_impronta_non_ripiega_su_x86() -> None:
    assert "*)             CARCH=x86_64" not in DEPLOY and "*) A=x86_64" not in ENGINE
