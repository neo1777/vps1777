"""
OAuth 2.1 endpoints — Dynamic Client Registration + Authorization Code + PKCE.

In versione MVP supporto solo flow code+PKCE per claude.ai. Single-tenant:
l'allowed email è 1 (l'admin), e i client DCR sono accettati con storage
in-memory (clear su restart — sufficiente per claude.ai che ri-registra).

Per multi-tenant / multi-client persistente → tema futuro.
"""
from __future__ import annotations

import hashlib
import secrets as pysecrets
import time
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from .audit import audit
from .jwt_helpers import JWTError, issue, verify
from .settings import get_settings


# ───── storage in-memory (semplice, single-process) ─────
# Per scalare a multi-replica usa Redis/Postgres + token store condiviso.

_clients: dict[str, dict[str, Any]] = {}     # client_id → metadata
_codes: dict[str, dict[str, Any]] = {}       # code → {client_id, redirect_uri, sub, code_challenge, expires_at}
_revoked_refresh: set[str] = set()           # jti dei refresh_token revocati


# ───── discovery ─────

async def well_known_protected(_request: Request) -> Response:
    s = get_settings()
    return JSONResponse({
        "resource": s.gateway_public_base or "",
        "authorization_servers": [s.gateway_public_base or ""],
    })


async def well_known_authserver(_request: Request) -> Response:
    s = get_settings()
    base = s.gateway_public_base or ""
    return JSONResponse({
        "issuer": base,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/token",
        "registration_endpoint": f"{base}/register",
        "scopes_supported": ["mcp:read", "mcp:write"],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    })


# ───── DCR (Dynamic Client Registration) ─────

async def register(request: Request) -> Response:
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_request"}, status_code=400)
    redirect_uris = body.get("redirect_uris") or []
    if not isinstance(redirect_uris, list) or not redirect_uris:
        return JSONResponse(
            {"error": "invalid_redirect_uri"}, status_code=400,
        )
    client_id = pysecrets.token_urlsafe(16)
    _clients[client_id] = {
        "redirect_uris": redirect_uris,
        "client_name": body.get("client_name", "unknown"),
        "registered_at": int(time.time()),
    }
    audit({"event": "oauth_register", "client_id": client_id})
    return JSONResponse(
        {
            "client_id": client_id,
            "client_id_issued_at": int(time.time()),
            "redirect_uris": redirect_uris,
            "token_endpoint_auth_method": "none",
        },
        status_code=201,
    )


# ───── authorize ─────

async def authorize(request: Request) -> Response:
    """
    Step 1 di OAuth: l'utente arriva via browser → redirect a /admin/login
    se non loggato, altrimenti emette code.
    """
    qp = request.query_params
    client_id = qp.get("client_id", "")
    redirect_uri = qp.get("redirect_uri", "")
    state = qp.get("state", "")
    code_challenge = qp.get("code_challenge", "")
    code_challenge_method = qp.get("code_challenge_method", "")
    response_type = qp.get("response_type", "")

    if response_type != "code":
        return JSONResponse({"error": "unsupported_response_type"}, status_code=400)
    if code_challenge_method != "S256":
        return JSONResponse({"error": "invalid_request", "reason": "PKCE S256 required"}, status_code=400)
    client = _clients.get(client_id)
    if not client:
        return JSONResponse({"error": "invalid_client"}, status_code=400)
    if redirect_uri not in client["redirect_uris"]:
        return JSONResponse({"error": "invalid_redirect_uri"}, status_code=400)

    # Verifica admin cookie (se già loggato)
    from .admin import verify_admin_cookie  # import qui per evitare circular
    email = verify_admin_cookie(request)
    if not email:
        # Redirect a /admin/login con next_url=/authorize?... (preserva params)
        next_url = str(request.url)
        return RedirectResponse(f"/admin/login?next={next_url}", status_code=303)

    # Genera code
    code = pysecrets.token_urlsafe(32)
    _codes[code] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "sub": email,
        "code_challenge": code_challenge,
        "expires_at": int(time.time()) + 300,
    }
    audit({"event": "oauth_code_issued", "client_id": client_id, "sub": email})

    # Redirect con code + state
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(f"{redirect_uri}{sep}code={code}&state={state}", status_code=302)


# ───── token ─────

async def token(request: Request) -> Response:
    s = get_settings()
    try:
        form = await request.form()
    except Exception:
        return JSONResponse({"error": "invalid_request"}, status_code=400)

    grant_type = form.get("grant_type", "")

    if grant_type == "authorization_code":
        code = str(form.get("code", ""))
        client_id = str(form.get("client_id", ""))
        redirect_uri = str(form.get("redirect_uri", ""))
        code_verifier = str(form.get("code_verifier", ""))

        ctx = _codes.pop(code, None)
        if not ctx:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        if ctx["expires_at"] < int(time.time()):
            return JSONResponse({"error": "invalid_grant", "reason": "expired"}, status_code=400)
        if ctx["client_id"] != client_id or ctx["redirect_uri"] != redirect_uri:
            return JSONResponse({"error": "invalid_grant", "reason": "mismatch"}, status_code=400)

        # PKCE check
        expected = _b64url_sha256(code_verifier)
        if expected != ctx["code_challenge"]:
            return JSONResponse({"error": "invalid_grant", "reason": "pkce"}, status_code=400)

        access = issue(
            typ="access", sub=ctx["sub"], aud=client_id,
            ttl=s.oauth_access_token_lifetime,
        )
        refresh_jti = pysecrets.token_urlsafe(16)
        refresh = issue(
            typ="refresh", sub=ctx["sub"], aud=client_id,
            ttl=s.oauth_refresh_token_lifetime, extra={"jti": refresh_jti},
        )
        audit({"event": "oauth_access_issued", "sub": ctx["sub"], "client_id": client_id})
        return JSONResponse({
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": s.oauth_access_token_lifetime,
            "refresh_token": refresh,
        })

    if grant_type == "refresh_token":
        rt = str(form.get("refresh_token", ""))
        client_id = str(form.get("client_id", ""))
        try:
            claims = verify(rt, expected_typ="refresh", expected_aud=client_id)
        except JWTError:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        jti = claims.get("jti", "")
        if jti in _revoked_refresh:
            return JSONResponse({"error": "invalid_grant", "reason": "revoked"}, status_code=400)
        sub = claims.get("sub", "")
        access = issue(typ="access", sub=sub, aud=client_id, ttl=s.oauth_access_token_lifetime)
        audit({"event": "oauth_refresh_used", "sub": sub, "client_id": client_id})
        return JSONResponse({
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": s.oauth_access_token_lifetime,
            "refresh_token": rt,  # rotation futura
        })

    return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)


def _b64url_sha256(s: str) -> str:
    import base64
    digest = hashlib.sha256(s.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
