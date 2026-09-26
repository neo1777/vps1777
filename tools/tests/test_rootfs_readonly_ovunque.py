"""Ogni servizio di `compose.yaml` gira col rootfs in sola lettura (`*readonly`).

Fino al 27/09/2026 nb1777-mcp era l'eccezione (`H43`, rinvio della postilla di
SECURITY.md): il servizio con Chromium restava scrivibile «finché non verifichiamo un
giro NotebookLM reale con le tmpfs». Misurato sulla VPS alla 0.57.1: dopo un giro vero
(`doctor`, 142 notebook letti) `docker diff` mostra solo `/run/secrets` e
`/usr/sbin/docker-init`, cioè niente scritto dal processo fuori dai volumi; nlm tiene
tutto sotto `$HOME=/var/lib/nlm` (volume), il server non lancia Chromium. L'unica
scrittura fuori dai volumi era dall'host: `archive-ingest` faceva `docker cp` in /tmp,
che con il rootfs read-only rifiuta — curato nello stesso cambio (exec + stdin nel
volume degli artefatti, vedi test_ingest_testuale_diretto.py).

Senza eccezioni, così una nuova ha bisogno di una riga qui con la sua ragione.
Solo stdlib (la CI lancia `uvx pytest` senza PyYAML): i blocchi si leggono dal testo.
"""
from __future__ import annotations

import re
from pathlib import Path

COMPOSE = Path(__file__).resolve().parents[2] / "compose.yaml"

# servizio → ragione. Vuoto di proposito.
ECCEZIONI: dict[str, str] = {}


def _servizi() -> dict[str, str]:
    testo = COMPOSE.read_text()
    corpo = testo[testo.index("\nservices:\n"):]
    # la prossima chiave di primo livello (i commenti in colonna 0 non chiudono)
    fine = re.search(r"^[a-z]", corpo[len("\nservices:\n"):], re.M)
    if fine:
        corpo = corpo[: len("\nservices:\n") + fine.start()]
    blocchi = re.split(r"^  ([a-z0-9][a-z0-9-]*):\s*$", corpo, flags=re.M)
    return {blocchi[i]: blocchi[i + 1] for i in range(1, len(blocchi), 2)}


def test_la_lettura_trova_i_servizi():
    assert {"gateway", "archive-mcp", "nb1777-mcp", "nb1777-bot", "ocr"} <= set(_servizi())


def test_ogni_servizio_ha_il_rootfs_read_only():
    senza = [nome for nome, blocco in _servizi().items()
             if nome not in ECCEZIONI
             and not re.search(r"^    <<:\s*\[[^\]]*\*readonly", blocco, re.M)
             and not re.search(r"^    read_only:\s*true", blocco, re.M)]
    assert not senza, (f"servizi senza rootfs read-only: {senza}. Aggiungi *readonly, "
                       f"o un'eccezione in ECCEZIONI con la ragione misurata.")
