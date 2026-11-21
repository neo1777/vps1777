"""
OAuth 2.1 endpoints — Dynamic Client Registration + Authorization Code + PKCE.

In versione MVP supporto solo flow code+PKCE per claude.ai. Single-tenant:
l'allowed email è 1 (l'admin). I client DCR sono PERSISTITI su disco (volume
gateway-data) → i connector sopravvivono ai restart del gateway.

Per multi-tenant / multi-replica → store condiviso (Redis/Postgres).
"""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import secrets as pysecrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from . import notifiche
from .audit import audit
from .jwt_helpers import JWTError, issue, verify
from .ratelimit import RateLimiter
from .settings import get_settings

# rate-limit per-IP sugli endpoint auth pubblici (best-effort, in-memory).
_REGISTER_LIMIT = RateLimiter(max_calls=10, window_s=300)   # DCR: 10 ogni 5 min
_TOKEN_LIMIT = RateLimiter(max_calls=60, window_s=60)       # token: 60 al minuto


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# ───── storage ─────
# I client DCR (registrazioni connector di claude.ai) sono PERSISTITI su disco
# (volume gateway-data): senza, ogni restart del gateway li perderebbe e ogni
# connector andrebbe ri-aggiunto su claude.ai. I codes sono effimeri (scadono in
# minuti) → restano in memoria. Per multi-replica → store condiviso (Redis/PG).

def _clients_file() -> Path:
    # accanto all'audit log, sul volume persistente /var/lib/gateway
    return Path(get_settings().audit_log_path).parent / "oauth_clients.json"


def _scrivi_stato(f: Path, dati: Any, evento: str) -> bool:
    """Tutto o niente: temporaneo accanto, poi rinomina. Con `write_text` un arresto a metà (o
    il disco pieno) lasciava il file troncato, e al riavvio lo stato ripartiva VUOTO: i refresh
    già ruotati tornavano validi e i connettori sparivano (giro di revisione del 21/11).

    Torna False se lo stato NON è su disco (e lo scrive nell'audit): chi ha appena cambiato
    qualcosa che deve sopravvivere a un riavvio (una revoca, una registrazione) lo deve sapere,
    e rifiutare l'operazione invece di rispondere come se fosse salvata."""
    tmp = f.with_name(f".{f.name}.tmp")
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(dati))
        os.replace(tmp, f)
    except (OSError, TypeError, ValueError) as exc:
        audit({"event": evento, "error": str(exc)})
        return False
    return True


def _metti_da_parte(f: Path, perche: str) -> None:
    """Il file che non si legge prende il nome `<nome>.illeggibile`, così la prossima scrittura
    non lo cancella; l'audit dice che cosa è successo, anche quando la rinomina non riesce."""
    try:
        os.replace(f, f.with_name(f.name + ".illeggibile"))
        esito = "messo da parte"
    except OSError as exc:
        esito = f"NON messo da parte ({exc})"
    audit({"event": "oauth_state_unreadable", "file": f.name, "error": f"{perche}; {esito}"})


def _leggi_stato(f: Path) -> tuple[Any, bool]:
    """(dati, illeggibile). Un file ASSENTE è una prima installazione: (None, False). Un file
    che c'è ma non si legge NON è la stessa cosa: si dice (audit) e si mette da parte col suo
    nome più `.illeggibile`, così la prossima scrittura non lo cancella senza traccia."""
    try:
        testo = f.read_text()
    except FileNotFoundError:
        return None, False
    except OSError as exc:
        _metti_da_parte(f, str(exc))
        return None, True
    try:
        return json.loads(testo), False
    except ValueError as exc:
        _metti_da_parte(f, str(exc))
        return None, True


def _load_clients() -> dict[str, dict[str, Any]]:
    dati, _ = _leggi_stato(_clients_file())
    return dati if isinstance(dati, dict) else {}


def _save_clients() -> bool:
    return _scrivi_stato(_clients_file(), _clients, "oauth_clients_persist_error")


def _revoked_file() -> Path:
    return Path(get_settings().audit_log_path).parent / "oauth_revoked.json"


# Se l'elenco dei refresh revocati c'era ma non si legge, non si sa più quali refresh sono già
# stati usati: da quel momento valgono solo quelli emessi DOPO (fail-closed). I connettori si
# riautorizzano una volta; un refresh rubato e già ruotato non torna valido.
_refresh_non_prima_di: float = 0.0


# Le FAMIGLIE revocate (OAuth 2.1 BCP, §4.14.2). Ogni refresh porta `fam`, l'id della catena
# nata da un'autorizzazione; se un refresh già ruotato viene ripresentato, uno dei due che lo
# hanno in mano è un ladro, e non si può sapere quale: si revoca la catena intera. Prima si
# rifiutava solo quel token, e chi aveva usato per primo il refresh rubato teneva la catena
# valida per 30 giorni (giro di revisione del 21/11/2026).
_famiglie_revocate: set[str] = set()

# Una revoca serve finché il token revocato non sarebbe scaduto da sé: dopo, lo rifiuta già la
# firma (`exp`). Senza una scadenza i due elenchi crescevano a ogni refresh, per sempre, e il
# file si riscriveva intero ogni volta. Qui la scadenza di ogni jti e di ogni famiglia; chi non
# ne ha una (uno stato scritto prima) prende la vita intera di un refresh da adesso.
_scade_jti: dict[str, float] = {}
_scade_fam: dict[str, float] = {}


def _vita_refresh() -> float:
    return float(getattr(get_settings(), "oauth_refresh_token_lifetime", 2_592_000) or 2_592_000)


def _scadenze_da(dati: Any, chiave: str) -> dict[str, float]:
    grezzo = dati.get(chiave) if isinstance(dati, dict) else None
    out: dict[str, float] = {}
    for k, v in (grezzo.items() if isinstance(grezzo, dict) else ()):
        try:
            out[str(k)] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def _load_revoked() -> set[str]:
    global _refresh_non_prima_di
    dati, illeggibile = _leggi_stato(_revoked_file())
    tardi = time.time() + _vita_refresh()
    if isinstance(dati, dict):                       # forma dal 21/11
        _refresh_non_prima_di = float(dati.get("non_prima_di") or 0)
        _famiglie_revocate.update(str(x) for x in (dati.get("famiglie") or []))
        _scade_fam.update(_scadenze_da(dati, "scadenze_famiglie"))
        _scade_jti.update(_scadenze_da(dati, "scadenze"))
        dati = dati.get("revocati")
    for fam in _famiglie_revocate:
        _scade_fam.setdefault(fam, tardi)
    if illeggibile or (dati is not None and not isinstance(dati, list)):
        _refresh_non_prima_di = time.time()
        return set()
    revocati = {str(x) for x in (dati or [])}        # una lista nuda: la forma di prima
    for jti in revocati:
        _scade_jti.setdefault(jti, tardi)
    return revocati


def _pota_revoche(ora: float) -> None:
    """Toglie le revoche di token ormai scaduti da sé."""
    for jti in [j for j in _revoked_refresh if _scade_jti.get(j, ora + 1) <= ora]:
        _revoked_refresh.discard(jti)
    for fam in [f for f in _famiglie_revocate if _scade_fam.get(f, ora + 1) <= ora]:
        _famiglie_revocate.discard(fam)
    for registro, vivi in ((_scade_jti, _revoked_refresh), (_scade_fam, _famiglie_revocate)):
        for k in [k for k in registro if k not in vivi]:
            del registro[k]


def _save_revoked() -> bool:
    """Scrive lo stato delle revoche, potato. La forma si ALLARGA soltanto: `revocati` e
    `famiglie` restano liste, come le legge la versione di prima; le scadenze stanno in chiavi
    nuove, che la versione di prima ignora."""
    _pota_revoche(time.time())
    return _scrivi_stato(_revoked_file(), {"revocati": sorted(_revoked_refresh),
                                           "famiglie": sorted(_famiglie_revocate),
                                           "non_prima_di": _refresh_non_prima_di,
                                           "scadenze": _scade_jti,
                                           "scadenze_famiglie": _scade_fam},
                         "oauth_revoked_persist_error")


_clients: dict[str, dict[str, Any]] = _load_clients()  # client_id → metadata (persistito)
_codes: dict[str, dict[str, Any]] = {}       # code → {...} (effimero, in-memory)
# jti dei refresh_token già usati/revocati — PERSISTITO su disco (sopravvive ai
# restart: una revoca deve restare tale). Ogni jti esce dall'elenco quando il suo
# token sarebbe scaduto comunque (`_pota_revoche`).
_revoked_refresh: set[str] = _load_revoked()
if _refresh_non_prima_di and not _revoked_file().exists():
    _save_revoked()        # la soglia deve sopravvivere al prossimo riavvio


# ───── discovery ─────

async def well_known_protected(_request: Request) -> Response:
    s = get_settings()
    return JSONResponse({
        "resource": s.gateway_public_base or "",
        "authorization_servers": [s.gateway_public_base or ""],
    })


async def well_known_authserver(_request: Request) -> Response:
    s = get_settings()
    base = s.gateway_public_base or ""
    return JSONResponse({
        "issuer": base,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/token",
        "registration_endpoint": f"{base}/register",
        "scopes_supported": ["mcp:read", "mcp:write"],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    })


# ───── DCR (Dynamic Client Registration) ─────
# La DCR è aperta per costruzione (claude.ai registra un client nuovo a ogni connettore),
# quindi chiunque può registrare un client e mandare al proprietario un link di consenso
# già pronto verso un redirect_uri suo (consent phishing). Tre difese (H84): cosa si
# accetta qui, la destinazione in chiaro sulla pagina di consenso con una conferma in più
# se non è nota, e un tetto alle registrazioni mai autorizzate.
_MAX_REDIRECT_URIS = 5
_MAX_URI_LEN = 512
_MAX_NOME = 80
_PENDENTI_MAX = 50              # registrazioni mai autorizzate tenute al massimo
_PENDENTE_TTL_S = 24 * 3600     # e per quanto tempo
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def _redirect_uri_ammesso(uri: Any) -> bool:
    """RFC 6749 §3.1.2 e RFC 8252 §7: https con un host, http solo verso il loopback (un'app
    sul PC), oppure uno schema privato a nome di dominio rovesciato (`com.example.app:/cb`).
    Mai frammento, credenziali o spazi nell'URI; quindi mai `javascript:`, `data:`, `file:`."""
    if not isinstance(uri, str) or not uri or len(uri) > _MAX_URI_LEN:
        return False
    if "#" in uri or any(c.isspace() or not c.isprintable() for c in uri):
        return False
    try:
        s = urlsplit(uri)
        host = s.hostname
    except ValueError:
        return False
    if s.username is not None or s.password is not None:
        return False
    if s.scheme == "https":
        return bool(host)
    if s.scheme == "http":
        return host in _LOOPBACK
    return "." in s.scheme


def _nome_client(valore: Any) -> str:
    """Il nome lo sceglie chi registra: niente caratteri di controllo e al massimo 80."""
    if not isinstance(valore, str):
        return "unknown"
    nome = "".join(c for c in valore if c.isprintable()).strip()[:_MAX_NOME]
    return nome or "unknown"


def _destinazione(redirect_uri: str) -> tuple[str, str]:
    """(dove, tipo) del redirect_uri: «nota» per gli host di fiducia (claude.ai, claude.com,
    o quelli di OAUTH_TRUSTED_REDIRECT_HOSTS), «locale» per un'app su questo computer
    (loopback), «app» per uno schema privato, «sconosciuta» per tutto il resto."""
    try:
        s = urlsplit(redirect_uri)
        host = s.hostname or ""
    except ValueError:   # un client registrato prima di H84 può avere un URI malformato
        return "?", "sconosciuta"
    if s.scheme not in ("http", "https"):
        return s.scheme, "app"
    if host in _LOOPBACK:
        return host, "locale"
    fidati = {h.strip().lower() for h in get_settings().oauth_trusted_redirect_hosts}
    return host, "nota" if host in fidati else "sconosciuta"


def _sfoltisci_pendenti(now: float) -> int:
    """Toglie le registrazioni mai autorizzate più vecchie di 24 h e, oltre le 50, le più
    vecchie. I client autorizzati almeno una volta non si toccano, e nemmeno quelli
    registrati prima di H84, che il campo `pendente` non ce l'hanno."""
    pendenti = sorted((int(v.get("registered_at", 0)), k)
                      for k, v in _clients.items() if v.get("pendente"))
    via = [k for t, k in pendenti if now - t > _PENDENTE_TTL_S]
    resto = [k for t, k in pendenti if now - t <= _PENDENTE_TTL_S]
    if len(resto) >= _PENDENTI_MAX:
        via += resto[:len(resto) - _PENDENTI_MAX + 1]   # posto per quella che arriva
    for k in via:
        _clients.pop(k, None)
    return len(via)


async def register(request: Request) -> Response:
    if not _REGISTER_LIMIT.allow(_ip(request), time.time()):
        return JSONResponse({"error": "rate_limited"}, status_code=429)
    try:
        body = await request.json()
    except ValueError:      # JSON non valido o non UTF-8
        return JSONResponse({"error": "invalid_request"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "invalid_request"}, status_code=400)
    redirect_uris = body.get("redirect_uris") or []
    if (not isinstance(redirect_uris, list) or not redirect_uris
            or len(redirect_uris) > _MAX_REDIRECT_URIS
            or not all(_redirect_uri_ammesso(u) for u in redirect_uris)):
        return JSONResponse(
            {"error": "invalid_redirect_uri"}, status_code=400,
        )
    now = int(time.time())
    tolti = _sfoltisci_pendenti(now)
    client_id = pysecrets.token_urlsafe(16)
    _clients[client_id] = {
        "redirect_uris": redirect_uris,
        "client_name": _nome_client(body.get("client_name")),
        "registered_at": now,
        "pendente": True,   # fino al primo «Autorizza»
    }
    if not _save_clients():
        # non è su disco: al prossimo riavvio il client sparirebbe e il connettore, già
        # configurato dall'altra parte, smetterebbe di funzionare senza un motivo visibile.
        # Meglio dirlo adesso (l'errore è già nell'audit) e far riprovare.
        _clients.pop(client_id, None)
        return JSONResponse({"error": "temporarily_unavailable"}, status_code=503)
    dove, tipo = _destinazione(redirect_uris[0])
    audit({"event": "oauth_register", "client_id": client_id, "redirect_host": dove,
           "destinazione": tipo, "pendenti_tolti": tolti})
    return JSONResponse(
        {
            "client_id": client_id,
            "client_id_issued_at": now,
            "redirect_uris": redirect_uris,
            "token_endpoint_auth_method": "none",
        },
        status_code=201,
    )


# ───── authorize + consent (H8) ─────
# Gli scope sono statici in questo single-tenant (l'unica identità è l'admin);
# li mostriamo nella consent page così l'utente vede COSA sta concedendo.
_SCOPES = "mcp:read, mcp:write"
_SPIEGA = {
    "nota": "una destinazione nota.",
    "locale": "un'app su questo computer.",
    "app": "un'app installata, che si presenta con questo schema.",
    "sconosciuta": "una destinazione che questo gateway non conosce.",
}
_DA_CONFERMARE = {"app", "sconosciuta"}


def _validate_authorize_params(params: Any) -> tuple[dict[str, str] | None, Response | None]:
    """Valida i parametri OAuth. Condiviso da GET (query) e POST (form) di consenso.

    Il POST di approvazione è forgiabile/replayabile quanto il GET: gli stessi
    controlli DEVONO valere per entrambi, o un redirect_uri non registrato
    passerebbe sul solo POST (open-redirect). Ritorna (campi_validati, None)
    oppure (None, Response d'errore).
    """
    client_id = str(params.get("client_id", ""))
    redirect_uri = str(params.get("redirect_uri", ""))
    state = str(params.get("state", ""))
    code_challenge = str(params.get("code_challenge", ""))
    code_challenge_method = str(params.get("code_challenge_method", ""))
    response_type = str(params.get("response_type", ""))

    if response_type != "code":
        return None, JSONResponse({"error": "unsupported_response_type"}, status_code=400)
    if code_challenge_method != "S256":
        return None, JSONResponse({"error": "invalid_request", "reason": "PKCE S256 required"}, status_code=400)
    if not code_challenge:
        # senza challenge la PKCE non protegge nulla: il code sarebbe scambiabile
        # da chiunque lo intercetti. Rifiuta invece di emettere un code inutile.
        return None, JSONResponse({"error": "invalid_request", "reason": "code_challenge required"}, status_code=400)
    client = _clients.get(client_id)
    if not client:
        return None, JSONResponse({"error": "invalid_client"}, status_code=400)
    if redirect_uri not in client["redirect_uris"]:
        return None, JSONResponse({"error": "invalid_redirect_uri"}, status_code=400)

    return {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "response_type": response_type,
        "client_name": str(client.get("client_name", "unknown")),
    }, None


def _consent_page(email: str, p: dict[str, str], manca_conferma: bool = False) -> Response:
    """Schermata di consenso (H8): l'admin approva ESPLICITAMENTE l'app prima che
    il code venga emesso. Servita dal gateway → riusa `_layout` di admin.py per la
    CSP-con-nonce e il token CSRF (che `_layout` inietta d'ufficio in ogni <form>).
    """
    from .admin import _csrf_token, _layout  # import qui: evita circular + heavy deps

    # I parametri OAuth vanno riproposti nel POST come hidden. Sono TUTTI
    # client-controlled (client_name arriva dalla DCR, state/redirect dal client):
    # html.escape su ognuno o si apre una XSS stored (es. via client_name).
    fields = "".join(
        f'<input type="hidden" name="{k}" value="{html.escape(p[k])}">'
        for k in ("client_id", "redirect_uri", "state",
                  "code_challenge", "code_challenge_method", "response_type")
    )
    dove, tipo = _destinazione(p["redirect_uri"])
    avviso = ""
    if tipo in _DA_CONFERMARE:
        avviso = (
            f'<div class="flash err">{"Manca la conferma qui sotto. " if manca_conferma else ""}'
            "Questa destinazione non è fra quelle note. Autorizza solo se il collegamento "
            "l'hai appena avviato tu da quest'app: chi ti manda un link di consenso già "
            "pronto riceverebbe l'accesso al tuo archivio e ai tuoi notebook.</div>"
            '<div class="row"><label><input type="checkbox" name="conferma_destinazione" '
            f'value="1" required> Ho avviato io il collegamento verso {html.escape(dove)}'
            "</label></div>")
    body = f"""
<header>
  <h1>vps1777 <em>consenso</em></h1>
  <div class="who">{html.escape(email)}</div>
</header>
<form method="POST" action="/authorize">
  {fields}
  <section>
    <div class="kicker">richiesta di accesso</div>
    <p>L'applicazione <strong>{html.escape(p["client_name"])}</strong> (il nome lo
       dichiara lei, non è verificato) chiede di collegarsi a questo gateway per tuo
       conto. Il permesso arriva a <strong>{html.escape(dove)}</strong>: {_SPIEGA[tipo]}</p>
    {avviso}
    <div class="row stack"><label>redirect_uri</label><input type="text" value="{html.escape(p["redirect_uri"])}" readonly></div>
    <div class="row stack"><label>ambiti richiesti</label><input type="text" value="{html.escape(_SCOPES)}" readonly></div>
    <div class="toolbar">
      <button type="submit" name="decision" value="allow" class="primary">Autorizza</button>
      <button type="submit" name="decision" value="deny">Rifiuta</button>
    </div>
  </section>
</form>
"""
    # csrf=... → _layout inietta <input name="csrf"> in OGNI form + CSP con nonce.
    resp = _layout("consenso", body, csrf=_csrf_token(email))
    # `form-action 'self'` (la CSP di _layout, giusta per l'admin) blocca in
    # Chrome ANCHE il redirect che segue il submit: il 302 del POST /authorize
    # verso redirect_uri muore in silenzio e «Autorizza» non fa nulla — l'unico
    # segno è in console. Si allarga all'ORIGIN del redirect_uri GIÀ validato
    # contro i client registrati (mai un jolly), solo su questa pagina.
    # Trovato al collaudo su macchina vergine (27/08): primo esercizio
    # end-to-end della consent (H8) con un client OAuth reale.
    o = urlsplit(p["redirect_uri"])
    csp = resp.headers.get("Content-Security-Policy", "")
    if o.scheme and o.netloc and "form-action 'self'" in csp:
        resp.headers["Content-Security-Policy"] = csp.replace(
            "form-action 'self'", f"form-action 'self' {o.scheme}://{o.netloc}", 1)
    return resp


async def authorize(request: Request) -> Response:
    """
    OAuth Authorization Endpoint (browser-facing).

    GET  → valida i parametri, richiede il login admin, poi mostra la CONSENT
           PAGE. Non emette più il code al volo: serve un'approvazione esplicita.
    POST → l'admin ha premuto Autorizza/Rifiuta. Con CSRF valido e parametri
           ri-validati: Autorizza emette il code, Rifiuta redirige con
           error=access_denied (OAuth 2.0 §4.1.2.1).

    Il round-trip di claude.ai completa: il client apre GET /authorize nel
    browser → login → consent → l'utente preme Autorizza (UN passaggio in più) →
    POST → redirect a redirect_uri con ?code=.
    """
    if request.method == "POST":
        return await _authorize_decide(request)

    params, err = _validate_authorize_params(request.query_params)
    if err is not None or params is None:
        return err or JSONResponse({"error": "invalid_request"}, status_code=400)

    # Verifica admin cookie (se già loggato)
    from .admin import verify_admin_cookie  # import qui per evitare circular
    email = verify_admin_cookie(request)
    if not email:
        # Redirect a /admin/login con next=<URL completo di /authorize>.
        # quote(safe="") è ESSENZIALE: l'URL di /authorize contiene i suoi
        # `&...` (code_challenge, code_challenge_method=S256, ...); senza
        # encoding quei parametri verrebbero letti come parametri di
        # /admin/login e PERSI → al ritorno la PKCE sparisce → "PKCE S256 required".
        next_url = quote(str(request.url), safe="")
        return RedirectResponse(f"/admin/login?next={next_url}", status_code=303)

    return _consent_page(email, params)


async def _authorize_decide(request: Request) -> Response:
    """POST della consent page: emette il code su Autorizza, access_denied su Rifiuta."""
    from .admin import _verify_csrf, verify_admin_cookie  # import qui: evita circular

    # Il cookie admin può essere scaduto tra il GET (consent) e questo POST:
    # ri-verificalo, o si emetterebbe un code senza sessione valida.
    email = verify_admin_cookie(request)
    if not email:
        next_url = quote(str(request.url), safe="")
        return RedirectResponse(f"/admin/login?next={next_url}", status_code=303)

    form = await request.form()

    # CSRF: stesso token firmato di admin.py (_csrf_token/_verify_csrf). Un form
    # ostile cross-origin non può leggerlo né forgiarlo (non ha la chiave) → il
    # POST fallisce anche se il cookie arrivasse. NON redirige a redirect_uri: la
    # richiesta non è fidata, si ferma qui.
    if not _verify_csrf(form, email):
        audit({"event": "oauth_consent_csrf_fail", "sub": email})
        return JSONResponse({"error": "invalid_request", "reason": "csrf"}, status_code=403)

    # Ri-valida i parametri PRIMA di qualsiasi redirect: così non si redirige mai
    # verso un redirect_uri non registrato (open-redirect), nemmeno sul Rifiuta.
    params, err = _validate_authorize_params(form)
    if err is not None or params is None:
        return err or JSONResponse({"error": "invalid_request"}, status_code=400)

    redirect_uri = params["redirect_uri"]
    state = params["state"]
    # `state` è opaco e scelto dal client: va url-encoded, o un '&'/'#' al suo
    # interno spezzerebbe la query di redirect.
    sep = "&" if "?" in redirect_uri else "?"

    dove, tipo = _destinazione(redirect_uri)
    if str(form.get("decision", "")) != "allow":
        # Rifiuto esplicito (o decision assente) → access_denied per spec OAuth.
        audit({"event": "oauth_consent_denied", "client_id": params["client_id"], "sub": email,
               "redirect_host": dove, "destinazione": tipo})
        return RedirectResponse(
            f"{redirect_uri}{sep}error=access_denied&state={quote(state, safe='')}",
            status_code=302,
        )

    # Verso una destinazione non nota serve la casella spuntata (H84): si ricontrolla qui,
    # perché `required` nel modulo lo fa solo il browser.
    if tipo in _DA_CONFERMARE and str(form.get("conferma_destinazione", "")) != "1":
        audit({"event": "oauth_consent_unconfirmed", "client_id": params["client_id"],
               "sub": email, "redirect_host": dove, "destinazione": tipo})
        return _consent_page(email, params, manca_conferma=True)

    # Autorizza → emette il code (stessa logica di prima, ora dietro consenso).
    client = _clients.get(params["client_id"]) or {}
    if client.pop("pendente", None):
        client["autorizzato_il"] = int(time.time())
        _save_clients()
    # Un consenso dato per sbaglio si vede solo se qualcuno lo dice: l'avviso arriva su
    # Telegram (il bot preleva la coda) con chi e dove, e dove revocarlo.
    base = get_settings().gateway_public_base.rstrip("/")
    notifiche.accoda("oauth", (
        f"🔐 Nuovo connettore autorizzato: «{params['client_name']}» verso {dove} "
        f"({_SPIEGA[tipo].rstrip('.')}). Se non sei stato tu, revocalo da "
        f"{base}/admin/connettori"))
    adesso = int(time.time())
    for vecchio in [c for c, v in _codes.items() if v["expires_at"] < adesso]:
        del _codes[vecchio]      # i codici mai scambiati non restano in memoria oltre la scadenza
    code = pysecrets.token_urlsafe(32)
    _codes[code] = {
        "client_id": params["client_id"],
        "redirect_uri": redirect_uri,
        "sub": email,
        "code_challenge": params["code_challenge"],
        "expires_at": int(time.time()) + 300,
    }
    audit({"event": "oauth_code_issued", "client_id": params["client_id"], "sub": email,
           "redirect_host": dove, "destinazione": tipo})
    return RedirectResponse(
        f"{redirect_uri}{sep}code={code}&state={quote(state, safe='')}", status_code=302)


# ───── connettori: elenco e revoca (/admin/connettori) ─────

def elenco_connettori() -> list[dict[str, Any]]:
    """I client registrati, dal più recente: nome dichiarato, dove va il permesso,
    quando è stato registrato e autorizzato. L'id si mostra per intero: serve alla revoca,
    e non è un segreto (il client è pubblico, `token_endpoint_auth_method: none`)."""
    out = []
    for cid, c in _clients.items():
        uris = c.get("redirect_uris") or [""]
        dove, tipo = _destinazione(str(uris[0]))
        out.append({"client_id": cid, "nome": str(c.get("client_name", "unknown")),
                    "dove": dove, "tipo": tipo,
                    "registrato": int(c.get("registered_at", 0) or 0),
                    "autorizzato": int(c.get("autorizzato_il", 0) or 0),
                    "pendente": bool(c.get("pendente"))})
    return sorted(out, key=lambda x: x["registrato"], reverse=True)


def revoca_client(client_id: str, by: str) -> bool:
    """Toglie il client: da qui il refresh si rifiuta (`invalid_client`), e l'accesso
    finisce quando scade l'ultimo access token (`OAUTH_ACCESS_TOKEN_LIFETIME`, 15 min)."""
    c = _clients.pop(client_id, None)
    if c is None:
        return False
    _save_clients()
    dove, tipo = _destinazione(str((c.get("redirect_uris") or [""])[0]))
    audit({"event": "oauth_client_revoked", "client_id": client_id, "by": by,
           "redirect_host": dove, "destinazione": tipo})
    return True


# ───── token ─────

async def token(request: Request) -> Response:
    if not _TOKEN_LIMIT.allow(_ip(request), time.time()):
        return JSONResponse({"error": "rate_limited"}, status_code=429)
    try:
        form = await request.form()
    except Exception:  # noqa: BLE001 — il parser dei form solleva tipi suoi (multipart rotto,
        # corpo troncato, client che chiude): per chi chiama sono tutti la stessa richiesta non valida
        return JSONResponse({"error": "invalid_request"}, status_code=400)

    grant_type = form.get("grant_type", "")
    if grant_type == "authorization_code":
        return _grant_code(form)
    if grant_type == "refresh_token":
        return _grant_refresh(form)
    return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)


def _grant_code(form: Any) -> Response:
    """Lo scambio del codice di autorizzazione (con PKCE) per la prima coppia di token."""
    s = get_settings()
    code = str(form.get("code", ""))
    client_id = str(form.get("client_id", ""))
    redirect_uri = str(form.get("redirect_uri", ""))
    code_verifier = str(form.get("code_verifier", ""))

    ctx = _codes.pop(code, None)
    if not ctx:
        return JSONResponse({"error": "invalid_grant"}, status_code=400)
    if client_id not in _clients:   # revocato fra il consenso e lo scambio
        return JSONResponse({"error": "invalid_client"}, status_code=400)
    if ctx["expires_at"] < int(time.time()):
        return JSONResponse({"error": "invalid_grant", "reason": "expired"}, status_code=400)
    if ctx["client_id"] != client_id or ctx["redirect_uri"] != redirect_uri:
        return JSONResponse({"error": "invalid_grant", "reason": "mismatch"}, status_code=400)

    # PKCE check — constant-time (H32). Il code_verifier è il segreto che il
    # client presenta al posto di un client_secret; confrontarlo con un `!=`
    # a corto-circuito trapelerebbe via timing la lunghezza del prefisso
    # corretto dell'hash atteso. hmac.compare_digest confronta in tempo
    # costante (entrambi ASCII base64url).
    expected = _b64url_sha256(code_verifier)
    if not hmac.compare_digest(expected, str(ctx["code_challenge"])):
        return JSONResponse({"error": "invalid_grant", "reason": "pkce"}, status_code=400)

    access = issue(
        typ="access", sub=ctx["sub"], aud=client_id,
        ttl=s.oauth_access_token_lifetime,
    )
    refresh_jti = pysecrets.token_urlsafe(16)
    refresh = issue(
        typ="refresh", sub=ctx["sub"], aud=client_id,
        ttl=s.oauth_refresh_token_lifetime,
        extra={"jti": refresh_jti, "fam": pysecrets.token_urlsafe(12)},
    )
    audit({"event": "oauth_access_issued", "sub": ctx["sub"], "client_id": client_id})
    return JSONResponse({
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": s.oauth_access_token_lifetime,
        "refresh_token": refresh,
    })


def _grant_refresh(form: Any) -> Response:
    """Il rinnovo: verifica il refresh, lo ruota e riconosce il riuso."""
    s = get_settings()
    rt = str(form.get("refresh_token", ""))
    client_id = str(form.get("client_id", ""))
    if client_id not in _clients:
        # revocato da /admin/connettori: il refresh muore qui, e con lui il connettore
        audit({"event": "oauth_refresh_revoked_client", "client_id": client_id})
        return JSONResponse({"error": "invalid_client"}, status_code=400)
    try:
        claims = verify(rt, expected_typ="refresh", expected_aud=client_id)
    except JWTError:
        return JSONResponse({"error": "invalid_grant"}, status_code=400)
    jti = claims.get("jti", "")
    if float(claims.get("iat") or 0) < _refresh_non_prima_di:
        audit({"event": "oauth_refresh_reuse", "client_id": client_id, "jti": jti,
               "reason": "prima_della_soglia"})
        return JSONResponse({"error": "invalid_grant", "reason": "revoked"}, status_code=400)
    fam = str(claims.get("fam") or "")
    if fam and fam in _famiglie_revocate:
        audit({"event": "oauth_refresh_reuse", "client_id": client_id, "jti": jti,
               "reason": "famiglia_revocata"})
        return JSONResponse({"error": "invalid_grant", "reason": "revoked"}, status_code=400)
    if jti in _revoked_refresh:
        # REUSE DETECTION (OAuth 2.1 BCP): un refresh già ruotato/revocato
        # ripresentato = segnale di furto → rifiuta, REVOCA LA FAMIGLIA e logga.
        audit({"event": "oauth_refresh_reuse", "client_id": client_id, "jti": jti,
               "reason": "famiglia_revocata" if fam else "riuso"})
        if fam:
            _famiglie_revocate.add(fam)
            _scade_fam[fam] = time.time() + _vita_refresh()
            _save_revoked()      # se non si scrive resta in memoria, e l'audit lo dice
        # il proprietario lo deve sapere: o un refresh è stato copiato, o un client ha
        # riprovato dopo una risposta persa. In tutti e due i casi il connettore va
        # ricollegato (una nuova autorizzazione): la catena di prima non vale più.
        nome = _nome_client((_clients.get(client_id) or {}).get("client_name"))
        notifiche.accoda("oauth_refresh_riuso",
                         f"⚠️ Un connettore ({nome}) ha ripresentato un refresh token già "
                         "usato: l'ho rifiutato e ho chiuso quella sessione del connettore, "
                         "che va ricollegato. Se non te lo aspetti, revocalo del tutto in "
                         "/admin/connettori.")
        return JSONResponse({"error": "invalid_grant", "reason": "revoked"}, status_code=400)
    sub = claims.get("sub", "")
    # ROTAZIONE: revoca (durevolmente) il refresh appena usato ed emettine uno
    # nuovo. Così un token rubato ha vita corta e il riuso si rileva.
    _revoked_refresh.add(jti)
    _scade_jti[jti] = float(claims.get("exp") or time.time() + _vita_refresh())
    if not _save_revoked():
        # La revoca non è su disco: se emettessi il refresh nuovo, dopo un riavvio quello appena
        # usato tornerebbe valido, e un refresh copiato con lui. Senza scrittura niente
        # rotazione: il client tiene il suo refresh e riprova (l'errore è già nell'audit).
        _revoked_refresh.discard(jti)
        _scade_jti.pop(jti, None)
        return JSONResponse({"error": "temporarily_unavailable"}, status_code=503)
    access = issue(typ="access", sub=sub, aud=client_id, ttl=s.oauth_access_token_lifetime)
    new_jti = pysecrets.token_urlsafe(16)
    # la famiglia segue la catena; un refresh di prima del 21/11 non ne ha una: nasce qui
    new_refresh = issue(typ="refresh", sub=sub, aud=client_id,
                        ttl=s.oauth_refresh_token_lifetime,
                        extra={"jti": new_jti, "fam": fam or pysecrets.token_urlsafe(12)})
    audit({"event": "oauth_refresh_rotated", "sub": sub, "client_id": client_id})
    return JSONResponse({
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": s.oauth_access_token_lifetime,
        "refresh_token": new_refresh,
    })


def _b64url_sha256(s: str) -> str:
    import base64
    digest = hashlib.sha256(s.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
