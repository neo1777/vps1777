"""
Pannello admin — /admin/{login,logout,nlm,audit,secrets}.

Tutto dietro `admin_cookie` (JWT typ=admin) settato dopo bcrypt verify.

`/admin/nlm` è il punto chiave: GET = form upload, POST = salva auth.json,
rimuove AUTH_PENDING.flag, restart non necessario (nb1777-mcp legge file on
demand, vedi nb1777-mcp/app/auth.py).
"""
from __future__ import annotations

import html
import json
import time
from pathlib import Path

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from .audit import audit, read_recent
from .jwt_helpers import JWTError, issue, verify
from .security import verify_admin_password
from .settings import get_settings


ADMIN_COOKIE = "vps1777_admin"


# ───── cookie helpers ─────

def verify_admin_cookie(request: Request) -> str | None:
    """Ritorna l'email se cookie valido, None altrimenti."""
    tok = request.cookies.get(ADMIN_COOKIE)
    if not tok:
        return None
    try:
        claims = verify(tok, expected_typ="admin", expected_aud="admin")
    except JWTError:
        return None
    email = claims.get("sub", "").lower()
    s = get_settings()
    if email != s.admin_email:
        return None
    return email


def _set_admin_cookie(response: Response, email: str) -> None:
    s = get_settings()
    tok = issue(
        typ="admin", sub=email, aud="admin",
        ttl=s.oauth_admin_cookie_lifetime,
    )
    response.set_cookie(
        ADMIN_COOKIE, tok,
        max_age=s.oauth_admin_cookie_lifetime,
        httponly=True,
        # `Secure` solo se siamo davvero su HTTPS (PUBLIC_BASE https): un cookie
        # Secure NON viene salvato dal browser su origine http, quindi su un
        # accesso HTTP (es. pannello onboarding su :8080 prima del Funnel) il
        # login andrebbe a vuoto. In produzione PUBLIC_BASE è https → Secure on.
        secure=s.gateway_public_base.startswith("https://"),
        samesite="lax",
        path="/admin",
    )


def _clear_admin_cookie(response: Response) -> None:
    response.delete_cookie(ADMIN_COOKIE, path="/admin")


def _require_admin(request: Request) -> tuple[str | None, Response | None]:
    email = verify_admin_cookie(request)
    if not email:
        return None, RedirectResponse("/admin/login", status_code=302)
    return email, None


# ───── HTML template minimale ─────
# (in F8 refactor: estrai in Jinja2 templates/)

_FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?'
    'family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&'
    'family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">'
)

# Timbro 1777: dark profondo, accent corallo, Fraunces display + JetBrains mono.
_CSS = """
<style>
:root{
  --bg:#0c0d10;--bg-card:#15161a;--bg-soft:#101116;
  --fg:#e8e6e1;--muted:#8a8a90;--faint:#5c5c63;
  --accent:#d97757;--accent-dim:#b35f44;
  --ok:#5eb87a;--warn:#d4a35e;--err:#c47158;
  --line:#262629;--line-soft:#1d1d20;
  --mono:'JetBrains Mono',ui-monospace,monospace;
  --display:'Fraunces',Georgia,serif;
  --sans:system-ui,-apple-system,'Segoe UI',sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:var(--sans);background:
  radial-gradient(1100px 500px at 80% -10%,rgba(217,119,87,.07),transparent 60%),var(--bg);
  color:var(--fg);line-height:1.6;padding:48px 24px;max-width:780px;margin:0 auto;
  -webkit-font-smoothing:antialiased}
header{margin-bottom:34px;padding-bottom:20px;border-bottom:1px solid var(--line)}
h1{font-family:var(--display);font-weight:500;font-size:30px;letter-spacing:.01em}
h1 em{color:var(--accent);font-style:normal;font-weight:600}
h2{font-family:var(--display);font-weight:500;font-size:19px;margin:0 0 14px}
.who{color:var(--muted);font-size:13px;margin-top:8px;font-family:var(--mono)}
.kicker{color:var(--faint);font-size:11px;text-transform:uppercase;letter-spacing:.14em;margin-bottom:16px;font-family:var(--mono)}
section{background:var(--bg-card);border:1px solid var(--line);padding:24px;border-radius:10px;margin-bottom:22px}
p{color:var(--fg)}
form .row{display:grid;grid-template-columns:160px 1fr;gap:18px;align-items:center;margin-bottom:16px}
form .row.stack{grid-template-columns:1fr;gap:8px}
label{color:var(--muted);font-size:13px}
input[type=email],input[type=password],input[type=text],input[type=file],textarea{
  background:var(--bg-soft);color:var(--fg);border:1px solid var(--line);padding:11px 13px;
  border-radius:7px;font-family:var(--mono);font-size:13px;width:100%}
input:focus,textarea:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px rgba(217,119,87,.12)}
.hint{color:var(--faint);font-size:12px;margin-top:4px}
.hint a{color:var(--accent-dim)}
.toolbar{display:flex;gap:10px;margin-top:20px;flex-wrap:wrap;align-items:center}
button,.btn{background:var(--bg-soft);color:var(--fg);border:1px solid var(--line);padding:9px 16px;
  border-radius:7px;cursor:pointer;text-decoration:none;font-size:13px;font-family:var(--sans);transition:.15s}
button.primary,.btn.primary{background:var(--accent);color:#15161a;border-color:var(--accent);font-weight:500}
button.primary:hover,.btn.primary:hover{background:var(--accent-dim)}
button:hover,.btn:hover{border-color:var(--accent)}
.flash{padding:12px 16px;border-radius:7px;margin-bottom:20px;font-size:13px}
.flash.ok{background:rgba(94,184,122,.1);border:1px solid var(--ok);color:var(--ok)}
.flash.err{background:rgba(196,113,88,.12);border:1px solid var(--err);color:var(--err)}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:8px;vertical-align:middle;box-shadow:0 0 8px currentColor}
.dot.ok{background:var(--ok);color:var(--ok)}.dot.warn{background:var(--warn);color:var(--warn)}
.dot.err{background:var(--err);color:var(--err)}.dot.off{background:var(--faint);color:transparent;box-shadow:none}
pre,code{font-family:var(--mono);font-size:12px}
code{color:var(--accent-dim);background:var(--bg-soft);padding:1px 6px;border-radius:4px}
pre{background:var(--bg-soft);padding:13px 15px;border-radius:7px;overflow-x:auto;margin:10px 0;border:1px solid var(--line-soft);color:var(--fg)}
pre code{background:none;padding:0;color:var(--fg)}
ol{margin-left:20px}ol li{margin-bottom:12px}
ul{margin-left:18px}ul li{margin-bottom:7px;color:var(--muted)}
nav.tabs{display:flex;gap:2px;margin-bottom:28px;border-bottom:1px solid var(--line);flex-wrap:wrap}
nav.tabs a{padding:9px 16px;color:var(--muted);text-decoration:none;font-size:13px;border-bottom:2px solid transparent;margin-bottom:-1px}
nav.tabs a:hover{color:var(--fg)}
nav.tabs a.active{color:var(--fg);border-color:var(--accent)}
.status-grid{display:grid;gap:12px;margin-bottom:8px}
.status-row{display:flex;align-items:center;gap:10px;padding:13px 16px;background:var(--bg-soft);border:1px solid var(--line-soft);border-radius:8px}
.status-row .lbl{font-weight:500}.status-row .val{color:var(--muted);font-size:12px;margin-left:auto;font-family:var(--mono)}
.audit-event{padding:7px 0;border-bottom:1px solid var(--line-soft);font-family:var(--mono);font-size:11px;display:flex;gap:14px}
.audit-event .ts{color:var(--faint);min-width:170px}.audit-event .ev{color:var(--accent-dim);min-width:180px}
.foot{color:var(--faint);font-size:11px;text-align:center;margin-top:40px;font-family:var(--mono);letter-spacing:.04em}
</style>
"""


def _layout(title: str, body: str, current: str = "", flash: str = "", flash_kind: str = "ok") -> HTMLResponse:
    tabs = ""
    if current:
        items = [
            ("setup", "Setup"),
            ("nlm", "NotebookLM"),
            ("secrets", "Secrets"),
            ("audit", "Audit"),
        ]
        rendered = "".join(
            f'<a href="/admin/{k}" class="{"active" if current==k else ""}">{label}</a>'
            for k, label in items
        )
        tabs = f'<nav class="tabs">{rendered}</nav>'
    flash_html = ""
    if flash:
        flash_html = f'<div class="flash {flash_kind}">{html.escape(flash)}</div>'
    out = f"""<!DOCTYPE html><html lang="it"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>vps1777 · {html.escape(title)}</title>
{_FONTS}
{_CSS}
</head><body>
{tabs}{flash_html}{body}
<div class="foot">vps1777 · gateway</div>
</body></html>"""
    return HTMLResponse(out)


# ───── /admin root ─────

async def admin_root(request: Request) -> Response:
    email, redirect = _require_admin(request)
    if redirect:
        return redirect
    return RedirectResponse("/admin/setup", status_code=302)


# ───── /admin/login ─────

async def login(request: Request) -> Response:
    if request.method == "GET":
        next_url = request.query_params.get("next", "/admin/")
        s = get_settings()
        body = f"""
<header>
  <h1>vps1777 <em>admin</em></h1>
  <div class="who">login</div>
</header>
<form method="POST" action="/admin/login">
  <input type="hidden" name="next" value="{html.escape(next_url)}">
  <section>
    <div class="kicker">accedi</div>
    <div class="row"><label>email</label><input type="email" name="email" required autofocus value="{html.escape(s.admin_email)}"></div>
    <div class="row"><label>password</label><input type="password" name="password" required></div>
    <div class="toolbar"><button type="submit" class="primary">Entra</button></div>
  </section>
</form>
"""
        return _layout("login", body)

    # POST
    form = await request.form()
    email = str(form.get("email", "")).strip().lower()
    password = str(form.get("password", ""))
    next_url = str(form.get("next", "/admin/"))
    s = get_settings()

    if email != s.admin_email or not verify_admin_password(password):
        audit({"event": "admin_login_fail", "email": email})
        # Aggiungiamo un piccolo delay per disincentivare brute-force
        time.sleep(0.5)
        return _layout(
            "login",
            f'<form method="POST" action="/admin/login"><input type="hidden" name="next" value="{html.escape(next_url)}"><section><div class="kicker">accedi</div><div class="row"><label>email</label><input type="email" name="email" required value="{html.escape(email)}"></div><div class="row"><label>password</label><input type="password" name="password" required autofocus></div><div class="toolbar"><button type="submit" class="primary">Entra</button></div></section></form>',
            flash="Email o password errati", flash_kind="err",
        )

    audit({"event": "admin_login_ok", "email": email})
    # anti open-redirect: `next` solo relativo o same-origin (PUBLIC_BASE)
    base = s.gateway_public_base
    if not (next_url.startswith("/") or (base and next_url.startswith(base))):
        next_url = "/admin/setup"
    resp = RedirectResponse(next_url, status_code=302)
    _set_admin_cookie(resp, email)
    return resp


async def logout(_request: Request) -> Response:
    resp = RedirectResponse("/admin/login", status_code=303)
    _clear_admin_cookie(resp)
    return resp


# ───── /admin/nlm — upload auth.json ─────

async def nlm_view(request: Request) -> Response:
    email, redirect = _require_admin(request)
    if redirect:
        return redirect

    s = get_settings()
    auth_dir = Path(s.nlm_auth_dir)
    auth_dir.mkdir(parents=True, exist_ok=True)
    auth_path = auth_dir / "auth.json"
    pending = auth_dir / "AUTH_PENDING.flag"

    if request.method == "POST":
        form = await request.form()
        upload = form.get("auth_file")
        if upload is None or not hasattr(upload, "read"):
            return RedirectResponse("/admin/nlm?msg=Nessun+file+caricato&kind=err", status_code=303)
        content = await upload.read()  # type: ignore[union-attr]
        try:
            if not content:
                raise ValueError("file vuoto")
            if len(content) > 1_000_000:
                raise ValueError("file troppo grande (>1MB)")
            parsed = json.loads(content.decode("utf-8"))
            if not isinstance(parsed, dict):
                raise ValueError("formato non atteso (non è un dict)")
            if "profiles" not in parsed:
                raise ValueError("manca chiave 'profiles' (auth.json di nlm)")
            auth_path.write_bytes(content)
            auth_path.chmod(0o600)
            if pending.exists():
                pending.unlink()
            audit({"event": "admin_nlm_upload", "by": email, "bytes": len(content)})
            msg = f"auth.json caricato ({len(content)} byte). nb1777-mcp prossima call leggerà il file."
            return RedirectResponse(f"/admin/nlm?msg={msg.replace(' ', '+')}&kind=ok", status_code=303)
        except ValueError as exc:
            audit({"event": "admin_nlm_upload_err", "by": email, "error": str(exc)})
            return RedirectResponse(
                f"/admin/nlm?msg=Errore:+{str(exc).replace(' ', '+')}&kind=err",
                status_code=303,
            )

    # GET
    auth_exists = auth_path.exists()
    pending_exists = pending.exists()
    auth_size = auth_path.stat().st_size if auth_exists else 0

    if auth_exists and not pending_exists:
        status_html = f'<div class="kicker"><span class="dot ok"></span>auth.json presente ({auth_size} byte). NotebookLM dovrebbe funzionare.</div>'
    elif pending_exists or not auth_exists:
        status_html = '<div class="kicker"><span class="dot warn"></span>AUTH_PENDING — carica auth.json per attivare NotebookLM.</div>'
    else:
        status_html = '<div class="kicker"><span class="dot"></span>stato sconosciuto</div>'

    flash = request.query_params.get("msg", "").replace("+", " ")
    flash_kind = request.query_params.get("kind", "ok")

    body = f"""
<header>
  <h1>vps1777 <em>admin</em> · NotebookLM</h1>
  <div class="who">{html.escape(email)}</div>
</header>
{status_html}
<section>
  <div class="kicker">come ottenere auth.json</div>
  <ol>
    <li>Sul TUO PC locale (Mint/Mac/Windows), installa <code>nlm</code>:
      <pre>curl -fsSL https://astral.sh/uv/install.sh | sh   # se non hai uv
uv tool install notebooklm-mcp-cli --python 3.12</pre>
    </li>
    <li>Login Google (apre browser):
      <pre>nlm login
nlm notebook list   # verifica</pre>
    </li>
    <li>Trova il file in:
      <pre>~/.notebooklm-mcp-cli/auth.json   # Linux/Mac
%USERPROFILE%\\.notebooklm-mcp-cli\\auth.json   # Windows</pre>
    </li>
    <li>Caricalo qui sotto.</li>
  </ol>
</section>

<form method="POST" action="/admin/nlm" enctype="multipart/form-data">
  <section>
    <div class="row"><label>auth.json</label><input type="file" name="auth_file" accept=".json,application/json" required></div>
    <div class="toolbar">
      <button type="submit" class="primary">Carica</button>
      <a class="btn" href="/admin/audit">Audit →</a>
      <form method="POST" action="/admin/logout" style="display:inline"><button type="submit">Logout</button></form>
    </div>
  </section>
</form>
"""
    return _layout("NotebookLM", body, current="nlm", flash=flash, flash_kind=flash_kind)


# ───── /admin/audit ─────

async def audit_view(request: Request) -> Response:
    email, redirect = _require_admin(request)
    if redirect:
        return redirect
    events = read_recent(200)
    rows: list[str] = []
    for e in reversed(events):
        ts = html.escape(e.get("ts", "?"))
        ev = html.escape(e.get("event", "?"))
        extra = {k: v for k, v in e.items() if k not in ("ts", "event")}
        ex = html.escape(json.dumps(extra, ensure_ascii=False))
        rows.append(f'<div class="audit-event"><span class="ts">{ts}</span><span class="ev">{ev}</span><span>{ex}</span></div>')
    body = f"""
<header>
  <h1>vps1777 <em>admin</em> · audit</h1>
  <div class="who">{html.escape(email)}</div>
</header>
<section>
  <div class="kicker">ultimi {len(events)} eventi</div>
  {''.join(rows) if rows else '<p style="color:var(--muted)">Nessun evento ancora.</p>'}
</section>
"""
    return _layout("audit", body, current="audit")


# ───── /admin/secrets (placeholder, da espandere) ─────

async def secrets_view(request: Request) -> Response:
    email, redirect = _require_admin(request)
    if redirect:
        return redirect
    body = f"""
<header>
  <h1>vps1777 <em>admin</em> · secrets</h1>
  <div class="who">{html.escape(email)}</div>
</header>
<section>
  <div class="kicker">gestione secrets</div>
  <p>I secret stanno in <code>/run/secrets/</code> (tmpfs read-only) e sono montati da file Docker.</p>
  <p>Per ruotare:</p>
  <ol>
    <li>Modifica il file in <code>secrets/&lt;name&gt;.txt</code> sull'host</li>
    <li>Da CLI: <code>docker compose restart gateway</code> (≤ 2s downtime)</li>
  </ol>
  <p>Vedi <a href="https://github.com/&lt;owner&gt;/vps1777/blob/main/docs/SECRETS.md" target="_blank" style="color:var(--accent)">docs/SECRETS.md</a>.</p>
</section>
"""
    return _layout("secrets", body, current="secrets")
