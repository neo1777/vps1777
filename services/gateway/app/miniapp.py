"""
Mini App Telegram — la plancia mobile di vps1777.

Flusso: il bot apre la Mini App nel WebApp environment; Telegram inietta
`initData` (URL-encoded, firmato HMAC-SHA256 col TOKEN del bot). Il frontend la
POSTa a /app/auth, il server valida (e verifica che sia l'OWNER), e ritorna un
JWT typ=miniapp da usare come Bearer sugli endpoint /app/api/*.

Divisione delle superfici (per non duplicare):
  - /admin  (web)   → desktop, operazioni pesanti (setup, upload profilo nlm)
  - Mini App        → mobile, azioni frequenti con auth trasparente Telegram
  - bot             → notifiche + launcher + comandi testuali rapidi

Sicurezza:
  - /app/auth        → owner-only (telegram_owner_id), initData fresca (12h) e
                       firmata; IP negli eventi di fallimento (H11).
  - /app/api/*       → Bearer typ=miniapp obbligatorio E `sub` ancora owner
                       corrente (H27): il token non sopravvive alla revoca
                       dell'owner. Cache-Control: no-store (middleware); CSP con
                       nonce sulla pagina.
  - connettori MCP   → gli URL contengono il gateway_secret: la pagina mostra la
                       forma MASCHERATA, l'URL vero si chiede esplicitamente
                       (?reveal=<name>) ed è un evento di audit (H26).
  - niente CSRF: gli endpoint usano Bearer header (mai cookie) → un form
    cross-origin non può forgiarlo.
La validazione HMAC e il parsing MCP puri stanno in miniapp_core (stdlib-only,
testati); le chiamate tool agli upstream in mcp_client.
"""
from __future__ import annotations

import json
import os
import secrets as pysecrets
import time
from pathlib import Path

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from .archive_indexer import count_rows, db_info, find_db
from .audit import audit, read_recent
from .jwt_helpers import JWTError, issue, verify
from .mcp_client import MCPCallError, call_tool
from .ratelimit import RateLimiter
from .miniapp_core import (
    connector_url,
    extract_answer,
    is_owner,
    masked_connector_url,
    parse_json_blocks,
    summarize_secrets,
    verify_init_data,
    version_gt,
)
from .settings import get_settings

# Nomi degli upstream come registrati in GATEWAY_UPSTREAMS (default compose).
# Se un'installazione li rinomina, gli endpoint rispondono 503 con messaggio
# chiaro — documentato in docs/MINIAPP.md.
NB_SERVICE = "nb1777"
ARCHIVE_SERVICE = "archive"

# Base pubblica di fallback quando GATEWAY_PUBLIC_BASE non è configurata (dev).
DEFAULT_PUBLIC_BASE = "http://localhost:8080"

# L'UNICO asset esterno della Mini App. È anche la sorgente CSP (H35): costante
# unica così l'header e il tag <script> non possono divergere — se qualcuno
# cambia l'URL dell'SDK senza toccare la CSP, l'SDK smette di caricare subito,
# invece che allargare la CSP di nascosto.
TELEGRAM_SDK_URL = "https://telegram.org/js/telegram-web-app.js"


# ───── helpers ─────

def _client_ip(request: Request) -> str:
    """IP del chiamante — stesso pattern di admin.py:_client_ip (replicato, non
    importato, per non far dipendere la Mini App dal modulo del pannello).
    uvicorn gira con proxy_headers=True → request.client.host è già l'IP reale
    dietro l'ingress; fallback su X-Forwarded-For."""
    if request.client and request.client.host:
        return request.client.host
    return (request.headers.get("x-forwarded-for", "") or "?").split(",")[0].strip()


def _bearer_claims(request: Request) -> dict | None:
    """Estrae e verifica il Bearer token typ=miniapp. None se assente/invalido.

    H27 — non basta che il token sia integro: il `sub` dev'essere ANCORA l'owner
    corrente. La firma prova solo che il gateway l'ha emesso in passato; se
    l'owner cambia (o viene tolto dal .env), un token già emesso resterebbe
    buono fino a scadenza — una revoca che non revoca. Il controllo è a ogni
    richiesta, non solo all'emissione, e FAIL-CLOSED come is_owner/H1: owner non
    configurato → nessuno passa (get_settings è cachata: costa una lettura di
    attributo, non un I/O)."""
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    try:
        claims = verify(token, expected_typ="miniapp", expected_aud="miniapp")
    except JWTError:
        return None
    owner_id = get_settings().telegram_owner_id
    if not is_owner(claims.get("sub", ""), owner_id):
        # Token firmato ma non più dell'owner: o l'owner è cambiato, o è stato
        # rimosso. Evento raro e significativo → in audit con IP (mai in silenzio).
        audit({
            "event": "miniapp_bearer_not_owner",
            "sub": str(claims.get("sub", "")),
            "owner_configured": bool(owner_id),
            "ip": _client_ip(request),
            "path": request.url.path,
        })
        return None
    return claims


def _unauthorized() -> JSONResponse:
    return JSONResponse({"error": "unauthorized"}, status_code=401)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _mcp_error(exc: MCPCallError) -> JSONResponse:
    return JSONResponse({"error": "mcp_error", "detail": str(exc)}, status_code=503)


# ───── auth ─────

_AUTH_LIMIT = RateLimiter(max_calls=20, window_s=300)  # /app/auth: 20 ogni 5 min


async def miniapp_auth(request: Request) -> Response:
    """POST /app/auth — il frontend manda initData, riceve JWT typ=miniapp.
    Owner-only: solo l'utente Telegram configurato ottiene un token."""
    s = get_settings()
    # H11: l'IP è la sola coordinata forense di /app/auth (niente sessione, niente
    # cookie). Va in TUTTI gli eventi di fallimento, non solo nel rate limiter:
    # senza, un brute force di initData non lascia traccia di CHI l'ha tentato.
    ip = _client_ip(request)
    if not _AUTH_LIMIT.allow(ip, time.time()):
        return JSONResponse({"error": "rate_limited"}, status_code=429)
    bot_token = s.effective_bot_token
    if not bot_token:
        return JSONResponse({"error": "bot_token_not_configured"}, status_code=503)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_request"}, status_code=400)
    init_data = body.get("init_data", "")
    parsed = verify_init_data(init_data, bot_token)
    if not parsed:
        # firma non valida O initData più vecchia di INIT_DATA_MAX_AGE_S (12h, H27)
        audit({"event": "miniapp_auth_fail", "ip": ip})
        return JSONResponse({"error": "invalid_init_data"}, status_code=401)
    try:
        user = json.loads(parsed.get("user", "{}"))
    except json.JSONDecodeError:
        audit({"event": "miniapp_auth_bad_user", "ip": ip})
        return JSONResponse({"error": "invalid_user"}, status_code=400)
    user_id = str(user.get("id", "0"))
    if user_id == "0":
        audit({"event": "miniapp_auth_bad_user", "ip": ip})
        return JSONResponse({"error": "no_user_id"}, status_code=400)
    if not s.telegram_owner_id:
        # fail-closed: senza owner configurato NON si emette alcun token, o la
        # Mini App si aprirebbe a chiunque abbia initData valida. Errore chiaro.
        audit({"event": "miniapp_auth_no_owner", "ip": ip})
        return JSONResponse({"error": "owner_not_configured"}, status_code=503)
    if not is_owner(user_id, s.telegram_owner_id):
        # difesa in profondità: il bot mostra il bottone solo all'owner, ma qui
        # non ci si fida del client — un initData valido di un altro utente non
        # deve poter ottenere un token per questo gateway.
        audit({"event": "miniapp_auth_denied", "user_id": user_id, "ip": ip})
        return JSONResponse({"error": "not_owner"}, status_code=403)
    tok = issue(
        typ="miniapp", sub=user_id, aud="miniapp",
        ttl=s.oauth_miniapp_token_lifetime,
        extra={"username": user.get("username", "")},
    )
    audit({"event": "miniapp_auth_ok", "user_id": user_id, "ip": ip})
    return JSONResponse({
        "access_token": tok,
        "expires_in": s.oauth_miniapp_token_lifetime,
        "user": {
            "id": user_id,
            "username": user.get("username", ""),
            "first_name": user.get("first_name", ""),
        },
    })


# ───── API (tutte dietro Bearer typ=miniapp) ─────

async def api_overview(request: Request) -> Response:
    """GET /app/api/overview — versione, upstreams, riassunto secrets, update."""
    if not _bearer_claims(request):
        return _unauthorized()
    s = get_settings()
    ob = Path(s.onboarding_dir)
    status = _read_json(ob / "update_status.json")
    running = os.environ.get("VPS1777_VERSION", "dev")
    latest = str(status.get("latest") or "")
    return JSONResponse({
        "version": {
            "running": running,
            "tag": os.environ.get("VPS1777_TAG", "dev"),
            "latest": latest,
            # solo un VERO upgrade: latest != running proporrebbe un downgrade
            # quando il check giornaliero è stantio rispetto all'ultima release.
            "available": version_gt(latest, running),
        },
        "upstreams": sorted(s.gateway_upstreams),
        "secrets": summarize_secrets(_read_json(ob / "secrets_status.json")),
        "update_intent_pending": (ob / "update_pending_update.json").exists(),
    })


async def api_plugins(request: Request) -> Response:
    """GET /app/api/plugins — connettori MCP, URL **mascherato** (H26).
    GET /app/api/plugins?reveal=<name> — l'URL VERO di UN connettore, su
    richiesta esplicita dell'owner (tap su "Mostra"/"Copia").

    Il gateway_secret sta nel path dell'URL: se lo mette la risposta di default,
    finisce nel DOM di un telefono — e da lì in uno screenshot, nella
    condivisione schermo, nella clipboard che si sincronizza sul cloud. Quindi:
    di default mascherato, e il reveal è puntuale (un connettore per volta),
    audito, e mai memorizzato dalla pagina.

    Il reveal è un query param e non una rotta nuova di proposito: /app/api/*
    è già coperto da `Cache-Control: no-store` (asgi_security) e dal Bearer.
    """
    claims = _bearer_claims(request)
    if not claims:
        return _unauthorized()
    s = get_settings()
    secret = s.effective_gateway_secret
    base = s.gateway_public_base or DEFAULT_PUBLIC_BASE
    names = sorted(s.gateway_upstreams)

    reveal = str(request.query_params.get("reveal", "")).strip()
    if reveal:
        # il nome va risolto contro il listato reale: mai riflettere in una URL
        # col segreto una stringa scelta dal client
        if reveal not in names:
            return JSONResponse({"error": "unknown_connector"}, status_code=404)
        audit({"event": "miniapp_secret_revealed", "user_id": claims.get("sub", ""),
               "connector": reveal, "ip": _client_ip(request)})
        return JSONResponse({"name": reveal, "url": connector_url(base, secret, reveal),
                             "has_secret": bool(secret)})

    items = [
        {"name": name, "url_masked": masked_connector_url(base, name, has_secret=bool(secret))}
        for name in names
    ]
    return JSONResponse({"plugins": items, "has_secret": bool(secret)})


async def api_notebooks(request: Request) -> Response:
    """GET /app/api/notebooks — lista notebook NotebookLM (via nb1777-mcp)."""
    if not _bearer_claims(request):
        return _unauthorized()
    try:
        texts = await call_tool(NB_SERVICE, "nb_list", timeout=120.0)
    except MCPCallError as exc:
        return _mcp_error(exc)
    nbs = [
        {"id": n.get("id", ""), "title": n.get("title") or "(senza titolo)",
         "emoji": n.get("emoji", "")}
        for n in parse_json_blocks(texts) if n.get("id")
    ]
    return JSONResponse({"notebooks": nbs})


async def api_ask(request: Request) -> Response:
    """POST /app/api/ask {notebook_id, question} — domanda RAG su un notebook.
    Long-running: una query NotebookLM può richiedere minuti (timeout ~290s,
    ≥ del timeout subprocess di nb1777-mcp)."""
    claims = _bearer_claims(request)
    if not claims:
        return _unauthorized()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_request"}, status_code=400)
    nb_id = str(body.get("notebook_id", "")).strip()
    question = str(body.get("question", "")).strip()
    if not nb_id or not question:
        return JSONResponse({"error": "missing_fields"}, status_code=400)
    audit({"event": "miniapp_ask", "user_id": claims.get("sub", ""), "notebook": nb_id})
    try:
        texts = await call_tool(
            NB_SERVICE, "notebook_query",
            {"notebook_id": nb_id, "question": question}, timeout=290.0,
        )
    except MCPCallError as exc:
        return _mcp_error(exc)
    return JSONResponse({"answer": extract_answer(texts[0]) if texts else ""})


async def api_archive_dbs(request: Request) -> Response:
    """GET /app/api/archive/dbs — DB dell'archivio con la scheda completa
    (righe, etichette, top, dimensione, mtime). Letti direttamente dal volume
    condiviso (stessa fonte di /admin/archive), non via MCP: più ricco e non
    dipende dall'upstream per un dato che il gateway ha in casa."""
    if not _bearer_claims(request):
        return _unauthorized()
    db_dir = Path(get_settings().archive_db_dir)
    infos = ([db_info(p) for p in sorted(db_dir.glob("*.db")) if p.is_file()]
             if db_dir.is_dir() else [])
    return JSONResponse({"databases": infos})


async def api_archive_db_delete(request: Request) -> Response:
    """POST /app/api/archive/db/delete {db} — elimina un DB (irreversibile).

    Stessa semantica di /admin/archive/delete: nome risolto contro il listato
    reale (find_db, niente traversal), audit, archive-mcp se ne accorge da solo.
    """
    claims = _bearer_claims(request)
    if not claims:
        return _unauthorized()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_request"}, status_code=400)
    name = str(body.get("db", "")).strip()
    path = find_db(get_settings().archive_db_dir, name)
    if path is None:
        return JSONResponse({"error": "db_not_found"}, status_code=404)
    rows = count_rows(path)
    try:
        path.unlink()
    except OSError:
        audit({"event": "miniapp_archive_delete_err", "user_id": claims.get("sub", ""), "db": name})
        return JSONResponse({"error": "delete_failed"}, status_code=500)
    audit({"event": "miniapp_archive_delete", "user_id": claims.get("sub", ""),
           "db": name, "rows": rows})
    return JSONResponse({"ok": True, "db": name, "rows": rows})


async def api_archive_search(request: Request) -> Response:
    """POST /app/api/archive/search {query, db?, limit?} — ricerca FTS5."""
    if not _bearer_claims(request):
        return _unauthorized()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_request"}, status_code=400)
    query = str(body.get("query", "")).strip()
    if not query:
        return JSONResponse({"error": "missing_query"}, status_code=400)
    db = str(body.get("db", "")).strip()
    try:
        limit = max(1, min(int(body.get("limit", 20)), 50))
    except (ValueError, TypeError):
        limit = 20
    try:
        texts = await call_tool(
            ARCHIVE_SERVICE, "search",
            {"query": query, "db_name": db, "limit": limit}, timeout=30.0,
        )
    except MCPCallError as exc:
        return _mcp_error(exc)
    return JSONResponse({"results": parse_json_blocks(texts)})


async def api_secrets(request: Request) -> Response:
    """GET /app/api/secrets — stato scadenze secret (da secrets_status.json,
    scritto dal check host settimanale)."""
    if not _bearer_claims(request):
        return _unauthorized()
    status = _read_json(Path(get_settings().onboarding_dir) / "secrets_status.json")
    return JSONResponse({
        "checked_at": status.get("checked_at", ""),
        "secrets": status.get("secrets", []),
    })


async def api_audit(request: Request) -> Response:
    """GET /app/api/audit?n=50 — ultimi eventi audit (più recente per primo)."""
    if not _bearer_claims(request):
        return _unauthorized()
    try:
        n = max(1, min(int(request.query_params.get("n", "50")), 200))
    except ValueError:
        n = 50
    events = read_recent(n)
    events.reverse()
    return JSONResponse({"events": events})


async def api_update_state(request: Request) -> Response:
    """GET /app/api/update/state — versione running vs latest + progress."""
    if not _bearer_claims(request):
        return _unauthorized()
    s = get_settings()
    ob = Path(s.onboarding_dir)
    status = _read_json(ob / "update_status.json")
    running = os.environ.get("VPS1777_VERSION", "dev")
    latest = str(status.get("latest") or "")
    return JSONResponse({
        "running_version": running,
        "running_tag": os.environ.get("VPS1777_TAG", "dev"),
        "latest": latest,
        "available": version_gt(latest, running),
        "intent_pending": (ob / "update_pending_update.json").exists(),
        "checked_at": status.get("checked_at", ""),
        "changelog_excerpt": status.get("changelog_excerpt", ""),
        "progress": _read_json(ob / "update_progress.json"),
    })


async def api_update_trigger(request: Request) -> Response:
    """POST /app/api/update — richiede l'update all'ultima versione nota.
    Stesso meccanismo del pulsante admin: scrive l'intent, la CLI host
    (vps1777-update.path) lo applica entro pochi secondi."""
    claims = _bearer_claims(request)
    if not claims:
        return _unauthorized()
    s = get_settings()
    ob = Path(s.onboarding_dir)
    status = _read_json(ob / "update_status.json")
    latest = str(status.get("latest") or "")
    if not latest:
        return JSONResponse(
            {"error": "no_known_version",
             "detail": "nessuna versione nota: attendi il check giornaliero"},
            status_code=409)
    if not version_gt(latest, os.environ.get("VPS1777_VERSION", "dev")):
        # mai proporre/eseguire un downgrade da qui (la CLI lo rifiuterebbe
        # comunque, ma il gate va messo alla fonte)
        return JSONResponse(
            {"error": "not_an_upgrade",
             "detail": f"latest nota (v{latest}) non è più nuova della versione in esecuzione"},
            status_code=409)
    intent = {
        "target_version": latest,
        "requested_by": f"miniapp:{claims.get('sub', '')}",
        "requested_at": time.time(),
        "nonce": pysecrets.token_hex(16),
    }
    path = ob / "update_pending_update.json"
    path.write_text(json.dumps(intent, indent=2) + "\n")
    # 0644 come nell'admin: l'intent non contiene segreti e dev'essere leggibile
    # dalla CLI host (uid diverso dal container).
    path.chmod(0o644)
    audit({"event": "miniapp_update_requested", "by": claims.get("sub", ""), "target": latest})
    return JSONResponse({"ok": True, "target": latest})


# ───── pagina ─────

async def app_index(_request: Request) -> Response:
    """GET /app — la Mini App. HTML self-contained; l'unico asset esterno è
    l'SDK WebApp di Telegram. CSP con nonce per-risposta (niente inline
    arbitrario), coerente con l'hardening delle pagine admin."""
    nonce = pysecrets.token_urlsafe(16)
    page = _PAGE.replace("__NONCE__", nonce).replace("__SDK_URL__", TELEGRAM_SDK_URL)
    resp = HTMLResponse(page)
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        # H35: il PATH esatto dell'SDK, non tutto l'host telegram.org. `script-src
        # https://telegram.org` autorizzerebbe QUALUNQUE file servito da quel
        # dominio (upload, pagine, redirect interni) come script della Mini App.
        # La query string non partecipa al path-match CSP (?56 continua a passare);
        # un redirect cross-origin non viene ri-controllato sul path, quindi
        # restringere qui non rompe il caricamento dell'SDK.
        f"script-src 'nonce-{nonce}' {TELEGRAM_SDK_URL}; "
        # style-src resta 'unsafe-inline': la pagina usa attributi style="" inline
        # (layout) e l'SDK Telegram tocca gli stili del documento. Toglierlo
        # richiede riscrivere il markup in classi e verificarlo su un client vero:
        # NON fatto qui, dichiarato aperto (H35 resta parziale). Con un nonce/hash
        # in style-src, 'unsafe-inline' verrebbe IGNORATO dai browser e il layout
        # cadrebbe — una mezza misura qui rompe, non protegge.
        "style-src 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; "
        "base-uri 'none'; object-src 'none'; form-action 'none'"
        # niente frame-ancestors: la Mini App DEVE poter stare nell'iframe dei
        # client Telegram Web (web.telegram.org) e nelle webview native. Non ho
        # modo di verificare qui l'elenco COMPLETO degli origin che la incorniciano
        # (client web ufficiali + eventuali domini futuri): una lista incompleta la
        # renderebbe non apribile. Il guadagno sarebbe comunque ~nullo — un frame
        # ostile di /app non ottiene nulla: niente cookie (auth via Bearer in
        # memoria JS) e senza initData la pagina non chiama nemmeno /app/auth.
        # Se l'owner usa SOLO i client mobile/desktop, può aggiungere
        # "frame-ancestors https://web.telegram.org" e provare Telegram Web.
    )
    return resp


_PAGE = r"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>vps1777 · pannello</title>
<script src="__SDK_URL__"></script>
<style>
  :root{
    --bg:#0f1115; --card:#181b22; --fg:#e8eaed; --muted:#9aa0aa;
    --line:#272b34; --accent:#5aa2ff; --ok:#39d98a; --warn:#ffb020; --err:#ff5d5d;
  }
  @media (prefers-color-scheme:light){
    :root{--bg:#f2f3f5;--card:#fff;--fg:#14161a;--muted:#6b7280;--line:#e4e6eb;}
  }
  *{box-sizing:border-box}
  html,body{margin:0;height:100%}
  body{font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    background:var(--bg);color:var(--fg);display:flex;flex-direction:column}
  #head{display:flex;align-items:center;justify-content:space-between;
    padding:14px 16px 6px;max-width:640px;width:100%;margin:0 auto}
  #head h1{font-size:18px;margin:0}
  #head .chip{display:flex;align-items:center;gap:8px;color:var(--muted);font-size:13px}
  .avatar{width:26px;height:26px;border-radius:50%;background:var(--accent);color:#fff;
    display:flex;align-items:center;justify-content:center;font-weight:700;font-size:12px}
  #view{flex:1;overflow-y:auto;-webkit-overflow-scrolling:touch;padding:8px 16px 16px;
    max-width:640px;width:100%;margin:0 auto}
  #tabs{display:flex;border-top:1px solid var(--line);background:var(--card);
    padding-bottom:env(safe-area-inset-bottom);flex:0 0 auto}
  #tabs button{flex:1;background:none;border:0;color:var(--muted);font:inherit;
    font-size:12px;padding:9px 0 7px;cursor:pointer;display:flex;flex-direction:column;
    align-items:center;gap:2px}
  #tabs button .ic{font-size:19px;line-height:1}
  #tabs button.on{color:var(--accent);font-weight:600}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;
    padding:14px 16px;margin-bottom:12px}
  .card h2{font-size:12px;text-transform:uppercase;letter-spacing:.06em;
    color:var(--muted);margin:0 0 10px;display:flex;justify-content:space-between;align-items:center}
  .card h2 .re{cursor:pointer;color:var(--accent);font-size:14px;border:0;background:none}
  .kv{display:flex;justify-content:space-between;gap:10px;padding:4px 0;font-size:14px}
  .kv .k{color:var(--muted)}
  .dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:7px;vertical-align:middle}
  .dot.ok{background:var(--ok)}.dot.err{background:var(--err)}.dot.warn{background:var(--warn)}
  .badge{font-size:11px;border-radius:6px;padding:1px 7px;border:1px solid var(--accent);color:var(--accent)}
  .badge.warn{border-color:var(--warn);color:var(--warn)}
  .badge.ok{border-color:var(--ok);color:var(--ok)}
  .item{border:1px solid var(--line);border-radius:11px;padding:11px 12px;margin-top:10px}
  .item:first-of-type{margin-top:0}
  .item.tap{cursor:pointer}
  .item.tap:active{opacity:.65}
  .pn{font-weight:600;display:flex;align-items:center;gap:8px;word-break:break-word}
  .pm{color:var(--muted);font-size:12px;margin-top:2px;word-break:break-all}
  /* URL su una riga sua + i due bottoni (Mostra/Copia) sotto: su un telefono
     stretto tre elementi in fila schiacciano l'URL a niente. */
  .urlrow{display:flex;gap:8px;align-items:stretch;margin-top:8px;flex-wrap:wrap}
  code.url{flex:1 1 100%;min-width:0;background:var(--bg);border:1px solid var(--line);border-radius:8px;
    padding:8px 10px;font:12px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;
    overflow:auto;white-space:nowrap}
  button.b{background:var(--accent);color:#fff;border:0;border-radius:9px;
    padding:9px 16px;font:inherit;font-weight:600;cursor:pointer}
  button.b:disabled{opacity:.5}
  button.b.sm{padding:9px 14px;font-size:14px}
  button.b.ghost{background:none;border:1px solid var(--line);color:var(--fg)}
  button.b.danger{background:var(--warn);color:#14161a}
  textarea,input[type=text]{width:100%;background:var(--bg);border:1px solid var(--line);
    border-radius:10px;color:var(--fg);font:inherit;padding:10px 12px;outline:none}
  textarea:focus,input:focus{border-color:var(--accent)}
  textarea{min-height:84px;resize:vertical}
  select{background:var(--bg);border:1px solid var(--line);border-radius:10px;
    color:var(--fg);font:inherit;padding:9px 10px;max-width:46%}
  .srow{display:flex;gap:8px;margin-bottom:10px}
  .srow input{flex:1;min-width:0}
  .answer{white-space:pre-wrap;word-break:break-word;font-size:14px;
    background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:12px;margin-top:10px}
  .empty{text-align:center;color:var(--muted);padding:22px 8px}
  .spin{display:inline-block;width:14px;height:14px;border:2px solid var(--muted);
    border-top-color:var(--accent);border-radius:50%;animation:sp .8s linear infinite;
    vertical-align:-2px;margin-right:8px}
  @keyframes sp{to{transform:rotate(360deg)}}
  mark{background:none;color:var(--accent);font-weight:600}
  table{width:100%;border-collapse:collapse;font-size:13px}
  td,th{text-align:left;padding:6px 4px;border-bottom:1px solid var(--line);vertical-align:top}
  th{color:var(--muted);font-weight:500;font-size:11px;text-transform:uppercase}
  tr:last-child td{border-bottom:0}
  .ev{font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;padding:5px 0;
    border-bottom:1px solid var(--line);word-break:break-word}
  .ev:last-child{border-bottom:0}
  .ev .t{color:var(--muted)}
  #toast{position:fixed;left:50%;bottom:74px;transform:translateX(-50%);
    background:var(--fg);color:var(--bg);border-radius:10px;padding:8px 16px;
    font-size:13px;opacity:0;transition:opacity .25s;pointer-events:none;z-index:9}
  .back{border:0;background:none;color:var(--accent);font:inherit;cursor:pointer;
    padding:0 0 8px;display:inline-flex;align-items:center;gap:4px}
</style>
</head>
<body>
  <div id="head">
    <h1>vps1777</h1>
    <div class="chip" id="who" style="display:none">
      <span id="whoName"></span><div class="avatar" id="whoAv">?</div>
    </div>
  </div>
  <div id="view"></div>
  <div id="tabs">
    <button data-tab="stato"    class="on"><span class="ic">⌂</span>Stato</button>
    <button data-tab="notebook"><span class="ic">📓</span>Notebook</button>
    <button data-tab="archivio"><span class="ic">🔎</span>Archivio</button>
    <button data-tab="sistema"><span class="ic">⚙</span>Sistema</button>
  </div>
  <div id="toast"></div>

<script nonce="__NONCE__">
(function(){
"use strict";
var TG = (window.Telegram && window.Telegram.WebApp) ? window.Telegram.WebApp : null;
var $ = function(id){ return document.getElementById(id); };
var view = $('view');

// ── tema Telegram → variabili CSS
if (TG) {
  TG.ready(); TG.expand();
  var tp = TG.themeParams || {}, rs = document.documentElement.style;
  if (tp.bg_color) rs.setProperty('--bg', tp.bg_color);
  if (tp.secondary_bg_color) rs.setProperty('--card', tp.secondary_bg_color);
  if (tp.text_color) rs.setProperty('--fg', tp.text_color);
  if (tp.hint_color) rs.setProperty('--muted', tp.hint_color);
  if (tp.button_color) rs.setProperty('--accent', tp.button_color);
}

// ── stato
var S = { token:null, user:null, overview:null, plugins:null,
          notebooks:null, dbs:null, tab:'stato', nb:null, updTimer:null };

function esc(s){ return String(s==null?'':s).replace(/[&<>"']/g, function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
function toast(msg){ var t=$('toast'); t.textContent=msg; t.style.opacity='1';
  clearTimeout(t._h); t._h=setTimeout(function(){t.style.opacity='0';},1800); }
function spin(txt){ return '<div class="empty"><span class="spin"></span>'+esc(txt||'carico…')+'</div>'; }

// ── auth + api wrapper (re-auth automatica su 401: il token dura 1h,
//    l'initData 12h (H27) → dentro la finestra la pagina si ri-autentica da sola
//    in silenzio; oltre, /app/auth risponde 401 e va riaperta dal bot)
function authenticate(){
  if (!TG || !TG.initData) return Promise.reject(new Error('no_telegram'));
  return fetch('/app/auth', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({init_data: TG.initData})
  }).then(function(r){
    if (r.status===403) throw new Error('not_owner');
    if (!r.ok) throw new Error('auth_'+r.status);
    return r.json();
  }).then(function(a){ S.token=a.access_token; S.user=a.user; showWho(); return a; });
}
function api(path, opts, canRetry){
  if (canRetry===undefined) canRetry=true;
  var p = S.token ? Promise.resolve() : authenticate();
  return p.then(function(){
    opts = opts || {};
    var h = {}; for (var k in (opts.headers||{})) h[k]=opts.headers[k];
    h['Authorization'] = 'Bearer '+S.token;
    return fetch(path, {method:opts.method||'GET', headers:h, body:opts.body});
  }).then(function(r){
    if (r.status===401 && canRetry){ S.token=null; return api(path, opts, false); }
    return r.json().catch(function(){ return {}; }).then(function(d){
      if (!r.ok){ var e=new Error(d.detail||d.error||('HTTP '+r.status)); e.data=d; throw e; }
      return d;
    });
  });
}
function post(path, body){ return api(path, {method:'POST',
  headers:{'Content-Type':'application/json'}, body: JSON.stringify(body||{})}); }

function showWho(){
  if (!S.user) return;
  var nm = S.user.first_name || S.user.username || ('id '+S.user.id);
  $('whoName').textContent = S.user.username ? '@'+S.user.username : nm;
  $('whoAv').textContent = (nm||'?').trim().charAt(0).toUpperCase();
  $('who').style.display = 'flex';
}

// ── navigazione tab
var tabBtns = document.querySelectorAll('#tabs button');
Array.prototype.forEach.call(tabBtns, function(b){
  b.addEventListener('click', function(){ show(b.getAttribute('data-tab')); });
});
function show(tab){
  S.tab = tab; S.nb = null;
  if (TG && TG.BackButton) TG.BackButton.hide();
  if (S.updTimer){ clearInterval(S.updTimer); S.updTimer=null; }
  Array.prototype.forEach.call(tabBtns, function(b){
    b.classList.toggle('on', b.getAttribute('data-tab')===tab);
  });
  ({stato:renderStato, notebook:renderNotebook,
    archivio:renderArchivio, sistema:renderSistema}[tab])();
}
function needTelegram(){
  view.innerHTML = '<div class="card"><div class="empty">Questa sezione richiede '+
    'l\'apertura <b>dal bot Telegram</b> (bottone “Pannello” o /pannello).</div></div>';
}

// ══ TAB: Stato ══
function renderStato(){
  view.innerHTML =
    '<div class="card"><h2>Gateway</h2>'+
    '<div class="kv"><span class="k">stato</span><span id="stG"><span class="spin"></span></span></div>'+
    '<div class="kv"><span class="k">versione</span><span id="stV">—</span></div>'+
    '<div class="kv"><span class="k">connettori</span><span id="stU">—</span></div>'+
    '<div class="kv"><span class="k">secret</span><span id="stS">—</span></div></div>'+
    '<div class="card"><h2>Connettori MCP <button class="re" id="rePl">↻</button></h2>'+
    '<div id="stPl">'+spin()+'</div>'+
    '<div class="pm" id="stHint" style="display:none;margin-top:10px">Incolla un URL in '+
    '<b>claude.ai → Settings → Connectors</b> per collegare il gateway.<br>'+
    'L\'URL contiene il <b>segreto</b> del gateway: resta mascherato finché non tocchi '+
    '“Mostra”, e torna mascherato da solo dopo 30s.</div></div>';
  $('rePl').onclick = function(){ S.plugins=null; loadPlugins(); };

  fetch('/health').then(function(r){return r.json()}).then(function(h){
    $('stG').innerHTML = '<span class="dot ok"></span>online';
    $('stU').textContent = (h.upstreams||[]).join(', ') || '—';
  }).catch(function(){ $('stG').innerHTML = '<span class="dot err"></span>irraggiungibile'; });

  if (!TG || !TG.initData){
    $('stV').textContent='—'; $('stS').textContent='—';
    $('stPl').innerHTML='<div class="empty">Apri dal bot Telegram per i dettagli.</div>';
    return;
  }
  api('/app/api/overview').then(function(o){
    S.overview=o;
    var v=o.version||{};
    $('stV').innerHTML = esc(v.running||'—') + (v.available
      ? ' <span class="badge warn">v'+esc(v.latest)+' disponibile</span>'
      : ' <span class="badge ok">aggiornato</span>');
    var sc=o.secrets||{};
    $('stS').innerHTML = sc.total
      ? (sc.overdue ? '<span class="dot warn"></span>'+sc.overdue+' da ruotare'
                    : '<span class="dot ok"></span>tutti ok')
      : '—';
  }).catch(function(e){ $('stV').textContent = err(e); });
  loadPlugins();
}
function loadPlugins(){
  if (!TG || !TG.initData) return;
  if (S.plugins) return paintPlugins();
  $('stPl').innerHTML = spin();
  api('/app/api/plugins').then(function(d){ S.plugins=d.plugins||[]; paintPlugins(); })
    .catch(function(e){ $('stPl').innerHTML='<div class="empty">'+esc(err(e))+'</div>'; });
}
// ── connettori MCP: l'URL contiene il gateway_secret (H26)
// Il server manda solo la forma MASCHERATA: il segreto NON è nel DOM, e nemmeno
// in un attributo data-* (che è DOM a tutti gli effetti: ispezionabile, copiabile,
// visibile a chiunque legga la pagina). L'URL vero si chiede a ?reveal=<name> solo
// quando l'owner tocca "Mostra"/"Copia", vive in una variabile di closure, e
// sparisce dallo schermo da solo dopo REVEAL_MS.
var REVEAL_MS = 30000;               // ri-mascheramento automatico
var CLIP_KEY = 'vps1777_clip_warned';  // avviso clipboard: una tantum
var clipWarnedMem = false;             // fallback se localStorage è negato

function clipWarned(){
  try { return localStorage.getItem(CLIP_KEY)==='1'; } catch(e){ return clipWarnedMem; }
}
function setClipWarned(){
  try { localStorage.setItem(CLIP_KEY,'1'); } catch(e){ clipWarnedMem=true; }
}
function warnClipboard(next){
  if (clipWarned()) return next();
  var msg='L\'URL contiene il SEGRETO del gateway: chi ce l\'ha entra nei tuoi MCP.\n\n'+
    'La clipboard del telefono si sincronizza spesso sul cloud (iCloud / appunti '+
    'condivisi) ed è leggibile da altre app: incolla subito e poi copia altro per '+
    'svuotarla.\n\nProcedo con la copia?';
  var go=function(ok){ if(!ok) return; setClipWarned(); next(); };
  if (TG && TG.showConfirm) TG.showConfirm(msg, go); else go(window.confirm(msg));
}
function revealUrl(name){  // → Promise<string> (l'URL vero, mai messo in S)
  return api('/app/api/plugins?reveal='+encodeURIComponent(name)).then(function(d){ return d.url||''; });
}
function paintPlugins(){
  var box=$('stPl'); if(!box) return;
  if (!S.plugins.length){ box.innerHTML='<div class="empty">Nessun connettore attivo.</div>'; return; }
  box.innerHTML='';
  S.plugins.forEach(function(p){
    var el=document.createElement('div'); el.className='item';
    el.innerHTML='<div class="pn">'+esc(p.name)+' <span class="badge">MCP</span></div>'+
      '<div class="urlrow"><code class="url"></code>'+
      '<button class="b sm ghost" data-act="show">Mostra</button>'+
      '<button class="b sm" data-act="copy">Copia</button></div>';
    var code=el.querySelector('code');
    var bShow=el.querySelector('[data-act=show]');
    var bCopy=el.querySelector('[data-act=copy]');
    var shown=null, timer=null;  // l'URL in chiaro vive QUI, non nel DOM né in S

    var mask=function(){
      if (timer){ clearTimeout(timer); timer=null; }
      shown=null; code.textContent=p.url_masked; bShow.textContent='Mostra';
    };
    var unmask=function(url){
      shown=url; code.textContent=url; bShow.textContent='Nascondi';
      if (timer) clearTimeout(timer);
      timer=setTimeout(mask, REVEAL_MS);  // non lasciarlo sullo schermo a oltranza
    };
    mask();

    bShow.onclick=function(){
      if (shown) return mask();
      bShow.disabled=true;
      revealUrl(p.name).then(function(u){ bShow.disabled=false; unmask(u); })
        .catch(function(e){ bShow.disabled=false; toast('Errore: '+err(e)); });
    };
    bCopy.onclick=function(){
      warnClipboard(function(){
        bCopy.disabled=true;
        revealUrl(p.name).then(function(u){
          bCopy.disabled=false;
          if (navigator.clipboard && navigator.clipboard.writeText){
            navigator.clipboard.writeText(u).then(function(){ toast('Copiato ✓'); },
              function(){ unmask(u); toast('Tieni premuto sull\'URL per copiarlo'); });
          } else { unmask(u); toast('Tieni premuto sull\'URL per copiarlo'); }
        }).catch(function(e){ bCopy.disabled=false; toast('Errore: '+err(e)); });
      });
    };
    box.appendChild(el);
  });
  $('stHint').style.display='block';
}

// ══ TAB: Notebook ══
function renderNotebook(){
  if (!TG || !TG.initData) return needTelegram();
  view.innerHTML = '<div class="card"><h2>Notebook <button class="re" id="reNb">↻</button></h2>'+
    '<div id="nbList">'+spin('carico i notebook…')+'</div></div>';
  $('reNb').onclick=function(){ S.notebooks=null; renderNotebook(); };
  if (S.notebooks) return paintNbs();
  api('/app/api/notebooks').then(function(d){ S.notebooks=d.notebooks||[]; paintNbs(); })
    .catch(function(e){ var b=$('nbList'); if(b) b.innerHTML='<div class="empty">'+esc(err(e))+'</div>'; });
}
function paintNbs(){
  var box=$('nbList'); if(!box) return;
  if (!S.notebooks.length){ box.innerHTML='<div class="empty">Nessun notebook (profilo nlm caricato?).</div>'; return; }
  box.innerHTML='';
  S.notebooks.forEach(function(n){
    var el=document.createElement('div'); el.className='item tap';
    el.innerHTML='<div class="pn">'+(n.emoji?esc(n.emoji)+' ':'')+esc(n.title)+'</div>'+
      '<div class="pm">'+esc(n.id)+'</div>';
    el.onclick=function(){ askView(n); };
    box.appendChild(el);
  });
}
function askView(nb){
  S.nb=nb;
  if (TG && TG.BackButton){ TG.BackButton.show(); TG.BackButton.onClick(backToNbs); }
  view.innerHTML =
    '<button class="back" id="bk">← notebook</button>'+
    '<div class="card"><h2>'+(nb.emoji?esc(nb.emoji)+' ':'')+esc(nb.title)+'</h2>'+
    '<textarea id="q" placeholder="La tua domanda su questo notebook…"></textarea>'+
    '<div style="margin-top:10px;display:flex;gap:8px;align-items:center">'+
    '<button class="b" id="go">Chiedi</button><span class="pm" id="wait"></span></div>'+
    '<div id="ans"></div></div>';
  $('bk').onclick=backToNbs;
  $('go').onclick=function(){
    var q=$('q').value.trim(); if(!q) return;
    var go=$('go'), w=$('wait'), t0=Date.now();
    go.disabled=true; $('ans').innerHTML='';
    var tick=setInterval(function(){
      w.innerHTML='<span class="spin"></span>NotebookLM… '+Math.round((Date.now()-t0)/1000)+'s (può richiedere minuti)';
    },1000);
    post('/app/api/ask', {notebook_id:nb.id, question:q}).then(function(d){
      clearInterval(tick); w.textContent=Math.round((Date.now()-t0)/1000)+'s';
      go.disabled=false;
      $('ans').innerHTML='<div class="answer"></div>';
      $('ans').firstChild.textContent=d.answer||'(risposta vuota)';
    }).catch(function(e){
      clearInterval(tick); w.textContent=''; go.disabled=false;
      $('ans').innerHTML='<div class="answer" style="border-color:var(--err)"></div>';
      $('ans').firstChild.textContent='Errore: '+err(e);
    });
  };
}
function backToNbs(){
  if (TG && TG.BackButton){ TG.BackButton.hide(); TG.BackButton.offClick(backToNbs); }
  renderNotebook();
}

// ══ TAB: Archivio ══
function renderArchivio(){
  if (!TG || !TG.initData) return needTelegram();
  view.innerHTML = '<div class="card"><h2>Cerca nell\'archivio</h2>'+
    '<div class="srow"><input type="text" id="aq" placeholder="parole chiave…">'+
    '<select id="adb"><option value="">tutti</option></select></div>'+
    '<button class="b" id="ago">Cerca</button>'+
    '<div id="ares" style="margin-top:10px"></div></div>'+
    '<div class="card"><h2>DB caricati <button class="re" id="reDbs">↻</button></h2>'+
    '<div id="adbs">'+spin()+'</div></div>';
  var go=function(){ archSearch(); };
  $('ago').onclick=go;
  $('aq').addEventListener('keydown', function(ev){ if(ev.key==='Enter') go(); });
  $('reDbs').onclick=loadDbs;
  if (S.dbs) paintDbs();  // cache per la reattività; poi rinfresco comunque
  loadDbs();
}
function loadDbs(){
  api('/app/api/archive/dbs').then(function(d){ S.dbs=d.databases||[]; paintDbs(); })
    .catch(function(e){ var b=$('adbs'); if(b) b.innerHTML='<div class="empty">'+esc(err(e))+'</div>'; });
}
function fmtSize(n){
  var u=['B','KB','MB','GB']; var i=0; n=n||0;
  while (n>=1024 && i<u.length-1){ n/=1024; i++; }
  return (i? n.toFixed(1) : n)+' '+u[i];
}
function paintDbs(){
  var sel=$('adb');
  if (sel){
    while (sel.options.length>1) sel.remove(1);  // reset (oltre "tutti")
    S.dbs.forEach(function(db){
      var o=document.createElement('option'); o.value=db.name; o.textContent=db.name; sel.appendChild(o);
    });
  }
  var box=$('adbs'); if(!box) return;
  if (!S.dbs.length){
    box.innerHTML='<div class="empty">Archivio vuoto — carica una fonte da /admin/archive.</div>'; return;
  }
  box.innerHTML='';
  S.dbs.forEach(function(db){
    var el=document.createElement('div'); el.className='item';
    var top=(db.top||[]).slice(0,3).map(function(t){
      return esc(t.label||'(senza etichetta)')+' ('+t.rows+')'; }).join(' · ');
    el.innerHTML='<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px">'+
      '<div style="min-width:0"><div style="font-weight:600">'+esc(db.name)+'</div>'+
      '<div class="pm">'+db.rows+' messaggi · '+db.labels+' etichette · '+fmtSize(db.size)+
      (db.mtime?' · '+esc(String(db.mtime).slice(0,10)):'')+'</div>'+
      (top?'<div class="pm" style="margin-top:2px">'+top+'</div>':'')+'</div>'+
      '<button class="b danger" style="width:auto;flex:none;padding:8px 12px">🗑</button></div>';
    el.querySelector('button').onclick=function(){ confirmDeleteDb(db.name, db.rows); };
    box.appendChild(el);
  });
}
function confirmDeleteDb(name, rows){
  var msg='Eliminare il DB "'+name+'" ('+rows+' messaggi)? L\'operazione non si annulla.';
  var go=function(ok){ if(!ok) return;
    post('/app/api/archive/db/delete', {db:name}).then(function(){
      toast('DB "'+name+'" eliminato'); S.dbs=null; loadDbs();
    }).catch(function(e){ toast('Errore: '+err(e)); });
  };
  if (TG && TG.showConfirm) TG.showConfirm(msg, go); else go(window.confirm(msg));
}
function archSearch(){
  var q=$('aq').value.trim(); if(!q) return;
  var box=$('ares'); box.innerHTML=spin('cerco…');
  post('/app/api/archive/search', {query:q, db:$('adb').value, limit:30}).then(function(d){
    var rs=d.results||[];
    if(!rs.length){ box.innerHTML='<div class="empty">Nessun risultato.</div>'; return; }
    box.innerHTML='';
    rs.forEach(function(r){
      var el=document.createElement('div'); el.className='item';
      var snip=esc(r.snip||r.snippet||'').replace(/«/g,'<mark>').replace(/»/g,'</mark>');
      el.innerHTML='<div class="pm">'+esc(r.db||'')+(r.project?' · '+esc(r.project):'')+
        (r.ts?' · '+esc(String(r.ts).slice(0,16)):'')+'</div>'+
        '<div style="font-size:14px;margin-top:4px">'+snip+'</div>';
      box.appendChild(el);
    });
  }).catch(function(e){ box.innerHTML='<div class="empty">'+esc(err(e))+'</div>'; });
}

// ══ TAB: Sistema ══
function renderSistema(){
  if (!TG || !TG.initData) return needTelegram();
  view.innerHTML =
    '<div class="card"><h2>Aggiornamenti</h2><div id="upd">'+spin()+'</div></div>'+
    '<div class="card"><h2>Secret <button class="re" id="reSec">↻</button></h2><div id="sec">'+spin()+'</div></div>'+
    '<div class="card"><h2>Audit — ultimi eventi <button class="re" id="reAud">↻</button></h2><div id="aud">'+spin()+'</div></div>';
  $('reSec').onclick=loadSecrets; $('reAud').onclick=loadAudit;
  loadUpdate(); loadSecrets(); loadAudit();
}
function loadUpdate(){
  api('/app/api/update/state').then(paintUpdate)
    .catch(function(e){ var b=$('upd'); if(b) b.innerHTML='<div class="empty">'+esc(err(e))+'</div>'; });
}
function paintUpdate(st){
  var b=$('upd'); if(!b) return;
  var p=st.progress||{};
  var h='<div class="kv"><span class="k">in esecuzione</span><span>v'+esc(st.running_version)+'</span></div>'+
    '<div class="kv"><span class="k">ultima release</span><span>'+(st.latest?'v'+esc(st.latest):'—')+'</span></div>'+
    '<div class="kv"><span class="k">ultimo check</span><span>'+esc(st.checked_at||'mai')+'</span></div>';
  // updater attivo (intent in coda o step in esecuzione) → mostra e polla
  if (st.intent_pending || p.status==='running'){
    h+='<div class="empty"><span class="spin"></span>'+esc(p.step_name||'updater in avvio')+'…</div>';
    b.innerHTML=h; pollUpdate(); return;
  }
  if (p.status==='failed' || p.status==='rolled_back'){
    h+='<div class="kv"><span class="k">ultimo update</span><span><span class="dot '+
      (p.status==='failed'?'err':'warn')+'"></span>'+esc(p.status)+
      (p.detail?' · '+esc(String(p.detail).slice(0,80)):'')+'</span></div>';
  }
  if (st.available){
    h+='<div style="margin-top:10px"><button class="b danger" id="doUpd">Aggiorna a v'+esc(st.latest)+'</button></div>';
    if (st.changelog_excerpt) h+='<div class="answer" style="max-height:180px;overflow:auto;font-size:12px" id="chl"></div>';
  } else if (st.latest){
    h+='<div class="kv"><span class="k">stato</span><span><span class="dot ok"></span>sei all\'ultima versione</span></div>';
  }
  b.innerHTML=h;
  var chl=$('chl'); if (chl) chl.textContent=st.changelog_excerpt;
  var btn=$('doUpd');
  if (btn) btn.onclick=function(){ confirmUpdate(st.latest); };
}
function confirmUpdate(target){
  var msg='Aggiorno vps1777 a v'+target+'? I servizi si riavviano (~1 min).';
  var go=function(ok){ if(!ok) return;
    post('/app/api/update').then(function(){ toast('Update richiesto'); pollUpdate(); })
      .catch(function(e){ toast('Errore: '+err(e)); });
  };
  if (TG && TG.showConfirm) TG.showConfirm(msg, go); else go(window.confirm(msg));
}
function pollUpdate(){
  if (S.updTimer) clearInterval(S.updTimer);
  var b=$('upd'); if(b) b.innerHTML='<div class="empty"><span class="spin"></span>update in corso… i servizi si riavviano</div>';
  var t0=Date.now();
  S.updTimer=setInterval(function(){
    if (S.tab!=='sistema'){ clearInterval(S.updTimer); S.updTimer=null; return; }
    api('/app/api/update/state').then(function(st){
      var p=st.progress||{};
      if (st.intent_pending || p.status==='running'){
        var b2=$('upd'); if(b2) b2.innerHTML='<div class="empty"><span class="spin"></span>step '+
          esc(p.step||'?')+' — '+esc(p.step_name||'preparo')+' · '+Math.round((Date.now()-t0)/1000)+'s</div>';
      } else {
        clearInterval(S.updTimer); S.updTimer=null;
        if (p.status==='ok') toast('Aggiornato a v'+st.running_version+' ✓');
        else if (p.status) toast('Update: '+p.status);
        paintUpdate(st);
      }
    }).catch(function(){ /* gateway in riavvio: continua a pollare */ });
  }, 4000);
}
function loadSecrets(){
  var b=$('sec'); if(b) b.innerHTML=spin();
  api('/app/api/secrets').then(function(d){
    var b2=$('sec'); if(!b2) return;
    var list=d.secrets||[];
    if(!list.length){ b2.innerHTML='<div class="empty">Stato non disponibile — gira <code>vps1777 secrets-status</code> sull\'host.</div>'; return; }
    var rows=list.map(function(it){
      var over=it.overdue;
      return '<tr><td><b>'+esc(it.name)+'</b><br><span class="pm">'+esc(it.label||'')+'</span></td>'+
        '<td>'+esc(it.age_days)+'g / '+esc(it.max_age_days)+'g</td>'+
        '<td><span class="dot '+(over?'warn':'ok')+'"></span>'+(over?'da ruotare':'ok')+'</td></tr>';
    }).join('');
    b2.innerHTML='<table><thead><tr><th>secret</th><th>età</th><th>stato</th></tr></thead><tbody>'+rows+'</tbody></table>'+
      (d.checked_at?'<div class="pm" style="margin-top:8px">ultimo check: '+esc(d.checked_at)+'</div>':'');
  }).catch(function(e){ var b2=$('sec'); if(b2) b2.innerHTML='<div class="empty">'+esc(err(e))+'</div>'; });
}
function loadAudit(){
  var b=$('aud'); if(b) b.innerHTML=spin();
  api('/app/api/audit?n=30').then(function(d){
    var b2=$('aud'); if(!b2) return;
    var evs=d.events||[];
    if(!evs.length){ b2.innerHTML='<div class="empty">Nessun evento.</div>'; return; }
    b2.innerHTML=evs.map(function(e){
      var extra=Object.keys(e).filter(function(k){return k!=='ts'&&k!=='event';})
        .map(function(k){return k+'='+String(e[k]);}).join(' ');
      return '<div class="ev"><span class="t">'+esc(String(e.ts||'').slice(5,16).replace('T',' '))+
        '</span> <b>'+esc(e.event||'?')+'</b> '+esc(extra.slice(0,120))+'</div>';
    }).join('');
  }).catch(function(e){ var b2=$('aud'); if(b2) b2.innerHTML='<div class="empty">'+esc(err(e))+'</div>'; });
}

// ── errori leggibili
function err(e){
  var m=String((e&&e.message)||e);
  if (m==='not_owner') return 'Questo account Telegram non è l\'owner del gateway.';
  if (m==='no_telegram') return 'Apri dal bot Telegram.';
  // initData oltre la finestra di 12h (H27): non è un bug, è la scadenza. La
  // pagina non può rinnovarla da sola — solo Telegram ne emette una nuova.
  if (m==='auth_401') return 'Sessione Telegram scaduta (12h). Chiudi e riapri il '+
    'pannello dal bot per rientrare.';
  // owner non configurato sul gateway → fail-closed (H1/H27): nessun token
  if (m==='auth_503') return 'Il gateway non ha un owner configurato '+
    '(TELEGRAM_OWNER_ID): per sicurezza non emette token.';
  return m;
}

// ── avvio
if (TG && TG.initData){
  authenticate().then(function(){ show('stato'); })
    .catch(function(e){
      view.innerHTML='<div class="card"><div class="empty">'+esc(err(e))+'</div></div>';
      if (String(e.message)!=='not_owner') show('stato');
    });
} else {
  show('stato');
}
})();
</script>
</body>
</html>"""
