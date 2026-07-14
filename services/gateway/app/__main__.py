"""Entry point: avvia uvicorn con app Starlette."""
from __future__ import annotations

import logging
import sys

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from .asgi_security import SecurityHeadersASGI, is_cors_scoped_path
from .routes import routes
from .settings import get_settings


class ScopedCORS:
    """CORSMiddleware applicato SOLO ai path che fanno davvero CORS cross-origin
    (discovery + core OAuth + Mini App /app) — vedi is_cors_scoped_path (H31).

    Perché non montarlo globale: con allow_credentials=True e claude.ai in
    allowlist, un CORS su TUTTA l'app lascerebbe claude.ai leggere le risposte di
    /admin (cookie dell'admin) via richiesta credenziata cross-origin. /admin è
    same-origin e già protetto da CSRF: non deve rispondere a preflight né
    esporre header CORS. Idem il proxy MCP (Bearer, non browser). Per i path
    fuori scope si va diritti all'app: nessun header CORS, nessun preflight."""

    def __init__(self, app, **cors_kwargs) -> None:
        self.plain = app
        self.cors = CORSMiddleware(app, **cors_kwargs)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and is_cors_scoped_path(scope.get("path", "")):
            await self.cors(scope, receive, send)
        else:
            await self.plain(scope, receive, send)


def build_app() -> Starlette:
    s = get_settings()
    middleware = [
        Middleware(SecurityHeadersASGI, hsts=s.gateway_public_base.startswith("https://")),
        Middleware(
            ScopedCORS,
            # niente fallback wildcard: con allow_credentials=True un `["*"]`
            # accoppiato ai cookie è pericoloso. Origine non configurata → CORS
            # spento (lista vuota, fail-closed). Il default è ["https://claude.ai"].
            allow_origins=s.oauth_cors_origins,
            allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
            # allow_headers=["*"] resta, ma ora è confinato agli endpoint OAuth +
            # /app (via ScopedCORS): l'origine è comunque ristretta a claude.ai e
            # il wildcard non tocca più /admin. Stringere a una allowlist di
            # header rischierebbe di rompere il preflight di claude.ai (che può
            # inviare header non previsti) senza chiudere nulla in più.
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
    # reda i segreti dagli access-log PRIMA di qualunque richiesta: il
    # gateway_secret vive nel path del proxy MCP → non deve finire in chiaro.
    from .logredact import install as _install_redact
    _install_redact([s.effective_gateway_secret])

    log = logging.getLogger("gateway")
    log.info("vps1777-gateway starting")
    log.info("public_base=%s", s.gateway_public_base or "(none)")
    log.info("upstreams=%s", s.gateway_upstreams)
    log.info("oauth_required=%s admin_email=%s", s.oauth_required, s.admin_email or "(none)")
    if not s.effective_gateway_secret:
        log.warning("GATEWAY_SECRET is EMPTY — proxy will reject all requests with 404")
    if not s.effective_signing_secret:
        log.warning("OAUTH_SIGNING_SECRET is EMPTY — JWT issuance will fail")
    if not s.telegram_owner_id:
        log.warning("TELEGRAM_OWNER_ID not set (or malformed → coerced to 0) — "
                    "Mini App /app/auth denies EVERYONE (fail-closed). Set it to enable.")

    uvicorn.run(
        "app.__main__:build_app",
        host=s.gateway_host,
        port=s.gateway_port,
        factory=True,
        log_config=None,  # usa il root logger configurato sopra
        access_log=True,
        proxy_headers=True,
        # Ristretto (era "*", che si fidava dell'XFF da chiunque → IP client
        # spoofabile). Default 127.0.0.1: fidati dell'XFF solo dal proxy locale.
        forwarded_allow_ips=s.gateway_forwarded_allow_ips,
    )


if __name__ == "__main__":
    main()
