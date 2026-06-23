"""
Helpers per emettere e verificare JWT con `typ` separati (sicurezza boundary).

typ:
  - "access"   — Bearer per /<SECRET>/<service>/mcp via claude.ai
  - "refresh"  — token long-lived per rinnovo access (claude.ai)
  - "admin"    — cookie del pannello /admin/*
  - "miniapp"  — JWT short-lived per Telegram Mini App
"""
from __future__ import annotations

import time
from typing import Any

import jwt

from .settings import get_settings


VALID_TYPS = {"access", "refresh", "admin", "miniapp"}


class JWTError(Exception):
    pass


def issue(
    *,
    typ: str,
    sub: str,
    aud: str,
    ttl: int,
    extra: dict[str, Any] | None = None,
) -> str:
    if typ not in VALID_TYPS:
        raise JWTError(f"typ '{typ}' non valido")
    s = get_settings()
    secret = s.effective_signing_secret
    if not secret:
        raise JWTError("OAUTH_SIGNING_SECRET non configurato")
    now = int(time.time())
    payload: dict[str, Any] = {
        "iss": s.gateway_public_base,
        "sub": sub,
        "aud": aud,
        "typ": typ,
        "iat": now,
        "exp": now + ttl,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, secret, algorithm="HS256")


def verify(
    token: str,
    *,
    expected_typ: str,
    expected_aud: str | None = None,
) -> dict[str, Any]:
    if expected_typ not in VALID_TYPS:
        raise JWTError(f"expected_typ '{expected_typ}' non valido")
    s = get_settings()
    secret = s.effective_signing_secret
    if not secret:
        raise JWTError("OAUTH_SIGNING_SECRET non configurato")
    options = {"verify_aud": expected_aud is not None}
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=expected_aud,
            options=options,
        )
    except jwt.PyJWTError as exc:
        raise JWTError(str(exc)) from exc
    # boundary: rifiuta token di tipo diverso
    if claims.get("typ") != expected_typ:
        raise JWTError(
            f"typ mismatch: atteso '{expected_typ}', ricevuto '{claims.get('typ')}'"
        )
    return claims
