"""
Reverse proxy MCP — /<SECRET>/<service>/<path:path> → http://<upstream>/<path>.

Verifica:
  1. SECRET nel path == GATEWAY_SECRET
  2. Bearer token JWT typ=access (se OAUTH_REQUIRED=true)
  3. service ∈ GATEWAY_UPSTREAMS

Streaming bidirezionale via httpx.AsyncClient. Niente buffering (compatibilità
MCP streamable-http che usa chunked transfer + SSE).
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from .audit import audit
from .jwt_helpers import JWTError, verify
from .settings import get_settings

log = logging.getLogger(__name__)

# Header che non vanno propagati tra hop
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
}


def _filter_headers(headers: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k.lower() not in HOP_BY_HOP}


def _check_bearer(request: Request) -> tuple[bool, str | None, dict | None]:
    """
    Ritorna (ok, error_string, claims).
    Se OAUTH_REQUIRED=False, ritorna sempre (True, None, None).
    I claims escono di qui perché l'audit della chiamata proxata deve poter
    dire CHI (sub) e CON QUALE AGENTE (client_id): prima loggava solo
    event/service/method/status, e da un accesso sospetto si risaliva
    all'utente ma non al client che l'aveva fatto (vaglio corso1777, 03/09).
    """
    s = get_settings()
    if not s.oauth_required:
        return True, None, None
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return False, "missing_bearer", None
    token = auth_header.split(None, 1)[1].strip()
    try:
        claims = verify(token, expected_typ="access")
    except JWTError as exc:
        return False, str(exc), None
    # Il proxy non ha un'audience fissa (l'aud dei token è il client_id DCR),
    # ma vps1777 è single-owner: si lega il token al PROPRIETARIO. Un access
    # token il cui `sub` non è un'email ammessa non è per questo gateway.
    # FAIL-CLOSED sulla lista vuota. Prima era `if allowed and <sub> not in allowed`:
    # con `oauth_allowed_emails` vuota la condizione era sempre falsa, il ramo di
    # rifiuto non veniva mai preso e QUALUNQUE access token valido passava. Non è un
    # caso di laboratorio: `ADMIN_EMAIL` arriva dall'installer, che a `engine.py:494`
    # la scrive con `p.get('admin_email','')` senza validazione lato server (il
    # controllo è solo nel JS della pagina di setup).
    #
    # Il precedente è in questo stesso repo, sul gemello: `miniapp_core.is_owner`
    # ritorna False quando l'owner non è configurato — «Se non sappiamo chi è
    # l'owner, nessuno lo è». Qui la premessa è la stessa e sta due righe sopra:
    # vps1777 è single-owner e il token si lega al PROPRIETARIO. Senza proprietario
    # configurato, nessun token è per questo gateway.
    #
    # Il motivo è DISTINTO da `subject_not_allowed` di proposito: i due casi si
    # curano in modo opposto — uno è un accesso da rifiutare, l'altro è un'istanza
    # da configurare, e nell'audit log devono potersi contare separatamente.
    # (Il gemello suggerisce un 503 invece di un 401 per questo caso: qui il
    # chiamante mappa tutto a 401 e cambiarlo tocca il contratto HTTP — passo
    # successivo, deliberatamente fuori da questa patch.)
    allowed = {e.lower() for e in s.oauth_allowed_emails}
    if not allowed:
        return False, "owner_not_configured", None
    if str(claims.get("sub", "")).lower() not in allowed:
        return False, "subject_not_allowed", None
    return True, None, claims


async def proxy(request: Request) -> Response:
    s = get_settings()
    path_params: dict[str, str] = request.path_params  # type: ignore[assignment]
    secret = path_params.get("secret", "")
    service = path_params.get("service", "")
    sub_path = path_params.get("path", "")

    # 0. `internal/` NON si attraversa. Il proxy è un catch-all su {path:path}:
    # senza questo blocco, un client esterno raggiungerebbe gli endpoint privati
    # di un upstream via /<secret>/<service>/internal/... — compreso quello che
    # installa il profilo NotebookLM su nb1777-mcp (H6). Quel canale è solo
    # gateway↔servizio, sulla rete interna. Vale per OGNI upstream, plugin
    # futuri inclusi: chi scrive un plugin ha un prefisso riservato di cui
    # fidarsi. Rifiuto PRIMA di ogni altro check → non rivela nulla.
    if sub_path == "internal" or sub_path.startswith("internal/"):
        audit({"event": "proxy_internal_blocked", "service": service, "path": sub_path})
        return JSONResponse({"error": "not_found"}, status_code=404)

    # 1. Secret check (constant-time)
    expected = s.effective_gateway_secret
    if not expected or not _constant_eq(secret, expected):
        audit({"event": "proxy_secret_mismatch", "service": service, "path": sub_path})
        return JSONResponse({"error": "not_found"}, status_code=404)

    # 2. Service registry
    upstream = s.gateway_upstreams.get(service)
    if not upstream:
        audit({"event": "proxy_unknown_service", "service": service})
        return JSONResponse(
            {"error": "unknown_service", "available": sorted(s.gateway_upstreams)},
            status_code=404,
        )

    # 3. Bearer
    ok, err, claims = _check_bearer(request)
    if not ok:
        audit({"event": "proxy_auth_fail", "service": service, "reason": err})
        return JSONResponse(
            {"error": "unauthorized", "reason": err},
            status_code=401,
            headers={"www-authenticate": 'Bearer realm="vps1777"'},
        )

    # 4. Forward
    target = f"http://{upstream}/{sub_path}".rstrip("/")
    if request.url.query:
        target = f"{target}?{request.url.query}"

    headers = _filter_headers(dict(request.headers))
    # Forza Host = upstream cosicché il backend non confonda l'hostname pubblico
    headers["host"] = upstream
    # Il bearer si ferma QUI: è già stato verificato tre righe sopra, nessun
    # backend lo legge, e un token che viaggia dove non serve è solo superficie
    # d'attacco in più (token passthrough — vaglio corso1777, 03/09). Se un
    # giorno un backend dovesse autenticare in proprio, gli si emette un token
    # SUO (audience del servizio), non si inoltra quello del client.
    headers.pop("authorization", None)

    method = request.method
    body = await request.body() if method in {"POST", "PUT", "PATCH"} else None

    timeout = httpx.Timeout(60.0, connect=5.0)
    client = httpx.AsyncClient(timeout=timeout, follow_redirects=False)

    try:
        # IMPORTANTE: send(stream=True) NON legge il body → poi lo streammiamo
        # con aiter_raw(). client.request() invece bufferizza tutto: un successivo
        # aiter_raw() solleverebbe httpx.StreamConsumed (rompendo OGNI proxy MCP).
        req = client.build_request(method, target, headers=headers, content=body)
        upstream_resp = await client.send(req, stream=True)
    except httpx.RequestError as exc:
        log.warning("proxy upstream error: %s", exc)
        await client.aclose()
        return JSONResponse(
            {"error": "bad_gateway", "reason": str(exc)},
            status_code=502,
        )

    audit({
        "event": "proxy_request",
        "service": service,
        "method": method,
        "status": upstream_resp.status_code,
        # CHI e CON QUALE AGENTE: sub è l'utente, client_id l'agente registrato
        # via DCR (nei nostri access token viaggia come `aud`). Con OAuth spento
        # restano None e la riga lo dice. NB: sub è un identificativo di persona
        # — la riga d'audit cambia classe di dato (vedi SECURITY.md §Audit).
        "sub": claims.get("sub") if claims else None,
        "client_id": claims.get("aud") if claims else None,
    })

    # Streaming response: passa attraverso il body byte-per-byte
    async def _gen() -> Any:
        try:
            async for chunk in upstream_resp.aiter_raw():
                yield chunk
        finally:
            await upstream_resp.aclose()
            await client.aclose()

    resp_headers = _filter_headers(dict(upstream_resp.headers))
    return StreamingResponse(
        _gen(),
        status_code=upstream_resp.status_code,
        headers=resp_headers,
        media_type=upstream_resp.headers.get("content-type"),
    )


def _constant_eq(a: str, b: str) -> bool:
    """Compare 2 stringhe in modo timing-safe."""
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a.encode("utf-8"), b.encode("utf-8")):
        result |= x ^ y
    return result == 0
