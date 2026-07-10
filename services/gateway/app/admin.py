"""
Pannello admin — /admin/{login,logout,nlm,audit,secrets}.

Tutto dietro `admin_cookie` (JWT typ=admin) settato dopo bcrypt verify.

`/admin/nlm` è il punto chiave: GET = form upload, POST = salva auth.json,
rimuove AUTH_PENDING.flag, restart non necessario (nb1777-mcp legge file on
demand, vedi nb1777-mcp/app/auth.py).
"""
from __future__ import annotations

import asyncio
import html
import io
import json
import os
import re
import secrets as pysecrets
import sqlite3
import tarfile
import time
from pathlib import Path

from . import archive_indexer

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

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
        # path="/" e NON "/admin": il flusso OAuth dopo il login va a /authorize
        # (fuori da /admin); con path=/admin il browser non manderebbe lì il
        # cookie → /authorize non vede la sessione → loop di login.
        path="/",
    )


def _clear_admin_cookie(response: Response) -> None:
    response.delete_cookie(ADMIN_COOKIE, path="/")


# ───── CSRF (synchronizer token firmato, legato alla sessione) ─────
# Difesa in profondità sopra a samesite=lax: un token imprevedibile e firmato,
# embeddato in ogni form e verificato su ogni POST. Un form ostile cross-origin
# non può leggerlo né forgiarlo (non ha la chiave di firma) → la POST fallisce
# anche se il cookie arrivasse. La verifica è CENTRALIZZATA in _require_admin:
# ogni POST admin — anche uno aggiunto in futuro — è protetto d'ufficio, senza
# doverselo ricordare handler per handler.
_CSRF_TTL_FALLBACK = 8 * 3600


def _csrf_token(email: str) -> str:
    s = get_settings()
    return issue(typ="csrf", sub=email, aud="csrf",
                 ttl=s.oauth_admin_cookie_lifetime or _CSRF_TTL_FALLBACK)


def _verify_csrf(form, email: str) -> bool:
    tok = str(form.get("csrf", ""))
    if not tok:
        return False
    try:
        claims = verify(tok, expected_typ="csrf", expected_aud="csrf")
    except JWTError:
        return False
    return claims.get("sub", "").lower() == email


async def _require_admin(request: Request) -> tuple[str | None, Response | None]:
    """Gate admin di ogni pagina. Sui POST verifica ANCHE il token CSRF."""
    email = verify_admin_cookie(request)
    if not email:
        return None, RedirectResponse("/admin/login", status_code=302)
    if request.method == "POST":
        form = await request.form()  # cache-ata: l'handler la rilegge a costo zero
        if not _verify_csrf(form, email):
            audit({"event": "admin_csrf_fail", "email": email, "path": request.url.path})
            return None, _layout(
                "errore",
                '<section><div class="kicker">sicurezza</div><p>Token CSRF mancante o '
                'non valido. Ricarica la pagina e riprova.</p></section>',
                flash="Richiesta rifiutata (protezione CSRF)", flash_kind="err",
            )
    return email, None


# ───── rate-limit login per-IP (difesa in profondità sopra la password forte) ─────
# In-memory, best-effort: dopo _LOGIN_MAX fallimenti da un IP entro _LOGIN_WINDOW,
# l'IP è bloccato per _LOGIN_LOCKOUT. Non è l'unica difesa (la password è forte per
# policy), ma ferma il brute-force da singola sorgente. Si azzera al restart.
_LOGIN_FAILS: dict[str, list[float]] = {}
_LOGIN_LOCK: dict[str, float] = {}
_LOGIN_WINDOW = 300.0
_LOGIN_MAX = 5
_LOGIN_LOCKOUT = 900.0


def _client_ip(request: Request) -> str:
    # uvicorn gira con proxy_headers=True → request.client.host è già l'IP reale
    # dietro l'ingress; fallback su X-Forwarded-For.
    if request.client and request.client.host:
        return request.client.host
    return (request.headers.get("x-forwarded-for", "") or "?").split(",")[0].strip()


def _login_lock_remaining(ip: str) -> float:
    return max(0.0, _LOGIN_LOCK.get(ip, 0.0) - time.time())


def _login_record_fail(ip: str) -> None:
    now = time.time()
    fails = [t for t in _LOGIN_FAILS.get(ip, []) if now - t < _LOGIN_WINDOW]
    fails.append(now)
    if len(fails) >= _LOGIN_MAX:
        _LOGIN_LOCK[ip] = now + _LOGIN_LOCKOUT
        _LOGIN_FAILS.pop(ip, None)
    else:
        _LOGIN_FAILS[ip] = fails


def _login_record_ok(ip: str) -> None:
    _LOGIN_FAILS.pop(ip, None)
    _LOGIN_LOCK.pop(ip, None)


# ───── HTML template minimale ─────
# Font di sistema (niente CDN esterno): la CSP resta senza origini esterne. Il
# CSS ha già i fallback (Georgia / ui-monospace / system-ui).

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
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{color:var(--faint);text-align:left;font-family:var(--mono);font-size:11px;text-transform:uppercase;letter-spacing:.08em;padding:6px 10px 8px;border-bottom:1px solid var(--line)}
td{padding:8px 10px;border-bottom:1px solid var(--line-soft);vertical-align:top}
td.top-labels{color:var(--muted);font-size:11.5px;max-width:240px}
button.danger{border-color:var(--err);color:var(--err)}
button.danger:hover{background:rgba(196,113,88,.12);border-color:var(--err)}
.audit-event{padding:7px 0;border-bottom:1px solid var(--line-soft);font-family:var(--mono);font-size:11px;display:flex;gap:14px}
.audit-event .ts{color:var(--faint);min-width:170px}.audit-event .ev{color:var(--accent-dim);min-width:180px}
.foot{color:var(--faint);font-size:11px;text-align:center;margin-top:40px;font-family:var(--mono);letter-spacing:.04em}
</style>
"""


def _layout(title: str, body: str, current: str = "", flash: str = "",
            flash_kind: str = "ok", csrf: str = "") -> HTMLResponse:
    tabs = ""
    if current:
        items = [
            ("setup", "Setup"),
            ("nlm", "NotebookLM"),
            ("archive", "Archive"),
            ("update", "Update"),
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
    # CSP stretta con nonce: gli script inline (es. polling della card update)
    # portano il nonce; niente 'unsafe-inline' per gli script, niente origini
    # esterne (i Google Fonts sono stati tolti → fallback di sistema).
    nonce = pysecrets.token_urlsafe(16)
    body = body.replace("<script>", f'<script nonce="{nonce}">')
    # inietta il token CSRF in OGNI form (così un nuovo form è protetto senza
    # doverci pensare). Il login (pre-auth) chiama _layout senza csrf → nessun
    # campo, coerente: /admin/login non è dietro _require_admin.
    if csrf:
        _field = f'<input type="hidden" name="csrf" value="{html.escape(csrf)}">'
        body = re.sub(r'(<form\b[^>]*>)', lambda m: m.group(1) + _field, body)
    out = f"""<!DOCTYPE html><html lang="it"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>vps1777 · {html.escape(title)}</title>
{_CSS}
</head><body>
{tabs}{flash_html}{body}
<div class="foot">vps1777 · gateway · v{html.escape(os.environ.get("VPS1777_VERSION", "dev"))}
 · tag {html.escape(os.environ.get("VPS1777_TAG", "dev"))}</div>
</body></html>"""
    resp = HTMLResponse(out)
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
    )
    resp.headers["X-Frame-Options"] = "DENY"
    return resp


# ───── /admin root ─────

async def admin_root(request: Request) -> Response:
    email, redirect = await _require_admin(request)
    if redirect:
        return redirect
    return RedirectResponse("/admin/setup", status_code=302)


# ───── /admin/login ─────

async def login(request: Request) -> Response:
    if request.method == "GET":
        next_url = request.query_params.get("next", "/admin/")
        body = f"""
<header>
  <h1>vps1777 <em>admin</em></h1>
  <div class="who">login</div>
</header>
<form method="POST" action="/admin/login">
  <input type="hidden" name="next" value="{html.escape(next_url)}">
  <section>
    <div class="kicker">accedi</div>
    <div class="row"><label>email</label><input type="email" name="email" required autofocus autocomplete="off"></div>
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
    ip = _client_ip(request)

    locked = _login_lock_remaining(ip)
    if locked > 0:
        audit({"event": "admin_login_locked", "ip": ip})
        await asyncio.sleep(0.5)
        return _layout(
            "login",
            '<section><div class="kicker">accedi</div><p>Troppi tentativi falliti. '
            f'Riprova fra {int(locked // 60) + 1} minuti.</p></section>',
            flash="Accesso temporaneamente bloccato per questo IP", flash_kind="err",
        )

    if email != s.admin_email or not verify_admin_password(password):
        _login_record_fail(ip)
        audit({"event": "admin_login_fail", "email": email, "ip": ip})
        # Delay anti-brute-force ASINCRONO: `time.sleep` bloccherebbe l'intero
        # event loop (un attaccante che martella /admin/login renderebbe il
        # gateway irraggiungibile — DoS su endpoint pubblico).
        await asyncio.sleep(0.5)
        return _layout(
            "login",
            f'<form method="POST" action="/admin/login"><input type="hidden" name="next" value="{html.escape(next_url)}"><section><div class="kicker">accedi</div><div class="row"><label>email</label><input type="email" name="email" required value="{html.escape(email)}"></div><div class="row"><label>password</label><input type="password" name="password" required autofocus></div><div class="toolbar"><button type="submit" class="primary">Entra</button></div></section></form>',
            flash="Email o password errati", flash_kind="err",
        )

    _login_record_ok(ip)
    audit({"event": "admin_login_ok", "email": email, "ip": ip})
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


# ───── /admin/nlm — upload del profilo nlm (notebooklm-mcp-cli 0.7.x) ─────
# La CLI nlm 0.7.x salva l'auth come CARTELLA profiles/default/{cookies.json,
# metadata.json} (non più un singolo auth.json). Qui si carica un tar.gz di
# quella cartella, che viene estratto in <nlm_auth_dir>/profiles/default/.

def _extract_nlm_profile(content: bytes, auth_dir: Path) -> int:
    """Estrae in sicurezza i file sotto profiles/ da un tar.gz. Ritorna #file."""
    n = 0
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as tar:
        for m in tar.getmembers():
            if not m.isfile():
                continue
            name = m.name.lstrip("./")
            parts = Path(name).parts
            if name.startswith("/") or ".." in parts:
                raise ValueError(f"percorso non sicuro nel tar: {m.name}")
            if not parts or parts[0] != "profiles":
                continue  # ignora tutto ciò che non è il profilo
            f = tar.extractfile(m)
            if f is None:
                continue
            dest = auth_dir / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(f.read())
            dest.chmod(0o600)
            n += 1
    return n


async def nlm_view(request: Request) -> Response:
    email, redirect = await _require_admin(request)
    if redirect:
        return redirect

    s = get_settings()
    auth_dir = Path(s.nlm_auth_dir)
    auth_dir.mkdir(parents=True, exist_ok=True)
    cookies_path = auth_dir / "profiles" / "default" / "cookies.json"
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
            if len(content) > 5_000_000:
                raise ValueError("file troppo grande (>5MB)")
            try:
                n = _extract_nlm_profile(content, auth_dir)
            except tarfile.TarError as e:
                raise ValueError(f"non è un tar.gz valido del profilo nlm ({e})") from e
            if not cookies_path.exists():
                raise ValueError("il tar non contiene profiles/default/cookies.json — taggi la cartella giusta?")
            if pending.exists():
                pending.unlink()
            audit({"event": "admin_nlm_upload", "by": email, "files": n})
            msg = f"Profilo nlm caricato ({n} file). NotebookLM attivo alla prossima call."
            return RedirectResponse(f"/admin/nlm?msg={msg.replace(' ', '+')}&kind=ok", status_code=303)
        except (ValueError, OSError) as exc:
            audit({"event": "admin_nlm_upload_err", "by": email, "error": str(exc)})
            return RedirectResponse(
                f"/admin/nlm?msg=Errore:+{str(exc).replace(' ', '+')}&kind=err",
                status_code=303,
            )

    # GET
    ok = cookies_path.exists() and not pending.exists()
    if ok:
        status_html = '<div class="kicker"><span class="dot ok"></span>Profilo nlm presente. NotebookLM dovrebbe funzionare.</div>'
    else:
        status_html = '<div class="kicker"><span class="dot warn"></span>Profilo nlm mancante — caricalo per attivare NotebookLM.</div>'

    flash = request.query_params.get("msg", "").replace("+", " ")
    flash_kind = request.query_params.get("kind", "ok")

    body = f"""
<header>
  <h1>vps1777 <em>admin</em> · NotebookLM</h1>
  <div class="who">{html.escape(email)}</div>
</header>
{status_html}
<section>
  <div class="kicker">come ottenere il profilo nlm</div>
  <ol>
    <li>Sul TUO PC, installa <code>nlm</code> (serve <a href="https://astral.sh" target="_blank">uv</a>):
      <pre>uv tool install notebooklm-mcp-cli --python 3.12</pre>
    </li>
    <li>Login Google (apre il browser):
      <pre>nlm login
nlm notebook list   # verifica</pre>
    </li>
    <li>Crea un tar.gz del profilo e caricalo qui sotto:
      <pre>cd ~/.notebooklm-mcp-cli
tar czf nlm-profile.tgz profiles/default</pre>
    </li>
  </ol>
</section>

<form method="POST" action="/admin/nlm" enctype="multipart/form-data">
  <section>
    <div class="row"><label>profilo nlm (.tgz)</label><input type="file" name="auth_file" accept=".tgz,.gz,.tar.gz,application/gzip" required></div>
    <div class="toolbar">
      <button type="submit" class="primary">Carica</button>
      <a class="btn" href="/admin/audit">Audit →</a>
      <form method="POST" action="/admin/logout" style="display:inline"><button type="submit">Logout</button></form>
    </div>
  </section>
</form>
"""
    return _layout("NotebookLM", body, current="nlm", flash=flash, flash_kind=flash_kind,
                   csrf=_csrf_token(email))


# ───── /admin/archive — upload + indicizzazione sessioni per archive-mcp ─────
# Il gateway monta il volume archive-data:rw. Riceve un .jsonl (sessione Claude
# Code), lo streamma su disco e lo indicizza in-process (archive_indexer, memoria
# costante) in <archive_db_dir>/<nome>.db. archive-mcp lo scopre da solo
# (scan-mode) → cercabile subito, nessun restart, nessun docker.sock.

_ARCHIVE_NAME_RE = re.compile(r"[^a-z0-9_-]+")


def _safe_db_name(raw: str, fallback: str = "archivio") -> str:
    name = _ARCHIVE_NAME_RE.sub("-", (raw or "").strip().lower()).strip("-")
    return name or fallback


def _archive_dbs() -> list[dict]:
    """Scheda (db_info) di ogni .db nella dir archive."""
    db_dir = Path(get_settings().archive_db_dir)
    if not db_dir.is_dir():
        return []
    return [archive_indexer.db_info(p)
            for p in sorted(db_dir.glob("*.db")) if p.is_file()]


def _fmt_size(n: float) -> str:
    """Dimensione leggibile (99.4 MB)."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _valid_archive_db(path: Path) -> bool:
    """True se il file è un SQLite con la tabella messages_fts attesa (drop-in)."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            conn.execute("SELECT 1 FROM messages_fts LIMIT 1")
            return True
        finally:
            conn.close()
    except sqlite3.Error:
        return False


async def archive_view(request: Request) -> Response:
    email, redirect = await _require_admin(request)
    if redirect:
        return redirect

    s = get_settings()
    db_dir = Path(s.archive_db_dir)
    db_dir.mkdir(parents=True, exist_ok=True)

    if request.method == "POST":
        form = await request.form()
        upload = form.get("jsonl_file")
        if upload is None or not hasattr(upload, "read"):
            return RedirectResponse("/admin/archive?msg=Nessun+file+caricato&kind=err", status_code=303)
        db_name = _safe_db_name(
            str(form.get("db_name") or ""),
            fallback=_safe_db_name(Path(getattr(upload, "filename", "") or "").stem),
        )
        project = str(form.get("project") or "").strip()
        suffix = Path(str(getattr(upload, "filename", "") or "")).suffix.lower() or ".jsonl"
        tmp = db_dir / f".upload-{db_name}-{os.getpid()}{suffix}"
        db_path = db_dir / f"{db_name}.db"
        try:
            # stream su disco a chunk (memoria costante anche su file da decine di MB)
            fh = upload.file  # type: ignore[union-attr]
            fh.seek(0)
            with open(tmp, "wb") as w:
                while True:
                    chunk = fh.read(1024 * 1024)
                    if not chunk:
                        break
                    w.write(chunk)
            if suffix == ".db":
                # drop-in: un .db già indicizzato. Valida lo schema prima di accettarlo.
                if not _valid_archive_db(tmp):
                    raise ValueError("il .db non ha lo schema atteso (messages_fts)")
                tmp.replace(db_path)
                n = archive_indexer.count_rows(db_path)
                verb = "caricato (drop-in)"
            else:
                # dispatch per estensione: .jsonl/.json → Claude Code; .zip → claude.ai; .md/.txt → testo
                n = archive_indexer.index_file(str(tmp), str(db_path), project=project)
                verb = "indicizzati"
            total = archive_indexer.count_rows(db_path)
            audit({"event": "admin_archive_ingest", "by": email, "db": db_name, "fmt": suffix, "rows": n})
            msg = f"{verb}: {n} record in '{db_name}' (totale {total}). Ricerca attiva subito."
            return RedirectResponse(f"/admin/archive?msg={msg.replace(' ', '+')}&kind=ok", status_code=303)
        except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
            audit({"event": "admin_archive_ingest_err", "by": email, "db": db_name, "error": str(exc)})
            return RedirectResponse(
                f"/admin/archive?msg=Errore:+{str(exc).replace(' ', '+')}&kind=err", status_code=303)
        finally:
            tmp.unlink(missing_ok=True)

    # GET
    dbs = _archive_dbs()
    if dbs:
        rows = ""
        for d in dbs:
            top = " · ".join(
                f"{html.escape(t['label'] or '(senza etichetta)')} ({t['rows']})"
                for t in d["top"][:3]
            )
            rows += (
                f"<tr><td><code>{html.escape(d['name'])}</code></td>"
                f"<td>{d['rows']}</td><td>{d['labels']}</td>"
                f'<td class="top-labels">{top}</td>'
                f"<td>{_fmt_size(d['size'])}</td>"
                f"<td>{html.escape(str(d['mtime'])[:10])}</td>"
                f'<td><form method="POST" action="/admin/archive/delete" class="delform">'
                f'<input type="hidden" name="db" value="{html.escape(d["name"])}">'
                f'<button type="submit" class="danger">Elimina</button></form></td></tr>'
            )
        table = (f'<section><div class="kicker">DB nell\'archivio</div>'
                 f'<table><thead><tr><th>nome</th><th>messaggi</th><th>etichette</th>'
                 f'<th>principali</th><th>dimensione</th><th>aggiornato</th><th></th></tr></thead>'
                 f'<tbody>{rows}</tbody></table>'
                 f'<p class="hint">Eliminare un DB toglie subito l\'archivio dalla ricerca. '
                 f'Per <em>resettarlo</em>: elimina e ricarica la fonte con lo stesso nome.</p>'
                 f"""</section>
<script>
document.querySelectorAll('form.delform').forEach(function(f){{
  f.addEventListener('submit', function(ev){{
    var db = f.querySelector('input[name=db]').value;
    if (!window.confirm('Eliminare definitivamente il DB "' + db + '"? La ricerca su questo archivio smette subito.'))
      ev.preventDefault();
  }});
}});
</script>""")
        status_html = f'<div class="kicker"><span class="dot ok"></span>{len(dbs)} DB caricati, cercabili subito via il tool <code>search</code>.</div>'
    else:
        table = ""
        status_html = '<div class="kicker"><span class="dot warn"></span>Archivio vuoto — carica una sessione per popolarlo.</div>'

    flash = request.query_params.get("msg", "").replace("+", " ")
    flash_kind = request.query_params.get("kind", "ok")
    body = f"""
<header>
  <h1>vps1777 <em>admin</em> · Archive</h1>
  <div class="who">{html.escape(email)}</div>
</header>
{status_html}
{table}
<section>
  <div class="kicker">carica una fonte da indicizzare</div>
  <p class="muted">Formati: <code>.zip</code> (export account claude.ai — conversazioni + design chats + docs — oppure export chat Telegram Desktop, <strong>JSON o HTML</strong>: lo zip della cartella <code>ChatExport_*</code> va bene così com'è), <code>.jsonl</code> (sessione Claude Code), <code>.json</code> (export Telegram Desktop, formato JSON), <code>.pdf</code> (documento con testo — non gli screenshot), <code>.md</code>/<code>.txt</code> (testo, es. output di web2md o lettoremd), <code>.db</code> (drop-in già indicizzato). Viene reso cercabile subito. Ricaricare lo stesso <em>nome DB</em> non duplica (dedup per id); fonti diverse sullo stesso nome si accumulano — ma non mischiare HTML e JSON della <em>stessa</em> chat nello stesso DB (chiavi diverse → doppioni).</p>
  <form method="POST" action="/admin/archive" enctype="multipart/form-data">
    <div class="row"><label>fonte</label><input type="file" name="jsonl_file" accept=".jsonl,.json,.zip,.md,.txt,.pdf,.db" required></div>
    <div class="row"><label>nome DB</label><input type="text" name="db_name" placeholder="es. cc (vuoto = dal nome file)"></div>
    <div class="row"><label>progetto</label><input type="text" name="project" placeholder="etichetta (vuoto = dedotta dalla fonte)"></div>
    <div class="toolbar">
      <button type="submit" class="primary">Carica e indicizza</button>
      <a class="btn" href="/admin/audit">Audit →</a>
      <form method="POST" action="/admin/logout" style="display:inline"><button type="submit">Logout</button></form>
    </div>
  </form>
</section>
<section>
  <div class="kicker">documenti e immagini (PDF-scansione, screenshot)</div>
  <p class="muted">I PDF <em>senza testo</em> (scansioni, screenshot) non si indicizzano qui: non hanno testo da estrarre. Ma <strong>NotebookLM può leggerli</strong> (OCR multimodale). Dall'host:</p>
  <pre>vps1777 archive-ingest &lt;file&gt; --db &lt;nome&gt; --verify</pre>
  <p class="muted">NotebookLM trascrive il documento (con una verifica di fedeltà opzionale), il testo viene indicizzato nell'archivio FTS e diventa cercabile qui accanto. Funziona con PDF-immagine, scansioni e qualunque file che NotebookLM sappia leggere. La trascrizione è generata da LLM: ottima per ritrovare contenuti, non garantita fedele al 100% su layout complessi.</p>
</section>
"""
    return _layout("Archive", body, current="archive", flash=flash, flash_kind=flash_kind,
                   csrf=_csrf_token(email))


async def archive_delete(request: Request) -> Response:
    """POST /admin/archive/delete — elimina un DB dell'archivio (irreversibile).

    Il nome viene risolto contro il listato reale della dir (find_db): niente
    path costruiti dall'input. archive-mcp se ne accorge da solo (scan-mode).
    """
    email, redirect = await _require_admin(request)
    if redirect:
        return redirect
    form = await request.form()
    name = _safe_db_name(str(form.get("db") or ""), fallback="")
    path = archive_indexer.find_db(get_settings().archive_db_dir, name)
    if path is None:
        audit({"event": "admin_archive_delete_err", "by": email, "db": name, "error": "not_found"})
        return RedirectResponse("/admin/archive?msg=DB+non+trovato&kind=err", status_code=303)
    rows = archive_indexer.count_rows(path)
    try:
        path.unlink()
    except OSError as exc:
        audit({"event": "admin_archive_delete_err", "by": email, "db": name, "error": str(exc)})
        return RedirectResponse(
            f"/admin/archive?msg=Errore:+{str(exc).replace(' ', '+')}&kind=err", status_code=303)
    audit({"event": "admin_archive_delete", "by": email, "db": name, "rows": rows})
    msg = f"DB '{name}' eliminato ({rows} messaggi). Per ripartire ricarica la fonte."
    return RedirectResponse(f"/admin/archive?msg={msg.replace(' ', '+')}&kind=ok", status_code=303)


# ───── /admin/update — canale di aggiornamento ─────
# Il gateway NON ha privilegi Docker (vedi onboarding.py): questo pannello
# raccoglie l'INTENT e mostra lo stato; l'update vero lo esegue la CLI host
# `vps1777` via systemd path unit (pattern collect→apply, come pending.json).
# File condivisi via bind-mount onboarding/:
#   update_status.json   ← scritto dal timer di check (letto qui)
#   update_pending_update.json → intent scritto qui (consumato dalla CLI)
#   update_progress.json ← scritto dalla CLI a ogni step (pollato qui)

def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


async def update_state(request: Request) -> Response:
    """JSON per il polling della card (stato check + progress updater)."""
    email = verify_admin_cookie(request)
    if not email:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    ob = Path(get_settings().onboarding_dir)
    return JSONResponse({
        "status": _read_json(ob / "update_status.json"),
        "progress": _read_json(ob / "update_progress.json"),
        "intent_pending": (ob / "update_pending_update.json").exists(),
        "running_version": os.environ.get("VPS1777_VERSION", "dev"),
        "running_tag": os.environ.get("VPS1777_TAG", "dev"),
    })


async def update_view(request: Request) -> Response:
    email, redirect = await _require_admin(request)
    if redirect:
        return redirect
    s = get_settings()
    ob = Path(s.onboarding_dir)
    status = _read_json(ob / "update_status.json")

    if request.method == "POST":
        latest = str(status.get("latest") or "")
        if not latest:
            return RedirectResponse(
                "/admin/update?msg=Nessuna+versione+nota:+attendi+il+check+giornaliero&kind=err",
                status_code=303)
        intent = {
            "target_version": latest,
            "requested_by": email,
            "requested_at": time.time(),
            "nonce": pysecrets.token_hex(16),
        }
        path = ob / "update_pending_update.json"
        path.write_text(json.dumps(intent, indent=2) + "\n")
        # 0644, non 0600: l'intent NON contiene segreti (target/nonce/email) e
        # dev'essere LEGGIBILE dalla CLI host, che può girare con un uid diverso
        # da quello del container gateway (uid 1000). La cancellazione la fa la
        # CLI grazie alla ownership della dir onboarding/, non del file.
        path.chmod(0o644)
        audit({"event": "admin_update_requested", "by": email, "target": latest})
        return RedirectResponse(
            "/admin/update?msg=Update+richiesto:+l'updater+parte+entro+pochi+secondi&kind=ok",
            status_code=303)

    # GET
    current = status.get("current") or os.environ.get("VPS1777_TAG", "dev")
    latest = status.get("latest")
    checked = status.get("checked_at", "mai")
    check_err = status.get("error")
    excerpt = status.get("changelog_excerpt", "")

    if check_err:
        head = ('<div class="kicker"><span class="dot warn"></span>'
                f'Ultimo check fallito ({html.escape(str(check_err))}) — dato stantio.</div>')
    elif latest and latest != current:
        head = ('<div class="kicker"><span class="dot warn"></span>'
                f'Aggiornamento disponibile: <strong>v{html.escape(str(latest))}</strong>'
                f' (sei alla {html.escape(str(current))}).</div>')
    elif latest:
        head = ('<div class="kicker"><span class="dot ok"></span>'
                'Sei alla versione più recente.</div>')
    else:
        head = ('<div class="kicker"><span class="dot off"></span>'
                'Nessun check ancora eseguito (il timer gira una volta al giorno).</div>')

    update_btn = ""
    if latest and latest != current and not check_err:
        update_btn = f"""
<form method="POST" action="/admin/update"
      onsubmit="return confirm('Aggiorno a v{html.escape(str(latest))}? Backup automatico prima, rollback automatico se non torna healthy.')">
  <div class="toolbar"><button type="submit" class="primary">Aggiorna a v{html.escape(str(latest))}</button></div>
</form>"""

    changelog_html = ""
    if excerpt:
        changelog_html = f'<section><div class="kicker">changelog</div><pre>{html.escape(excerpt)}</pre></section>'

    flash = request.query_params.get("msg", "").replace("+", " ")
    flash_kind = request.query_params.get("kind", "ok")

    body = f"""
<header>
  <h1>vps1777 <em>admin</em> · update</h1>
  <div class="who">{html.escape(email)}</div>
</header>
{head}
<section>
  <div class="status-grid">
    <div class="status-row"><span class="lbl">versione deployata</span><span class="val">{html.escape(str(current))}</span></div>
    <div class="status-row"><span class="lbl">ultima release</span><span class="val">{html.escape(str(latest or '?'))}</span></div>
    <div class="status-row"><span class="lbl">ultimo check</span><span class="val">{html.escape(str(checked))}</span></div>
  </div>
  {update_btn}
  <p class="hint">L'update è eseguito dalla CLI host (backup → pull verificato → migrazioni →
  health-gate → rollback automatico su fallimento). Da terminale: <code>vps1777 update</code>.</p>
</section>
{changelog_html}
<section id="progress-card" style="display:none">
  <div class="kicker">avanzamento update</div>
  <div class="status-grid" id="progress-body"></div>
</section>
<script>
async function pollProgress() {{
  try {{
    const r = await fetch('/admin/update/state', {{cache: 'no-store'}});
    if (!r.ok) throw new Error(r.status);
    const d = await r.json();
    const p = d.progress || {{}};
    const card = document.getElementById('progress-card');
    const bodyEl = document.getElementById('progress-body');
    if (p.step_name) {{
      card.style.display = '';
      const cls = p.status === 'ok' ? 'ok' : (p.status === 'running' ? 'warn' : 'err');
      bodyEl.innerHTML = '<div class="status-row"><span class="dot ' + cls + '"></span>' +
        '<span class="lbl">step ' + p.step + ' — ' + p.step_name + '</span>' +
        '<span class="val">' + p.status + (p.detail ? ' · ' + p.detail : '') + '</span></div>' +
        '<div class="status-row"><span class="lbl">target</span><span class="val">v' + (p.target || '?') +
        ' · ' + (p.updated_at || '') + '</span></div>';
      if (p.status === 'running' || d.intent_pending) setTimeout(pollProgress, 2000);
    }} else if (d.intent_pending) {{
      card.style.display = '';
      bodyEl.innerHTML = '<div class="status-row"><span class="dot warn"></span>' +
        '<span class="lbl">updater in avvio…</span></div>';
      setTimeout(pollProgress, 2000);
    }}
  }} catch (e) {{
    // il gateway stesso si riavvia a metà update: continua a pollare
    const card = document.getElementById('progress-card');
    card.style.display = '';
    document.getElementById('progress-body').innerHTML =
      '<div class="status-row"><span class="dot warn"></span>' +
      '<span class="lbl">gateway in riavvio… riprovo</span></div>';
    setTimeout(pollProgress, 2000);
  }}
}}
pollProgress();
</script>
"""
    return _layout("update", body, current="update", flash=flash, flash_kind=flash_kind,
                   csrf=_csrf_token(email))


# ───── /admin/audit ─────

async def audit_view(request: Request) -> Response:
    email, redirect = await _require_admin(request)
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
    return _layout("audit", body, current="audit", csrf=_csrf_token(email))


# ───── /admin/secrets — età, scadenze, rotazione ─────
# Legge onboarding/secrets_status.json, scritto dal check host (`vps1777
# secrets-status`, timer settimanale): l'età deriva dall'mtime dei file secret.

async def secrets_view(request: Request) -> Response:
    email, redirect = await _require_admin(request)
    if redirect:
        return redirect
    s = get_settings()
    status = _read_json(Path(s.onboarding_dir) / "secrets_status.json")
    secrets = status.get("secrets", [])
    if secrets:
        rows = ""
        for it in secrets:
            over = it.get("overdue")
            badge = (f'<span class="dot {"warn" if over else "ok"}"></span>'
                     f'{"da ruotare" if over else "ok"}')
            rows += (
                f'<tr><td><code>{html.escape(str(it.get("name", "")))}</code><br>'
                f'<span class="muted">{html.escape(str(it.get("label", "")))}</span></td>'
                f'<td>{it.get("age_days", "?")}g <span class="muted">/ max {it.get("max_age_days", "?")}g</span></td>'
                f'<td>{badge}</td>'
                f'<td><span class="muted">{html.escape(str(it.get("note", "")))}</span></td></tr>'
            )
        table = ('<section><table><thead><tr><th>secret</th><th>età</th><th>stato</th>'
                 f'<th>rotazione</th></tr></thead><tbody>{rows}</tbody></table></section>')
        checked = html.escape(str(status.get("checked_at", "")))
        status_html = f'<div class="kicker">ultimo check: {checked}</div>'
    else:
        table = ""
        status_html = ('<div class="kicker"><span class="dot off"></span>stato non ancora '
                       'disponibile — gira <code>vps1777 secrets-status</code> sull\'host</div>')
    body = f"""
<header>
  <h1>vps1777 <em>admin</em> · secrets</h1>
  <div class="who">{html.escape(email)}</div>
</header>
{status_html}
{table}
<section>
  <div class="kicker">come ruotare</div>
  <p class="muted">La rotazione è guidata da CLI sull'host (mostra la nuova, la salvi nel password manager). Un check settimanale avvisa su Telegram i secret oltre soglia.</p>
  <pre>cd /home/vps1777/vps1777 && sudo -u vps1777 ./tools/rotate-secret.sh &lt;nome&gt;</pre>
  <p class="muted">Attenzione: ruotare <code>oauth_signing_secret</code> invalida i token (i connettori si ri-autenticano); <code>gateway_secret</code> cambia le URL MCP (vanno ri-aggiunti su claude.ai). Password e token bot sono solo manuali. La policy password impone min 16, ≥3 classi, niente pattern comuni.</p>
</section>
"""
    return _layout("secrets", body, current="secrets", csrf=_csrf_token(email))
