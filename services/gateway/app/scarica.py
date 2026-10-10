"""La rotta pubblica dei link firmati: GET /scarica/<nome>?t=<gettone> (P15, 10/10/2026).

`studio_download` (nb1777) ritorna un link valido 30 minuti per aprire un artefatto senza
la password del pannello. Questa rotta non ha autenticazione propria: il gettone È
l'autorizzazione, e a verificarlo è nb1777-mcp, l'unico che ne conosce la chiave. Qui si
inoltra in streaming (S13), si limita il ritmo per IP e si scrive l'audit.
"""
from __future__ import annotations

import logging
import time
from contextlib import AsyncExitStack

import httpx
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response, StreamingResponse

from . import nlm_client
from .audit import audit
from .ratelimit import RateLimiter

log = logging.getLogger("gateway.scarica")

# Un link si apre poche volte; chi prova gettoni a raffica no. 30 ogni 5 minuti per IP.
_LIMITE = RateLimiter(max_calls=30, window_s=300)

# Niente cache intermedie, niente Referer verso altri siti: il gettone sta nell'URL.
_INTESTAZIONI = {"cache-control": "no-store", "referrer-policy": "no-referrer",
                 "x-content-type-options": "nosniff"}


def _ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return (request.headers.get("x-forwarded-for", "") or "?").split(",")[0].strip()


async def scarica(request: Request) -> Response:
    ip = _ip(request)
    nome = request.path_params.get("name", "")
    if not _LIMITE.allow(ip, time.time()):
        return PlainTextResponse("troppe richieste: riprova fra qualche minuto",
                                 status_code=429, headers=_INTESTAZIONI)
    pila = AsyncExitStack()
    try:
        upstream, _client = await pila.enter_async_context(
            nlm_client.link_stream(nome, request.query_params.get("t", "")))
    except httpx.RequestError as exc:
        await pila.aclose()
        log.warning("scarica: nb1777-mcp irraggiungibile (%s)", exc)
        return PlainTextResponse("servizio non raggiungibile, riprova fra poco",
                                 status_code=503, headers=_INTESTAZIONI)
    if upstream.status_code != 200:
        try:
            await upstream.aread()
            motivo = str(upstream.json().get("reason") or "link non valido")
        except (ValueError, httpx.HTTPError):
            motivo = "link non valido"
        stato = upstream.status_code if upstream.status_code in (403, 404) else 502
        await pila.aclose()
        audit({"event": "link_scarica", "name": nome, "status": stato, "ip": ip,
               "esito": "rifiutato"})
        return PlainTextResponse(motivo, status_code=stato, headers=_INTESTAZIONI)
    audit({"event": "link_scarica", "name": nome, "status": 200, "ip": ip, "esito": "ok"})

    async def _pezzi():
        try:
            async for pezzo in upstream.aiter_raw():
                yield pezzo
        finally:
            await pila.aclose()

    safe = nome.replace('"', "").replace("\\", "")
    headers = dict(_INTESTAZIONI)
    headers["content-disposition"] = f'attachment; filename="{safe}"'
    if upstream.headers.get("content-length"):
        headers["content-length"] = upstream.headers["content-length"]
    return StreamingResponse(_pezzi(), media_type="application/octet-stream", headers=headers)
