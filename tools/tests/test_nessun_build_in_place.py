"""«Nessun aggiornamento build-in-place» — la frase di SECURITY.md, provata.

Perché esiste (27/08/2026, lavoro a80025f1): la garanzia chiude il paragrafo
supply-chain — le immagini arrivano da GHCR verificate contro `images.lock`,
MAI ricostruite sulla macchina — e non aveva un'ancora. L'ancora è questa:
nessun compose che possa girare in ESERCIZIO porta una chiave `build:`. Se ne
comparisse una, `docker compose up` su quella macchina potrebbe COSTRUIRE
un'immagine locale invece di usare quella firmata — e il build-in-place
rientrerebbe da un overlay senza che nessuna review se ne accorga.

Il perimetro è DERIVATO (glob su compose*.yaml), non elencato a mano: un
overlay nuovo entra da solo nel controllo. Le eccezioni sono dichiarate una
per una CON la ragione — il metodo di ATTESI in tools/doc-riferimenti.py.
"""
from __future__ import annotations

import re
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]

# Compose che DICHIARATAMENTE non girano in esercizio, con la ragione:
ESCLUSI = {
    "compose.build.yaml": "è il file DELLA build: lo usa la CI per costruire le "
                          "immagini che poi firma — mai `up` su una macchina",
    "compose.dev.yaml": "ambiente di sviluppo locale, mai in esercizio",
}

# `build:` come CHIAVE yaml a inizio voce (con la sua indentazione), non la
# parola dentro un commento o un valore.
_BUILD = re.compile(r"^\s*build\s*:", re.M)


def _righe_build(testo: str) -> list[int]:
    return [testo[:m.start()].count("\n") + 1 for m in _BUILD.finditer(testo)]


def test_nessun_compose_di_esercizio_ha_build():
    visti = sorted(RADICE.glob("compose*.yaml"))
    assert visti, "nessun compose trovato: il perimetro del test è rotto"
    colpevoli = []
    for f in visti:
        if f.name in ESCLUSI:
            continue
        righe = _righe_build(f.read_text(encoding="utf-8"))
        if righe:
            colpevoli.append(f"{f.name}:{righe}")
    assert not colpevoli, (
        f"chiave `build:` in compose di ESERCIZIO: {colpevoli}\n"
        "  «Nessun aggiornamento build-in-place» (SECURITY.md) vale finché le\n"
        "  immagini arrivano SOLO da GHCR verificate contro images.lock. Se il\n"
        "  file è legittimamente di build/dev, dichiaralo in ESCLUSI con la ragione."
    )


def test_la_sonda_sa_dire_di_no():
    """Un controllo che non può fallire non misura, afferma."""
    assert _righe_build("services:\n  x:\n    build: .\n") == [3]
    assert _righe_build("# build: commentato\n  image: ghcr.io/x@sha256:aa\n") == []


def test_gli_esclusi_esistono_ancora():
    """Un'eccezione per un file sparito è una riga morta che assolve il nulla."""
    for nome in ESCLUSI:
        assert (RADICE / nome).is_file(), (
            f"{nome} è in ESCLUSI ma non esiste più: togli la riga o aggiorna il nome")
