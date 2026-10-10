"""P13 (11/10/2026): la cella «per senso» di /admin/archive. Deps del lock (admin vero)."""
from __future__ import annotations

from app import admin


def test_da_aggiornare_mostra_numeri_e_comando():
    c = admin._cella_indice({"stato": "da_aggiornare", "messaggi": 266219, "dopo": 1234,
                             "generato": "2026-10-06T01:46:51Z",
                             "cura": "vps1777 indice-notturno --db recupero-20260924"})
    assert "<strong>da aggiornare</strong>" in c and "266219 indicizzati" in c
    assert "1234 righe arrivate dopo" in c and "costruito il 2026-10-06" in c
    assert "indice-notturno --db recupero-20260924" in c


def test_assente_e_l_html_non_passa():
    c = admin._cella_indice({"stato": "assente", "cura": "<script>x</script>"})
    assert "nessun indice" in c and "<script>" not in c and "&lt;script&gt;" in c
