"""353ab958 — `studio_download` prova che il file c'è, non lo promette.

Il difetto: dopo `_run(...)` la funzione faceva `return output_path`, cioè restituiva
*il percorso che il chiamante aveva chiesto*, non un fatto osservato. Un `nlm` che esce 0
senza scrivere produceva un path valido verso il nulla, e l'errore arrivava molto più a
valle — addosso a chi apriva il file.

Si mocka `_run`, così i casi si costruiscono senza nlm né rete: il confine è esattamente
dove sta il difetto.
"""
from __future__ import annotations

import pytest

from app import core


def test_esce_0_ma_non_scrive_nulla_deve_ALZARE(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "_run", lambda *a, **k: None)   # exit 0, zero scritture
    with pytest.raises(core.NLMError) as e:
        core.studio_download("audio", "nb1", tmp_path / "mai-scritto.m4a")
    assert "non esiste" in str(e.value)
    assert "SERVER" in str(e.value)      # e dice DOVE cercarlo: è la trappola vera


def test_file_VUOTO_deve_ALZARE(monkeypatch, tmp_path) -> None:
    """Peggio di un file assente: ha il nome giusto e passa ogni controllo di esistenza."""
    out = tmp_path / "vuoto.m4a"
    monkeypatch.setattr(core, "_run", lambda *a, **k: out.write_bytes(b""))
    with pytest.raises(core.NLMError) as e:
        core.studio_download("audio", "nb1", out)
    assert "VUOTO" in str(e.value)


def test_il_caso_BUONO_passa_e_torna_il_path(monkeypatch, tmp_path) -> None:
    """Il controllo positivo: senza, una guardia che alza sempre sembrerebbe corretta."""
    out = tmp_path / "buono.m4a"
    monkeypatch.setattr(core, "_run", lambda *a, **k: out.write_bytes(b"\x00" * 64))
    assert core.studio_download("audio", "nb1", out) == out
    assert out.stat().st_size == 64


def test_tipo_sconosciuto_alza_PRIMA_di_lanciare_nlm(monkeypatch, tmp_path) -> None:
    chiamato = []
    monkeypatch.setattr(core, "_run", lambda *a, **k: chiamato.append(1))
    with pytest.raises(core.NLMError):
        core.studio_download("non-esiste", "nb1", tmp_path / "x")
    assert not chiamato, "ha lanciato nlm per un tipo che sapeva già essere invalido"
