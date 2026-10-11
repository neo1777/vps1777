"""P2 (11/10/2026): il modello di embedding si carica all'avvio, e si sa quanto ci ha messo.

Il modello e5 si caricava alla prima search_ibrida: chi la lanciava aspettava il
caricamento, e il 04/10, con la cache dei DB a riempire il tetto di 2 GB, il kernel ha messo
il modello in swap e il caricamento è durato 8 min 25 s (34 errori dei client in un giorno).
Ora un thread lo carica all'avvio, se c'è almeno un indice che lo userà, e scrive nel log
quanto ci ha messo. `/health` dice lo stato: è la misura del confronto sul tetto di memoria.

Stdlib: il caricamento vero (onnxruntime) è sostituito da un finto.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import semantica  # noqa: E402


@pytest.fixture(autouse=True)
def pulito(monkeypatch):
    monkeypatch.setattr(semantica, "_SESSIONE", None)
    monkeypatch.setattr(semantica, "_TOKENIZER", None)
    monkeypatch.setattr(semantica, "_STATO", {"stato": "non_caricato"})
    yield


def _modello(d: Path) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    (d / "model.onnx").write_bytes(b"x")
    (d / "tokenizer.json").write_text("{}")
    return d


def test_senza_file_del_modello_lo_stato_e_assente(tmp_path):
    assert semantica.stato_modello(tmp_path / "manca")["stato"] == "assente"


def test_coi_file_ma_non_caricato(tmp_path):
    assert semantica.stato_modello(_modello(tmp_path / "m"))["stato"] == "non_caricato"


def test_riscaldato_dice_quanto_ci_ha_messo(tmp_path, monkeypatch, caplog):
    m = _modello(tmp_path / "m")
    monkeypatch.setattr(semantica, "apri_modello", lambda d, thread=2: ("sessione", "tok"))
    with caplog.at_level("INFO"):
        semantica.riscalda_modello(m, indici=1)
    s = semantica.stato_modello(m)
    assert s["stato"] == "caricato" and isinstance(s["secondi"], float) and s["secondi"] >= 0
    assert s.get("da") == "avvio"
    assert any("caricato in" in r.getMessage() for r in caplog.records)
    # e la prima ricerca non lo ricarica
    assert semantica._carica_modello(m) == ("sessione", "tok")


def test_senza_indici_non_lo_carica(tmp_path, monkeypatch):
    m = _modello(tmp_path / "m")
    chiamate = []
    monkeypatch.setattr(semantica, "apri_modello", lambda d, thread=2: chiamate.append(d))
    semantica.riscalda_modello(m, indici=0)
    assert chiamate == [] and semantica.stato_modello(m)["stato"] == "non_caricato"


def test_un_errore_di_caricamento_si_vede_e_non_uccide_niente(tmp_path, monkeypatch):
    m = _modello(tmp_path / "m")

    def rotto(d, thread=2):
        raise RuntimeError("onnx illeggibile")
    monkeypatch.setattr(semantica, "apri_modello", rotto)
    semantica.riscalda_modello(m, indici=2)          # non solleva: è un thread di avvio
    s = semantica.stato_modello(m)
    assert s["stato"] == "errore" and "onnx illeggibile" in s["errore"]


def test_caricato_alla_prima_ricerca_lo_dice(tmp_path, monkeypatch):
    m = _modello(tmp_path / "m")
    monkeypatch.setattr(semantica, "apri_modello", lambda d, thread=2: ("s", "t"))
    semantica._carica_modello(m)
    s = semantica.stato_modello(m)
    assert s["stato"] == "caricato" and s["da"] == "prima ricerca"
