"""S13 (05/10/2026): il gateway non tiene in RAM un artefatto e non si ferma mentre indicizza.

① `nlm_artifact` diceva «inoltra in streaming» ma raccoglieva tutti i pezzi in una lista e
poi li univa: un video intero in memoria per ogni download, nel servizio esposto a Internet.
Ora restituisce una `StreamingResponse` che legge da nb1777-mcp mentre scrive al browser, e
chiude lo stream a valle quando ha finito.

② `index_file` (e la copia dell'upload) giravano DENTRO l'event loop: un archivio grosso da
`/admin/archive` fermava per minuti tutto il gateway, OAuth e proxy MCP compresi. Ora
girano in un thread, uno alla volta.

Deps del lock, come `test_gamba2_xff_da_destra.py`: admin vero, nb1777-mcp finto.
"""
from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager

from starlette.requests import Request
from starlette.responses import StreamingResponse

from app import admin, archive_indexer


class _Upstream:
    def __init__(self, eventi):
        self.status_code = 200
        self.headers = {"content-length": "6"}
        self.eventi = eventi

    async def aiter_raw(self):
        for i, pezzo in enumerate((b"ab", b"cd", b"ef")):
            self.eventi.append(f"pezzo {i}")
            yield pezzo


def _richiesta(nome: str) -> Request:
    return Request({"type": "http", "method": "GET", "path": f"/admin/nlm/artifact/{nome}",
                    "headers": [], "query_string": b"", "path_params": {"name": nome}})


def test_l_artefatto_passa_a_pezzi_e_lo_stream_si_chiude_dopo(monkeypatch):
    eventi: list[str] = []

    @asynccontextmanager
    async def finto_stream(nome):
        eventi.append("aperto")
        try:
            yield _Upstream(eventi), None
        finally:
            eventi.append("chiuso")

    async def admin_ok(request):
        return "a@example.invalid", None

    monkeypatch.setattr(admin.nlm_client, "artifact_stream", finto_stream)
    monkeypatch.setattr(admin, "_require_admin", admin_ok)
    monkeypatch.setattr(admin, "audit", lambda e: None)

    async def scenario():
        resp = await admin.nlm_artifact(_richiesta("podcast.mp3"))
        assert isinstance(resp, StreamingResponse), "il file intero passerebbe dalla RAM"
        assert eventi == ["aperto"], f"letto prima di rispondere: {eventi}"
        corpo = b"".join([p async for p in resp.body_iterator])
        return resp, corpo

    resp, corpo = asyncio.run(scenario())
    assert corpo == b"abcdef"
    assert eventi == ["aperto", "pezzo 0", "pezzo 1", "pezzo 2", "chiuso"]
    assert 'filename="podcast.mp3"' in resp.headers["content-disposition"]
    assert resp.headers["content-length"] == "6"


def test_index_file_non_gira_nel_thread_dell_event_loop(monkeypatch, tmp_path):
    """Si misura il thread dove gira `index_file` durante un upload vero da /admin/archive."""
    visto: dict[str, object] = {}

    def finto_index(path, db, project=""):
        visto["thread"] = threading.current_thread()
        return 1

    monkeypatch.setattr(archive_indexer, "index_file", finto_index)
    async def scenario():
        visto["loop"] = threading.current_thread()
        await admin._indicizza(str(tmp_path / "f.jsonl"), str(tmp_path / "x.db"), "")
    asyncio.run(scenario())
    assert visto["thread"] is not visto["loop"]
