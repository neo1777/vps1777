"""Le cure nate dalla prima fetta della revisione col catalogo: stato OAuth, proxy, token.
Dipendenze del lock (oauth, proxy e jwt veri)."""
from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace

import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Route

from app import jwt_helpers, notifiche, oauth, proxy

_SEGRETO = "s" * 40
_FIRMA = "f" * 48


# ── OAuth: lo stato che non finisce su disco ────────────────────────────────────────────────

@pytest.fixture
def stato(tmp_path, monkeypatch):
    imp = SimpleNamespace(audit_log_path=str(tmp_path / "audit.log"), effective_signing_secret=_FIRMA,
                          gateway_public_base="https://gw.example.invalid",
                          oauth_access_token_lifetime=900, oauth_refresh_token_lifetime=1000,
                          oauth_trusted_redirect_hosts=["claude.ai"])
    monkeypatch.setattr(oauth, "get_settings", lambda: imp)
    monkeypatch.setattr(jwt_helpers, "get_settings", lambda: imp)
    eventi: list[dict] = []
    monkeypatch.setattr(oauth, "audit", eventi.append)
    monkeypatch.setattr(oauth.notifiche, "accoda", lambda *a, **k: None)
    monkeypatch.setattr(oauth, "_refresh_non_prima_di", 0.0)
    for nome in ("_revoked_refresh", "_famiglie_revocate"):
        monkeypatch.setattr(oauth, nome, set())
    for nome in ("_scade_jti", "_scade_fam", "_codes"):
        monkeypatch.setattr(oauth, nome, {})
    monkeypatch.setattr(oauth, "_clients", {"cid": {"redirect_uris": ["https://claude.ai/cb"]}})
    return tmp_path, eventi


def _refresh(jti="j1", fam="fam1"):
    return jwt_helpers.issue(typ="refresh", sub="a@example.invalid", aud="cid", ttl=1000,
                             extra={"jti": jti, "fam": fam})


def _rinnova(token):
    r = oauth._grant_refresh({"refresh_token": token, "client_id": "cid"})
    return r.status_code, json.loads(r.body)


def test_senza_scrittura_niente_rotazione(stato, monkeypatch):
    """Se la revoca del refresh usato non arriva su disco, il refresh nuovo NON si emette: dopo
    un riavvio quello vecchio tornerebbe valido. Il client tiene il suo e riprova."""
    _, eventi = stato
    vecchio = _refresh()
    monkeypatch.setattr(oauth.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disco pieno")))
    codice, corpo = _rinnova(vecchio)
    assert codice == 503 and corpo == {"error": "temporarily_unavailable"}
    assert "j1" not in oauth._revoked_refresh
    assert any(e["event"] == "oauth_revoked_persist_error" for e in eventi)
    monkeypatch.undo()
    monkeypatch.setattr(oauth, "audit", lambda e: None)
    monkeypatch.setattr(oauth.notifiche, "accoda", lambda *a, **k: None)


def test_la_rotazione_riuscita_scrive_la_scadenza(stato):
    cartella, _ = stato
    codice, corpo = _rinnova(_refresh())
    assert codice == 200 and corpo["refresh_token"]
    su_disco = json.loads((cartella / "oauth_revoked.json").read_text())
    assert su_disco["revocati"] == ["j1"]                    # resta una lista: la forma di prima
    assert su_disco["scadenze"]["j1"] > time.time()


def test_le_revoche_scadute_escono(stato, monkeypatch):
    cartella, _ = stato
    oauth._revoked_refresh.update({"vecchio", "vivo"})
    oauth._scade_jti.update({"vecchio": time.time() - 5, "vivo": time.time() + 500})
    oauth._famiglie_revocate.add("famvecchia")
    oauth._scade_fam["famvecchia"] = time.time() - 5
    assert oauth._save_revoked() is True
    su_disco = json.loads((cartella / "oauth_revoked.json").read_text())
    assert su_disco["revocati"] == ["vivo"] and su_disco["famiglie"] == []
    assert set(su_disco["scadenze"]) == {"vivo"} and su_disco["scadenze_famiglie"] == {}


def test_uno_stato_senza_scadenze_ne_prende_una_al_caricamento(stato):
    cartella, _ = stato
    (cartella / "oauth_revoked.json").write_text(json.dumps(
        {"revocati": ["a"], "famiglie": ["f"], "non_prima_di": 0}))      # la forma della 0.96.0
    assert oauth._load_revoked() == {"a"}
    adesso = time.time()
    assert adesso < oauth._scade_jti["a"] <= adesso + 1001
    assert adesso < oauth._scade_fam["f"] <= adesso + 1001


def test_un_file_che_non_si_apre_viene_messo_da_parte(stato):
    cartella, eventi = stato
    f = cartella / "oauth_clients.json"
    f.mkdir()                                   # c'è, ma leggerlo dà OSError
    assert oauth._load_clients() == {}
    assert (cartella / "oauth_clients.json.illeggibile").exists() and not f.exists()
    assert "messo da parte" in eventi[0]["error"]


def test_la_registrazione_non_salvata_si_rifiuta(stato, monkeypatch):
    monkeypatch.setattr(oauth, "_save_clients", lambda: False)
    monkeypatch.setattr(oauth, "_REGISTER_LIMIT", SimpleNamespace(allow=lambda *a: True))

    class Richiesta:
        client = SimpleNamespace(host="192.0.2.1")

        async def json(self):
            return {"redirect_uris": ["https://claude.ai/cb"]}

    prima = set(oauth._clients)
    r = asyncio.run(oauth.register(Richiesta()))
    assert r.status_code == 503 and set(oauth._clients) == prima


# ── la firma dei token ──────────────────────────────────────────────────────────────────────

def test_un_segreto_di_firma_corto_si_rifiuta(monkeypatch):
    monkeypatch.setattr(jwt_helpers, "get_settings", lambda: SimpleNamespace(
        effective_signing_secret="x" * 31, gateway_public_base=""))
    with pytest.raises(jwt_helpers.JWTError, match="troppo corto"):
        jwt_helpers.issue(typ="access", sub="a", aud="b", ttl=10)
    with pytest.raises(jwt_helpers.JWTError, match="troppo corto"):
        jwt_helpers.verify("qualcosa", expected_typ="access")
    monkeypatch.setattr(jwt_helpers, "get_settings", lambda: SimpleNamespace(
        effective_signing_secret="x" * 32, gateway_public_base=""))
    assert jwt_helpers.verify(jwt_helpers.issue(typ="access", sub="a", aud="b", ttl=10),
                              expected_typ="access")["sub"] == "a"


# ── la coda degli avvisi ────────────────────────────────────────────────────────────────────

def test_una_coda_rotta_si_dice_e_si_mette_da_parte(tmp_path, monkeypatch):
    f = tmp_path / "notifiche.json"
    eventi: list[dict] = []
    monkeypatch.setattr(notifiche, "_file", lambda: f)
    monkeypatch.setattr(notifiche, "audit", eventi.append)
    assert notifiche._leggi() == [] and eventi == []                 # assente: coda vuota, zitta
    f.write_text('[{"kind": "x"')
    assert notifiche._leggi() == []
    assert eventi[0]["event"] == "notifiche_unreadable" and "messa da parte" in eventi[0]["error"]
    assert (tmp_path / "notifiche.json.illeggibile").exists()


# ── il proxy ────────────────────────────────────────────────────────────────────────────────

class _Corpo(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b"ok"


@pytest.fixture
def banco(monkeypatch):
    righe: list[dict] = []
    monkeypatch.setattr(proxy, "audit", righe.append)
    monkeypatch.setattr(proxy, "_in_corso", {})
    monkeypatch.setattr(proxy, "get_settings", lambda: SimpleNamespace(
        effective_gateway_secret=_SEGRETO, gateway_upstreams={"nb": "nb1777:8000"},
        oauth_required=False, gateway_limit_concurrency=10))
    vero = httpx.AsyncClient
    creati: list[httpx.AsyncClient] = []

    def client(**kw):
        c = vero(transport=httpx.MockTransport(lambda req: httpx.Response(200, stream=_Corpo())), **kw)
        creati.append(c)
        return c

    monkeypatch.setattr(proxy.httpx, "AsyncClient", client)
    app = Starlette(routes=[Route("/{secret}/{service}/{path:path}", proxy.proxy,
                                  methods=["GET", "POST"])])

    async def _chiama(metodo="GET", corpo=None):
        async with vero(transport=httpx.ASGITransport(app=app), base_url="http://gw") as c:
            return await c.request(metodo, f"/{_SEGRETO}/nb/mcp", content=corpo)

    return SimpleNamespace(chiama=lambda *a, **k: asyncio.run(_chiama(*a, **k)), righe=righe,
                           creati=creati, app=app)


def test_il_posto_si_lascia_a_ogni_richiesta(banco):
    for _ in range(12):                    # più della quota (4 su 10): se non si lasciasse, 503
        assert banco.chiama().status_code == 200
    assert proxy._in_corso == {"nb": 0}
    assert all(c.is_closed for c in banco.creati)


def test_oltre_la_quota_di_un_upstream_si_risponde_503(banco):
    proxy._in_corso["nb"] = 4              # la quota: il 40% di 10
    r = banco.chiama()
    assert r.status_code == 503 and r.headers["retry-after"] == "5"
    assert banco.righe[-1] == {"event": "proxy_upstream_busy", "service": "nb"}
    assert proxy._in_corso["nb"] == 4      # il rifiuto non prende e non lascia posti


def test_la_risposta_chiude_anche_se_il_generatore_non_parte(banco):
    """Un client che se ne va prima del corpo: il generatore non parte, e la chiusura la fa la
    risposta. Qui la risposta si costruisce e si abbandona senza mai iterarla."""
    async def giro():
        risposta = httpx.Response(200, stream=_Corpo())
        c = proxy.httpx.AsyncClient()            # quello del banco, col trasporto finto
        proxy._in_corso["nb"] = 1
        flusso = proxy._Flusso("nb", ["t"], time.monotonic(), c, risposta)
        r = proxy._RispostaChiusa(flusso.corpo(), status_code=200, chiusura=flusso.chiudi)

        async def ricevi():
            return {"type": "http.disconnect"}

        async def manda(_m):
            raise OSError("il client ha chiuso")

        with pytest.raises(BaseException):
            await r({"type": "http", "asgi": {"spec_version": "2.0"}}, ricevi, manda)
        return c

    c = asyncio.run(giro())
    assert c.is_closed and proxy._in_corso["nb"] == 0
    assert banco.righe[-1]["event"] == "proxy_tool" and banco.righe[-1]["esito"] == "interrotto"


def test_un_batch_enorme_lascia_poche_righe(banco):
    lotto = json.dumps([{"jsonrpc": "2.0", "id": i, "method": "tools/call",
                         "params": {"name": f"t{i}"}} for i in range(500)]).encode()
    banco.chiama("POST", lotto)
    tool = [r for r in banco.righe if r["event"] == "proxy_tool"]
    assert len(tool) == proxy._TOOL_PER_RICHIESTA + 1
    assert tool[-1]["tool"] == "(altri 480 nella stessa richiesta)"


def test_il_confronto_del_segreto_non_guarda_la_lunghezza():
    assert proxy._constant_eq("abc", "abc") and not proxy._constant_eq("abc", "abcd")
    assert proxy._constant_eq("è", "è") and not proxy._constant_eq("è", "e")
    assert proxy._constant_eq("", "") is True       # per questo c'è `not expected` davanti


def test_la_guardia_interna_risponde_404_anche_a_un_header_non_ascii(monkeypatch):
    """Prima `hmac.compare_digest(got, atteso)` sulle str: un «è» nell'header sollevava TypeError,
    cioè un 500 al posto del 404 che nasconde la rotta (rilievo di Sagoma sul confronto del proxy,
    25/11). Ora la guardia passa da `proxy._constant_eq`, che confronta le impronte."""
    from app import routes
    monkeypatch.setattr(routes, "audit", lambda evento: None)

    def entra(valore: str):
        richiesta = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"),
                                    headers={"x-vps1777-archive-desc": valore})
        return routes._guardia_interna(richiesta, "prova", atteso="giusto")

    assert entra("giusto") is None
    for sbagliato in ("sbagliato", "è", "giustò", ""):
        risposta = entra(sbagliato)
        assert risposta is not None and risposta.status_code == 404, sbagliato
