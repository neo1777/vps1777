"""nb1777-mcp dopo la rilettura col catalogo di requisiti (undicesima fetta).

Tre fili: uno stato che si perdeva in silenzio, id «indovinati» restituiti come certi, e
scritture dichiarate riuscite senza rileggere.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app import conferma, core, memoria

QUI = Path(__file__).resolve().parents[1]


@pytest.fixture()
def stato(tmp_path, monkeypatch):
    f = tmp_path / "nb1777-state" / "memoria.json"
    monkeypatch.setattr(memoria, "_state_path", lambda: f)
    return f


def test_lo_stato_si_scrive_in_modo_atomico(stato) -> None:
    assert memoria._save({"acked_version": "v2.6"}) is True
    assert memoria._load() == {"acked_version": "v2.6"}
    assert not stato.with_name(stato.name + ".tmp").exists()


def test_un_ack_che_non_si_salva_non_risulta_registrato(stato, monkeypatch) -> None:
    monkeypatch.setattr(memoria, "_save", lambda st: False)
    with pytest.raises(OSError, match="non è stato salvato"):
        memoria.set_ack("v2.6")


def test_uno_stato_rovinato_si_dice_nel_log(stato, caplog) -> None:
    stato.parent.mkdir(parents=True)
    stato.write_text('{"acked_version": "v2', encoding="utf-8")      # troncato
    with caplog.at_level("WARNING"):
        assert memoria._load() == {}
    assert "illeggibile" in caplog.text


def test_le_coppie_dei_giorni_passati_non_si_accumulano(stato) -> None:
    memoria._save({"drift_sent": {"v1.0->v2.6": "2020-01-01", "v1.1->v2.6": "2020-01-02"}})
    memoria.note_drift("v2.5", "v2.6")
    rimaste = memoria._load()["drift_sent"]
    assert list(rimaste) == ["v2.5->v2.6"], rimaste


def test_una_fonte_il_cui_id_non_si_sa_non_viene_indovinata(monkeypatch) -> None:
    monkeypatch.setattr(core, "_source_ids", lambda nb: {"a", "b"})     # niente di nuovo dopo l'add
    monkeypatch.setattr(core, "_run", lambda args, **k: None)
    with pytest.raises(core.IdNonDeterminato, match="NON\\s+riprovare"):
        core._add_and_resolve_id("nb", [], timeout=1)


def test_due_fonti_nuove_insieme_non_si_tira_a_sorte(monkeypatch) -> None:
    giri = iter([{"a"}, {"a", "b", "c"}])
    monkeypatch.setattr(core, "_source_ids", lambda nb: next(giri))
    monkeypatch.setattr(core, "_run", lambda args, **k: None)
    with pytest.raises(core.IdNonDeterminato):
        core._add_and_resolve_id("nb", [], timeout=1)


def test_la_rinomina_si_rilegge(monkeypatch) -> None:
    monkeypatch.setattr(core, "_run", lambda args, **k: None)
    monkeypatch.setattr(core, "nb_get", lambda nb_id: {"title": "titolo vecchio"})
    with pytest.raises(core.NLMError, match="non risulta"):
        core.nb_rename("nb", "titolo nuovo")
    monkeypatch.setattr(core, "nb_get", lambda nb_id: {"title": "titolo nuovo"})
    core.nb_rename("nb", "titolo nuovo")


def test_la_cancellazione_si_controlla_nell_elenco(monkeypatch) -> None:
    monkeypatch.setattr(core, "_run", lambda args, **k: None)
    monkeypatch.setattr(core, "nb_list", lambda: [{"id": "nb"}, {"id": "altro"}])
    with pytest.raises(core.NLMError, match="ancora nell'elenco"):
        core.nb_delete("nb")
    monkeypatch.setattr(core, "nb_list", lambda: [{"id": "altro"}])
    core.nb_delete("nb")


def test_un_notebook_creato_fra_omonimi_non_prende_l_id_del_vecchio(monkeypatch) -> None:
    class P:
        stdout = stderr = ""
    monkeypatch.setattr(core, "_run", lambda args, **k: P())
    monkeypatch.setattr(core, "nb_list", lambda: [{"id": "vecchio", "title": "Appunti"}, {"id": "nuovo", "title": "Appunti"}])
    with pytest.raises(core.IdNonDeterminato):
        core.nb_create("Appunti")


def test_il_gettone_di_conferma_ha_128_bit() -> None:
    firma = conferma.gettone("nb_delete", "x").split(".", 1)[1]
    assert len(firma) == 32
    assert conferma.verifica(conferma.gettone("nb_delete", "x"), "nb_delete", "x") is None


def test_la_versione_di_nlm_nel_messaggio_e_quella_fissata() -> None:
    fissata = re.search(r'"notebooklm-mcp-cli==([0-9.]+)"', (QUI / "pyproject.toml").read_text("utf-8")).group(1)
    server = (QUI / "app" / "server.py").read_text("utf-8")
    assert set(re.findall(r"notebooklm-mcp-cli==([0-9.]+)", server)) == {fissata}
