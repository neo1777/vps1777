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
from .settings import UPSTREAMS_SCARTATI, get_settings


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
        # 🔴 `all({})` è True: senza questa guardia un dict VUOTO dava 200 «sano»
        # avendo sondato ZERO backend — il ciclo su zero elementi.
        # ⚠️ E chi consuma questo endpoint è il FAIL-CLOSED dell'update:
        # `deep_health_ok` (tools/vps1777.py:517) esce 0 solo su status 200. Un 200
        # a vuoto dichiarava sana una release in cui il proxy MCP non instrada più
        # nulla, e il ramo `if not healthy: rollback` non scattava per un guasto
        # che gli stava esattamente sotto il naso.
        # 📌 Zero upstream non è una configurazione possibile: il default di
        # `compose.yaml:79` ne porta due. Un dict vuoto significa GATEWAY_UPSTREAMS
        # scritto male — tipicamente i prefissi `nome=` dimenticati — e fino a oggi
        # il parser scartava le voci in SILENZIO. Ora le riporta.
        if not checks:
            body["ok"] = False
            scartate = list(getattr(s, "upstreams_scartati", None) or UPSTREAMS_SCARTATI)
            body["errore"] = (
                "nessun upstream da sondare: GATEWAY_UPSTREAMS è vuoto o tutte le "
                "sue voci sono malformate. Forma attesa: nome=host:porta, separate "
                "da virgola."
            )
            if scartate:
                body["scartate"] = scartate
            return JSONResponse(body, status_code=503)
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

# #278 — vocabolario CHIUSO del campo `ruolo`. È il gemello di `RUOLI` in
# `services/archive-mcp/app/db.py`, e i due DEVONO concordare: i servizi hanno
# contesti di build separati (nessun import possibile fra loro), quindi la
# coerenza non può venire dal linguaggio e viene da un test che legge entrambi i
# file (`test_internal_archive_description.py`). Duplicare senza quel test
# sarebbe la copia che diverge in silenzio.
_RUOLI_AMMESSI: tuple[str, ...] = ("primario", "fotografia", "riscontro", "riservato")


def _guardia_interna(request: Request, evento: str) -> JSONResponse | None:
    """Il portone di `/internal/archive/*`: `None` se si può passare, un 404 se no.

    Difesa in profondità, in quest'ordine — ogni gradino risponde **404**, non 403:
    un 403 confermerebbe l'esistenza della rotta a chi la sta cercando.
      1. l'IP del chiamante dev'essere interno (loopback o rete privata). Serve
         perché Caddy fa `reverse_proxy gateway:8080` CATCH-ALL: queste rotte sono
         raggiungibili dall'esterno per costruzione, e il blocco `internal/` di
         proxy.py copre i path *proxati verso gli upstream*, non le rotte native
         del gateway. Un chiamante che passa dall'ingress viene risolto al suo IP
         pubblico → cade qui, **prima ancora del segreto**.
      2. segreto condiviso DEDICATO, confronto constant-time, fail-closed.

    ⚠️ ESTRATTA il 07/09/2026, quando la #278 ha aggiunto la SECONDA rotta interna
      dell'archivio. Copiare questi due gradini sarebbe stato più breve e più
      pericoloso: due copie di un controllo di sicurezza divergono, e a divergere
      è quella che nessuno rilegge. Qui c'è una sola implementazione, e il test
      pretende che OGNI rotta `internal_archive_*` la chiami come prima istruzione
      — non che la riscriva bene.
    """
    if not ip_is_internal(request.client.host if request.client else None):
        audit({"event": evento, "reason": "not_internal"})
        return JSONResponse({"error": "not_found"}, status_code=404)

    # segreto DEDICATO, non quello del canale nlm: privilegio minimo fra servizi.
    atteso = get_settings().effective_archive_desc_secret
    got = request.headers.get("x-vps1777-archive-desc", "")
    if not atteso or not hmac.compare_digest(got, atteso):
        audit({"event": evento, "reason": "secret"})
        return JSONResponse({"error": "not_found"}, status_code=404)
    return None


def _path_del_db(db: str) -> tuple[Path | None, JSONResponse | None]:
    """Il file del DB `db`, o l'errore da restituire.

    Il `db` dev'essere in whitelist di caratteri e deve ESISTERE; il PATH lo
    costruisce il gateway a partire dalla propria directory, mai il chiamante —
    niente path traversal possibile per costruzione.
    """
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", db):
        return None, JSONResponse({"error": "bad_db"}, status_code=400)
    db_path = Path(get_settings().archive_db_dir) / f"{db}.db"
    if not db_path.is_file():
        return None, JSONResponse({"error": "unknown_db"}, status_code=404)
    return db_path, None


async def internal_archive_description(request: Request) -> JSONResponse:
    """Scrive la `description` di un archivio per conto di archive-mcp."""
    negato = _guardia_interna(request, "archive_desc_denied")
    if negato is not None:
        return negato

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "bad_json"}, status_code=400)
    db = str(body.get("db", ""))
    desc = str(body.get("description", ""))

    db_path, errore = _path_del_db(db)
    if errore is not None:
        return errore

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


async def internal_archive_ruolo(request: Request) -> JSONResponse:
    """Scrive il `ruolo` di un archivio per conto di archive-mcp (#278).

    Stessa strada e stesso portone della `description`, con UNA differenza che
    conta: qui il valore è a **vocabolario chiuso**. La D17 nasceva dal fatto che
    la description è testo libero che arriva nel contesto di un LLM con
    l'autorevolezza di un metadato di sistema; un campo che accetta quattro
    parole non ha quel problema — non perché ci fidiamo del chiamante, ma perché
    non c'è un posto dove infilare un'istruzione. Il cap di lunghezza e il filtro
    dei caratteri di controllo qui non servono, e non ci sono: metterli
    suggerirebbe che il campo sia libero.

    Il valore VUOTO è ammesso e vuol dire «ritira la dichiarazione»: il DB torna
    `non dichiarato`, che non è la stessa cosa di «primario» né di «cancellato».
    """
    negato = _guardia_interna(request, "archive_ruolo_denied")
    if negato is not None:
        return negato

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "bad_json"}, status_code=400)
    db = str(body.get("db", ""))
    ruolo = str(body.get("ruolo", "")).strip().lower()

    db_path, errore = _path_del_db(db)
    if errore is not None:
        return errore

    if ruolo and ruolo not in _RUOLI_AMMESSI:
        # PARLANTE: chi sbaglia il valore riceve l'elenco, non un «400». Un
        # vocabolario chiuso che non dice quali sono le parole è un indovinello.
        return JSONResponse({"error": "bad_ruolo", "ammessi": list(_RUOLI_AMMESSI)},
                            status_code=400)

    archive_indexer.set_meta(db_path, "ruolo", ruolo)
    audit({"event": "archive_ruolo_set", "db": db, "ruolo": ruolo or "(ritirato)"})
    return JSONResponse({"ok": True, "db": db, "ruolo": ruolo})


routes = [
    Route("/health", health, methods=["GET"]),
    # D9 — inoltro della set_description da archive-mcp (rete interna + segreto)
    Route("/internal/archive/description", internal_archive_description, methods=["POST"]),
    # #278 — stessa strada per il campo `ruolo` (vocabolario chiuso)
    Route("/internal/archive/ruolo", internal_archive_ruolo, methods=["POST"]),

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
    # Il file lo possiede nb1777-mcp (H6): qui si INOLTRA, non si monta nulla.
    Route("/admin/nlm/artifact/{name}", admin.nlm_artifact, methods=["GET"]),
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
