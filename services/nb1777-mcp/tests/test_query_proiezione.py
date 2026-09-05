"""notebook_query — proiezione compatta e il non-citato che si vede (#275).

Il caso vivo (05/09/2026): una risposta da 78k char (quasi tutta `cited_text`
di catalogo) e, in un'altra, una sezione «di ricerca» con dati di enti mai
presenti nelle fonti — generazione del modello servita nello stesso piatto del
contenuto citato. La cura è in `core._proietta_query`, pura: si testa qui,
senza nlm né rete.
"""
from __future__ import annotations

from app import core

_RISPOSTA = {
    "answer": ("Il progetto usa un ledger verificato in CI [1, 2].\n\n"
               "Secondo studi recenti il 90% dei team fallisce qui.\n\n"
               "Il gate fallisce se l'evidenza sparisce [3]."),
    "conversation_id": "conv-1",
    "sources_used": ["s1", "s1", "s2", "s1"],
    "references": [
        {"source_id": "s1", "citation_number": 1, "cited_text": "x" * 500},
        {"source_id": "s2", "citation_number": 2, "cited_text": "y" * 500},
        {"source_id": "s1", "citation_number": 3, "cited_text": "z" * 500},
    ],
}


def test_compatta_di_default_e_piena_con_verbose() -> None:
    compatta = core._proietta_query(dict(_RISPOSTA), verbose=False)
    for ref in compatta["references"]:
        assert "cited_text" not in ref and len(ref["anteprima"]) <= 160
    piena = core._proietta_query(dict(_RISPOSTA), verbose=True)
    assert piena["references"][0]["cited_text"] == "x" * 500


def test_sources_used_deduplicate_in_ordine() -> None:
    out = core._proietta_query(dict(_RISPOSTA), verbose=False)
    assert out["sources_used"] == ["s1", "s2"]


def test_il_paragrafo_senza_marcatori_viene_dichiarato() -> None:
    out = core._proietta_query(dict(_RISPOSTA), verbose=False)
    sc = out["senza_citazioni"]
    assert sc["paragrafi"] == 1 and sc["su_totale"] == 3
    assert sc["anteprime"][0].startswith("Secondo studi recenti")
    assert "ipotesi" in out["nota"]
    # l'answer NON viene toccata: si dichiara, non si amputa
    assert out["answer"] == _RISPOSTA["answer"]


def test_risposta_tutta_citata_non_porta_la_nota() -> None:
    tutta = dict(_RISPOSTA)
    tutta["answer"] = "Solo cose lette [1].\n\nAnche queste [2, 3]."
    out = core._proietta_query(tutta, verbose=False)
    assert "senza_citazioni" not in out and "nota" not in out
