"""La lettura della sezione `secrets:` di un compose, nei casi che le prove non percorrevano (25/11/2026).

Prima di spezzare `_secrets_mancanti_in` (QUA-04) la copertura per rami diceva che mancavano
quattro strade: il compose che non c'è, la sezione che finisce quando si torna a colonna 0, la
sezione senza figli, le righe vuote e i commenti dentro il blocco.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("vps1777_cli_sezione", _ROOT / "tools" / "vps1777.py")
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)


def _repo(tmp_path: Path, compose: str, pieni: tuple[str, ...] = ()) -> Path:
    (tmp_path / "secrets").mkdir()
    for nome in pieni:
        (tmp_path / "secrets" / nome).write_text("valore\n", encoding="utf-8")
    (tmp_path / "compose.yaml").write_text(compose, encoding="utf-8")
    return tmp_path


def test_un_compose_che_non_ce_non_dichiara_niente(tmp_path):
    assert v._secrets_mancanti_in(tmp_path / "manca.yaml", tmp_path, set()) == []


def test_la_sezione_finisce_a_colonna_zero_e_salta_vuote_e_commenti(tmp_path):
    repo = _repo(tmp_path, (
        "secrets:\n"
        "  # un commento dentro il blocco\n"
        "\n"
        "  uno:\n"
        "    file: ./secrets/uno\n"
        "  due:\n"
        "    file: ./secrets/due\n"
        "volumes:\n"
        "  tre:\n"
        "    file: ./secrets/tre\n"), pieni=("uno",))
    visti: set = set()
    fuori = v._secrets_mancanti_in(repo / "compose.yaml", repo, visti)
    assert len(fuori) == 1 and fuori[0].startswith("due → ./secrets/due   [ASSENTE")
    assert visti == {("uno", "./secrets/uno"), ("due", "./secrets/due")}, "«tre» sta sotto volumes:"


def test_una_sezione_senza_figli_non_e_un_formato_inatteso(tmp_path):
    repo = _repo(tmp_path, "secrets:\n\nservices:\n  a:\n    image: x\n")
    assert v._secrets_mancanti_in(repo / "compose.yaml", repo, set()) == []


def test_una_sezione_piena_ma_illeggibile_si_dice(tmp_path):
    repo = _repo(tmp_path, "secrets:\n  uno:\n    external: true\n")
    fuori = v._secrets_mancanti_in(repo / "compose.yaml", repo, set())
    assert len(fuori) == 1 and "formato inatteso" in fuori[0]
