"""
OAuth 2.1 endpoints — Dynamic Client Registration + Authorization Code + PKCE.

In versione MVP supporto solo flow code+PKCE per claude.ai. Single-tenant:
l'allowed email è 1 (l'admin). I client DCR sono PERSISTITI su disco (volume
gateway-data) → i connector sopravvivono ai restart del gateway.

Per multi-tenant / multi-replica → store condiviso (Redis/Postgres).
"""
from __future__ import annotations

import hashlib
import json
import secrets as pysecrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from .audit import audit
from .jwt_helpers import JWTError, issue, verify
from .settings import get_settings


# ───── storage ─────
# I client DCR (registrazioni connector di claude.ai) sono PERSISTITI su disco
# (volume gateway-data): senza, ogni restart del gateway li perderebbe e ogni
# connector andrebbe ri-aggiunto su claude.ai. I codes sono effimeri (scadono in
# minuti) → restano in memoria. Per multi-replica → store condiviso (Redis/PG).

def _clients_file() -> Path:
    # accanto all'audit log, sul volume persistente /var/lib/gateway
    return Path(get_settings().audit_log_path).parent / "oauth_clients.json"


def _load_clients() -> dict[str, dict[str, Any]]:
    try:
        return json.loads(_clients_file().read_text())
    except Exception:
        return {}


def _save_clients() -> None:
    try:
        f = _clients_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(_clients))
    except Exception as exc:  # non fatale: resta in memoria per questa sessione
        audit({"event": "oauth_clients_persist_error", "error": str(exc)})


def _revoked_file() -> Path:
    return Path(get_settings().audit_log_path).parent / "oauth_revoked.json"


def _load_revoked() -> set[str]:
    try:
        return set(json.loads(_revoked_file().read_text()))
    except Exception:
        return set()


def _save_revoked() -> None:
    try:
        f = _revoked_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(sorted(_revoked_refresh)))
    except Exception as exc:  # non fatale: resta in memoria per questa sessione
        audit({"event": "oauth_revoked_persist_error", "error": str(exc)})


_clients: dict[str, dict[str, Any]] = _load_clients()  # client_id → metadata (persistito)
_codes: dict[str, dict[str, Any]] = {}       # code → {...} (effimero, in-memory)
# jti dei refresh_token già usati/revocati — PERSISTITO su disco (sopravvive ai
# restart: una revoca deve restare tale). Cresce coi refresh; a scala personale
# resta piccolo (i jti contano solo finché il token non sarebbe scaduto).
_revoked_refresh: set[str] = _load_revoked()


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
    _save_clients()   # persiste → sopravvive ai restart del gateway
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
    if not code_challenge:
        # senza challenge la PKCE non protegge nulla: il code sarebbe scambiabile
        # da chiunque lo intercetti. Rifiuta invece di emettere un code inutile.
        return JSONResponse({"error": "invalid_request", "reason": "code_challenge required"}, status_code=400)
    client = _clients.get(client_id)
    if not client:
        return JSONResponse({"error": "invalid_client"}, status_code=400)
    if redirect_uri not in client["redirect_uris"]:
        return JSONResponse({"error": "invalid_redirect_uri"}, status_code=400)

    # Verifica admin cookie (se già loggato)
    from .admin import verify_admin_cookie  # import qui per evitare circular
    email = verify_admin_cookie(request)
    if not email:
        # Redirect a /admin/login con next=<URL completo di /authorize>.
        # quote(safe="") è ESSENZIALE: l'URL di /authorize contiene i suoi
        # `&...` (code_challenge, code_challenge_method=S256, ...); senza
        # encoding quei parametri verrebbero letti come parametri di
        # /admin/login e PERSI → al ritorno la PKCE sparisce → "PKCE S256 required".
        next_url = quote(str(request.url), safe="")
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

    # Redirect con code + state. `state` è opaco e scelto dal client: va
    # url-encoded, o un '&'/'#' al suo interno spezzerebbe la query di redirect.
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(
        f"{redirect_uri}{sep}code={code}&state={quote(state, safe='')}", status_code=302)


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
            # REUSE DETECTION (OAuth 2.1 BCP): un refresh già ruotato/revocato
            # ripresentato = segnale di furto → rifiuta e logga.
            audit({"event": "oauth_refresh_reuse", "client_id": client_id, "jti": jti})
            return JSONResponse({"error": "invalid_grant", "reason": "revoked"}, status_code=400)
        sub = claims.get("sub", "")
        # ROTAZIONE: revoca (durevolmente) il refresh appena usato ed emettine uno
        # nuovo. Così un token rubato ha vita corta e il riuso si rileva.
        _revoked_refresh.add(jti)
        _save_revoked()
        access = issue(typ="access", sub=sub, aud=client_id, ttl=s.oauth_access_token_lifetime)
        new_jti = pysecrets.token_urlsafe(16)
        new_refresh = issue(typ="refresh", sub=sub, aud=client_id,
                            ttl=s.oauth_refresh_token_lifetime, extra={"jti": new_jti})
        audit({"event": "oauth_refresh_rotated", "sub": sub, "client_id": client_id})
        return JSONResponse({
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": s.oauth_access_token_lifetime,
            "refresh_token": new_refresh,
        })

    return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)


def _b64url_sha256(s: str) -> str:
    import base64
    digest = hashlib.sha256(s.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
