"""Parte 2 (12/10/2026): un lavoro che aspetta il lucchetto dell'archivio lo dice, e non
manda a guardare la path unit come se nessuno l'avesse preso. Deps del lock (admin vero)."""
from __future__ import annotations

from app import admin


def _riga(**k):
    return {"id": "20261012T190000Z-0123abcd", "file": "export.zip", "db": "prova",
            "stato": "in-coda", "accodato": "2026-10-12T19:00:00Z", **k}


def test_in_attesa_dice_chi_tiene_l_archivio():
    s = admin._sezione_caricamenti([_riga(attesa="indice-notturno <b>")])
    assert "aspetta il suo turno: indice-notturno &lt;b&gt; sta lavorando" in s
    assert "nessuno l'ha preso" not in s


def test_fermo_senza_attesa_manda_alla_unit():
    s = admin._sezione_caricamenti([_riga(fermo=True)])
    assert "nessuno l'ha preso" in s and "vps1777-ingest.path" in s
