"""Middleware ASGI di header di sicurezza — puro stdlib, zero dipendenze.

Isolato qui (fuori da __main__, che importa starlette/uvicorn) così è
importabile e testabile in modo stdlib-only, come archive_indexer: la CI gira i
test del gateway con `uvx pytest` senza installare le deps pesanti.
(NB: `security.py` è un altro modulo — il wrapper bcrypt — e importa bcrypt.)
"""
from __future__ import annotations


class SecurityHeadersASGI:
    """Aggiunge header di sicurezza SAFE-per-tutti (nosniff, Referrer-Policy,
    HSTS su https). Pure-ASGI: inietta gli header su `http.response.start` senza
    bufferizzare il body → non rompe lo streaming del proxy MCP (a differenza di
    BaseHTTPMiddleware). CSP e X-Frame-Options DENY restano sulle sole pagine
    admin (in _layout): la mini-app Telegram deve poter stare in iframe.

    Sulle risposte admin aggiunge anche `Cache-Control: no-store`: le pagine di
    controllo devono dire SEMPRE la verità (es. la versione deployata nel footer),
    mai un render vecchio ricaricato dalla cache del browser. Path-based → vale
    anche per ogni endpoint admin futuro, senza doverlo ricordare handler per
    handler (stessa logica 'difesa a prescindere' del token CSRF).
    """

    def __init__(self, app, hsts: bool) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        _path = scope.get("path", "")
        is_admin = _path == "/admin" or _path.startswith("/admin/")

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
                if is_admin:
                    add("Cache-Control", "no-store")
            await send(message)

        await self.app(scope, receive, send_wrapper)
