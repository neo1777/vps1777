"""Giro di revisione del 21/11/2026 su nb1777-mcp: tre difetti piccoli che non devono tornare."""
from __future__ import annotations

import time

from app import conferma, core, link_firmati


def test_un_gettone_con_caratteri_non_ascii_e_un_no_non_un_errore():
    # `hmac.compare_digest` su stringhe solleva TypeError coi non ASCII: da Internet,
    # `/scarica/x.mp4?t=123.é` dava 500 col traceback nel log invece di «non vale»
    assert link_firmati.verifica("9999999999.é", "x.mp4") is not None
    assert conferma.verifica("9999999999.é", "note_delete", "id") is not None


def test_l_attesa_non_dorme_oltre_il_tetto(monkeypatch):
    monkeypatch.setattr(core, "studio_status", lambda nb, aid: {"status": "in_progress"})
    t0 = time.monotonic()
    esito = core.studio_wait("nb", "a1", poll_interval=30.0, timeout=0.3,
                             restituisci_al_tetto=True)
    assert time.monotonic() - t0 < 2.0, "ha dormito l'intervallo intero, oltre il tetto"
    assert esito["in_corso"] is True


def test_un_id_che_non_c_e_non_passa_per_in_corso_e_basta(monkeypatch):
    monkeypatch.setattr(core, "studio_status", lambda nb, aid: {})
    esito = core.studio_wait("nb", "non-esiste", poll_interval=0.01, timeout=0.05,
                             restituisci_al_tetto=True)
    assert esito["trovato"] is False and "studio_list" in esito["nota"]
