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
