"""
Test della consent page OAuth (H8) e del confronto PKCE constant-time (H32).

Perché così: la CI del gateway gira con `uvx pytest`, un ambiente SENZA le deps
pesanti (starlette, pyjwt, httpx, bcrypt, multipart non sono installate — vedi il
commento in admin_core.py). Non posso quindi usare Starlette TestClient né
importare oauth.py "liscio" (importa starlette e, via jwt_helpers, pyjwt).

La soluzione onesta: carico il VERO oauth.py stubbando le sue dipendenze in
sys.modules (fake `starlette.*`, fake pacchetto `app` con moduli-stub per audit/
jwt_helpers/ratelimit/settings/admin), poi esercito i suoi handler reali con
Request/Response finti. Si testa il CONTROL FLOW effettivo di oauth.py (GET →
consent, POST allow → code, POST deny → access_denied, POST senza CSRF → rifiuto,
redirect_uri manomesso → rifiuto), non una reimplementazione. Il seam CSRF/cookie
resta su admin.py (stubbato): qui si verifica che oauth LO CHIAMI e ne onori il
verdetto.

Un E2E completo con TestClient richiederebbe starlette installato → non fattibile
in questa CI. Documentato nel report.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import time
import types
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "app"


# ─────────────────────────── stub delle dipendenze ───────────────────────────

class _Resp:
    def __init__(self, content=None, status_code=200, headers=None, media_type=None):
        self.body = content
        self.status_code = status_code
        self.headers = dict(headers or {})


class _JSONResponse(_Resp):
    def __init__(self, content=None, status_code=200, headers=None):
        super().__init__(content, status_code, headers)
        self.data = content


class _RedirectResponse(_Resp):
    def __init__(self, url="", status_code=307, headers=None):
        super().__init__(None, status_code, headers)
        self.location = str(url)
        self.headers["location"] = str(url)


class _LayoutResult(_Resp):
    """Cattura ciò che _consent_page passa a _layout: body HTML + csrf + title."""
    def __init__(self, title, body, csrf):
        super().__init__(body, 200, None)
        self.title = title
        self.body = body
        self.csrf = csrf


class _Settings:
    audit_log_path = "/nonexistent/vps1777-test/audit.jsonl"
    oauth_access_token_lifetime = 900
    oauth_refresh_token_lifetime = 2_592_000
    gateway_public_base = "https://gw.example"
    oauth_trusted_redirect_hosts = ["claude.ai", "claude.com"]


class _RateLimiter:
    def __init__(self, max_calls=0, window_s=0):
        pass

    def allow(self, ip, now):
        return True


class _JWTError(Exception):
    pass


def _install_stubs() -> types.ModuleType:
    """Registra gli stub in sys.modules e carica il VERO oauth.py come app.oauth."""
    # fake starlette
    st = types.ModuleType("starlette")
    st_req = types.ModuleType("starlette.requests")
    st_req.Request = object
    st_resp = types.ModuleType("starlette.responses")
    st_resp.Response = _Resp
    st_resp.JSONResponse = _JSONResponse
    st_resp.RedirectResponse = _RedirectResponse
    sys.modules["starlette"] = st
    sys.modules["starlette.requests"] = st_req
    sys.modules["starlette.responses"] = st_resp

    # fake pacchetto app + sottomoduli
    app_pkg = types.ModuleType("app")
    app_pkg.__path__ = [str(APP_DIR)]
    sys.modules["app"] = app_pkg

    def _submod(name, **attrs):
        m = types.ModuleType(f"app.{name}")
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[f"app.{name}"] = m
        setattr(app_pkg, name, m)
        return m

    _submod("audit", audit=lambda ev: None)
    _submod(
        "jwt_helpers",
        JWTError=_JWTError,
        issue=lambda **kw: f"tok-{kw.get('typ', '?')}",
        verify=lambda *a, **k: {"sub": "admin@x.com", "jti": "j1"},
    )
    _submod("ratelimit", RateLimiter=_RateLimiter)
    _submod("settings", get_settings=lambda: _Settings())

    # admin stub: le funzioni che oauth importa lazy. I test le sovrascrivono.
    admin = _submod(
        "admin",
        verify_admin_cookie=lambda req: "admin@x.com",
        _csrf_token=lambda email: f"csrf-{email}",
        _verify_csrf=lambda form, email: form.get("csrf") == "valid",
        _layout=lambda title, body, current="", flash="", flash_kind="ok", csrf="": _LayoutResult(title, body, csrf),
    )

    spec = importlib.util.spec_from_file_location("app.oauth", str(APP_DIR / "oauth.py"))
    oauth = importlib.util.module_from_spec(spec)
    sys.modules["app.oauth"] = oauth
    spec.loader.exec_module(oauth)
    oauth._admin_stub = admin  # comodità per i test
    return oauth


oauth = _install_stubs()
admin_stub = sys.modules["app.admin"]


# ─────────────────────────── fake Request ───────────────────────────

class FakeRequest:
    def __init__(self, method="GET", query=None, form=None,
                 url="https://gw.example/authorize?x=1", client_host="1.2.3.4"):
        self.method = method
        self.query_params = dict(query or {})
        self._form = dict(form or {})
        self.url = url
        self.client = types.SimpleNamespace(host=client_host)

    async def form(self):
        return self._form

    async def json(self):
        return self._json


def run(coro):
    return asyncio.run(coro)


# ─────────────────────────── fixtures di stato ───────────────────────────

@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    """Registry client pulito + un client registrato + code store vuoto + admin
    stub ai default. Ogni test parte da uno stato noto."""
    oauth._clients.clear()
    oauth._clients["cid"] = {
        "redirect_uris": ["https://claude.ai/cb"],
        "client_name": "Claude",
        "registered_at": 0,
    }
    oauth._codes.clear()
    admin_stub.verify_admin_cookie = lambda req: "admin@x.com"
    admin_stub._csrf_token = lambda email: f"csrf-{email}"
    admin_stub._verify_csrf = lambda form, email: form.get("csrf") == "valid"
    admin_stub._layout = lambda title, body, current="", flash="", flash_kind="ok", csrf="": _LayoutResult(title, body, csrf)
    yield


def _valid_query(**over):
    q = {
        "client_id": "cid",
        "redirect_uri": "https://claude.ai/cb",
        "state": "st-123",
        "code_challenge": "chal",
        "code_challenge_method": "S256",
        "response_type": "code",
    }
    q.update(over)
    return q


# ─────────────────────────── GET: validazioni ───────────────────────────

def test_get_missing_code_challenge_400():
    r = run(oauth.authorize(FakeRequest(query=_valid_query(code_challenge=""))))
    assert r.status_code == 400
    assert r.data["reason"] == "code_challenge required"


def test_get_wrong_pkce_method_400():
    r = run(oauth.authorize(FakeRequest(query=_valid_query(code_challenge_method="plain"))))
    assert r.status_code == 400
    assert "S256" in r.data["reason"]


def test_get_unknown_client_400():
    r = run(oauth.authorize(FakeRequest(query=_valid_query(client_id="ghost"))))
    assert r.status_code == 400
    assert r.data["error"] == "invalid_client"


def test_get_unregistered_redirect_uri_400():
    r = run(oauth.authorize(FakeRequest(query=_valid_query(redirect_uri="https://evil.example/cb"))))
    assert r.status_code == 400
    assert r.data["error"] == "invalid_redirect_uri"


# ─────────────────────────── GET: login gate ───────────────────────────

def test_get_not_logged_in_redirects_to_login():
    admin_stub.verify_admin_cookie = lambda req: None
    url = "https://gw.example/authorize?client_id=cid&code_challenge=chal"
    r = run(oauth.authorize(FakeRequest(query=_valid_query(), url=url)))
    assert r.status_code == 303
    assert r.location.startswith("/admin/login?next=")
    # next è url-encoded per intero (i '&' dei param non devono spezzarsi)
    assert "%3F" in r.location or "%3A" in r.location
    assert "&code_challenge" not in r.location  # non deve esserci un & grezzo


# ─────────────────────────── GET: consent page (H8) ───────────────────────────

def test_get_logged_in_shows_consent_not_code():
    r = run(oauth.authorize(FakeRequest(query=_valid_query())))
    # NON è un redirect con code: è la pagina di consenso
    assert getattr(r, "location", "") == ""
    assert r.status_code == 200
    body = r.body
    assert "Autorizza" in body and "Rifiuta" in body
    assert "Claude" in body                       # client_name mostrato
    assert 'name="code_challenge" value="chal"' in body  # PKCE riproposta nel POST
    assert 'name="state" value="st-123"' in body
    assert 'action="/authorize"' in body
    # la consent page porta il token CSRF a _layout (che lo inietta in ogni form)
    assert r.csrf == "csrf-admin@x.com"
    # nessun code emesso mostrando solo la consent
    assert oauth._codes == {}


def test_consent_csp_form_action_allarga_all_origin_del_redirect_uri():
    """Il difetto trovato al collaudo vergine (27/08): con `form-action 'self'`
    Chrome blocca in silenzio il 302 post-submit verso redirect_uri e il bottone
    «Autorizza» non fa nulla. La consent page deve allargare form-action
    all'ORIGIN del redirect_uri validato — e SOLO a quello."""
    _CSP_PROD = (
        "default-src 'self'; script-src 'self' 'nonce-x'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
    )

    def _layout_con_csp(title, body, current="", flash="", flash_kind="ok", csrf=""):
        r = _LayoutResult(title, body, csrf)
        r.headers["Content-Security-Policy"] = _CSP_PROD
        return r

    admin_stub._layout = _layout_con_csp
    r = run(oauth.authorize(FakeRequest(query=_valid_query())))
    csp = r.headers["Content-Security-Policy"]
    assert "form-action 'self' https://claude.ai;" in csp
    # nessun'altra direttiva toccata, niente jolly
    assert csp.startswith("default-src 'self';")
    assert "object-src 'none'" in csp and "https:" not in csp.replace(
        "https://claude.ai", "")


def test_consent_csp_intatta_se_layout_non_dichiara_form_action():
    """Controprova del verso: se _layout non porta la CSP (o non ha
    form-action 'self'), la consent page non inventa un header nuovo."""
    r = run(oauth.authorize(FakeRequest(query=_valid_query())))
    assert "Content-Security-Policy" not in r.headers


def test_consent_page_escapes_client_name_xss():
    oauth._clients["cid"]["client_name"] = '<script>alert(1)</script>'
    r = run(oauth.authorize(FakeRequest(query=_valid_query())))
    assert "<script>alert(1)</script>" not in r.body
    assert "&lt;script&gt;" in r.body


def test_consent_page_escapes_state_in_hidden_field():
    r = run(oauth.authorize(FakeRequest(query=_valid_query(state='"><script>x</script>'))))
    assert "<script>x</script>" not in r.body


# ─────────────────────────── POST: Autorizza → code ───────────────────────────

def test_post_allow_valid_csrf_emits_code_and_redirects():
    form = _valid_query()
    form["csrf"] = "valid"
    form["decision"] = "allow"
    r = run(oauth.authorize(FakeRequest(method="POST", form=form)))
    assert r.status_code == 302
    assert r.location.startswith("https://claude.ai/cb?code=")
    assert "state=st-123" in r.location
    # il code è stato memorizzato col contesto giusto
    assert len(oauth._codes) == 1
    ctx = next(iter(oauth._codes.values()))
    assert ctx["client_id"] == "cid"
    assert ctx["sub"] == "admin@x.com"
    assert ctx["code_challenge"] == "chal"


def test_post_allow_urlencodes_state():
    form = _valid_query(state="a b&c")
    form["csrf"] = "valid"
    form["decision"] = "allow"
    r = run(oauth.authorize(FakeRequest(method="POST", form=form)))
    assert "state=a%20b%26c" in r.location  # &/spazio encoded, non spezzano la query


# ─────────────────────────── POST: Rifiuta → access_denied ───────────────────────────

def test_post_deny_redirects_access_denied_no_code():
    form = _valid_query()
    form["csrf"] = "valid"
    form["decision"] = "deny"
    r = run(oauth.authorize(FakeRequest(method="POST", form=form)))
    assert r.status_code == 302
    assert "error=access_denied" in r.location
    assert r.location.startswith("https://claude.ai/cb?")
    assert "state=st-123" in r.location
    assert oauth._codes == {}  # nessun code emesso


def test_post_missing_decision_treated_as_deny():
    form = _valid_query()
    form["csrf"] = "valid"  # decision assente → access_denied (fail-closed)
    r = run(oauth.authorize(FakeRequest(method="POST", form=form)))
    assert "error=access_denied" in r.location
    assert oauth._codes == {}


# ─────────────────────────── POST: CSRF ───────────────────────────

def test_post_without_csrf_rejected_403_no_code():
    form = _valid_query()
    form["decision"] = "allow"  # ma nessun csrf valido
    r = run(oauth.authorize(FakeRequest(method="POST", form=form)))
    assert r.status_code == 403
    assert r.data["reason"] == "csrf"
    # NON redirige a redirect_uri e NON emette code
    assert getattr(r, "location", "") == ""
    assert oauth._codes == {}


def test_post_bad_csrf_rejected_403():
    form = _valid_query()
    form["csrf"] = "WRONG"
    form["decision"] = "allow"
    r = run(oauth.authorize(FakeRequest(method="POST", form=form)))
    assert r.status_code == 403
    assert oauth._codes == {}


# ─────────────────────────── POST: parametri manomessi ───────────────────────────

def test_post_tampered_redirect_uri_rejected_no_code():
    # CSRF valido ma redirect_uri non registrato (open-redirect tentato via POST)
    form = _valid_query(redirect_uri="https://evil.example/cb")
    form["csrf"] = "valid"
    form["decision"] = "allow"
    r = run(oauth.authorize(FakeRequest(method="POST", form=form)))
    assert r.status_code == 400
    assert r.data["error"] == "invalid_redirect_uri"
    assert oauth._codes == {}


def test_post_not_logged_in_redirects_login():
    admin_stub.verify_admin_cookie = lambda req: None
    form = _valid_query()
    form["csrf"] = "valid"
    form["decision"] = "allow"
    r = run(oauth.authorize(FakeRequest(method="POST", form=form)))
    assert r.status_code == 303
    assert r.location.startswith("/admin/login?next=")
    assert oauth._codes == {}


# ─────────────────────────── E2E parziale: GET consent → POST allow ───────────────────────────

def test_roundtrip_get_consent_then_post_allow():
    """Il round-trip che deve completare per claude.ai: GET mostra il consenso,
    poi il POST di Autorizza emette il code verso redirect_uri."""
    q = _valid_query()
    getr = run(oauth.authorize(FakeRequest(query=q)))
    assert getr.status_code == 200 and "Autorizza" in getr.body

    # i campi hidden riproposti dal form (li riusiamo tali e quali nel POST)
    postform = dict(q)
    postform["csrf"] = "valid"
    postform["decision"] = "allow"
    postr = run(oauth.authorize(FakeRequest(method="POST", form=postform)))
    assert postr.status_code == 302
    assert postr.location.startswith("https://claude.ai/cb?code=")
    assert len(oauth._codes) == 1


# ─────────────────────────── H32: PKCE constant-time nel token endpoint ───────────────────────────

def _seed_code(verifier="verif-secret"):
    code = "thecode"
    oauth._codes[code] = {
        "client_id": "cid",
        "redirect_uri": "https://claude.ai/cb",
        "sub": "admin@x.com",
        "code_challenge": oauth._b64url_sha256(verifier),
        "expires_at": int(time.time()) + 300,
    }
    return code


def test_token_pkce_correct_verifier_ok():
    code = _seed_code("verif-secret")
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": "cid",
        "redirect_uri": "https://claude.ai/cb",
        "code_verifier": "verif-secret",
    }
    r = run(oauth.token(FakeRequest(method="POST", form=form)))
    assert r.status_code == 200
    assert "access_token" in r.data
    assert "refresh_token" in r.data


def test_token_pkce_wrong_verifier_rejected():
    code = _seed_code("verif-secret")
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": "cid",
        "redirect_uri": "https://claude.ai/cb",
        "code_verifier": "WRONG-verifier",
    }
    r = run(oauth.token(FakeRequest(method="POST", form=form)))
    assert r.status_code == 400
    assert r.data["reason"] == "pkce"


def test_token_uses_compare_digest_for_pkce():
    """Guardia H32: il confronto PKCE deve passare per hmac.compare_digest
    (constant-time), non un `==` a corto-circuito."""
    import inspect
    src = inspect.getsource(oauth.token)
    assert "compare_digest" in src, "il confronto PKCE non è constant-time (H32)"
    assert "code_challenge\"] ==" not in src and "== ctx[\"code_challenge\"]" not in src


# ─────────────────────────── DCR e destinazione del consenso (H84) ───────────────────────────
# Il consent phishing: la DCR è aperta, quindi chiunque registra un client col suo
# redirect_uri e manda al proprietario un link di consenso già pronto. Si accettano solo
# URI sensati, la pagina dice dove va il permesso, e verso una destinazione non nota
# serve una conferma in più, ricontrollata anche dal server.

def _registra(body):
    req = FakeRequest(method="POST")
    req._json = body
    return run(oauth.register(req))


@pytest.mark.parametrize("uri", [
    "https://claude.ai/api/mcp/auth_callback",
    "http://127.0.0.1:33418/callback",
    "http://localhost:6274/oauth/callback",
    "http://[::1]:8080/cb",
    "com.example.app:/oauth2redirect",
])
def test_dcr_accetta_gli_uri_sensati(uri):
    r = _registra({"redirect_uris": [uri], "client_name": "x"})
    assert r.status_code == 201


@pytest.mark.parametrize("uri", [
    "javascript:alert(1)",
    "data:text/html,ciao",
    "file:///etc/passwd",
    "http://evil.example/cb",              # http solo verso il loopback
    "http://localhost.evil.example/cb",
    "https://claude.ai@evil.example/cb",   # credenziali nell'URI
    "https://claude.ai/cb#frammento",
    "https:///senza-host",
    "https://claude.ai/c b",
    "https://claude.ai/" + "a" * 600,
    "",
    42,
])
def test_dcr_rifiuta_gli_uri_pericolosi(uri):
    r = _registra({"redirect_uris": [uri]})
    assert r.status_code == 400
    assert r.data["error"] == "invalid_redirect_uri"


def test_dcr_rifiuta_troppi_uri_e_un_corpo_non_oggetto():
    assert _registra({"redirect_uris": ["https://claude.ai/cb"] * 6}).status_code == 400
    assert _registra(["https://claude.ai/cb"]).status_code == 400


def test_dcr_ripulisce_il_nome_e_segna_la_registrazione_pendente():
    r = _registra({"redirect_uris": ["https://claude.ai/cb"],
                   "client_name": "Claude\u202e\x00" + "z" * 200})
    c = oauth._clients[r.data["client_id"]]
    assert "\x00" not in c["client_name"] and "\u202e" not in c["client_name"]
    assert len(c["client_name"]) <= 80
    assert c["pendente"] is True


def test_dcr_toglie_le_pendenti_vecchie_e_tiene_un_tetto(monkeypatch):
    now = 10_000_000
    monkeypatch.setattr(oauth.time, "time", lambda: now)
    oauth._clients["vecchia"] = {"redirect_uris": ["https://claude.ai/cb"], "client_name": "v",
                                 "registered_at": now - 25 * 3600, "pendente": True}
    for i in range(oauth._PENDENTI_MAX):
        oauth._clients[f"p{i:02d}"] = {"redirect_uris": ["https://claude.ai/cb"],
                                       "client_name": "p", "registered_at": now - 100 + i,
                                       "pendente": True}
    oauth._clients["autorizzata"] = {"redirect_uris": ["https://claude.ai/cb"],
                                     "client_name": "a", "registered_at": 0}
    r = _registra({"redirect_uris": ["https://claude.ai/cb"]})
    assert r.status_code == 201
    assert "vecchia" not in oauth._clients and "p00" not in oauth._clients
    assert "p01" in oauth._clients
    assert "autorizzata" in oauth._clients and "cid" in oauth._clients   # mai toccate
    pendenti = [k for k, v in oauth._clients.items() if v.get("pendente")]
    assert len(pendenti) == oauth._PENDENTI_MAX


def test_consenso_verso_claude_dice_la_destinazione_senza_conferma():
    r = run(oauth.authorize(FakeRequest(query=_valid_query())))
    assert "<strong>claude.ai</strong>" in r.body
    assert "non è verificato" in r.body
    assert "conferma_destinazione" not in r.body


def _client_sconosciuto():
    oauth._clients["ext"] = {"redirect_uris": ["https://evil.example/cb"],
                             "client_name": "Claude", "registered_at": 0, "pendente": True}
    return _valid_query(client_id="ext", redirect_uri="https://evil.example/cb")


def test_consenso_verso_una_destinazione_sconosciuta_chiede_la_conferma():
    r = run(oauth.authorize(FakeRequest(query=_client_sconosciuto())))
    assert "<strong>evil.example</strong>" in r.body
    assert 'name="conferma_destinazione"' in r.body and "required" in r.body


def test_autorizza_senza_conferma_non_emette_il_code():
    form = _client_sconosciuto()
    form.update(csrf="valid", decision="allow")
    r = run(oauth.authorize(FakeRequest(method="POST", form=form)))
    assert getattr(r, "location", "") == ""
    assert "Manca la conferma" in r.body
    assert oauth._codes == {}
    assert oauth._clients["ext"].get("pendente") is True


def test_autorizza_con_conferma_emette_il_code_e_toglie_pendente():
    form = _client_sconosciuto()
    form.update(csrf="valid", decision="allow", conferma_destinazione="1")
    r = run(oauth.authorize(FakeRequest(method="POST", form=form)))
    assert r.location.startswith("https://evil.example/cb?code=")
    assert "pendente" not in oauth._clients["ext"]
    assert oauth._clients["ext"]["autorizzato_il"] > 0


def test_la_destinazione_distingue_nota_locale_app_sconosciuta():
    assert oauth._destinazione("https://claude.ai/cb") == ("claude.ai", "nota")
    assert oauth._destinazione("https://CLAUDE.com/cb") == ("claude.com", "nota")
    assert oauth._destinazione("http://127.0.0.1:9/cb") == ("127.0.0.1", "locale")
    assert oauth._destinazione("com.example.app:/cb") == ("com.example.app", "app")
    assert oauth._destinazione("https://claude.ai.evil.example/cb")[1] == "sconosciuta"
    assert oauth._destinazione("https://[::1/cb") == ("?", "sconosciuta")   # client vecchio, URI rotto


# ─────────────────────────── avviso e revoca dei connettori ───────────────────────────
# Un consenso dato per sbaglio si vede solo se qualcuno lo dice: a ogni «Autorizza» il
# gateway accoda un avviso (il bot lo porta su Telegram), e da /admin/connettori si revoca.

@pytest.fixture
def coda(tmp_path, monkeypatch):
    notifiche = sys.modules["app.notifiche"]
    monkeypatch.setattr(notifiche, "_file", lambda: tmp_path / "notifiche.json")
    return notifiche


def test_autorizza_accoda_l_avviso_con_nome_e_destinazione(coda):
    form = _valid_query()
    form.update(csrf="valid", decision="allow")
    run(oauth.authorize(FakeRequest(method="POST", form=form)))
    items = coda.preleva()
    assert len(items) == 1 and items[0]["kind"] == "oauth"
    assert "«Claude»" in items[0]["text"] and "claude.ai" in items[0]["text"]
    assert "https://gw.example/admin/connettori" in items[0]["text"]
    assert coda.preleva() == []          # prelevato = uscito dalla coda


def test_rifiuta_non_accoda_niente(coda):
    form = _valid_query()
    form.update(csrf="valid", decision="deny")
    run(oauth.authorize(FakeRequest(method="POST", form=form)))
    assert coda.preleva() == []


def test_la_coda_tiene_gli_ultimi_50(coda):
    for i in range(60):
        coda.accoda("oauth", f"n{i}")
    items = coda.preleva()
    assert len(items) == 50 and items[0]["text"] == "n10"


def test_elenco_connettori_dice_dove_e_se_e_pendente():
    oauth._clients["nuovo"] = {"redirect_uris": ["https://evil.example/cb"], "client_name": "X",
                               "registered_at": 5, "pendente": True}
    el = {c["client_id"]: c for c in oauth.elenco_connettori()}
    assert el["cid"]["dove"] == "claude.ai" and el["cid"]["pendente"] is False
    assert el["nuovo"]["tipo"] == "sconosciuta" and el["nuovo"]["pendente"] is True
    assert [c["client_id"] for c in oauth.elenco_connettori()][0] == "nuovo"   # più recente prima


def _token(form):
    return run(oauth.token(FakeRequest(method="POST", form=form)))


def test_revocato_il_refresh_si_rifiuta():
    assert oauth.revoca_client("cid", by="admin@x.com") is True
    r = _token({"grant_type": "refresh_token", "refresh_token": "rt", "client_id": "cid"})
    assert r.status_code == 400 and r.data["error"] == "invalid_client"
    assert oauth.revoca_client("cid", by="admin@x.com") is False   # già tolto


def test_revocato_fra_consenso_e_scambio_il_code_non_vale():
    form = _valid_query()
    form.update(csrf="valid", decision="allow")
    loc = run(oauth.authorize(FakeRequest(method="POST", form=form))).location
    code = loc.split("code=")[1].split("&")[0]
    oauth.revoca_client("cid", by="admin@x.com")
    r = _token({"grant_type": "authorization_code", "code": code, "client_id": "cid",
                "redirect_uri": "https://claude.ai/cb", "code_verifier": "v"})
    assert r.data["error"] == "invalid_client"
