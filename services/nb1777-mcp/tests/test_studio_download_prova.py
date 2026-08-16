"""353ab958 — `studio_download` prova che il file c'è, non lo promette.

Il difetto: dopo `_run(...)` la funzione faceva `return output_path`, cioè restituiva
*il percorso che il chiamante aveva chiesto*, non un fatto osservato. Un `nlm` che esce 0
senza scrivere produceva un path valido verso il nulla, e l'errore arrivava molto più a
valle — addosso a chi apriva il file.

Si mocka `_run`, così i casi si costruiscono senza nlm né rete: il confine è esattamente
dove sta il difetto.

H6-bis (09/08): il `output_path` del chiamante non è più una DESTINAZIONE, solo un NOME —
il file nasce in `NLM_ARTIFACTS`. Qui la fixture punta quella env a `tmp_path`, così i casi
restano gli stessi e in più si prova che la destinazione non è più scegliibile da fuori.
"""
from __future__ import annotations

import pytest

from app import core


@pytest.fixture(autouse=True)
def artefatti_in_tmp(monkeypatch, tmp_path):
    """La directory degli artefatti per la durata del test (niente /var/lib)."""
    d = tmp_path / "artefatti"
    monkeypatch.setenv("NLM_ARTIFACTS", str(d))
    return d


def test_esce_0_ma_non_scrive_nulla_deve_ALZARE(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "_run", lambda *a, **k: None)   # exit 0, zero scritture
    with pytest.raises(core.NLMError) as e:
        core.studio_download("audio", "nb1", "mai-scritto.m4a")
    assert "non esiste" in str(e.value)
    assert "SERVER" in str(e.value)      # e dice DOVE cercarlo: è la trappola vera


def test_file_VUOTO_deve_ALZARE(monkeypatch, artefatti_in_tmp) -> None:
    """Peggio di un file assente: ha il nome giusto e passa ogni controllo di esistenza."""
    monkeypatch.setattr(
        core, "_run", lambda *a, **k: (artefatti_in_tmp / "vuoto.m4a").write_bytes(b""))
    with pytest.raises(core.NLMError) as e:
        core.studio_download("audio", "nb1", "vuoto.m4a")
    assert "VUOTO" in str(e.value)


def test_il_caso_BUONO_passa_e_torna_il_path(monkeypatch, artefatti_in_tmp) -> None:
    """Il controllo positivo: senza, una guardia che alza sempre sembrerebbe corretta."""
    out = artefatti_in_tmp / "buono.m4a"
    monkeypatch.setattr(core, "_run", lambda *a, **k: out.write_bytes(b"\x00" * 64))
    assert core.studio_download("audio", "nb1", "buono.m4a") == out
    assert out.stat().st_size == 64


def test_tipo_sconosciuto_alza_PRIMA_di_lanciare_nlm(monkeypatch) -> None:
    chiamato = []
    monkeypatch.setattr(core, "_run", lambda *a, **k: chiamato.append(1))
    with pytest.raises(core.NLMError):
        core.studio_download("non-esiste", "nb1", "x")
    assert not chiamato, "ha lanciato nlm per un tipo che sapeva già essere invalido"


# ── H6-bis: la destinazione non la sceglie il chiamante ──────────────────────
#
# Perché è una guardia e non un dettaglio: fra i servizi in esercizio questo
# container è l'unico che monta il volume dei cookie Google (H6 lo ha tolto al
# gateway apposta), ed è l'unico che ci SCRIVE — il backup e il check scadenze lo
# montano in sola lettura. Un `output_path` libero è una scrittura arbitraria
# proprio là dentro.

def test_un_path_ASSOLUTO_del_chiamante_NON_e_una_destinazione(
        monkeypatch, artefatti_in_tmp, tmp_path) -> None:
    """Il caso che motiva tutto: `/var/lib/nlm/...` non deve essere raggiungibile."""
    vietato = tmp_path / "nlm" / "profiles" / "default"
    vietato.mkdir(parents=True)
    bersaglio = vietato / "cookies.json"
    bersaglio.write_text("i-cookie-buoni", encoding="utf-8")

    scritti: list = []
    monkeypatch.setattr(
        core, "_run",
        lambda args, **k: scritti.append(args) or
        (artefatti_in_tmp / "cookies.json").write_bytes(b"\x00" * 8))

    p = core.studio_download("audio", "nb1", str(bersaglio))
    assert p.parent == artefatti_in_tmp, "il file è finito fuori dalla directory artefatti"
    assert p.name == "cookies.json"      # il NOME si conserva, la directory no
    assert bersaglio.read_text(encoding="utf-8") == "i-cookie-buoni", "sovrascritto!"
    # e nemmeno `nlm` ha mai visto il path del chiamante
    assert str(bersaglio) not in " ".join(scritti[0])


@pytest.mark.parametrize("raw,atteso", [
    ("../../etc/passwd", "passwd"),
    ("/tmp/round-15.m4a", "round-15.m4a"),
    ("sotto/dir/x.pdf", "x.pdf"),
    (".nascosto", "nascosto"),
    ("nome con spazi e/slash.m4a", "slash.m4a"),
    ("ok_già-buono.v2.m4a", "ok_gi_-buono.v2.m4a"),   # gli accenti non restano nel nome
])
def test_safe_artifact_name_riduce_a_un_nome_innocuo(raw, atteso) -> None:
    assert core.safe_artifact_name(raw) == atteso


@pytest.mark.parametrize("raw", ["..", ".", "...", "/", "/////"])
def test_safe_artifact_name_ALZA_se_non_resta_niente(raw) -> None:
    """Un nome inventato al posto di uno vuoto farebbe nascere il file a caso."""
    with pytest.raises(core.NLMError):
        core.safe_artifact_name(raw)


def test_artifact_path_serve_solo_quello_che_esiste_DENTRO(artefatti_in_tmp, tmp_path) -> None:
    fuori = tmp_path / "segreto.txt"
    fuori.write_text("no", encoding="utf-8")
    (artefatti_in_tmp).mkdir(parents=True, exist_ok=True)
    (artefatti_in_tmp / "dentro.m4a").write_bytes(b"\x00")

    assert core.artifact_path("dentro.m4a").name == "dentro.m4a"      # controprova positiva
    with pytest.raises(core.NLMError):
        core.artifact_path("../segreto.txt")
    with pytest.raises(core.NLMError):
        core.artifact_path("mai-scaricato.m4a")


def test_artifact_list_elenca_solo_file_e_dal_piu_recente(artefatti_in_tmp) -> None:
    import os
    import time
    artefatti_in_tmp.mkdir(parents=True, exist_ok=True)
    (artefatti_in_tmp / "sotto").mkdir()                   # una directory: NON deve comparire
    vecchio = artefatti_in_tmp / "vecchio.m4a"
    nuovo = artefatti_in_tmp / "nuovo.m4a"
    vecchio.write_bytes(b"\x00" * 3)
    nuovo.write_bytes(b"\x00" * 5)
    vecchia_data = time.time() - 3600
    os.utime(vecchio, (vecchia_data, vecchia_data))

    voci = core.artifact_list()
    assert [v["name"] for v in voci] == ["nuovo.m4a", "vecchio.m4a"]
    assert voci[0]["bytes"] == 5
