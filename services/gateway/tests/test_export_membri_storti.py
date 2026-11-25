"""Un export claude.ai con membri dalla forma inattesa non ferma l'ingest e non inventa righe (25/11/2026, QUA-04).

I quattro rami di `_iter_claude_zip` che le prove non percorrevano: una design chat che non è un
oggetto, un progetto che non è un oggetto, un documento che non è un oggetto, un documento senza
contenuto.
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import archive_indexer as ai  # noqa: E402


def _righe(tmp_path: Path, membri: dict) -> list:
    z = tmp_path / "export.zip"
    with zipfile.ZipFile(z, "w") as f:
        for nome, dato in membri.items():
            f.writestr(nome, json.dumps(dato))
    return list(ai._iter_claude_zip(z, ai._Budget()))


def test_di_un_progetto_entrano_solo_i_documenti_con_contenuto(tmp_path):
    righe = _righe(tmp_path, {"projects/p.json": {"name": "Prog", "docs": [
        "non un oggetto",
        {"uuid": "d-vuoto", "filename": "vuoto.md", "content": ""},
        {"uuid": "d1", "filename": "a.md", "content": "testo", "created_at": "2026-01-01"},
        {"content": "senza nome né uuid"},
    ]}})
    assert righe[0] == ("d1", "project:Prog", "2026-01-01", "[a.md]\ntesto")
    assert len(righe) == 2 and righe[1][1:] == ("project:Prog", "", "senza nome né uuid")
    assert righe[1][0], "senza uuid la riga ne riceve uno calcolato"


def test_un_progetto_che_non_e_un_oggetto_non_da_righe(tmp_path):
    assert _righe(tmp_path, {"projects/p.json": ["lista"], "projects/q.json": "testo"}) == []


def test_una_design_chat_che_non_e_un_oggetto_non_ferma_l_ingest(tmp_path):
    righe = _righe(tmp_path, {"design_chats/d.json": "solo una stringa",
                              "projects/p.json": {"name": "", "docs": [{"content": "c"}]}})
    progetto = [r for r in righe if not isinstance(r, ai._Skip)]
    assert [r[1] for r in progetto] == ["project:senza-nome"]
