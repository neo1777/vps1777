"""`archive_indexer.main`: un modo per volta, dalla riga di comando (25/11/2026).

Misurato prima di spezzarla (QUA-04): le prove chiamavano `main` solo per `--retag` e `--migra` a
secco. Restavano senza prova il modo normale (indicizzare e raccontare che cosa si è scritto),
`--classify`, `--migra-telegram`, `--retag --scrivi`, e i rifiuti: input assente, DB di uscita
mancante, file che l'indexer non sa leggere, DB senza le colonne che la migrazione pretende.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import archive_indexer  # noqa: E402


def _sessione(tmp_path: Path, *righe: dict) -> Path:
    f = tmp_path / "sessione.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in righe))
    return f


def _messaggio(uuid: str, testo: str, **altro) -> dict:
    return {"type": "user", "uuid": uuid, "timestamp": "2026-01-01T00:00:00Z", "cwd": "/home/x/progetto",
            "message": {"role": "user", "content": testo}, **altro}


def _db(tmp_path: Path, *righe: tuple) -> Path:
    db = tmp_path / "arch.db"
    archive_indexer.write_rows(db, list(righe))
    return db


def test_un_input_che_non_c_e_si_dice_ed_esce_1(tmp_path, capsys):
    assert archive_indexer.main([str(tmp_path / "assente.jsonl"), str(tmp_path / "out.db")]) == 1
    assert "input non trovato" in capsys.readouterr().err
    assert not (tmp_path / "out.db").exists()


def test_senza_db_di_uscita_non_si_indicizza(tmp_path, capsys):
    assert archive_indexer.main([str(_sessione(tmp_path, _messaggio("u1", "ciao")))]) == 1
    assert "manca il file .db di output" in capsys.readouterr().err


def test_il_modo_normale_racconta_letti_scritti_e_deduplicati(tmp_path, capsys):
    sessione = _sessione(tmp_path, _messaggio("u1", "ciao"), _messaggio("u2", "mondo"))
    db = tmp_path / "out.db"
    assert archive_indexer.main([str(sessione), str(db), "--project", "prova"]) == 0
    assert "letti 2 record → scritti 2 · deduplicati 0  (totale nel DB: 2)" in capsys.readouterr().out
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT DISTINCT project FROM messages").fetchall() == [("prova",)]
    # la seconda volta sono gli stessi: letti ma non scritti, e il totale non si somma
    assert archive_indexer.main([str(sessione), str(db), "--project", "prova"]) == 0
    assert "letti 2 record → scritti 0 · deduplicati 2  (totale nel DB: 2)" in capsys.readouterr().out


def test_gli_scarti_si_dicono_solo_se_ci_sono(tmp_path, capsys):
    pulita = _sessione(tmp_path, _messaggio("u1", "ciao"))
    assert archive_indexer.main([str(pulita), str(tmp_path / "a.db")]) == 0
    assert "scartati" not in capsys.readouterr().out
    sporca = _sessione(tmp_path, _messaggio("u1", "ciao"), {"type": "system", "uuid": "s1"})
    assert archive_indexer.main([str(sporca), str(tmp_path / "b.db")]) == 0
    assert "scartati 1 record (lapidi in `skipped`" in capsys.readouterr().out


def test_un_file_che_l_indexer_non_sa_leggere_esce_2_col_motivo(tmp_path, capsys):
    strano = tmp_path / "foglio.xyz"
    strano.write_text("x")
    assert archive_indexer.main([str(strano), str(tmp_path / "out.db")]) == 2
    assert "formato non supportato" in capsys.readouterr().err


def test_classify_stampa_un_verdetto_per_riga_e_non_scrive_niente(tmp_path, capsys):
    sessione = _sessione(tmp_path, _messaggio("u1", "ciao"), {"type": "system", "uuid": "s1"})
    assert archive_indexer.main([str(sessione), "--classify"]) == 0
    assert capsys.readouterr().out.splitlines() == ["keep:user", "skip:non-message"]
    assert list(tmp_path.glob("*.db")) == []


def test_migra_telegram_senza_il_nome_del_proprietario_si_rifiuta(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("ARCHIVE_TELEGRAM_PROPRIETARIO", raising=False)
    db = _db(tmp_path, ("m1", "chat", "2026", "[Mario] ciao", "", "", "", "", ""))
    assert archive_indexer.main([str(db), "--migra-telegram", "--scrivi"]) == 2
    assert "ARCHIVE_TELEGRAM_PROPRIETARIO" in capsys.readouterr().err


@pytest.mark.parametrize("scrivi", [False, True])
def test_migra_telegram_conta_sempre_e_scrive_solo_con_scrivi(tmp_path, capsys, monkeypatch, scrivi):
    monkeypatch.setenv("ARCHIVE_TELEGRAM_PROPRIETARIO", "Mario")
    db = _db(tmp_path, ("m1", "chat", "2026", "[Mario] ciao", "", "", "", "", ""),
             ("m2", "chat", "2026", "[Anna] ehi", "", "", "", "", ""))
    assert archive_indexer.main([str(db), "--migra-telegram", *(["--scrivi"] if scrivi else [])]) == 0
    detto = capsys.readouterr()
    assert json.loads(detto.out) == {"human": 1, "other": 1, "scritto": scrivi}
    assert ("[a secco]" in detto.err) is (not scrivi)
    with sqlite3.connect(db) as c:
        senders = [r[0] for r in c.execute("SELECT sender FROM messages ORDER BY uuid")]
    assert senders == (["user", "altro"] if scrivi else ["", ""])


def test_migra_su_un_db_senza_speaker_esce_2_col_motivo(tmp_path, capsys):
    db = tmp_path / "vecchio.db"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE messages(uuid TEXT PRIMARY KEY, content TEXT, sender TEXT)")
    assert archive_indexer.main([str(db), "--migra"]) == 2
    assert "non ha la colonna `speaker`" in capsys.readouterr().err


def test_retag_con_scrivi_salva_davvero(tmp_path, capsys):
    db = _db(tmp_path, ("m1", "p", "2026-01-01T00:00:00Z", "testo mio", "user", "", "", "", ""))
    with sqlite3.connect(db) as c:
        c.execute("UPDATE messages SET voice='SEGNAPOSTO'")
    assert archive_indexer.main([str(db), "--retag", "--scrivi"]) == 0
    detto = capsys.readouterr()
    esito = json.loads(detto.out.strip().splitlines()[-1])
    assert esito["scritto"] is True and esito["cambiate"] == 1
    assert "[a secco]" not in detto.err
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT voice FROM messages").fetchone()[0] != "SEGNAPOSTO"


def test_i_modi_che_non_indicizzano_vincono_sul_db_di_uscita(tmp_path, capsys):
    # con --classify il secondo argomento non si apre: nessun DB nasce
    sessione = _sessione(tmp_path, _messaggio("u1", "ciao"))
    assert archive_indexer.main([str(sessione), str(tmp_path / "out.db"), "--classify"]) == 0
    assert capsys.readouterr().out.strip() == "keep:user"
    assert not (tmp_path / "out.db").exists()
