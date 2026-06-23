"""
Mini App Telegram — auth via initData HMAC.

Quando il bot apre la Mini App nel WebApp environment, Telegram inietta
`initData` (URL-encoded firmato HMAC-SHA256 con il TOKEN del bot).
Il frontend la POSTa qui, validiamo, e ritorniamo un JWT typ=miniapp
1h da usare come Bearer per le chiamate MCP.

Riferimento: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from .audit import audit
from .jwt_helpers import issue
from .settings import get_settings


def _verify_init_data(init_data: str, bot_token: str) -> dict | None:
    """
    Valida initData HMAC. Ritorna il payload parsato (dict) se ok, None altrimenti.
    Spec Telegram: secret_key = HMAC_SHA256("WebAppData", bot_token); hash è da escludere dal data_check.
    """
    if not init_data or not bot_token:
        return None
    pairs = list(parse_qsl(init_data, strict_parsing=False, keep_blank_values=True))
    received_hash = None
    data_pairs: list[tuple[str, str]] = []
    for k, v in pairs:
        if k == "hash":
            received_hash = v
        else:
            data_pairs.append((k, v))
    if not received_hash:
        return None

    data_pairs.sort(key=lambda kv: kv[0])
    data_check = "\n".join(f"{k}={v}" for k, v in data_pairs)

    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected = hmac.new(secret_key, data_check.encode("utf-8"), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, received_hash):
        return None

    # Scadenza: 24h (Telegram garantisce auth_date sec since epoch)
    auth_date = int(dict(data_pairs).get("auth_date", "0") or "0")
    if auth_date == 0 or (time.time() - auth_date) > 86400:
        return None

    return dict(data_pairs)


# ───── routes ─────

async def app_index(_request: Request) -> Response:
    """Placeholder Mini App (HTML statico). In F8 expand."""
    body = """<!DOCTYPE html><html><head><title>vps1777</title></head>
<body><h1>vps1777 Mini App</h1>
<p>Placeholder. Implementazione completa: F8.</p>
<script>
  // Telegram WebApp SDK injecte da Telegram
  if (window.Telegram && Telegram.WebApp) {
    Telegram.WebApp.ready();
    document.body.innerHTML += '<pre>initData: ' + Telegram.WebApp.initData + '</pre>';
  }
</script></body></html>"""
    return HTMLResponse(body)


async def miniapp_auth(request: Request) -> Response:
    """POST /app/auth — il frontend manda initData, riceve JWT typ=miniapp."""
    s = get_settings()
    bot_token = s.effective_bot_token
    if not bot_token:
        return JSONResponse({"error": "bot_token_not_configured"}, status_code=503)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_request"}, status_code=400)
    init_data = body.get("init_data", "")
    parsed = _verify_init_data(init_data, bot_token)
    if not parsed:
        audit({"event": "miniapp_auth_fail"})
        return JSONResponse({"error": "invalid_init_data"}, status_code=401)
    try:
        user = json.loads(parsed.get("user", "{}"))
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid_user"}, status_code=400)
    user_id = str(user.get("id", "0"))
    if user_id == "0":
        return JSONResponse({"error": "no_user_id"}, status_code=400)
    tok = issue(
        typ="miniapp", sub=user_id, aud="miniapp",
        ttl=s.oauth_miniapp_token_lifetime,
        extra={"username": user.get("username", "")},
    )
    audit({"event": "miniapp_auth_ok", "user_id": user_id})
    return JSONResponse({"access_token": tok, "expires_in": s.oauth_miniapp_token_lifetime})
