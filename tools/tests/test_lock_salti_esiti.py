"""Gli esiti di `tools/lock-salti.py`: che cosa dice e con che codice esce, strada per strada.

0 = nessun attraversamento di confine; 1 = almeno uno, con le righe RATIFICA-RICHIESTA per il
gate; 2 = non misurato (lock mancante, illeggibile, vuoto, o una versione che non si sa ordinare).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("lock_salti", _ROOT / "tools" / "lock-salti.py")
ls = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ls)


def _lock(percorso: Path, pacchetti: dict[str, str]) -> Path:
    righe = ["version = 1"]
    for nome, ver in pacchetti.items():
        righe += ["", "[[package]]", f'name = "{nome}"', f'version = "{ver}"']
    percorso.write_text("\n".join(righe) + "\n", encoding="utf-8")
    return percorso


def _corri(tmp_path, prima: dict[str, str], dopo: dict[str, str], capsys):
    rc = ls.confronta(_lock(tmp_path / "prima.lock", prima), _lock(tmp_path / "dopo.lock", dopo))
    uscita = capsys.readouterr()
    return rc, uscita.out, uscita.err


def test_niente_cambia_esce_zero_e_lo_dice(tmp_path, capsys):
    rc, out, err = _corri(tmp_path, {"mcp": "1.3.1", "httpx": "0.27.0"},
                          {"mcp": "1.3.1", "httpx": "0.27.0"}, capsys)
    assert rc == 0 and err == ""
    assert "lock: 2 → 2 pacchetti" in out and "✓ nessun attraversamento di confine" in out
    assert "entrati" not in out and "patch/minor" not in out


def test_un_salto_di_patch_si_elenca_e_non_ferma(tmp_path, capsys):
    rc, out, _ = _corri(tmp_path, {"mcp": "1.3.1"}, {"mcp": "1.3.2"}, capsys)
    assert rc == 0 and "· patch/minor" in out and "mcp" in out
    assert "ATTRAVERSA UN CONFINE" not in out


def test_un_confine_esce_uno_con_la_riga_per_il_gate(tmp_path, capsys):
    rc, out, err = _corri(tmp_path, {"starlette": "0.45.0", "mcp": "1.3.1", "anyio": "4.0.0"},
                          {"starlette": "0.46.0", "mcp": "2.0.0", "anyio": "4.0.1"}, capsys)
    assert rc == 1 and err == ""
    assert "⛔ ATTRAVERSA UN CONFINE" in out and "⛔ 2 attraversamento/i di confine" in out
    assert "RATIFICA-RICHIESTA: mcp==2.0.0" in out and "RATIFICA-RICHIESTA: starlette==0.46.0" in out
    assert "RATIFICA-RICHIESTA: anyio" not in out and "· patch/minor" in out
    assert "nessun attraversamento" not in out


def test_entrati_e_usciti_si_dicono_anche_da_soli(tmp_path, capsys):
    rc, out, _ = _corri(tmp_path, {"mcp": "1.0.0", "vecchio": "1.0.0"},
                        {"mcp": "1.0.0", "nuovo": "1.0.0"}, capsys)
    assert rc == 0 and "· entrati: nuovo" in out and "· usciti:  vecchio" in out
    rc, out, _ = _corri(tmp_path, {"mcp": "1.0.0"}, {"mcp": "1.0.0", "nuovo": "1.0.0"}, capsys)
    assert "· entrati: nuovo" in out and "· usciti:  —" in out


def test_una_versione_che_non_si_sa_ordinare_non_e_misurata(tmp_path, capsys):
    rc, out, err = _corri(tmp_path, {"mcp": "1.0.0", "strano": "abc"},
                          {"mcp": "2.0.0", "strano": "abd"}, capsys)
    assert rc == 2, "il non misurato vince anche sul confine"
    assert "NON MISURATO — versioni che non so ordinare" in err and "strano" in err
    assert "RATIFICA-RICHIESTA" not in out and "⛔ ATTRAVERSA UN CONFINE" in out


def test_un_lock_che_manca_non_e_misurato(tmp_path, capsys):
    dopo = _lock(tmp_path / "dopo.lock", {"mcp": "1.0.0"})
    assert ls.confronta(tmp_path / "non-c-e.lock", dopo) == 2
    uscita = capsys.readouterr()
    assert "NON MISURATO: manca" in uscita.err and "non-c-e.lock" in uscita.err and uscita.out == ""


def test_un_lock_illeggibile_non_e_misurato(tmp_path, capsys):
    dopo = _lock(tmp_path / "dopo.lock", {"mcp": "1.0.0"})
    rotto = tmp_path / "rotto.lock"
    rotto.write_text("[[package\nname = rotto", encoding="utf-8")
    assert ls.confronta(rotto, dopo) == 2
    assert "NON MISURATO: lock illeggibile" in capsys.readouterr().err
    rotto.write_bytes(b"\xff\xfe non utf-8")
    assert ls.confronta(dopo, rotto) == 2
    assert "NON MISURATO: lock illeggibile" in capsys.readouterr().err


def test_un_lock_senza_pacchetti_non_e_misurato(tmp_path, capsys):
    dopo = _lock(tmp_path / "dopo.lock", {"mcp": "1.0.0"})
    vuoto = tmp_path / "vuoto.lock"
    vuoto.write_text("version = 1\n", encoding="utf-8")
    assert ls.confronta(vuoto, dopo) == 2
    assert "nessun pacchetto letto" in capsys.readouterr().err
