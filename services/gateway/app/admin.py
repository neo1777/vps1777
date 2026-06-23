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
from typing import Any

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
        secure=True,
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

_CSS = """
<style>
:root{--bg:#0d0e10;--fg:#e4e2dd;--muted:#86868b;--accent:#d97757;--ok:#5eb87a;--warn:#d4a35e;--err:#c47158;--line:#2a2a2c;--bg-card:#15161a}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;background:var(--bg);color:var(--fg);line-height:1.55;padding:40px 24px;max-width:760px;margin:0 auto}
header{margin-bottom:36px;padding-bottom:18px;border-bottom:1px solid var(--line)}
h1{font-weight:600;letter-spacing:.02em}h1 em{color:var(--accent);font-style:normal;font-weight:400}
.who{color:var(--muted);font-size:13px;margin-top:6px}
.kicker{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:14px}
section{background:var(--bg-card);border:1px solid var(--line);padding:22px;border-radius:6px;margin-bottom:24px}
form .row{display:grid;grid-template-columns:140px 1fr;gap:16px;align-items:center;margin-bottom:14px}
label{color:var(--muted);font-size:13px}
input[type=email],input[type=password],input[type=text],input[type=file]{background:var(--bg);color:var(--fg);border:1px solid var(--line);padding:10px 12px;border-radius:4px;font-family:inherit;font-size:14px;width:100%}
input:focus{outline:none;border-color:var(--accent)}
.toolbar{display:flex;gap:10px;margin-top:18px;flex-wrap:wrap}
button,.btn{background:var(--bg);color:var(--fg);border:1px solid var(--line);padding:8px 14px;border-radius:4px;cursor:pointer;text-decoration:none;font-size:13px;font-family:inherit}
button.primary,.btn.primary{background:var(--accent);color:#15161a;border-color:var(--accent)}
button:hover,.btn:hover{border-color:var(--accent)}
.flash{padding:10px 14px;border-radius:4px;margin-bottom:18px;font-size:13px}
.flash.ok{background:rgba(94,184,122,.1);border:1px solid var(--ok);color:var(--ok)}
.flash.err{background:rgba(196,113,88,.1);border:1px solid var(--err);color:var(--err)}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:middle}
.dot.ok{background:var(--ok)}.dot.warn{background:var(--warn)}.dot.err{background:var(--err)}
pre,code{font-family:'JetBrains Mono',monospace;font-size:12px}
pre{background:var(--bg);padding:10px;border-radius:4px;overflow-x:auto;margin:8px 0}
ol li{margin-bottom:12px}
nav.tabs{display:flex;gap:0;margin-bottom:24px;border-bottom:1px solid var(--line)}
nav.tabs a{padding:8px 16px;color:var(--muted);text-decoration:none;font-size:13px;border-bottom:2px solid transparent}
nav.tabs a.active{color:var(--fg);border-color:var(--accent)}
.audit-event{padding:6px 0;border-bottom:1px solid var(--line);font-family:'JetBrains Mono',monospace;font-size:11px;display:flex;gap:12px}
.audit-event .ts{color:var(--muted);min-width:170px}.audit-event .ev{color:var(--accent);min-width:170px}
</style>
"""


def _layout(title: str, body: str, current: str = "", flash: str = "", flash_kind: str = "ok") -> HTMLResponse:
    tabs = ""
    if current:
        items = [
            ("secrets", "Secrets"),
            ("nlm", "NotebookLM"),
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
{_CSS}
</head><body>
{tabs}{flash_html}{body}
</body></html>"""
    return HTMLResponse(out)


# ───── /admin root ─────

async def admin_root(request: Request) -> Response:
    email, redirect = _require_admin(request)
    if redirect:
        return redirect
    return RedirectResponse("/admin/nlm", status_code=302)


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
