"""La rotta pubblica dei link di caricamento monouso: /carica/<gettone> (P15, 10/10/2026).

`source_upload_link` (nb1777) apre un link valido 15 minuti e una volta sola. In GET qui
c'è una pagina minima per scegliere il file; in PUT o POST il corpo è il file grezzo
(`curl -T file URL`) e passa in streaming a nb1777-mcp, che consuma il gettone, scrive il
file con un tetto, lo aggiunge come fonte e lo cancella. Il gateway non verifica niente
(non ha il registro dei gettoni): limita il ritmo per IP, passa, scrive l'audit.
"""
from __future__ import annotations

import logging
import secrets
import time
from urllib.parse import unquote

import httpx
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from . import nlm_client
from .audit import audit
from .ratelimit import RateLimiter

log = logging.getLogger("gateway.carica")

_LIMITE = RateLimiter(max_calls=20, window_s=300)
_INTESTAZIONI = {"cache-control": "no-store", "referrer-policy": "no-referrer"}

_PAGINA = """<!doctype html>
<html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Carica una fonte</title>
<style nonce="__N__">
:root{color-scheme:light dark;--fg:#1d1f23;--bg:#f6f6f4;--muted:#6b6f76;--line:#d5d6d2;--accent:#2d6cdf}
@media (prefers-color-scheme:dark){:root{--fg:#e8e8e6;--bg:#16181c;--muted:#9a9ea6;--line:#33363d;--accent:#6e9bff}}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif}
main{max-width:520px;margin:0 auto;padding:32px 16px}
h1{font-size:20px;margin:0 0 8px}p{color:var(--muted);margin:0 0 20px}
input,button{font:inherit;width:100%;box-sizing:border-box;margin-top:10px}
input{padding:12px;border:1px solid var(--line);border-radius:10px;background:none;color:var(--fg)}
button{padding:12px;border:0;border-radius:10px;background:var(--accent);color:#fff;font-weight:600}
button:disabled{opacity:.5}#esito{margin-top:18px;white-space:pre-wrap}
</style></head><body><main>
<h1>Carica una fonte nel notebook</h1>
<p>Il link vale una volta sola e per 15 minuti. Massimo 200 MB.</p>
<input type="file" id="f"><button id="b">Carica</button><div id="esito"></div>
<script nonce="__N__">
var b=document.getElementById('b'),e=document.getElementById('esito');
b.onclick=function(){var f=document.getElementById('f').files[0];if(!f)return;
b.disabled=true;e.textContent='Carico '+f.name+'…';
fetch(location.pathname+'?nome='+encodeURIComponent(f.name),{method:'PUT',body:f})
.then(function(r){return r.json().then(function(d){return [r.ok,d]})})
.then(function(x){e.textContent=x[0]?('Fatto: '+x[1].nome+' è una fonte del notebook.'):('Non è andata: '+(x[1].reason||x[1].error));})
.catch(function(err){b.disabled=false;e.textContent='Errore di rete: '+err;});};
</script></main></body></html>"""


def _ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return (request.headers.get("x-forwarded-for", "") or "?").split(",")[0].strip()


async def carica(request: Request) -> Response:
    gettone = request.path_params.get("t", "")
    if request.method == "GET":
        nonce = secrets.token_urlsafe(16)
        csp = (f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
               "connect-src 'self'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'")
        return HTMLResponse(_PAGINA.replace("__N__", nonce),
                            headers={**_INTESTAZIONI, "content-security-policy": csp})
    ip = _ip(request)
    if not _LIMITE.allow(ip, time.time()):
        return JSONResponse({"error": "rate_limited", "reason": "troppe richieste: riprova fra "
                             "qualche minuto"}, status_code=429, headers=_INTESTAZIONI)
    nome = unquote(request.query_params.get("nome") or request.headers.get("x-nome-file") or "file")
    try:
        r = await nlm_client.carica(gettone, nome, request.stream(),
                                    request.headers.get("content-length"))
    except httpx.RequestError as exc:
        log.warning("carica: nb1777-mcp irraggiungibile (%s)", exc)
        return JSONResponse({"error": "irraggiungibile", "reason": "servizio non raggiungibile, "
                             "riprova fra poco"}, status_code=503, headers=_INTESTAZIONI)
    try:
        dati = r.json()
    except ValueError:
        dati = {"error": "risposta_illeggibile"}
    audit({"event": "link_carica", "name": str(dati.get("nome") or nome), "status": r.status_code,
           "ip": ip, "esito": "ok" if r.status_code == 200 else "rifiutato"})
    return JSONResponse(dati, status_code=r.status_code, headers=_INTESTAZIONI)
