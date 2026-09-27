"""`limit` ha un pavimento e un tetto (rimando s3-2026-07-12-clamp-limit-archive, aperto
dal 12/07, rilievo F0-C3 del 27/09).

Con `limit=-1` la ricerca faceva `collected[:-1]` e perdeva IN SILENZIO l'ultimo
risultato; con `limit=0` restituiva niente senza dire perché; con un numero enorme
chiedeva a SQLite e al connettore una risposta senza misura. Ora sotto 1 è un errore che
parla, sopra il tetto si taglia al tetto.
"""
from __future__ import annotations

import pytest

from test_campi_testo import db  # noqa: F401  (la fixture: un DB con testo e azioni)


@pytest.mark.parametrize("limite", [0, -1, -50])
def test_limit_sotto_1_e_un_errore_che_parla(db, limite) -> None:  # noqa: F811
    with pytest.raises(ValueError, match="limit"):
        db.search("prova", limit=limite)


def test_limit_oltre_il_tetto_si_taglia(db) -> None:  # noqa: F811
    assert db._limite(10_000) == db.LIMITE_MASSIMO
    assert db._limite(7) == 7
