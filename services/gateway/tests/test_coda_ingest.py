"""P16 (11/10/2026): l'indicizzazione di /admin/archive come lavoro a parte.

Il gateway mette il file in coda e scrive un intent (app/coda_ingest.py); il servizio
compose `ingest` lo indicizza (app/ingest_worker.py), lanciato dall'host. Qui le parti
che non hanno bisogno di docker: la coda, lo stato per la pagina, il lavoro stesso.
"""
from __future__ import annotations

import json
import os
import stat
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import coda_ingest as ci  # noqa: E402
from app import ingest_worker as iw  # noqa: E402

ADESSO = 1791720000.0   # 2026-10-11T...Z, fisso


@pytest.fixture()
def posto(tmp_path):
    ob = tmp_path / "onboarding"
    db_dir = tmp_path / "archive" / "db"
    ob.mkdir()
    db_dir.mkdir(parents=True)
    return ob, db_dir


def _tmp(db_dir: Path, testo: str = "# titolo\n\nuna riga da cercare\n") -> Path:
    p = db_dir / ".upload-x.md"
    p.write_text(testo, encoding="utf-8")
    return p


def test_accoda_sposta_il_file_e_scrive_l_intent(posto):
    ob, db_dir = posto
    tmp = _tmp(db_dir)
    jid = ci.accoda(ob, db_dir, tmp, db="note", suffisso=".md", nome_file="a/b/note.md",
                    project="p", description="d", by="owner@example.invalid", adesso=ADESSO)
    assert ci.ID_RE.match(jid)
    assert not tmp.exists()
    assert (db_dir.parent / "coda" / f"{jid}.md").read_text(encoding="utf-8").startswith("# titolo")
    intent = ob / ci.CODA / f"{jid}.json"
    d = json.loads(intent.read_text(encoding="utf-8"))
    assert d["db"] == "note" and d["suffisso"] == ".md" and d["file"] == "note.md"
    assert d["id"] == jid
    # non leggibile da ogni utente dell'host
    assert stat.S_IMODE(intent.stat().st_mode) == 0o640
    # nella cartella sorvegliata dalla path unit c'è solo l'intent, nessun temporaneo
    assert [p.name for p in (ob / ci.CODA).iterdir()] == [f"{jid}.json"]
    assert not list(ob.glob(".*.tmp"))


@pytest.mark.parametrize("db,suffisso", [("../x", ".md"), ("", ".md"), ("ok", ".db"),
                                         ("ok", ".exe"), ("a b", ".md")])
def test_accoda_rifiuta_nomi_e_formati(posto, db, suffisso):
    ob, db_dir = posto
    with pytest.raises(ValueError):
        ci.accoda(ob, db_dir, _tmp(db_dir), db=db, suffisso=suffisso, nome_file="x")
    assert not (ob / ci.CODA).exists()


def test_lo_stato_dice_in_coda_e_fermo(posto):
    ob, db_dir = posto
    jid = ci.accoda(ob, db_dir, _tmp(db_dir), db="note", suffisso=".md", nome_file="n.md")
    (lav,) = ci.lavori(ob)
    assert lav["id"] == jid and lav["stato"] == "in-coda" and lav["fermo"] is False
    assert ci.qualcuno_aperto([lav])
    (lav,) = ci.lavori(ob, adesso=time.time() + ci.FERMO_DOPO_S + 5)
    assert lav["fermo"] is True


def test_l_esito_vince_sull_intent_e_l_ordine_e_dal_piu_nuovo(posto):
    ob, db_dir = posto
    (ob / ci.ESITI).mkdir()
    (ob / ci.CODA).mkdir()
    vecchio, nuovo = "20261011T100000Z-aaaaaaaa", "20261011T110000Z-bbbbbbbb"
    (ob / ci.ESITI / f"{vecchio}.json").write_text(json.dumps({"stato": "fatto", "righe": 3}))
    # lo stesso id ancora in coda (la CLI scrive l'esito e POI toglie l'intent)
    (ob / ci.CODA / f"{vecchio}.json").write_text(json.dumps({"db": "x"}))
    (ob / ci.CODA / f"{nuovo}.json").write_text(json.dumps({"db": "y"}))
    (ob / ci.CODA / "estraneo.json").write_text("{}")
    elenco = ci.lavori(ob)
    assert [d["id"] for d in elenco] == [nuovo, vecchio]
    assert elenco[1]["stato"] == "fatto"


def test_il_lavoro_indicizza_scrive_la_descrizione_e_toglie_il_file(posto):
    ob, db_dir = posto
    jid = ci.accoda(ob, db_dir, _tmp(db_dir), db="note", suffisso=".md", nome_file="n.md")
    codice, esito = iw.esegui_coda(jid, "note", ".md", "prog", "le mie note", db_dir=str(db_dir))
    assert codice == 0, esito
    assert esito["righe"] >= 1 and esito["totale"] == esito["righe"]
    assert not (db_dir.parent / "coda" / f"{jid}.md").exists()
    from app import archive_indexer
    assert archive_indexer.get_meta(db_dir / "note.db", "description") == "le mie note"


def test_il_lavoro_ricontrolla_gli_argomenti(posto):
    _, db_dir = posto
    assert iw.esegui_coda("../../etc/passwd", "note", ".md", db_dir=str(db_dir))[0] == 2
    assert iw.esegui_coda("20261011T100000Z-aaaaaaaa", "../x", ".md", db_dir=str(db_dir))[0] == 2
    assert iw.esegui_coda("20261011T100000Z-aaaaaaaa", "x", ".db", db_dir=str(db_dir))[0] == 2


def test_un_file_che_non_c_e_e_un_rifiuto_parlante(posto):
    _, db_dir = posto
    codice, esito = iw.esegui_coda("20261011T100000Z-aaaaaaaa", "x", ".md", db_dir=str(db_dir))
    assert codice == 3 and "non c'è" in esito["errore"]


def test_un_formato_illeggibile_e_un_rifiuto_parlante_e_il_file_sparisce(posto):
    ob, db_dir = posto
    tmp = db_dir / ".upload-x.zip"
    tmp.write_bytes(b"non sono uno zip")
    jid = ci.accoda(ob, db_dir, tmp, db="x", suffisso=".zip", nome_file="x.zip")
    codice, esito = iw.esegui_coda(jid, "x", ".zip", db_dir=str(db_dir))
    assert codice == 3 and esito["errore"]
    assert not (db_dir.parent / "coda" / f"{jid}.zip").exists()


def test_gli_orfani_vecchi_se_ne_vanno_i_recenti_no(posto):
    _, db_dir = posto
    coda = db_dir.parent / "coda"
    coda.mkdir()
    vecchio, recente = coda / "vecchio.zip", coda / "recente.zip"
    vecchio.write_text("x")
    recente.write_text("x")
    t = time.time() - iw.ORFANO_DOPO_S - 60
    os.utime(vecchio, (t, t))
    assert iw._pulisci_orfani(coda, tranne=coda / "altro") == 1
    assert not vecchio.exists() and recente.exists()


def test_main_stampa_una_riga_json(posto, capsys, monkeypatch):
    ob, db_dir = posto
    monkeypatch.setattr(iw, "DB_DIR", str(db_dir))
    monkeypatch.setattr(iw.esegui_coda, "__kwdefaults__", {"db_dir": str(db_dir)})
    jid = ci.accoda(ob, db_dir, _tmp(db_dir), db="note", suffisso=".md", nome_file="n.md")
    assert iw.main(["coda", "--id", jid, "--db", "note", "--suffisso", ".md"]) == 0
    ultima = capsys.readouterr().out.strip().splitlines()[-1]
    assert json.loads(ultima)["righe"] >= 1
