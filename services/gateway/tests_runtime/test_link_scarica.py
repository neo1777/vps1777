"""P15 (10/10/2026): la rotta pubblica /scarica/<nome>?t= del gateway.

Deps del lock: il gateway vero, nb1777-mcp finto. Il gateway non verifica il gettone (non
ne ha la chiave): lo passa a nb1777 e ne inoltra la risposta. Qui si prova che inoltra in
streaming, che un rifiuto torna come testo leggibile senza aprire niente, che si scrive
l'audit e che il ritmo per IP ha un tetto.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

from starlette.requests import Request

from app import scarica
from app.ratelimit import RateLimiter


class _Upstream:
    def __init__(self, status, corpo=b"", pezzi=(b"ab", b"cd")):
        self.status_code = status
        self.headers = {"content-length": "4"} if status == 200 else {}
        self._corpo, self._pezzi = corpo, pezzi

    async def aread(self):
        return self._corpo

    def json(self):
        return json.loads(self._corpo)

    async def aiter_raw(self):
        for p in self._pezzi:
            yield p


def _richiesta(nome, t="1.abc", ip="203.0.113.7"):
    return Request({"type": "http", "method": "GET", "path": f"/scarica/{nome}",
                    "headers": [], "query_string": f"t={t}".encode(),
                    "path_params": {"name": nome}, "client": (ip, 5555)})


def _prepara(monkeypatch, upstream):
    chiamate, audit, chiuso = [], [], []

    @asynccontextmanager
    async def finto(nome, gettone):
        chiamate.append((nome, gettone))
        try:
            yield upstream, None
        finally:
            chiuso.append(nome)

    monkeypatch.setattr(scarica.nlm_client, "link_stream", finto)
    monkeypatch.setattr(scarica, "audit", audit.append)
    monkeypatch.setattr(scarica, "_LIMITE", RateLimiter(max_calls=30, window_s=300))
    return chiamate, audit, chiuso


async def _leggi(resp):
    corpo = b""
    async for p in resp.body_iterator:
        corpo += p if isinstance(p, bytes) else p.encode()
    return corpo


def test_link_valido_passa_in_streaming(monkeypatch):
    chiamate, audit, chiuso = _prepara(monkeypatch, _Upstream(200))
    resp = asyncio.run(scarica.scarica(_richiesta("pod.m4a", t="99.firma")))
    assert resp.status_code == 200
    assert chiamate == [("pod.m4a", "99.firma")], "il gettone va a nb1777 così com'è"
    assert resp.headers["content-disposition"] == 'attachment; filename="pod.m4a"'
    assert resp.headers["cache-control"] == "no-store"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert asyncio.run(_leggi(resp)) == b"abcd"
    assert chiuso == ["pod.m4a"], "lo stream verso nb1777 si chiude a fine risposta"
    assert audit[0]["event"] == "link_scarica" and audit[0]["esito"] == "ok"


def test_link_rifiutato_torna_il_motivo(monkeypatch):
    corpo = json.dumps({"error": "link_non_valido",
                        "reason": "il link è scaduto (30 minuti)"}).encode()
    _, audit, chiuso = _prepara(monkeypatch, _Upstream(403, corpo))
    resp = asyncio.run(scarica.scarica(_richiesta("pod.m4a")))
    assert resp.status_code == 403
    assert "scaduto" in resp.body.decode()
    assert chiuso == ["pod.m4a"]
    assert audit[0]["status"] == 403 and audit[0]["esito"] == "rifiutato"


def test_il_ritmo_per_ip_ha_un_tetto(monkeypatch):
    _prepara(monkeypatch, _Upstream(403, b'{"reason": "no"}'))
    monkeypatch.setattr(scarica, "_LIMITE", RateLimiter(max_calls=2, window_s=300))
    stati = [asyncio.run(scarica.scarica(_richiesta("x.m4a"))).status_code for _ in range(3)]
    assert stati == [403, 403, 429]


def test_la_rotta_sta_prima_del_proxy():
    from app.routes import routes
    percorsi = [r.path for r in routes]
    assert percorsi.index("/scarica/{name}") < percorsi.index("/{secret}/{service}")
