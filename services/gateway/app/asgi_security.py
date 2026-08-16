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


# ───── Tetto sul BODY: contare i byte veri, non credere a chi li dichiara ─────
#
# PERCHÉ ESISTE (voce 92118d4e, aperta il 03/08 dal rilievo di b82df434 sulla #94):
#   la guardia sul `Content-Length` in admin.py copre il caso ONESTO. L'header lo
#   dichiara il CLIENT: chi vuole riempire il disco lo omette (transfer-encoding
#   chunked) o ci scrive un numero piccolo. E il taglio che conta i byte veri
#   (admin.py, il `while` sul chunk) parte quando `upload.file` è GIÀ PIENO —
#   starlette ha già bufferizzato tutto: protegge la destinazione, non l'arrivo.
#
# PERCHÉ QUI E NON NEL PROXY — misurato il 09/08, ed è il motivo per cui la cura
#   ha cambiato forma rispetto a come la voce la immaginava:
#     Caddy              nessun tetto oggi  → si può mettere (`request_body`)
#     cloudflared        tetto della PIATTAFORMA Cloudflare (100 MB, all'edge)
#     tailscale serve    NESSUN tetto sul body documentato — solo banda
#   ⇒ un tetto su Caddy copre UNO dei tre ingressi e lascia nudo proprio quello
#   di default (tailscale). L'unico punto che li vede tutti e tre è il gateway.
#   Caddy resta utile come difesa in profondità, non come la difesa.
BODY_CAP_DEFAULT = 32 * 1024 * 1024      # 32 MB — largo per form, OAuth, JSON-RPC MCP

# I path che ricevono upload VERI e hanno bisogno del tetto alto.
# ⚠️ È una lista enumerata a mano, e di solito è la forma che ci morde: chi non è
#   in lista non dà errore, dà silenzio. QUI NO, ed è la ragione per cui è
#   accettabile: chi manca prende il tetto BASSO e risponde 413 — l'omissione
#   fallisce RUMOROSAMENTE, al primo upload, invece di aprire un buco muto.
#   (Prefissi, non path esatti: come il `no_store` qui sotto, vale anche per gli
#   endpoint futuri sotto lo stesso ramo senza doverlo ricordare handler per handler.)
UPLOAD_PREFIXES = ("/admin/archive", "/admin/nlm")


def body_cap_for(path: str, *, default: int, upload: int) -> int:
    """Il tetto che vale per QUESTO path. Logica pura: stdlib, testabile senza rete."""
    for p in UPLOAD_PREFIXES:
        if path == p or path.startswith(p + "/"):
            return upload
    return default


class BodyCapASGI:
    """Chiude con 413 chi manda più byte del tetto, contandoli MENTRE arrivano.

    Pure-ASGI e non `BaseHTTPMiddleware` per la stessa ragione di
    SecurityHeadersASGI: non bufferizza, quindi non rompe lo streaming del proxy MCP.

    🔑 NON solleva un'eccezione al superamento, e non è un dettaglio di stile: le
    middleware utente stanno DENTRO `ServerErrorMiddleware`, che intercetta e
    risponde **500**. Un tetto che risponde «errore del server» quando il client
    manda troppo dice la cosa sbagliata a chi la legge (e non si distingue da un
    guasto nostro). Qui si risponde 413 direttamente e si consegna
    `http.disconnect` all'app, che smette di leggere da sé.
    """

    def __init__(self, app, *, default_max: int = BODY_CAP_DEFAULT,
                 upload_max: int = BODY_CAP_DEFAULT) -> None:
        self.app = app
        self.default_max = default_max
        self.upload_max = upload_max

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        tetto = body_cap_for(scope.get("path", ""),
                             default=self.default_max, upload=self.upload_max)
        stato = {"letti": 0, "risposto": False}

        async def send_413() -> None:
            stato["risposto"] = True
            await send({
                "type": "http.response.start",
                "status": 413,
                "headers": [(b"content-type", b"text/plain; charset=utf-8"),
                            (b"connection", b"close")],
            })
            await send({"type": "http.response.body",
                        "body": b"body oltre il tetto consentito\n"})

        # Difesa a costo zero PRIMA di leggere un byte: se il client DICHIARA più
        # del tetto, gli si crede — sulla sua parola si può solo rifiutare, mai
        # accettare. Un Content-Length assente o mentito cade nel conteggio sotto.
        for k, v in scope.get("headers") or []:
            if k.lower() == b"content-length":
                try:
                    if int(v) > tetto:
                        await send_413()
                        return
                except ValueError:
                    break
                break

        async def receive_contando():
            msg = await receive()
            if msg.get("type") == "http.request":
                stato["letti"] += len(msg.get("body", b"") or b"")
                if stato["letti"] > tetto:
                    if not stato["risposto"]:
                        await send_413()
                    # all'app diciamo che il client se n'è andato: smette di
                    # leggere senza che noi si debba sollevare nulla.
                    return {"type": "http.disconnect"}
            return msg

        async def send_filtrando(message):
            # Se abbiamo già risposto 413, l'app non deve poter iniziare la SUA
            # risposta: un secondo `http.response.start` è un errore di protocollo.
            if stato["risposto"]:
                return
            await send(message)

        await self.app(scope, receive_contando, send_filtrando)


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
