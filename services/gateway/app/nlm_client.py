"""
Il gateway NON possiede più il profilo NotebookLM: lo chiede a nb1777-mcp (H6).

Prima il gateway — l'unico servizio esposto su Internet — montava in scrittura
il volume coi cookie di sessione Google. Ora quel volume lo monta solo
nb1777-mcp; il gateway parla con lui su rete Docker interna, autenticandosi con
un segreto condiviso. Un gateway compromesso non può né leggere né riscrivere la
sessione Google: può solo chiedere «c'è un profilo?» e «installa questo tar».
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from .settings import get_settings

log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(30.0, connect=5.0)
_HEADER = "x-vps1777-internal"


def _base_and_headers() -> tuple[str, dict[str, str]]:
    s = get_settings()
    return s.nlm_internal_base.rstrip("/"), {_HEADER: s.effective_gateway_secret}


async def status() -> dict | None:
    """
    Stato del profilo: {"ok", "has_cookies", "pending"}.
    `None` se nb1777-mcp non è raggiungibile (l'admin lo mostra come tale invece
    di mentire dicendo "profilo assente").
    """
    base, headers = _base_and_headers()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(f"{base}/internal/nlm/status", headers=headers)
        if r.status_code != 200:
            log.warning("nlm status: nb1777-mcp ha risposto %s", r.status_code)
            return None
        return r.json()
    except (httpx.RequestError, ValueError) as exc:
        log.warning("nlm status: nb1777-mcp irraggiungibile (%s)", exc)
        return None


async def artifacts() -> list[dict] | None:
    """Gli artefatti scaricati da NotebookLM: [{name, bytes, mtime}].

    `None` se nb1777-mcp non risponde — la pagina lo dice, invece di mostrare una
    lista vuota che sembrerebbe «non ne hai» ([[la sonda senza credenziali]]).
    """
    base, headers = _base_and_headers()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(f"{base}/internal/nlm/artifacts", headers=headers)
        if r.status_code != 200:
            log.warning("nlm artifacts: nb1777-mcp ha risposto %s", r.status_code)
            return None
        return r.json().get("artifacts", [])
    except (httpx.RequestError, ValueError) as exc:
        log.warning("nlm artifacts: nb1777-mcp irraggiungibile (%s)", exc)
        return None


@asynccontextmanager
async def artifact_stream(name: str) -> AsyncIterator[tuple[httpx.Response, httpx.AsyncClient]]:
    """Apre lo STREAM di un artefatto. Il chiamante lo inoltra a valle senza bufferare.

    Un artefatto è un audio o un video: leggerlo in memoria nel gateway per poi
    riemetterlo significherebbe tenere in RAM un file intero per ogni download. Lo
    stesso motivo per cui `proxy.py` usa `send(stream=True)` invece di `request()`.

    Il gateway NON monta il volume: chiede il file a chi lo possiede (H6). Qui passa
    solo il NOME, e a validarlo è nb1777-mcp — che è l'unico a sapere cosa c'è dentro.
    """
    base, headers = _base_and_headers()
    client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=5.0))
    try:
        req = client.build_request(
            "GET", f"{base}/internal/nlm/artifact", params={"name": name}, headers=headers)
        resp = await client.send(req, stream=True)
    except httpx.RequestError:
        await client.aclose()
        raise
    try:
        yield resp, client
    finally:
        await resp.aclose()
        await client.aclose()


async def upload(content: bytes) -> tuple[int | None, str | None]:
    """
    Installa il profilo. Ritorna (#file, None) se ok, (None, motivo) se no.
    Un tar invalido viene rifiutato da nb1777-mcp SENZA toccare il profilo buono.
    """
    base, headers = _base_and_headers()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(
                f"{base}/internal/nlm/profile",
                headers={**headers, "content-type": "application/gzip"},
                content=content,
            )
    except httpx.RequestError as exc:
        return None, f"nb1777-mcp irraggiungibile ({exc})"

    if r.status_code == 200:
        try:
            return int(r.json().get("files", 0)), None
        except ValueError:
            return None, "risposta non valida da nb1777-mcp"
    try:
        reason = r.json().get("reason") or r.text
    except ValueError:
        reason = r.text
    return None, str(reason)
