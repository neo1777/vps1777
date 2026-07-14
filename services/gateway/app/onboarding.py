"""
/admin/setup — pannello di onboarding (timbro 1777).

Raccoglie i dati che mancano per rendere lo stack pienamente operativo:
  - Tailscale auth-key
  - Telegram bot token + owner id
  - PUBLIC_BASE (URL pubblico, opzionale: di norma lo ricava deploy.sh dopo
    il login Tailscale)
  - NotebookLM auth.json (gestito dalla pagina dedicata /admin/nlm)

Il gateway NON ha privilegi Docker né accesso ai secret host (montati ro):
quindi NON applica le azioni. Scrive i valori in
  $ONBOARDING_DIR/pending.json   (bind-mount condiviso col PC)
e l'utente lancia dal proprio PC:
  ./deploy.sh --apply
che legge il file via SSH, scrive i veri secret/.env, fa `tailscale up`,
imposta PUBLIC_BASE e riavvia i servizi.

Questo separa nettamente "raccolta dati" (web, senza privilegi) da
"applicazione" (deploy.sh dal PC, con SSH+sudo).
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from .admin import _csrf_token, _layout, _require_admin
from . import nlm_client
from .audit import audit
from .settings import get_settings


async def _status() -> dict[str, tuple[str, str]]:
    """
    Ritorna {chiave: (stato, dettaglio)} con stato in {ok,warn,off}.
    Euristiche lato gateway (non ha visibilità diretta sul sidecar Tailscale).
    """
    s = get_settings()
    out: dict[str, tuple[str, str]] = {}

    # PUBLIC_BASE / URL
    pb = s.gateway_public_base
    if pb and pb.startswith("https://"):
        out["url"] = ("ok", pb)
    elif pb:
        out["url"] = ("warn", pb)
    else:
        out["url"] = ("off", "non impostato")

    # Tailscale (deduzione: URL .ts.net presente)
    if pb and ".ts.net" in pb:
        out["tailscale"] = ("ok", "Funnel attivo")
    else:
        out["tailscale"] = ("off", "non configurato")

    # NotebookLM auth: il profilo lo possiede nb1777-mcp (H6) — il gateway non
    # monta più quel volume, chiede lo stato su rete interna.
    nlm = await nlm_client.status()
    if nlm is None:
        out["nlm"] = ("warn", "nb1777-mcp non raggiungibile")
    elif nlm.get("ok"):
        out["nlm"] = ("ok", "profilo nlm presente")
    else:
        out["nlm"] = ("off", "profilo nlm non caricato")

    # Bot Telegram
    if s.effective_bot_token:
        out["bot"] = ("ok", "token presente")
    else:
        out["bot"] = ("off", "token non impostato")

    return out


def _pending_path() -> Path:
    s = get_settings()
    d = Path(s.onboarding_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d / "pending.json"


# pending.json contiene authkey Tailscale + bot token IN CHIARO finché non parte
# `deploy.sh --apply` (che lo consuma e lo cancella). Se l'apply non arriva mai,
# quei segreti resterebbero a marcire su disco → TTL: dopo PENDING_TTL il file è
# considerato scaduto e cancellato alla prima lettura (auto-wipe) — H36.
PENDING_TTL = timedelta(hours=24)


def _pending_is_stale(submitted_at: str | None, now: datetime) -> bool:
    """True se il pending è più vecchio di PENDING_TTL. Logica pura (testabile).

    Fail-closed: senza timestamp, o con un timestamp non parsabile, lo si tratta
    come scaduto (meglio ri-chiedere i dati che tenere segreti di età ignota)."""
    if not submitted_at:
        return True
    try:
        ts = datetime.fromisoformat(submitted_at)
    except ValueError:
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return now - ts > PENDING_TTL


def _read_pending() -> dict:
    """Legge pending.json applicando il TTL. Se assente/illeggibile → {}. Se
    scaduto → lo cancella (auto-wipe dei segreti in chiaro) e ritorna {}."""
    pp = _pending_path()
    try:
        data = json.loads(pp.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict) or _pending_is_stale(
        data.get("submitted_at"), datetime.now(timezone.utc)
    ):
        try:
            pp.unlink()
        except OSError:
            pass
        audit({"event": "onboarding_pending_expired"})
        return {}
    return data


async def setup_view(request: Request) -> Response:
    email, redirect = await _require_admin(request)
    if redirect:
        return redirect

    if request.method == "POST":
        form = await request.form()
        pending: dict[str, str] = {}
        # Solo i campi compilati finiscono nel pending (merge non distruttivo).
        # _read_pending applica il TTL: se il precedente è scaduto si riparte da
        # zero (niente merge su segreti vecchi) invece di prolungarne la vita.
        existing = _read_pending()
        pp = _pending_path()
        for key in ("tailscale_authkey", "telegram_bot_token", "telegram_owner_id", "public_base"):
            val = str(form.get(key, "")).strip()
            if val:
                pending[key] = val
        merged = {**existing, **pending}
        merged["submitted_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            pp.write_text(json.dumps(merged, indent=2), encoding="utf-8")
            pp.chmod(0o600)
        except OSError as exc:
            return RedirectResponse(
                f"/admin/setup?msg=Errore+scrittura:+{str(exc).replace(' ', '+')}&kind=err",
                status_code=303,
            )
        # Audit senza valori sensibili: solo i nomi dei campi
        audit({"event": "onboarding_pending_saved", "by": email, "fields": list(pending)})
        n = len([k for k in pending if k != "submitted_at"])
        return RedirectResponse(
            f"/admin/setup?msg={n}+valori+salvati.+Ora+lancia+./deploy.sh+--apply+dal+tuo+PC&kind=ok",
            status_code=303,
        )

    # ───── GET ─────
    st = await _status()
    flash = request.query_params.get("msg", "").replace("+", " ")
    flash_kind = request.query_params.get("kind", "ok")

    def dot(state: str) -> str:
        return f'<span class="dot {state}"></span>'

    # _read_pending applica il TTL: un pending scaduto viene cancellato qui (al
    # semplice caricamento della pagina) e non risulta più "in attesa".
    has_pending = bool(_read_pending())

    body = f"""
<header>
  <h1>vps1777 <em>setup</em></h1>
  <div class="who">{html.escape(email)}</div>
</header>

<section>
  <div class="kicker">stato dei componenti</div>
  <div class="status-grid">
    <div class="status-row">{dot(st['tailscale'][0])}<span class="lbl">Tailscale Funnel</span><span class="val">{html.escape(st['tailscale'][1])}</span></div>
    <div class="status-row">{dot(st['url'][0])}<span class="lbl">URL pubblico</span><span class="val">{html.escape(st['url'][1])}</span></div>
    <div class="status-row">{dot(st['nlm'][0])}<span class="lbl">NotebookLM auth</span><span class="val">{html.escape(st['nlm'][1])}</span></div>
    <div class="status-row">{dot(st['bot'][0])}<span class="lbl">Bot Telegram</span><span class="val">{html.escape(st['bot'][1])}</span></div>
  </div>
</section>

<form method="POST" action="/admin/setup">
  <section>
    <h2>1 · Tailscale Funnel</h2>
    <p class="hint">Genera una pre-auth key su
      <a href="https://login.tailscale.com/admin/settings/keys" target="_blank">login.tailscale.com/admin/settings/keys</a>
      (Generate auth key, Reusable off). Serve a esporre il gateway su HTTPS pubblico.</p>
    <div class="row stack">
      <label>Tailscale auth-key</label>
      <input type="password" name="tailscale_authkey" placeholder="tskey-auth-...">
    </div>
  </section>

  <section>
    <h2>2 · Bot Telegram</h2>
    <p class="hint">Token da <a href="https://t.me/BotFather" target="_blank">@BotFather</a>
      (/newbot o Revoke). Owner ID da <a href="https://t.me/userinfobot" target="_blank">@userinfobot</a>.</p>
    <div class="row stack">
      <label>TELEGRAM_BOT_TOKEN</label>
      <input type="password" name="telegram_bot_token" placeholder="123456:AAF...">
    </div>
    <div class="row stack">
      <label>TELEGRAM_OWNER_ID</label>
      <input type="text" name="telegram_owner_id" placeholder="123456789">
    </div>
  </section>

  <section>
    <h2>3 · URL pubblico <span style="color:var(--faint);font-size:13px">(opzionale)</span></h2>
    <p class="hint">Di norma <code>deploy.sh --apply</code> lo ricava da solo dopo il login Tailscale.
      Compila solo se usi Caddy/Cloudflared con un dominio tuo.</p>
    <div class="row stack">
      <label>PUBLIC_BASE</label>
      <input type="text" name="public_base" placeholder="https://vps.tuosito.com">
    </div>
    <div class="toolbar">
      <button type="submit" class="primary">Salva configurazione</button>
      <a class="btn" href="/admin/nlm">Carica profilo NotebookLM →</a>
    </div>
  </section>
</form>

<section>
  <h2>4 · Applica</h2>
  <p>Dopo aver salvato, dal <strong>tuo PC</strong> (nella cartella del repo):</p>
  <pre><code>./deploy.sh --apply</code></pre>
  <p class="hint">Legge i valori salvati via SSH, configura Tailscale + secret + URL,
    riavvia i servizi. {'<strong style="color:var(--warn)">Config in attesa di applicazione.</strong>' if has_pending else ''}</p>
  <ul>
    <li>Per NotebookLM: usa il bottone sopra (carica il <code>tar.gz</code> del profilo nlm) — è già attivo al volo, senza <code>--apply</code>.</li>
    <li>I valori sensibili restano cifrati nei Docker secret dopo l'apply; il file <code>pending.json</code> viene cancellato.</li>
  </ul>
</section>
"""
    return _layout("setup", body, current="setup", flash=flash, flash_kind=flash_kind,
                   csrf=_csrf_token(email))
