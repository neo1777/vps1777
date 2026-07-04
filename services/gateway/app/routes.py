"""Registry routes Starlette."""
from __future__ import annotations

import asyncio

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import admin, miniapp, oauth, onboarding, proxy
from .settings import get_settings


async def health(request: Request) -> JSONResponse:
    s = get_settings()
    body: dict = {
        "ok": True,
        "service": "vps1777-gateway",
        "oauth_required": s.oauth_required,
        "upstreams": sorted(s.gateway_upstreams),
    }
    # ?deep=1: proba TCP gli upstream MCP dalla rete backend. Usato dal
    # health-gate di `vps1777 update` (via compose exec) — nessuna assunzione
    # su porte host, funziona con qualunque overlay ingress.
    if request.query_params.get("deep"):
        checks: dict[str, bool] = {}
        for name, hostport in s.gateway_upstreams.items():
            host, _, port = hostport.rpartition(":")
            try:
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, int(port)), timeout=3,
                )
                writer.close()
                await writer.wait_closed()
                checks[name] = True
            except (OSError, asyncio.TimeoutError, ValueError):
                checks[name] = False
        body["deep"] = checks
        if not all(checks.values()):
            body["ok"] = False
            return JSONResponse(body, status_code=503)
    return JSONResponse(body)


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
    Route("/admin/setup", onboarding.setup_view, methods=["GET", "POST"]),
    Route("/admin/nlm", admin.nlm_view, methods=["GET", "POST"]),
    Route("/admin/audit", admin.audit_view, methods=["GET"]),
    Route("/admin/secrets", admin.secrets_view, methods=["GET"]),

    # Mini App
    Route("/app", miniapp.app_index, methods=["GET"]),
    Route("/app/", miniapp.app_index, methods=["GET"]),
    Route("/app/auth", miniapp.miniapp_auth, methods=["POST"]),
    Route("/app/plugins", miniapp.plugins_list, methods=["GET"]),

    # Reverse proxy MCP — catch-all, ULTIMA
    Route("/{secret}/{service}", proxy.proxy,
          methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]),
    Route("/{secret}/{service}/{path:path}", proxy.proxy,
          methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]),
]
