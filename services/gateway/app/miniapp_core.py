"""Validazione initData Telegram — pura stdlib, zero dipendenze di terze parti.

Isolata qui (fuori da miniapp.py, che importa starlette) così è importabile e
testabile stdlib-only, come archive_indexer / asgi_security: la CI gira i test
del gateway con `uvx pytest` senza installare le deps pesanti.

Spec: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
from __future__ import annotations

import hashlib
import hmac
import json as _json
import time
from urllib.parse import parse_qsl

# Finestra di validità di `initData` (H27). Era 24h.
# Telegram NON revoca una initData: finché è dentro la finestra, chiunque la
# ottenga (screenshot, log del client, condivisione schermo, backup della
# webview) può scambiarla per un JWT typ=miniapp con una sola POST a /app/auth.
# La finestra è quindi la vita utile di un replay. 12h coprono una giornata di
# lavoro senza dover riaprire il pannello dal bot, e dimezzano quella vita.
# Scaduta la finestra, il frontend riceve 401 e chiede di riaprire dal bot.
INIT_DATA_MAX_AGE_S = 12 * 3600  # 12h


def verify_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_s: int = INIT_DATA_MAX_AGE_S,
    now: float | None = None,
) -> dict | None:
    """Valida l'HMAC di `initData`. Ritorna il payload parsato (dict) se valido,
    None altrimenti.

    secret_key = HMAC_SHA256("WebAppData", bot_token); il campo `hash` è escluso
    dal data_check_string. Scarta se più vecchio di max_age_s (auth_date).
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

    # Freshness: auth_date è secondi epoch. 0/mancante o troppo vecchio → scarta.
    auth_date = int(dict(data_pairs).get("auth_date", "0") or "0")
    _now = time.time() if now is None else now
    if auth_date == 0 or (_now - auth_date) > max_age_s:
        return None

    return dict(data_pairs)


def is_owner(user_id: object, owner_id: int) -> bool:
    """True SOLO se l'utente è l'owner configurato.

    FAIL-CLOSED: owner_id==0 (non configurato, o coerzione silenziosa di un
    valore malformato nel .env) → False. Se non sappiamo chi è l'owner, nessuno
    lo è. Prima ritornava True ("nessun filtro"): un OWNER_ID vuoto o storto in
    produzione apriva bot e Mini App a QUALUNQUE utente Telegram con initData
    valida. Il gate chiamante deve distinguere il caso "non configurato" per dare
    un errore chiaro (503) invece di un generico 403."""
    if not owner_id:
        return False
    try:
        return int(user_id) == int(owner_id)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return False


# ───── URL dei connettori MCP (contengono il gateway_secret) ─────
# H26: il gateway_secret vive nel PATH dell'URL del connettore
# (`/<SECRET>/<service>/mcp`). Stamparlo nel DOM della Mini App lo espone a
# tutto ciò che vede lo schermo di un telefono — screenshot, condivisione
# schermo, cronologia della webview — e copiarlo in clipboard lo consegna alla
# sincronizzazione cloud della tastiera/OS. Default = MASCHERATO; l'URL completo
# è un'azione esplicita e audita, non il contenuto di default della pagina.

SECRET_MASK = "•" * 8      # bullet a lunghezza FISSA: non rivela la lunghezza del segreto
SECRET_PLACEHOLDER = "<SECRET>"  # segreto non configurato: non c'è niente da mascherare


def connector_url(base: str, secret: str, name: str) -> str:
    """URL completo del connettore MCP — CONTIENE IL SEGRETO.
    Va servito solo su richiesta esplicita dell'owner (reveal), mai di default."""
    b = (base or "").rstrip("/")
    return f"{b}/{secret or SECRET_PLACEHOLDER}/{name}/mcp"


def masked_connector_url(base: str, name: str, *, has_secret: bool = True) -> str:
    """Come `connector_url`, col segreto sostituito da un mask a lunghezza fissa.
    È questa la forma che può stare nel DOM."""
    b = (base or "").rstrip("/")
    return f"{b}/{SECRET_MASK if has_secret else SECRET_PLACEHOLDER}/{name}/mcp"


# ───── parsing risposte MCP (streamable-http) ─────
# Il gateway chiama gli upstream MCP direttamente (rete backend) per gli
# endpoint della Mini App. La risposta può arrivare come JSON puro o come SSE
# (text/event-stream, payload nella riga `data:`) — stessa gestione del bot.

def parse_mcp_payload(content_type: str, text: str) -> dict:
    """Estrae il payload JSON-RPC da una risposta MCP streamable-http.
    Solleva ValueError se non c'è payload riconoscibile."""
    if "text/event-stream" in (content_type or ""):
        for line in text.splitlines():
            if line.startswith("data:"):
                data = line[5:].strip()
                if data:
                    return _json.loads(data)
        raise ValueError("risposta SSE MCP senza payload 'data:'")
    return _json.loads(text)


def extract_tool_texts(rpc: dict) -> list[str]:
    """Dai content block del risultato tools/call ritorna i testi.
    Solleva ValueError con messaggio leggibile se il tool ha fallito."""
    if "error" in rpc:
        raise ValueError(str(rpc["error"].get("message", rpc["error"])))
    result = rpc.get("result", {}) or {}
    content = result.get("content", []) or []
    texts = [
        b.get("text", "") for b in content
        if isinstance(b, dict) and b.get("type", "text") == "text"
    ]
    if result.get("isError"):
        raise ValueError((texts[0] if texts else "tool error")[:500])
    return texts


def parse_json_blocks(texts: list[str]) -> list[dict]:
    """Interpreta i content block come oggetti JSON (un dict per block, o un
    block con un array). Blocchi non-JSON vengono ignorati — stessa tolleranza
    del bot: le versioni di FastMCP serializzano in modi diversi."""
    out: list[dict] = []
    for txt in texts:
        try:
            obj = _json.loads(txt)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, list):
            out.extend(x for x in obj if isinstance(x, dict))
        elif isinstance(obj, dict):
            out.append(obj)
    return out


def parse_string_blocks(texts: list[str]) -> list[str]:
    """Interpreta i content block come stringhe (es. list_databases → list[str]).
    Tollera le varie serializzazioni FastMCP: un block con un array JSON, un
    block per stringa (JSON-quoted o plain)."""
    out: list[str] = []
    for txt in texts:
        try:
            obj = _json.loads(txt)
        except (ValueError, TypeError):
            if txt:
                out.append(txt)
            continue
        if isinstance(obj, list):
            out.extend(str(x) for x in obj)
        elif isinstance(obj, (str, int, float)):
            out.append(str(obj))
    return out


def extract_answer(text: str) -> str:
    """notebook_query può ritornare il testo incapsulato in JSON
    ({"answer": "..."}): all'utente va mostrato il testo, non l'involucro.
    Se non è quel formato, il testo passa invariato."""
    try:
        obj = _json.loads(text)
    except (ValueError, TypeError):
        return text
    if isinstance(obj, dict) and isinstance(obj.get("answer"), str):
        return obj["answer"]
    return text


def version_gt(a: str, b: str) -> bool:
    """True se la versione `a` è maggiore di `b` (semver semplice X.Y.Z).
    Un update è "disponibile" solo se latest > running — `latest != running`
    proporrebbe un downgrade quando il check giornaliero è stantio (es. latest
    0.15.0 letto prima di una release, running 0.15.2). Componenti non numerici
    → confronto stringa, meglio di un crash."""
    if not a or not b:
        return False
    try:
        ta = tuple(int(x) for x in a.strip().lstrip("v").split("."))
        tb = tuple(int(x) for x in b.strip().lstrip("v").split("."))
        return ta > tb
    except ValueError:
        return a > b


def summarize_secrets(status: dict) -> dict:
    """Riassunto compatto di secrets_status.json per la card overview."""
    secrets = status.get("secrets", []) or []
    overdue = [s.get("name", "?") for s in secrets if s.get("overdue")]
    return {
        "total": len(secrets),
        "overdue": len(overdue),
        "overdue_names": overdue,
        "checked_at": status.get("checked_at", ""),
    }
