"""P12 (11/10/2026): il bot dice gli errori veri, formatta la risposta e sceglie il notebook a bottoni.

Fino alla 0.80 un errore del tool (JSON-RPC `error`, o `isError` con il messaggio nel testo)
arrivava a Neo come «Risposta vuota.»: il bot leggeva `result.content` e, non trovandolo,
diceva che NotebookLM non aveva risposto. E `/chiedi` stampava il JSON grezzo di
notebook_query, fonti comprese, tagliato a 4000 caratteri.

Qui le funzioni pure (stdlib) di `app/formato.py`; i comandi stanno in test_comandi.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import formato  # noqa: E402

NB = "0f6c2a8e-1b2c-4d5e-8f90-123456789abc"


def _rpc_ok(*testi: str) -> dict:
    return {"jsonrpc": "2.0", "id": 1,
            "result": {"content": [{"type": "text", "text": t} for t in testi]}}


# ── la risposta MCP ─────────────────────────────────────────────────────────────

def test_payload_da_sse_e_da_json():
    sse = "event: message\ndata: " + json.dumps(_rpc_ok("ciao")) + "\n\n"
    assert formato.payload_rpc("text/event-stream", sse)["result"]["content"][0]["text"] == "ciao"
    assert formato.payload_rpc("application/json", json.dumps(_rpc_ok("x")))["id"] == 1


def test_payload_illeggibile_e_un_errore_che_si_legge():
    with pytest.raises(formato.ErroreMCP, match="senza payload"):
        formato.payload_rpc("text/event-stream", "event: ping\n\n")
    with pytest.raises(formato.ErroreMCP, match="non è JSON"):
        formato.payload_rpc("application/json", "<html>502</html>")


def test_errore_json_rpc_non_diventa_risposta_vuota():
    rpc = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "notebook_id mancante"}}
    with pytest.raises(formato.ErroreMCP, match="notebook_id mancante"):
        formato.testi(rpc)


def test_tool_fallito_dice_il_suo_messaggio():
    rpc = {"jsonrpc": "2.0", "id": 1, "result": {
        "isError": True, "content": [{"type": "text", "text": "Auth NotebookLM scaduta"}]}}
    with pytest.raises(formato.ErroreMCP, match="Auth NotebookLM scaduta"):
        formato.testi(rpc)


def test_testi_del_risultato():
    assert formato.testi(_rpc_ok("a", "b")) == ["a", "b"]


# ── i notebook e la tastiera ───────────────────────────────────────────────────

def test_notebook_da_un_blocco_per_notebook_o_da_un_array():
    uno = [json.dumps({"id": NB, "title": "Libro"}), json.dumps({"id": "x", "title": "Altro"})]
    array = [json.dumps([{"id": NB, "title": "Libro"}])]
    assert [n["id"] for n in formato.notebook(uno)] == [NB, "x"]
    assert formato.notebook(array) == [{"id": NB, "title": "Libro"}]
    assert formato.notebook(["non json"]) == []


def test_tastiera_una_riga_per_notebook_e_le_pagine():
    nbs = [{"id": f"id-{i}", "title": f"Notebook {i}"} for i in range(20)]
    righe = formato.tastiera(nbs, pagina=0)
    assert righe[0] == [("Notebook 0", "nb:id-0")]
    assert len([r for r in righe if r[0][1].startswith("nb:")]) == formato.PER_PAGINA
    assert righe[-1] == [("altri ›", "nbp:1")]
    ultima = formato.tastiera(nbs, pagina=2)
    assert ultima[-1] == [("‹ indietro", "nbp:1")]
    assert ultima[0] == [("Notebook 16", "nb:id-16")]


def test_tastiera_titoli_lunghi_e_vuoti():
    righe = formato.tastiera([{"id": "a", "title": "x" * 200}, {"id": "b", "title": ""}])
    assert len(righe[0][0][0]) <= formato.TITOLO_MAX and righe[0][0][0].endswith("…")
    assert righe[1][0][0] == "(senza titolo)"


def test_callback_data_sta_nei_64_byte_di_telegram():
    (riga,) = formato.tastiera([{"id": NB, "title": "t"}])
    assert len(riga[0][1].encode()) <= 64


def test_riconosce_un_id_di_notebook():
    assert formato.e_id_notebook(NB) and formato.e_id_notebook(NB.upper())
    assert not formato.e_id_notebook("come") and not formato.e_id_notebook(NB[:-1])


# ── la risposta formattata ─────────────────────────────────────────────────────

_PAYLOAD = {
    "answer": "Il capitolo parla di **mixin** [1] e di <componenti> [2][3].",
    "references": [
        {"citation_number": 1, "source_id": "s1", "anteprima": "…"},
        {"citation_number": 2, "source_id": "s2", "anteprima": "…"},
        {"citation_number": 3, "source_id": "s1", "anteprima": "…"},
    ],
}


def test_risposta_in_html_col_grassetto_e_senza_tag_iniettati():
    testo = formato.risposta_html(_PAYLOAD, {"s1": "Cap. 4 — Mixin", "s2": "Appunti"})
    assert "<b>mixin</b>" in testo
    assert "&lt;componenti&gt;" in testo and "<componenti>" not in testo
    assert "**" not in testo


def test_risposta_elenca_le_fonti_una_volta_coi_loro_numeri():
    testo = formato.risposta_html(_PAYLOAD, {"s1": "Cap. 4 — Mixin", "s2": "Appunti"})
    fonti = testo.split("<b>Fonti</b>")[1]
    assert "[1, 3] Cap. 4 — Mixin" in fonti and "[2] Appunti" in fonti
    assert fonti.count("Mixin") == 1


def test_risposta_senza_titoli_dice_il_numero_e_basta():
    testo = formato.risposta_html(_PAYLOAD, {})
    assert "[1, 3] fonte s1" in testo


def test_risposta_incapsulata_in_json_e_senza_citazioni():
    payload = {"answer": json.dumps({"answer": "solo testo"}),
               "senza_citazioni": {"paragrafi": 2, "su_totale": 3},
               "nota": "2 paragrafi su 3 senza citazioni"}
    testo = formato.risposta_html(payload, {})
    assert testo.startswith("solo testo") and "<b>Fonti</b>" not in testo
    assert "<i>2 paragrafi su 3 senza citazioni</i>" in testo


def test_risposta_vuota_lo_dice_davvero():
    assert "nessun testo" in formato.risposta_html({"answer": ""}, {})


# ── i messaggi lunghi ──────────────────────────────────────────────────────────

def test_spezza_ai_paragrafi_senza_perdere_niente():
    testo = "\n\n".join(f"paragrafo {i} " + "x" * 900 for i in range(10))
    pezzi = formato.spezza(testo, tetto=4000)
    assert len(pezzi) > 1 and all(len(p) <= 4000 for p in pezzi)
    assert "\n\n".join(pezzi) == testo


def test_spezza_un_paragrafo_gigante_toglie_i_tag_dove_taglia():
    testo = "<b>" + "y" * 9000 + "</b>"
    pezzi = formato.spezza(testo, tetto=4000)
    assert all(len(p) <= 4000 for p in pezzi)
    assert "".join(pezzi) == "y" * 9000
