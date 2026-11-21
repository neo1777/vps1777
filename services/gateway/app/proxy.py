"""
Reverse proxy MCP — /<SECRET>/<service>/<path:path> → http://<upstream>/<path>.

Verifica:
  1. SECRET nel path == GATEWAY_SECRET
  2. Bearer token JWT typ=access (se OAUTH_REQUIRED=true)
  3. service ∈ GATEWAY_UPSTREAMS

Streaming bidirezionale via httpx.AsyncClient. Niente buffering (compatibilità
MCP streamable-http che usa chunked transfer + SSE).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any
from urllib.parse import unquote

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from .audit import audit
from .jwt_helpers import JWTError, verify
from .settings import get_settings

log = logging.getLogger(__name__)

# Header che non vanno propagati tra hop
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
}


# S11 (05/10/2026): una riga d'audit per ogni chiamata a un tool, con nome, durata ed
# esito. Prima `proxy_request` diceva solo servizio e status HTTP, scritto quando partono
# gli header: un tool che moriva a metà, o un client che chiudeva prima (claude.ai a
# circa 30 s), restava un 200. Gli ARGOMENTI non si registrano mai: possono essere
# testo personale; il nome del tool no.
_ERRORE_TOOL = b'"isError":true'


def tool_chiamati(body: bytes | None) -> list[str]:
    """I nomi dei tool in un corpo JSON-RPC (`tools/call` → `params.name`), anche in un
    batch. Nient'altro del corpo esce di qui."""
    if not body:
        return []
    try:
        msg = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return []
    nomi = []
    for m in msg if isinstance(msg, list) else [msg]:
        if isinstance(m, dict) and m.get("method") == "tools/call":
            nome = (m.get("params") or {}).get("name") if isinstance(m.get("params"), dict) else None
            nomi.append(str(nome)[:80] if nome else "?")
    return nomi


# Un batch JSON-RPC può portare migliaia di `tools/call`: nell'audit ne vanno i primi, e una riga
# sola dice quanti altri ce n'erano (una riga a chiamata, senza tetto, gonfiava il registro).
_TOOL_PER_RICHIESTA = 20


def _audit_tool(service: str, tools: list[str], t0: float, esito: str, status: int | None) -> None:
    ms = int((time.monotonic() - t0) * 1000)
    for nome in tools[:_TOOL_PER_RICHIESTA]:
        audit({"event": "proxy_tool", "service": service, "tool": nome,
               "ms": ms, "esito": esito, "status": status})
    if len(tools) > _TOOL_PER_RICHIESTA:
        audit({"event": "proxy_tool", "service": service,
               "tool": f"(altri {len(tools) - _TOOL_PER_RICHIESTA} nella stessa richiesta)",
               "ms": ms, "esito": esito, "status": status})


# ── un upstream lento non si prende tutto il gateway ────────────────────────────────────────
# Il tetto di connessioni è uno solo per tutto il processo (`GATEWAY_LIMIT_CONCURRENCY`): senza
# una quota per upstream, le chiamate ferme su un servizio lento occupavano tutti i posti, e il
# pannello, OAuth e l'altro servizio rispondevano 503. Ogni upstream può tenerne al più una
# quota; oltre, la richiesta riceve subito 503 con `Retry-After`.
_QUOTA_PER_UPSTREAM = 0.4
_in_corso: dict[str, int] = {}
_CORPO_TIMEOUT_S = 120.0     # entro quanto il client deve aver mandato il corpo


def _prendi_posto(service: str, s: Any) -> bool:
    tetto = max(1, int(int(getattr(s, "gateway_limit_concurrency", 100) or 100) * _QUOTA_PER_UPSTREAM))
    if _in_corso.get(service, 0) >= tetto:
        return False
    _in_corso[service] = _in_corso.get(service, 0) + 1
    return True


def _lascia_posto(service: str) -> None:
    _in_corso[service] = max(0, _in_corso.get(service, 0) - 1)


class _RispostaChiusa(StreamingResponse):
    """Una risposta in streaming che chiude l'upstream COMUNQUE finisca. La chiusura stava solo
    nel `finally` del generatore: se il client se ne andava prima che il generatore partisse,
    quel `finally` non girava mai e connessione e client restavano aperti."""

    def __init__(self, *args: Any, chiusura: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._chiusura = chiusura

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self._chiusura()


def _filter_headers(headers: dict[str, str]) -> dict[str, str]:
    # `x-vps1777-*` è il canale gateway↔servizio (il segreto degli endpoint interni viaggia lì):
    # quello che manda il CLIENT non si inoltra mai, lo aggiunge solo il gateway dove serve.
    return {k: v for k, v in headers.items()
            if k.lower() not in HOP_BY_HOP and not k.lower().startswith("x-vps1777-")}


def _segmenti_a_punti(sub_path: str) -> bool:
    """Un segmento `.` o `..`, anche con i punti scritti `%2e` (una o più volte codificati)."""
    for seg in sub_path.replace("\\", "/").split("/"):
        prima = None
        while seg != prima and "%" in seg:
            prima, seg = seg, unquote(seg)
        if seg in (".", ".."):
            return True
    return False


def _check_bearer(request: Request) -> tuple[bool, str | None, dict | None]:
    """
    Ritorna (ok, error_string, claims).
    Se OAUTH_REQUIRED=False, ritorna sempre (True, None, None).
    I claims escono di qui perché l'audit della chiamata proxata deve poter
    dire CHI (sub) e CON QUALE AGENTE (client_id): prima loggava solo
    event/service/method/status, e da un accesso sospetto si risaliva
    all'utente ma non al client che l'aveva fatto (vaglio corso1777, 03/09).
    """
    s = get_settings()
    if not s.oauth_required:
        return True, None, None
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return False, "missing_bearer", None
    token = auth_header.split(None, 1)[1].strip()
    try:
        claims = verify(token, expected_typ="access")
    except JWTError as exc:
        return False, str(exc), None
    # Il proxy non ha un'audience fissa (l'aud dei token è il client_id DCR),
    # ma vps1777 è single-owner: si lega il token al PROPRIETARIO. Un access
    # token il cui `sub` non è un'email ammessa non è per questo gateway.
    # FAIL-CLOSED sulla lista vuota. Prima era `if allowed and <sub> not in allowed`:
    # con `oauth_allowed_emails` vuota la condizione era sempre falsa, il ramo di
    # rifiuto non veniva mai preso e QUALUNQUE access token valido passava. Non è un
    # caso di laboratorio: `ADMIN_EMAIL` arriva dall'installer, che a `engine.py:494`
    # la scrive con `p.get('admin_email','')` senza validazione lato server (il
    # controllo è solo nel JS della pagina di setup).
    #
    # Il precedente è in questo stesso repo, sul gemello: `miniapp_core.is_owner`
    # ritorna False quando l'owner non è configurato — «Se non sappiamo chi è
    # l'owner, nessuno lo è». Qui la premessa è la stessa e sta due righe sopra:
    # vps1777 è single-owner e il token si lega al PROPRIETARIO. Senza proprietario
    # configurato, nessun token è per questo gateway.
    #
    # Il motivo è DISTINTO da `subject_not_allowed` di proposito: i due casi si
    # curano in modo opposto — uno è un accesso da rifiutare, l'altro è un'istanza
    # da configurare, e nell'audit log devono potersi contare separatamente.
    # (Il gemello suggerisce un 503 invece di un 401 per questo caso: qui il
    # chiamante mappa tutto a 401 e cambiarlo tocca il contratto HTTP — passo
    # successivo, deliberatamente fuori da questa patch.)
    allowed = {e.lower() for e in s.oauth_allowed_emails}
    if not allowed:
        return False, "owner_not_configured", None
    if str(claims.get("sub", "")).lower() not in allowed:
        return False, "subject_not_allowed", None
    return True, None, claims


async def proxy(request: Request) -> Response:
    s = get_settings()
    # Starlette tipizza `path_params` come dict[str, Any]: qui sono sempre stringhe del percorso
    path_params: dict[str, str] = request.path_params  # type: ignore[assignment]
    service = path_params.get("service", "")
    sub_path = path_params.get("path", "")

    negato, upstream, claims = _ammetti(request, s, path_params.get("secret", ""), service, sub_path)
    if negato is not None:
        return negato

    if not _prendi_posto(service, s):
        audit({"event": "proxy_upstream_busy", "service": service})
        return JSONResponse({"error": "upstream_busy"}, status_code=503,
                            headers={"retry-after": "5"})
    try:
        body = None
        if request.method in {"POST", "PUT", "PATCH"}:
            # un client che apre la richiesta e non manda il corpo non tiene il posto per sempre
            body = await asyncio.wait_for(request.body(), timeout=_CORPO_TIMEOUT_S)
    except asyncio.TimeoutError:
        _lascia_posto(service)
        return JSONResponse({"error": "request_timeout"}, status_code=408)
    except BaseException:
        _lascia_posto(service)
        raise
    return await _inoltra(request, service, upstream, sub_path, body, claims)


def _ammetti(request: Request, s: Any, secret: str, service: str,
             sub_path: str) -> tuple[Response | None, str, dict | None]:
    """I controlli prima dell'inoltro, nell'ordine in cui devono stare: percorso interno,
    segreto, servizio, bearer. Torna (rifiuto, upstream, claims): se `rifiuto` c'è, si risponde
    quello."""
    # 0. `internal/` NON si attraversa. Il proxy è un catch-all su {path:path}:
    # senza questo blocco, un client esterno raggiungerebbe gli endpoint privati
    # di un upstream via /<secret>/<service>/internal/... — compreso quello che
    # installa il profilo NotebookLM su nb1777-mcp (H6). Quel canale è solo
    # gateway↔servizio, sulla rete interna. Vale per OGNI upstream, plugin
    # futuri inclusi: chi scrive un plugin ha un prefisso riservato di cui
    # fidarsi. Rifiuto PRIMA di ogni altro check → non rivela nulla.
    # Il confronto da solo non bastava (giro di revisione del 21/11): `x/../internal/…` non
    # comincia per `internal/`, ma httpx toglie i segmenti `.` e `..` quando costruisce l'URL, e
    # all'upstream arrivava `/internal/…`. Quindi: un percorso con un segmento `.` o `..` (anche
    # scritto `%2e`) non passa affatto, nemmeno verso un percorso che interno non è.
    # Idem una barra in testa (`//internal/…`): nessun percorso vero ne ha.
    interno = sub_path == "internal" or sub_path.startswith("internal/")
    if interno or sub_path.startswith("/") or _segmenti_a_punti(sub_path):
        audit({"event": "proxy_internal_blocked", "service": service, "path": sub_path})
        return JSONResponse({"error": "not_found"}, status_code=404), "", None

    # 1. Secret check (constant-time)
    expected = s.effective_gateway_secret
    if not expected or not _constant_eq(secret, expected):
        audit({"event": "proxy_secret_mismatch", "service": service, "path": sub_path})
        return JSONResponse({"error": "not_found"}, status_code=404), "", None

    # 2. Service registry
    upstream = s.gateway_upstreams.get(service)
    if not upstream:
        audit({"event": "proxy_unknown_service", "service": service})
        return JSONResponse(
            {"error": "unknown_service", "available": sorted(s.gateway_upstreams)},
            status_code=404,
        ), "", None

    # 3. Bearer
    ok, err, claims = _check_bearer(request)
    if not ok:
        audit({"event": "proxy_auth_fail", "service": service, "reason": err})
        return JSONResponse(
            {"error": "unauthorized", "reason": err},
            status_code=401,
            headers={"www-authenticate": 'Bearer realm="vps1777"'},
        ), "", None
    return None, upstream, claims


async def _inoltra(request: Request, service: str, upstream: str, sub_path: str,
                   body: bytes | None, claims: dict | None) -> Response:
    """Manda la richiesta all'upstream e ne restituisce la risposta in streaming. Chi chiama ha
    già preso il posto per `service`: qui lo si lascia in OGNI uscita."""
    target = f"http://{upstream}/{sub_path}".rstrip("/")
    if request.url.query:
        target = f"{target}?{request.url.query}"

    headers = _filter_headers(dict(request.headers))
    # Forza Host = upstream cosicché il backend non confonda l'hostname pubblico
    headers["host"] = upstream
    # Il bearer si ferma QUI: è già stato verificato, nessun backend lo legge, e un
    # token che viaggia dove non serve è solo superficie d'attacco in più (token
    # passthrough — vaglio corso1777, 03/09). Se un giorno un backend dovesse
    # autenticare in proprio, gli si emette un token SUO (audience del servizio),
    # non si inoltra quello del client.
    headers.pop("authorization", None)

    method = request.method
    tools = tool_chiamati(body)
    t0 = time.monotonic()
    client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0), follow_redirects=False)

    try:
        # IMPORTANTE: send(stream=True) NON legge il body → poi lo streammiamo
        # con aiter_raw(). client.request() invece bufferizza tutto: un successivo
        # aiter_raw() solleverebbe httpx.StreamConsumed (rompendo OGNI proxy MCP).
        req = client.build_request(method, target, headers=headers, content=body)
        upstream_resp = await client.send(req, stream=True)
    except httpx.InvalidURL as exc:
        # un percorso che non è un URL (`a%00b`): colpa della richiesta, non dell'upstream
        await client.aclose()
        _lascia_posto(service)
        _audit_tool(service, tools, t0, "400", 400)
        return JSONResponse({"error": "bad_request", "reason": str(exc)}, status_code=400)
    except httpx.RequestError as exc:
        log.warning("proxy upstream error: %s", exc)
        await client.aclose()
        _lascia_posto(service)
        _audit_tool(service, tools, t0, "502", 502)
        return JSONResponse(
            {"error": "bad_gateway", "reason": str(exc)},
            status_code=502,
        )
    except BaseException:
        await client.aclose()
        _lascia_posto(service)
        raise

    audit({
        "event": "proxy_request",
        "service": service,
        "method": method,
        "status": upstream_resp.status_code,
        # CHI e CON QUALE AGENTE: sub è l'utente, client_id l'agente registrato
        # via DCR (nei nostri access token viaggia come `aud`). Con OAuth spento
        # restano None e la riga lo dice. NB: sub è un identificativo di persona
        # — la riga d'audit cambia classe di dato (vedi SECURITY.md §Audit).
        "sub": claims.get("sub") if claims else None,
        "client_id": claims.get("aud") if claims else None,
    })

    flusso = _Flusso(service, tools, t0, client, upstream_resp)
    return _RispostaChiusa(
        flusso.corpo(),
        status_code=upstream_resp.status_code,
        headers=_filter_headers(dict(upstream_resp.headers)),
        media_type=upstream_resp.headers.get("content-type"),
        chiusura=flusso.chiudi,
    )


class _Flusso:
    """Il corpo di una risposta dell'upstream mentre passa, e la sua chiusura. `esito` parte da
    «interrotto»: se il generatore non parte nemmeno è perché il client ha chiuso prima.
    `chiudi` gira una volta sola, chiamata dal generatore o dalla risposta: scrive l'esito dei
    tool, chiude upstream e client, lascia il posto dell'upstream."""

    def __init__(self, service: str, tools: list[str], t0: float,
                 client: httpx.AsyncClient, risposta: httpx.Response) -> None:
        self.service, self.tools, self.t0 = service, tools, t0
        self.client, self.risposta = client, risposta
        self.esito = "interrotto"
        self._chiuso = False

    async def chiudi(self) -> None:
        if self._chiuso:
            return
        self._chiuso = True
        try:
            _audit_tool(self.service, self.tools, self.t0, self.esito, self.risposta.status_code)
            await self.risposta.aclose()
            await self.client.aclose()
        finally:
            _lascia_posto(self.service)

    async def corpo(self) -> Any:
        """Passa il corpo byte per byte, guardando se un tool ha risposto con un errore."""
        esito, coda = "ok", b""
        try:
            async for chunk in self.risposta.aiter_raw():
                if self.tools and esito == "ok":
                    # il marcatore può cadere a cavallo di due pezzi: si tiene la coda
                    finestra = coda + chunk.replace(b'": ', b'":')
                    if _ERRORE_TOOL in finestra:
                        esito = "errore_tool"
                    coda = finestra[-len(_ERRORE_TOOL):]
                yield chunk
            self.esito = esito
        except httpx.TimeoutException:
            self.esito = "timeout"
            raise
        except (asyncio.CancelledError, GeneratorExit):
            self.esito = "interrotto"        # il client ha chiuso prima della fine
            raise
        except Exception:
            self.esito = "errore_stream"
            raise
        finally:
            await self.chiudi()


def _constant_eq(a: str, b: str) -> bool:
    """Confronta due stringhe in tempo costante, con la primitiva della libreria standard: la
    versione fatta in casa usciva subito se le lunghezze erano diverse, e così la lunghezza del
    segreto si poteva misurare. (Sui byte: `compare_digest` non accetta str non ASCII.)"""
    import hmac
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
