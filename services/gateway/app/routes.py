"""Registry routes Starlette."""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import admin, miniapp, oauth, proxy
from .settings import get_settings


async def health(_request: Request) -> JSONResponse:
    s = get_settings()
    return JSONResponse({
        "ok": True,
        "service": "vps1777-gateway",
        "oauth_required": s.oauth_required,
        "upstreams": sorted(s.gateway_upstreams),
    })


routes = [
    Route("/health", health, methods=["GET"]),

    # OAuth discovery
    Route("/.well-known/oauth-protected-resource", oauth.well_known_protected, methods=["GET"]),
    Route("/.well-known/oauth-authorization-server", oauth.well_known_authserver, methods=["GET"]),

    # OAuth core
    Route("/register", oauth.register, methods=["POST"]),
    Route("/authorize", oauth.authorize, methods=["GET"]),
    Route("/token", oauth.token, methods=["POST"]),

    # Admin
    Route("/admin", admin.admin_root, methods=["GET"]),
    Route("/admin/", admin.admin_root, methods=["GET"]),
    Route("/admin/login", admin.login, methods=["GET", "POST"]),
    Route("/admin/logout", admin.logout, methods=["POST"]),
    Route("/admin/nlm", admin.nlm_view, methods=["GET", "POST"]),
    Route("/admin/audit", admin.audit_view, methods=["GET"]),
    Route("/admin/secrets", admin.secrets_view, methods=["GET"]),

    # Mini App
    Route("/app", miniapp.app_index, methods=["GET"]),
    Route("/app/", miniapp.app_index, methods=["GET"]),
    Route("/app/auth", miniapp.miniapp_auth, methods=["POST"]),

    # Reverse proxy MCP — catch-all, ULTIMA
    Route("/{secret}/{service}", proxy.proxy,
          methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]),
    Route("/{secret}/{service}/{path:path}", proxy.proxy,
          methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]),
]
