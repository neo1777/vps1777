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
