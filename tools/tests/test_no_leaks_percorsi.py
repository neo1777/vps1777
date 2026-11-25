"""Ogni strada di `main` del gate anti-leak, sul comportamento: esito, righe stampate, righe assenti.

Perché esiste (25/11/2026, QUA-04). `main` misurava 30 di complessità e le prove del repo ne
percorrevano 24 rami su 54: il resto lo vedeva solo la CI sul repo vero, dove quasi tutte le strade
sono verdi. Prima di spezzarla serve un banco che dica, per ogni strada, che cosa esce. Qui ogni
caso costruisce i file in una cartella, finge `tracked_files` e chiama `main()`.

I valori che somigliano a segreti si compongono a pezzi (`_p`), come in `test_no_leaks.py`: questo
file non deve far scattare il gate che prova.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

_RADICE = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("check_no_leaks_percorsi",
                                               _RADICE / "security" / "check_no_leaks.py")
g = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(g)


def _p(*pezzi: str) -> str:
    return "".join(pezzi)


TSKEY = _p("tsk", "ey-auth-", "kA9fQ2xL7mN4pR8s")
AGE = _p("AGE-SECRET", "-KEY-1", "Q" * 58)
IP_PUB = _p("93.184.", "216.34")
IP_PUB2 = _p("93.184.", "216.35")
TSNET = _p("host.abc", "-def.ts.net")
PROSA = _p("la password è ", "Xy7!kq9#Lm2")
NUDA = _p("pw: ", "Qz8$wE3!rT")


def gira(tmp_path, monkeypatch, capsys, file: dict, *, r4: bool = False,
         tracciati: list[str] | None = None) -> tuple[int, str]:
    for nome, dato in file.items():
        p = tmp_path / nome
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(dato if isinstance(dato, bytes) else dato.encode("utf-8"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(g, "tracked_files", lambda: list(tracciati if tracciati is not None else file))
    monkeypatch.setattr(g.sys, "argv", ["check_no_leaks.py", *(["--r4"] if r4 else [])])
    esito = g.main()
    return esito, capsys.readouterr().out


CASI = [
    # nome, file, esito, deve contenere, non deve contenere
    ("pulito", {"README.md": "testo\n"}, 0, ["✓ gate anti-leak"], ["[R"]),
    ("R1 per mestiere", {".env": "A=1\n"}, 1, ["[R1] .env", "PER MESTIERE"], []),
    ("R1 ammesso, poi letto", {".env.example": "X=1\n"}, 0, ["✓ gate anti-leak"], ["[R1]"]),
    ("R1 ammesso ma con un indirizzo", {".env.example": f"X={IP_PUB}\n"}, 1, ["[R3] .env.example:1"], ["[R1]"]),
    ("export di sessione", {"2026-01-01-120000-x.txt": "x\n"}, 1,
     ["[R1] 2026-01-01-120000-x.txt", "export di sessione tracciato"], []),
    ("database", {"dati/a.sqlite-wal": "x"}, 1, ["[R1] dati/a.sqlite-wal", "database tracciato"], []),
    ("jsonl fixture piccola", {"tests/fixtures/a.jsonl": '{"a":1}\n'}, 0, ["✓ gate"], ["[R1]"]),
    ("jsonl fixture piccola con segreto", {"tests/data/a.jsonl": TSKEY + "\n"}, 1,
     ["[R2] tests/data/a.jsonl:1"], ["[R1]"]),
    ("jsonl fixture grande", {"tests/fixtures/b.jsonl": "x" * (64 * 1024 + 1)}, 1,
     ["[R1] tests/fixtures/b.jsonl", "supera il tetto fixture (65537 B > 65536 B)"], []),
    ("jsonl fuori dalle fixture", {"logs/c.jsonl": "{}\n"}, 1, ["sta fuori da tests/fixtures/"], []),
    ("binario e non UTF-8", {"a.bin": b"\x00" + TSKEY.encode(), "b.txt": b"caff\xe8 " + TSKEY.encode()}, 0,
     ["(non scansionati come testo: 1 file binari, 1 non UTF-8", "✓ gate"], ["[R2]"]),
    ("esente da R3, non da R2", {"tools/tests/test_no_leaks.py": f"{IP_PUB}\n{TSKEY}\n{AGE}\n"}, 1,
     ["[R2] tools/tests/test_no_leaks.py:2 → sembra"], ["[R3]"]),
    ("esente da R3 e da R2", {"security/check_no_leaks.py": f"{IP_PUB} {TSKEY}\n"}, 0, ["✓ gate"], ["[R"]),
    ("esente da R2, non da R3", {"security/findings.yml": f"{TSKEY}\n{IP_PUB}\n"}, 1,
     ["[R3] security/findings.yml:2"], ["[R2]"]),
    ("un indirizzo per file", {"doc/a.md": f"riga\n{IP_PUB}\n{IP_PUB2}\n"}, 1,
     ["[R3] doc/a.md:2", "un indirizzo IP pubblico"], ["doc/a.md:3"]),
    ("indirizzi ammessi e privati", {"doc/b.md": "1.1.1.1 10.0.0.1 192.0.2.7\n"}, 0, ["✓ gate"], ["[R3]"]),
    ("tailnet vera", {"doc/c.md": f"x\n{TSNET}\n"}, 1, ["[R3] doc/c.md:2", "nome di tailnet reale"], []),
    ("tailnet del segnaposto", {"doc/d.md": "x.tailnet-esempio.ts.net\n"}, 0, ["✓ gate"], ["[R3]"]),
    ("segreti: uno per forma e per file", {"doc/g.md": f"{TSKEY}\n{AGE}\n{TSKEY}\n"}, 1,
     ["[R2] doc/g.md:1", "[R2] doc/g.md:2", "RUOTATO"], ["doc/g.md:3"]),
]


@pytest.mark.parametrize("nome,file,esito,si,no", CASI, ids=[c[0] for c in CASI])
def test_ogni_strada(tmp_path, monkeypatch, capsys, nome, file, esito, si, no):
    e, out = gira(tmp_path, monkeypatch, capsys, file)
    assert e == esito, out
    for pezzo in si:
        assert pezzo in out, (pezzo, out)
    for pezzo in no:
        assert pezzo not in out, (pezzo, out)
    assert TSKEY not in out and AGE not in out and IP_PUB not in out, "un valore stampato"


def test_un_file_tracciato_che_non_ce_piu_si_salta(tmp_path, monkeypatch, capsys):
    e, out = gira(tmp_path, monkeypatch, capsys, {"a.md": "x\n"}, tracciati=["a.md", "sparito.md"])
    assert e == 0 and "✓ gate" in out


def test_gli_avvisi_r4_si_contano_e_si_elencano_solo_a_richiesta(tmp_path, monkeypatch, capsys):
    file = {"doc/e.md": PROSA + "\n", "doc/f.md": NUDA + "\n"}
    e, out = gira(tmp_path, monkeypatch, capsys, file)
    # la password in prosa ha anche la forma di una nuda: R4a e R4b sulla stessa riga, 3 avvisi
    assert e == 0 and "⚠ gate anti-leak, R4 — 3 avvisi" in out and "--r4`" in out
    assert "[R4a]" not in out and "[R4b]" not in out
    e, out = gira(tmp_path, monkeypatch, capsys, file, r4=True)
    assert e == 0 and "[R4a] doc/e.md:1" in out and "[R4b] doc/f.md:1" in out
    assert "Xy7!kq9#Lm2" not in out and "Qz8$wE3!rT" not in out


def test_con_un_rosso_gli_avvisi_non_si_stampano(tmp_path, monkeypatch, capsys):
    e, out = gira(tmp_path, monkeypatch, capsys, {"doc/e.md": PROSA + "\n", ".env": "x\n"}, r4=True)
    assert e == 1 and "[R1] .env" in out and "R4" not in out and "Perché la build è rossa" in out


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root legge anche un file 000")
def test_un_file_illeggibile_non_e_un_verde(tmp_path, monkeypatch, capsys):
    file = {"doc/chiuso.md": "x\n", "doc/e.md": PROSA + "\n", "a.bin": b"\x00"}
    for nome, dato in file.items():
        (tmp_path / nome).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / nome).write_bytes(dato if isinstance(dato, bytes) else dato.encode())
    os.chmod(tmp_path / "doc/chiuso.md", 0)
    try:
        e, out = gira(tmp_path, monkeypatch, capsys, {}, tracciati=list(file))
    finally:
        os.chmod(tmp_path / "doc/chiuso.md", 0o644)
    assert e == 2, out
    assert "NON MISURATO su 1 file" in out and "doc/chiuso.md (PermissionError)" in out
    assert "⚠ gate anti-leak, R4 — 2 avvisi" in out and "1 file binari" in out
    assert "✓ gate" not in out
