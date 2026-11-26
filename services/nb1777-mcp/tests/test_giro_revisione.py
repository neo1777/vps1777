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


def test_i_posizionali_che_vengono_da_fuori_passano_dopo_il_separatore():
    # giro di revisione del 21/11: un id o un testo che comincia per «-» veniva letto da nlm come
    # un'opzione (`--profile=altro` come id; una domanda «- qual è…» → «no such option»)
    argv = core._argv(["query", "notebook", core._P("--profile=altro"), core._P("- qual è il punto?"),
                       "--json", "--timeout", "30"])
    assert argv == ["query", "notebook", "--json", "--timeout", "30", "--",
                    "--profile=altro", "- qual è il punto?"]
    assert core._argv(["--version"]) == ["--version"]           # niente posizionali: niente separatore


def test_ogni_chiamata_a_nlm_passa_da_argv(monkeypatch):
    visti: list[list[str]] = []

    class _Fatto:
        returncode, stdout, stderr = 0, "{}", ""
    monkeypatch.setattr(core.subprocess, "run", lambda cmd, **k: visti.append(cmd) or _Fatto())
    # dal 22/11/2026 nb_rename rilegge il titolo: qui interessa l'argv, la rilettura è finta
    monkeypatch.setattr(core, "nb_get", lambda nb_id: {"title": "-1 giorno"})
    core.nb_rename("nb-1", "-1 giorno")
    assert visti[-1][1:] == ["notebook", "rename", "--", "nb-1", "-1 giorno"]
    core.source_rename("nb-1", "s-1", "--confirm")
    assert visti[-1][1:] == ["source", "rename", "-n", "nb-1", "--", "s-1", "--confirm"]


def test_gli_artefatti_scaduti_e_in_eccesso_si_tolgono_prima_di_scaricare(tmp_path, monkeypatch):
    # giro di revisione del 21/11: il volume cresceva senza tetto fino a riempire il disco
    import os
    monkeypatch.setenv("NLM_ARTIFACTS", str(tmp_path))
    monkeypatch.setattr(core, "ARTEFATTI_GIORNI", 30)
    monkeypatch.setattr(core, "ARTEFATTI_MAX_BYTE", 250)
    monkeypatch.setattr(core, "ARTEFATTI_LIBERO_MINIMO", 0)
    ora = 1_800_000_000.0
    for nome, giorni in (("vecchio.mp4", 40), ("a.mp3", 3), ("b.mp3", 2), ("c.mp3", 1)):
        f = tmp_path / nome
        f.write_bytes(b"x" * 100)
        os.utime(f, (ora - giorni * 86400,) * 2)
    tolti = core.fai_posto_agli_artefatti(ora=ora)
    assert tolti == {"scaduti": 1, "in_eccesso": 1}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["b.mp3", "c.mp3"]   # restano i più nuovi


def _artefatti(tmp_path, monkeypatch, voci, *, giorni=30, max_byte=10**9):
    """Una cartella di artefatti: (nome, giorni di età) → file da 100 byte. Ora fissa."""
    import os
    monkeypatch.setenv("NLM_ARTIFACTS", str(tmp_path))
    monkeypatch.setattr(core, "ARTEFATTI_GIORNI", giorni)
    monkeypatch.setattr(core, "ARTEFATTI_MAX_BYTE", max_byte)
    monkeypatch.setattr(core, "ARTEFATTI_LIBERO_MINIMO", 0)
    ora = 1_800_000_000.0
    for nome, eta in voci:
        f = tmp_path / nome
        f.write_bytes(b"x" * 100)
        os.utime(f, (ora - eta * 86400,) * 2)
    return ora


def _non_si_cancella(monkeypatch, prefisso):
    from pathlib import Path
    vero = Path.unlink

    def unlink(self, *a, **k):
        if self.name.startswith(prefisso):
            raise PermissionError(13, "negato", str(self))
        return vero(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", unlink)


def test_uno_scaduto_che_non_si_cancella_resta_e_conta_nel_tetto(tmp_path, monkeypatch, caplog):
    """Il file scaduto che non si lascia togliere non è «tolto»: resta fra quelli che pesano, il
    giro sull'eccesso lo riprova, e alla fine si dice quante volte non c'è riuscito. Il suo peso
    resta nel conto: per tornare sotto il tetto se ne vanno i due più nuovi."""
    ora = _artefatti(tmp_path, monkeypatch, [("duro-vecchio.mp4", 40), ("a.mp3", 3), ("b.mp3", 2)],
                     max_byte=150)
    _non_si_cancella(monkeypatch, "duro-")
    with caplog.at_level("INFO"):
        tolti = core.fai_posto_agli_artefatti(ora=ora)
    assert tolti == {"scaduti": 0, "in_eccesso": 2}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["duro-vecchio.mp4"]
    assert "2 file non si sono lasciati leggere o cancellare" in caplog.text
    assert "tolti 0 scaduti (oltre 30 giorni) e 2 in eccesso" in caplog.text


def test_un_file_che_non_si_lascia_guardare_si_conta_e_non_ferma_il_giro(tmp_path, monkeypatch, caplog):
    from pathlib import Path
    ora = _artefatti(tmp_path, monkeypatch, [("cieco.mp4", 40), ("vecchio.mp4", 40), ("a.mp3", 1)])
    vero = Path.stat

    def stat(self, *a, **k):
        if self.name == "cieco.mp4":
            raise OSError(5, "errore di I/O", str(self))
        return vero(self, *a, **k)

    monkeypatch.setattr(Path, "stat", stat)
    with caplog.at_level("INFO"):
        tolti = core.fai_posto_agli_artefatti(ora=ora)
    monkeypatch.setattr(Path, "stat", vero)
    assert tolti == {"scaduti": 1, "in_eccesso": 0}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.mp3", "cieco.mp4"]
    assert "1 file non si sono lasciati leggere o cancellare" in caplog.text


def test_cartelle_e_link_non_sono_artefatti_e_zero_giorni_non_fa_scadere_niente(tmp_path, monkeypatch, caplog):
    ora = _artefatti(tmp_path, monkeypatch, [("antico.mp4", 400), ("bersaglio.mp3", 400)], giorni=0)
    (tmp_path / "cartella").mkdir()
    (tmp_path / "link.mp3").symlink_to(tmp_path / "bersaglio.mp3")
    with caplog.at_level("INFO"):
        assert core.fai_posto_agli_artefatti(ora=ora) == {"scaduti": 0, "in_eccesso": 0}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["antico.mp4", "bersaglio.mp3", "cartella",
                                                           "link.mp3"]
    assert "artefatti:" not in caplog.text          # niente tolto, niente da dire


def test_senza_ora_vale_l_orologio(tmp_path, monkeypatch):
    ora = _artefatti(tmp_path, monkeypatch, [("vecchio.mp4", 40), ("nuovo.mp3", 1)])
    monkeypatch.setattr(core.time, "time", lambda: ora)
    assert core.fai_posto_agli_artefatti() == {"scaduti": 1, "in_eccesso": 0}


def test_senza_spazio_il_download_non_parte(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setenv("NLM_ARTIFACTS", str(tmp_path))
    monkeypatch.setattr(core, "ARTEFATTI_LIBERO_MINIMO", 10**18)
    with pytest.raises(core.NLMError, match="spazio su disco insufficiente"):
        core.fai_posto_agli_artefatti()
