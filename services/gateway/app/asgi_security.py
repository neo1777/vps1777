"""Helper di sicurezza a livello ASGI — puro stdlib, zero dipendenze.

Contiene il middleware degli header di sicurezza e due classificatori puri
(path che fanno davvero CORS, IP interni) usati da __main__ (scoping CORS) e da
routes (gate di /health?deep). Isolato qui (fuori da __main__, che importa
starlette/uvicorn) così è importabile e testabile in modo stdlib-only, come
archive_indexer: la CI gira i test del gateway con `uvx pytest` senza installare
le deps pesanti — starlette NON è disponibile lì.
(NB: `security.py` è un altro modulo — il wrapper bcrypt — e importa bcrypt.)
"""
from __future__ import annotations

import ipaddress

# CSP di default: rete di sicurezza globale per QUALSIASI risposta che non porti
# già la sua (H34). Le pagine admin (_layout) e Mini App (miniapp) impostano una
# CSP con nonce più permissiva: quella VINCE, perché il middleware aggiunge la
# default solo se l'header manca (add() rispetta present). Per JSON/redirect/SSE
# (health, OAuth, proxy MCP) `default-src 'none'` non rompe nulla — non caricano
# risorse — ma blinda ogni endpoint HTML futuro che si scordasse la sua CSP.
DEFAULT_CSP = "default-src 'none'; base-uri 'none'; frame-ancestors 'none'"

# Path che partecipano davvero a CORS cross-origin (H31): discovery + core OAuth
# (claude.ai chiama /register, /authorize, /token, /.well-known/oauth-*) e la
# Mini App (/app). Tutto il resto — /admin (same-origin + CSRF), il proxy MCP
# (parla via Bearer, non da browser) — NON deve vedere gli header CORS.
_CORS_EXACT = frozenset({"/register", "/authorize", "/token", "/app", "/app/"})


def is_cors_scoped_path(path: str) -> bool:
    """True se il path è uno di quelli che fanno CORS cross-origin legittimo."""
    return (
        path in _CORS_EXACT
        or path.startswith("/.well-known/oauth-")
        or path.startswith("/app/")
    )


def ip_is_internal(host: str | None) -> bool:
    """True se l'IP è loopback o in una rete privata (RFC1918/RFC4193/link-local).

    Usato per riservare /health?deep ai chiamanti interni: l'updater lo chiama
    via `compose exec` dentro il container gateway → 127.0.0.1 (loopback); un
    servizio della rete Docker backend arriva da un IP privato. Un chiamante
    esterno che passa dall'ingress viene risolto da uvicorn al suo IP PUBBLICO
    via X-Forwarded-For (forwarded_allow_ips include le reti private) → cade a
    False. `host` None/non-IP → False (fail-closed)."""
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


class SecurityHeadersASGI:
    """Aggiunge header di sicurezza SAFE-per-tutti (nosniff, Referrer-Policy,
    HSTS su https). Pure-ASGI: inietta gli header su `http.response.start` senza
    bufferizzare il body → non rompe lo streaming del proxy MCP (a differenza di
    BaseHTTPMiddleware). CSP e X-Frame-Options DENY restano sulle sole pagine
    admin (in _layout): la mini-app Telegram deve poter stare in iframe.

    Sulle risposte admin e sulle API della Mini App (/app/api) aggiunge anche
    `Cache-Control: no-store`: le pagine/dati di controllo devono dire SEMPRE la
    verità (es. la versione deployata, lo stato update), mai un render vecchio
    ricaricato dalla cache del browser/webview. Path-based → vale anche per ogni
    endpoint futuro sotto quei prefissi, senza doverlo ricordare handler per
    handler (stessa logica 'difesa a prescindere' del token CSRF). La pagina
    /app in sé resta cacheabile (statica), come /health e il proxy MCP.
    """

    def __init__(self, app, hsts: bool) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        _path = scope.get("path", "")
        no_store = (_path == "/admin" or _path.startswith("/admin/")
                    or _path.startswith("/app/api/") or _path == "/app/auth")

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                present = {h[0].lower() for h in headers}

                def add(k: str, v: str) -> None:
                    if k.lower().encode() not in present:
                        headers.append((k.encode(), v.encode()))

                add("X-Content-Type-Options", "nosniff")
                add("Referrer-Policy", "no-referrer")
                # Permissions-Policy: nega di default le API del browser che il
                # gateway non usa (camera, microfono, geolocalizzazione). COOP:
                # isola il contesto di navigazione da finestre cross-origin.
                add("Permissions-Policy", "geolocation=(), microphone=(), camera=(), usb=()")
                add("Cross-Origin-Opener-Policy", "same-origin")
                # CSP di default SOLO dove manca: admin/miniapp mettono la loro
                # (con nonce) prima, quindi present la contiene e add() la
                # rispetta — la default non sovrascrive chi ce l'ha già (H34).
                add("Content-Security-Policy", DEFAULT_CSP)
                if self.hsts:
                    add("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
                if no_store:
                    add("Cache-Control", "no-store")
            await send(message)

        await self.app(scope, receive, send_wrapper)
