"""Le strade di `_iter_memories` (memories.json dell'export claude.ai): la memoria delle
conversazioni, quelle dei Project nelle due forme, i file di memoria, e ciò che si salta."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import archive_indexer as ai  # noqa: E402


def _righe(dati) -> list[tuple]:
    """(etichetta, ts, testo, sender) di ogni riga, nell'ordine."""
    return [(r[1], r[2], r[3], r[4]) for r in ai._iter_memories(dati)]


def test_un_account_solo_vale_come_una_lista_di_uno():
    acc = {"conversations_memory": "so questo"}
    assert _righe(acc) == _righe([acc]) == [("memory:conversations", "", "so questo", "memory")]


def test_cio_che_non_e_un_account_si_salta_e_il_vuoto_non_fa_righe():
    assert _righe(["testo", None, 3, {}, {"conversations_memory": "   "},
                   {"conversations_memory": 7}]) == []
    assert _righe(None) == []


def test_le_memorie_dei_project_come_mappa_prendono_la_chiave_o_il_nome():
    pm = {"uuid-1": "testo uno",
          "uuid-2": {"memory": "testo due", "name": "Progetto"},
          "uuid-3": {"content": "testo tre", "project_uuid": "altro-uuid"},
          "uuid-4": {"text": "testo quattro"},
          "uuid-5": {"name": "senza testo"},
          "uuid-6": "   ",
          "uuid-7": 42}
    assert _righe({"project_memories": pm}) == [
        ("memory:project:uuid-1", "", "testo uno", "memory"),
        ("memory:project:Progetto", "", "testo due", "memory"),
        ("memory:project:altro-uuid", "", "testo tre", "memory"),
        ("memory:project:uuid-4", "", "testo quattro", "memory"),
    ]


def test_le_memorie_dei_project_come_lista_prendono_la_posizione():
    assert _righe({"project_memories": ["zero", None, "due"]}) == [
        ("memory:project:0", "", "zero", "memory"),
        ("memory:project:2", "", "due", "memory"),
    ]
    assert _righe({"project_memories": "né mappa né lista"}) == []


def test_fra_memory_content_e_text_vince_il_primo_che_c_e_e_il_nome_batte_l_uuid():
    pm = {"k": {"memory": "", "content": "dal content", "text": "dal text",
                "name": "Nome", "project_uuid": "uuid"}}
    assert _righe({"project_memories": pm}) == [("memory:project:Nome", "", "dal content", "memory")]


def test_i_file_di_memoria_portano_percorso_e_data():
    files = [{"path": "/areas/a.md", "content": "corpo a", "updated_at": "2026-08-29T10:00:00Z"},
             {"name": "solo-nome", "content": "corpo b"},
             {"path": "/areas/c.md", "name": "ignorato", "content": "corpo c", "updated_at": None},
             {"content": "senza percorso"},
             {"path": "/areas/vuoto.md", "content": "  "},
             {"path": "/areas/non-testo.md", "content": 5},
             {"path": "/areas/senza-contenuto.md"},
             "non un oggetto"]
    assert _righe({"memory_files": files}) == [
        ("memory:file:/areas/a.md", "2026-08-29T10:00:00Z", "corpo a", "memory"),
        ("memory:file:solo-nome", "", "corpo b", "memory"),
        ("memory:file:/areas/c.md", "", "corpo c", "memory"),
    ]
    assert _righe({"memory_files": None}) == []


def test_l_ordine_e_conversazioni_poi_project_poi_file_account_per_account():
    acc = {"memory_files": [{"path": "f", "content": "file"}],
           "project_memories": {"p": "progetto"},
           "conversations_memory": "conversazioni"}
    etichette = [r[0] for r in _righe([acc, {"conversations_memory": "secondo"}])]
    assert etichette == ["memory:conversations", "memory:project:p", "memory:file:f",
                         "memory:conversations"]
