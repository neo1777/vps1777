"""P10 (10/10/2026): la Mini App cerca per parole e per senso, e la domanda si ritrova.

Funzioni pure di miniapp_core (stdlib-only, come il resto dei test del gateway):
- `risposta_mini_app`: la risposta di notebook_query con le fonti visibili e il non-citato
  dichiarato. Prima `extract_answer` buttava via references e `senza_citazioni`.
- `RisposteRecenti`: una risposta già arrivata si ritrova per 30 minuti, anche se il
  telefono era in tasca quando è stata ritirata.
- `righe_ricerca`: `search` dà le righe, `search_ibrida` un oggetto {righe, saltati?}.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import miniapp_core  # noqa: E402


def test_in_corso_non_e_una_risposta():
    out = miniapp_core.risposta_mini_app(
        {"stato": "in_corso", "query_id": "abc123", "nota": "ritirala dopo"}, {})
    assert out == {"stato": "in_corso"}, "il query_id resta sul server: la Mini App rilancia la domanda"


def test_le_fonti_si_vedono_col_titolo():
    out = miniapp_core.risposta_mini_app({
        "answer": "Il tetto è 2 GB [1]. Lo dice il compose [2].",
        "references": [
            {"citation_number": 1, "source_id": "s-a", "anteprima": "memoria 2g per archive-mcp"},
            {"citation_number": 2, "source_id": "s-b", "anteprima": "mem_limit: 2g"},
            "spazzatura",
        ],
        "sources_used": ["s-a", "s-b"],
    }, {"s-a": "CHANGELOG", "s-b": "compose.yaml"})
    assert out["stato"] == "pronta"
    assert out["answer"].startswith("Il tetto è 2 GB")
    assert out["fonti"] == [
        {"n": 1, "titolo": "CHANGELOG", "anteprima": "memoria 2g per archive-mcp"},
        {"n": 2, "titolo": "compose.yaml", "anteprima": "mem_limit: 2g"},
    ]
    assert "senza_citazioni" not in out


def test_titolo_ignoto_non_fa_cadere_la_risposta():
    out = miniapp_core.risposta_mini_app(
        {"answer": "x [1]", "references": [{"citation_number": 1, "source_id": "s-z"}]}, {})
    assert out["fonti"] == [{"n": 1, "titolo": "", "anteprima": ""}]


def test_il_non_citato_si_dichiara():
    out = miniapp_core.risposta_mini_app({
        "answer": "Primo [1].\n\nSecondo senza marcatore.",
        "references": [],
        "senza_citazioni": {"paragrafi": 1, "su_totale": 2, "anteprime": ["Secondo senza"]},
        "nota": "i paragrafi elencati non portano marcatori",
    }, {})
    assert out["senza_citazioni"] == {"paragrafi": 1, "su_totale": 2}
    assert out["nota"].startswith("i paragrafi")


def test_risposta_in_json_incapsulato():
    # alcune versioni di FastMCP serializzano il dict come testo JSON: la Mini App
    # riceve comunque il testo, non l'involucro
    out = miniapp_core.risposta_mini_app({"answer": '{"answer": "dentro"}'}, {})
    assert out["answer"] == "dentro"


class _Orologio:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_la_risposta_si_ritrova_per_mezz_ora():
    ora = _Orologio()
    rr = miniapp_core.RisposteRecenti(ora=ora)
    chiave = ("774", "nb-1", "quanto costa?")
    assert rr.prendi(chiave) is None
    rr.metti(chiave, {"stato": "pronta", "answer": "poco"})
    ora.t += 29 * 60
    assert rr.prendi(chiave)["answer"] == "poco"
    ora.t += 2 * 60
    assert rr.prendi(chiave) is None, "dopo 30 minuti la risposta scade"


def test_le_risposte_tenute_hanno_un_tetto():
    ora = _Orologio()
    rr = miniapp_core.RisposteRecenti(ora=ora, massimo=3)
    for i in range(5):
        ora.t += 1
        rr.metti(("u", "nb", f"q{i}"), {"answer": str(i)})
    assert rr.prendi(("u", "nb", "q0")) is None and rr.prendi(("u", "nb", "q1")) is None
    assert rr.prendi(("u", "nb", "q4"))["answer"] == "4"


def test_righe_della_ricerca_per_parole():
    righe, saltati = miniapp_core.righe_ricerca(
        [{"db": "a", "uuid": "1"}, {"db": "b", "uuid": "2"}], "parole")
    assert [r["uuid"] for r in righe] == ["1", "2"] and saltati == []


def test_righe_della_ricerca_per_senso():
    righe, saltati = miniapp_core.righe_ricerca([{
        "righe": [{"db": "a", "uuid": "1", "origine": "vettori", "pezzo": 3}],
        "indici": [], "parametri": {},
        "saltati": [{"db": "c", "ramo": "vettori", "motivo": "indice assente"}],
    }], "senso")
    assert righe[0]["pezzo"] == 3
    assert saltati == [{"db": "c", "ramo": "vettori", "motivo": "indice assente"}]


def test_ricerca_per_senso_senza_oggetto():
    assert miniapp_core.righe_ricerca([], "senso") == ([], [])
