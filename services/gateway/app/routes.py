"""Registry routes Starlette."""
from __future__ import annotations

import asyncio

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

import hmac
import re
from pathlib import Path

from . import admin, archive_indexer, miniapp, oauth, onboarding, proxy
from .audit import audit
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



# ═══════════════════════════════════════════════════════════════════════════
# D9 — set_description inoltrata al gateway (strada C, decisione di Neo 20/07)
# ═══════════════════════════════════════════════════════════════════════════
# IL PROBLEMA: `archive-mcp` monta il volume degli archivi in SOLA LETTURA per
# scelta deliberata (compose.yaml:142), ma il suo tool `set_description` apre il
# DB in scrittura. Due dichiarazioni entrambe vere che insieme mentono: il tool
# promette una scrittura che il suo container non può fare. Verificato
# strutturale, non regressione (test idempotente rieseguito dopo il deploy 0.39.4:
# fallisce ancora).
#
# PERCHÉ QUESTA STRADA e non "monto rw" o "tolgo il tool": la docstring di
# `set_meta` nel gateway dice già, testuale, «la usano l'upload (admin) E IL TOOL
# MCP set_description». **L'inoltro non è un design nuovo: è l'architettura che
# il gateway credeva di avere e che nessuno aveva mai scritto.**
#
# D17 DENTRO (Neo: «dentro la D9, non separata») — il rischio vero è LATO USCITA,
# non lato ingresso: questa description finisce dentro il contesto di un LLM che
# interroga l'archivio, con l'autorevolezza di un metadato di sistema. Un testo
# in forma di istruzione lì dentro è un tentativo di dirottare chi legge, e nessuno
# sospetta del campo "descrizione". Perciò qui sotto: cap di lunghezza, rifiuto dei
# caratteri di controllo, e AUDIT di ogni scrittura (un canale di scrittura senza
# log è un canale di cui non sai se è stato usato).
_MAX_DESCRIZIONE = 4096


async def internal_archive_description(request: Request) -> JSONResponse:
    """Scrive la `description` di un archivio per conto di archive-mcp.

    Difesa in profondità, in quest'ordine — ogni gradino risponde **404**, non 403:
    un 403 confermerebbe l'esistenza della rotta a chi la sta cercando.
      1. l'IP del chiamante dev'essere interno (loopback o rete privata). Serve
         perché Caddy fa `reverse_proxy gateway:8080` CATCH-ALL: questa rotta è
         raggiungibile dall'esterno per costruzione, e il blocco `internal/` di
         proxy.py copre i path *proxati verso gli upstream*, non le rotte native
         del gateway. Un chiamante che passa dall'ingress viene risolto al suo IP
         pubblico → cade qui, **prima ancora del segreto**.
      2. segreto condiviso, confronto constant-time, fail-closed.
      3. il `db` dev'essere in whitelist; il PATH lo costruisce il gateway, mai
         il chiamante (niente path traversal possibile per costruzione).
    """
    s = get_settings()
    if not ip_is_internal(request.client.host if request.client else None):
        audit({"event": "archive_desc_denied", "reason": "not_internal"})
        return JSONResponse({"error": "not_found"}, status_code=404)

    # segreto DEDICATO, non quello del canale nlm: privilegio minimo fra servizi.
    atteso = s.effective_archive_desc_secret
    got = request.headers.get("x-vps1777-archive-desc", "")
    if not atteso or not hmac.compare_digest(got, atteso):
        audit({"event": "archive_desc_denied", "reason": "secret"})
        return JSONResponse({"error": "not_found"}, status_code=404)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "bad_json"}, status_code=400)
    db = str(body.get("db", ""))
    desc = str(body.get("description", ""))

    # nome del DB: solo caratteri innocui, e deve ESISTERE fra quelli caricati.
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", db):
        return JSONResponse({"error": "bad_db"}, status_code=400)
    db_path = Path(s.archive_db_dir) / f"{db}.db"
    if not db_path.is_file():
        return JSONResponse({"error": "unknown_db"}, status_code=404)

    # D17 — la description è DATO NON FIDATO: finirà nel contesto di un LLM.
    if len(desc) > _MAX_DESCRIZIONE:
        return JSONResponse({"error": "too_long", "max": _MAX_DESCRIZIONE}, status_code=413)
    if any(ord(c) < 32 and c not in "\n\t" for c in desc):
        # i caratteri di controllo non servono a una descrizione e sono il modo
        # classico di nascondere testo a chi rilegge (e di spezzare un rendering).
        return JSONResponse({"error": "control_chars"}, status_code=400)

    archive_indexer.set_meta(db_path, "description", desc)
    audit({"event": "archive_desc_set", "db": db, "len": len(desc)})
    return JSONResponse({"ok": True, "db": db, "len": len(desc)})


routes = [
    Route("/health", health, methods=["GET"]),
    # D9 — inoltro della set_description da archive-mcp (rete interna + segreto)
    Route("/internal/archive/description", internal_archive_description, methods=["POST"]),

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
    Route("/admin/update/check", admin.update_check, methods=["POST"]),
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
