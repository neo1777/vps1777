"""Il tetto sul body conta i byte VERI — voce 92118d4e (stdlib-only, offline).

La voce diceva: la guardia sul `Content-Length` copre il caso onesto, «chi vuole
riempire la tmpfs omette l'header (chunked) o ci scrive un numero piccolo». Questi
test misurano esattamente quel caso, che è l'unico che conta.

Perché stanno QUI e non in `tests_runtime/`: `asgi_security` è puro stdlib (come
dichiara la sua testa), quindi il tetto si prova senza uvicorn e senza rete — gira
nella suite `uvx` come gli altri. Il vicino `test_gamba2_xff_da_destra.py` sta in
runtime perché misura una DIPENDENZA (uvicorn); qui il codice è nostro.

⭐ CONTROPROVA INCLUSA (`test_senza_middleware_il_body_passa_intero`): senza il
middleware lo stesso scenario arriva intero all'app. Senza quella, questi test
direbbero «413» anche se il 413 arrivasse da un'altra ragione, e non proverebbero
che è il tetto a fermarlo.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import asgi_security  # noqa: E402


def _scope(path: str = "/admin/archive", headers=None) -> dict:
    return {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "scheme": "http",
        "client": ("203.0.113.7", 5555),
        "server": ("127.0.0.1", 8080),
        "headers": headers or [(b"host", b"vps1777")],
    }


def _esegui(mw, scope, chunks):
    """Manda `chunks` al middleware e ritorna (status, byte_visti_dall_app).

    `byte_visti_dall_app` è ciò che l'applicazione a valle è riuscita a leggere:
    è la misura che conta — un 413 che arriva DOPO che l'app ha già ingoiato tutto
    non protegge niente.
    """
    esito = {"status": None, "letti_dall_app": 0}

    async def app(scope, receive, send):
        while True:
            msg = await receive()
            if msg["type"] == "http.disconnect":
                return
            esito["letti_dall_app"] += len(msg.get("body", b"") or b"")
            if not msg.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    da_mandare = list(chunks)

    async def receive():
        if da_mandare:
            corpo = da_mandare.pop(0)
            return {"type": "http.request", "body": corpo, "more_body": bool(da_mandare)}
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            esito["status"] = message["status"]

    # `mw` è sempre un costruttore (app → app avvolta): così la controprova può
    # passare l'identità e percorrere ESATTAMENTE lo stesso codice di test.
    asyncio.run(mw(app)(scope, receive, send))
    return esito["status"], esito["letti_dall_app"]


def _con_tetto(default_max: int, upload_max: int):
    def costruisci(app):
        return asgi_security.BodyCapASGI(app, default_max=default_max, upload_max=upload_max)
    return costruisci


# ───────────────────────── il classificatore (logica pura) ─────────────────────────

def test_i_path_di_upload_prendono_il_tetto_alto():
    for p in ("/admin/archive", "/admin/archive/", "/admin/nlm"):
        assert asgi_security.body_cap_for(p, default=10, upload=999) == 999, p


def test_tutto_il_resto_prende_il_tetto_basso():
    # /token, /register e il proxy MCP non ricevono upload: se un giorno uno di
    # loro ne riceve, prende 413 e ce ne accorgiamo — non silenzio.
    for p in ("/token", "/register", "/admin/login", "/health", "/s3cr3t/archive/mcp"):
        assert asgi_security.body_cap_for(p, default=10, upload=999) == 10, p


def test_un_path_che_SOMIGLIA_a_uno_di_upload_non_eredita_il_tetto_alto():
    # `/admin/archiveXYZ` non è sotto `/admin/archive`: il confronto è per
    # segmento, non per prefisso di stringa.
    assert asgi_security.body_cap_for("/admin/archivio-finto", default=10, upload=999) == 10
    assert asgi_security.body_cap_for("/admin/nlmsomething", default=10, upload=999) == 10


# ───────────────────────── il caso che la voce descriveva ─────────────────────────

def test_chunked_senza_content_length_oltre_il_tetto_viene_fermato():
    """Il caso malevolo: nessun header dichiarato, byte a raffica."""
    mw = _con_tetto(default_max=1024, upload_max=1024)
    status, letti = _esegui(mw, _scope("/token"), [b"x" * 600, b"x" * 600, b"x" * 600])
    assert status == 413
    # l'app non deve aver visto più del tetto: il taglio avviene MENTRE arriva
    assert letti <= 1024, f"l'app ha letto {letti} byte oltre il tetto"


def test_content_length_che_MENTE_non_salva_chi_lo_scrive():
    """Dichiara 10 byte, ne manda 3000. È il caso che l'header non può cogliere."""
    mw = _con_tetto(default_max=1024, upload_max=1024)
    status, letti = _esegui(
        mw, _scope("/token", [(b"host", b"vps1777"), (b"content-length", b"10")]),
        [b"x" * 1500, b"x" * 1500])
    assert status == 413
    assert letti <= 1024


def test_content_length_onesto_oltre_il_tetto_e_rifiutato_senza_leggere_nulla():
    """Sulla parola del client si può solo RIFIUTARE, mai accettare."""
    mw = _con_tetto(default_max=1024, upload_max=1024)
    status, letti = _esegui(
        mw, _scope("/token", [(b"host", b"vps1777"), (b"content-length", b"999999")]),
        [b"x" * 10])
    assert status == 413
    assert letti == 0, "ha letto byte pur potendo rifiutare prima"


def test_sotto_il_tetto_passa_intero():
    """La guardia che blocca il legittimo si finisce per disattivarla."""
    mw = _con_tetto(default_max=4096, upload_max=4096)
    status, letti = _esegui(mw, _scope("/token"), [b"x" * 1000, b"x" * 1000])
    assert status == 200
    assert letti == 2000


def test_upload_grande_passa_sul_path_di_upload_e_no_altrove():
    """Lo STESSO body: ammesso su /admin/archive, rifiutato su /token."""
    mw = _con_tetto(default_max=1024, upload_max=1024 * 1024)
    corpo = [b"x" * 5000]
    assert _esegui(mw, _scope("/admin/archive"), corpo)[0] == 200
    assert _esegui(mw, _scope("/token"), corpo)[0] == 413


def test_il_websocket_non_viene_toccato():
    scope = _scope("/token")
    scope["type"] = "websocket"
    mw = _con_tetto(default_max=1, upload_max=1)
    status, _ = _esegui(mw, scope, [b"x" * 100])
    assert status == 200, "il tetto HTTP non deve intercettare altri protocolli"


# ───────────────────────── la controprova ─────────────────────────

def test_senza_middleware_il_body_passa_intero():
    """Senza il tetto, lo scenario di sopra arriva INTERO all'app.

    È ciò che rende gli assert precedenti una prova invece di una coincidenza: se
    un giorno il 413 arrivasse da un'altra parte, questo test resterebbe verde e
    la differenza fra i due sarebbe l'unica cosa che ancora misura il tetto.
    """
    def nessun_middleware(app):
        return app

    status, letti = _esegui(nessun_middleware, _scope("/token"),
                            [b"x" * 600, b"x" * 600, b"x" * 600])
    assert status == 200
    assert letti == 1800, "senza middleware l'app deve vedere tutti i byte"
