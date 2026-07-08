"""Entry point: avvia uvicorn con app Starlette."""
from __future__ import annotations

import logging
import sys

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from .routes import routes
from .settings import get_settings


class SecurityHeadersASGI:
    """Aggiunge header di sicurezza SAFE-per-tutti (nosniff, Referrer-Policy,
    HSTS su https). Pure-ASGI: inietta gli header su `http.response.start` senza
    bufferizzare il body → non rompe lo streaming del proxy MCP (a differenza di
    BaseHTTPMiddleware). CSP e X-Frame-Options DENY restano sulle sole pagine
    admin (in _layout): la mini-app Telegram deve poter stare in iframe."""

    def __init__(self, app, hsts: bool) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                present = {h[0].lower() for h in headers}

                def add(k: str, v: str) -> None:
                    if k.lower().encode() not in present:
                        headers.append((k.encode(), v.encode()))

                add("X-Content-Type-Options", "nosniff")
                add("Referrer-Policy", "no-referrer")
                if self.hsts:
                    add("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
            await send(message)

        await self.app(scope, receive, send_wrapper)


def build_app() -> Starlette:
    s = get_settings()
    middleware = [
        Middleware(SecurityHeadersASGI, hsts=s.gateway_public_base.startswith("https://")),
        Middleware(
            CORSMiddleware,
            allow_origins=s.oauth_cors_origins or ["*"],
            allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
            allow_headers=["*"],
            allow_credentials=True,
        ),
    ]
    return Starlette(routes=routes, middleware=middleware, debug=False)


def main() -> None:
    s = get_settings()
    logging.basicConfig(
        level=s.log_level.upper(),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
    )
    log = logging.getLogger("gateway")
    log.info("vps1777-gateway starting")
    log.info("public_base=%s", s.gateway_public_base or "(none)")
    log.info("upstreams=%s", s.gateway_upstreams)
    log.info("oauth_required=%s admin_email=%s", s.oauth_required, s.admin_email or "(none)")
    if not s.effective_gateway_secret:
        log.warning("GATEWAY_SECRET is EMPTY — proxy will reject all requests with 404")
    if not s.effective_signing_secret:
        log.warning("OAUTH_SIGNING_SECRET is EMPTY — JWT issuance will fail")

    uvicorn.run(
        "app.__main__:build_app",
        host=s.gateway_host,
        port=s.gateway_port,
        factory=True,
        log_config=None,  # usa il root logger configurato sopra
        access_log=True,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
