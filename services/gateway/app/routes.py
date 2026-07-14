"""Registry routes Starlette."""
from __future__ import annotations

import asyncio

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import admin, miniapp, oauth, onboarding, proxy
from .asgi_security import ip_is_internal
from .settings import get_settings


async def health(request: Request) -> JSONResponse:
    s = get_settings()
    want_deep = bool(request.query_params.get("deep"))

    # ?deep proba i backend MCP via TCP: è un vettore d'abuso (port-scan /
    # amplificazione) se aperto a chiunque → riservato ai chiamanti interni
    # (H33). L'updater lo chiama via `compose exec` dentro il gateway → loopback;
    # un esterno viene risolto al suo IP pubblico via XFF → 403.
    client_host = request.client.host if request.client else None
    if want_deep and not ip_is_internal(client_host):
        return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)

    # Body pubblico MINIMO (H33): solo `{"ok": true}`. Niente `oauth_required`
    # (postura auth), niente banner `service`, e niente `upstreams` — i NOMI dei
    # servizi interni non li deve elencare un endpoint non autenticato. La Mini
    # App li prende ora da /app/api/overview (dietro Bearer). L'healthcheck Docker
    # e l'installer si accontentano di `{"ok": ...}`.
    body: dict = {"ok": True}
    if want_deep:
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
    # GET mostra la consent page (H8); POST è l'approvazione/rifiuto dell'admin.
    Route("/authorize", oauth.authorize, methods=["GET", "POST"]),
    Route("/token", oauth.token, methods=["POST"]),

    # Admin
    Route("/admin", admin.admin_root, methods=["GET"]),
    Route("/admin/", admin.admin_root, methods=["GET"]),
    Route("/admin/login", admin.login, methods=["GET", "POST"]),
    Route("/admin/logout", admin.logout, methods=["POST"]),
    Route("/admin/setup", onboarding.setup_view, methods=["GET", "POST"]),
    Route("/admin/nlm", admin.nlm_view, methods=["GET", "POST"]),
    Route("/admin/archive", admin.archive_view, methods=["GET", "POST"]),
    Route("/admin/archive/delete", admin.archive_delete, methods=["POST"]),
    Route("/admin/update", admin.update_view, methods=["GET", "POST"]),
    Route("/admin/update/state", admin.update_state, methods=["GET"]),
    Route("/admin/audit", admin.audit_view, methods=["GET"]),
    Route("/admin/secrets", admin.secrets_view, methods=["GET"]),

    # Mini App (pagina + API dietro Bearer typ=miniapp)
    Route("/app", miniapp.app_index, methods=["GET"]),
    Route("/app/", miniapp.app_index, methods=["GET"]),
    Route("/app/auth", miniapp.miniapp_auth, methods=["POST"]),
    Route("/app/api/overview", miniapp.api_overview, methods=["GET"]),
    Route("/app/api/plugins", miniapp.api_plugins, methods=["GET"]),
    Route("/app/api/notebooks", miniapp.api_notebooks, methods=["GET"]),
    Route("/app/api/ask", miniapp.api_ask, methods=["POST"]),
    Route("/app/api/archive/dbs", miniapp.api_archive_dbs, methods=["GET"]),
    Route("/app/api/archive/db/delete", miniapp.api_archive_db_delete, methods=["POST"]),
    Route("/app/api/archive/search", miniapp.api_archive_search, methods=["POST"]),
    Route("/app/api/secrets", miniapp.api_secrets, methods=["GET"]),
    Route("/app/api/audit", miniapp.api_audit, methods=["GET"]),
    Route("/app/api/update/state", miniapp.api_update_state, methods=["GET"]),
    Route("/app/api/update", miniapp.api_update_trigger, methods=["POST"]),

    # Reverse proxy MCP — catch-all, ULTIMA
    Route("/{secret}/{service}", proxy.proxy,
          methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]),
    Route("/{secret}/{service}/{path:path}", proxy.proxy,
          methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]),
]
