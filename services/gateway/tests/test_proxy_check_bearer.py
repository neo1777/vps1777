"""`_check_bearer` — il debito di test dichiarato nella #73, saldato.

La #73 ha curato un fail-open: `if allowed and <sub> not in allowed` — con
`oauth_allowed_emails` vuota la condizione era sempre falsa, il ramo di rifiuto non
veniva mai preso e **qualunque access token valido attraversava il proxy**. La PR è in
`main` (`c557186`) e diceva, in chiaro, che il test mancava: `proxy.py` importa
`starlette`, che nell'ambiente di chi l'ha scritta non c'era.

⭐ Il limite era dell'AMBIENTE, non del progetto — e il repo aveva già la soluzione:
`test_oauth_consent.py` carica il **vero** `oauth.py` stubbando le dipendenze in
`sys.modules`. Lo stesso qui. *Un debito dichiarato non è un debito pagato: la frase
che lo dichiara dà la stessa quiete di una cura, ed è per questo che va tolta.*

Solo stdlib + gli stub. Nessuna rete, nessun token vero.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "app"


class _Resp:
    def __init__(self, content=None, status_code=200, headers=None, media_type=None):
        self.body = content
        self.status_code = status_code
        self.headers = dict(headers or {})


class _JWTError(Exception):
    pass


class _Settings:
    """I due campi che `_check_bearer` guarda. I test li riscrivono per caso."""
    oauth_required = True
    oauth_allowed_emails: list[str] = []


_SETTINGS = _SettingsHolder = _Settings()
_CLAIMS: dict = {}
_ERRORE_VERIFY: Exception | None = None
AUDIT: list[dict] = []


def _verify(token, expected_typ=None, **kw):
    if _ERRORE_VERIFY is not None:
        raise _ERRORE_VERIFY
    return dict(_CLAIMS)


def _modulo(nome: str) -> types.ModuleType:
    """Il modulo se c'è già, altrimenti uno nuovo registrato."""
    m = sys.modules.get(nome)
    if m is None:
        m = types.ModuleType(nome)
        sys.modules[nome] = m
    return m


def _install_stubs():
    """Registra gli stub e carica il VERO proxy.py come app.proxy.

    ⚠️ Gli stub di `starlette` si AGGIUNGONO, non si sostituiscono, e non si
    registrano con `setdefault`. Ragione misurata: `test_oauth_consent.py` installa
    il proprio `starlette.responses` — che ha `Response`, `JSONResponse`,
    `RedirectResponse` ma **non** `StreamingResponse`, perché `oauth.py` non ne ha
    bisogno. Con `setdefault` il mio stub non veniva registrato, e `proxy.py`
    falliva l'import con «cannot import name 'StreamingResponse'» *solo quando i due
    file girano insieme*: da solo il mio passava.
    🔑 Un test che passa isolato e rompe la suite è peggio di un test rosso — e la
    causa non era nel mio file né nel suo, ma nel fatto che condividono `sys.modules`.
    Riempire i buchi invece di rivendicare il modulo fa convivere entrambi, e se
    `starlette` è quello VERO (in CI lo è) `hasattr` è già True e non tocco nulla.
    """
    _modulo("starlette")
    st_req = _modulo("starlette.requests")
    if not hasattr(st_req, "Request"):
        st_req.Request = object
    st_resp = _modulo("starlette.responses")
    for nome, valore in (("Response", _Resp), ("JSONResponse", _Resp),
                         ("StreamingResponse", _Resp)):
        if not hasattr(st_resp, nome):
            setattr(st_resp, nome, valore)
    # httpx è una dipendenza vera del gateway e a questi test non serve: se manca,
    # uno stub vuoto basta a far passare l'import di proxy.py.
    try:
        import httpx  # noqa: F401
    except ImportError:  # pragma: no cover
        sys.modules.setdefault("httpx", types.ModuleType("httpx"))

    app_pkg = sys.modules.get("app")
    if app_pkg is None:
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

    _submod("audit", audit=lambda ev: AUDIT.append(ev))
    _submod("jwt_helpers", JWTError=_JWTError, verify=_verify)
    _submod("settings", get_settings=lambda: _SETTINGS)

    spec = importlib.util.spec_from_file_location("app.proxy", str(APP_DIR / "proxy.py"))
    proxy = importlib.util.module_from_spec(spec)
    sys.modules["app.proxy"] = proxy
    spec.loader.exec_module(proxy)
    return proxy


proxy = _install_stubs()


class _Req:
    """Il minimo che `_check_bearer` usa di una Request: gli header."""
    def __init__(self, authorization: str | None = None):
        self.headers = {"authorization": authorization} if authorization is not None else {}


@pytest.fixture(autouse=True)
def _pulisci():
    global _CLAIMS, _ERRORE_VERIFY
    _SETTINGS.oauth_required = True
    _SETTINGS.oauth_allowed_emails = []
    _CLAIMS = {"sub": "chiunque@example.invalid", "typ": "access"}
    _ERRORE_VERIFY = None
    AUDIT.clear()
    yield


# ───────────── IL CASO DELLA #73: la lista vuota ─────────────

def test_lista_vuota_rifiuta_anche_un_token_valido():
    """Il fail-open curato: `verify` riesce, il token è buono, e prima passava."""
    _SETTINGS.oauth_allowed_emails = []
    ok, err = proxy._check_bearer(_Req("Bearer tok-valido"))
    assert ok is False
    assert err == "owner_not_configured"


def test_il_motivo_e_DISTINTO_da_subject_not_allowed():
    """Sono due casi che si curano in modo opposto — uno è un accesso da rifiutare,
    l'altro un'istanza da configurare — e nell'audit devono contarsi separatamente.
    Se collassassero in una stringa sola, chi legge il log non saprebbe se manca
    l'owner o se qualcuno sta bussando."""
    _SETTINGS.oauth_allowed_emails = []
    _, err_vuota = proxy._check_bearer(_Req("Bearer t"))
    _SETTINGS.oauth_allowed_emails = ["neo@example.invalid"]
    _CLAIMS["sub"] = "altro@example.invalid"
    _, err_estraneo = proxy._check_bearer(_Req("Bearer t"))
    assert err_vuota != err_estraneo
    assert (err_vuota, err_estraneo) == ("owner_not_configured", "subject_not_allowed")


def test_la_lista_di_stringhe_vuote_NON_E_PRODUCIBILE_dalla_config():
    """⚠️ Il buco che questa guardia NON copre, e perché non serve che lo copra.

    `if not allowed` guarda se il set è vuoto. Un set `{''}` è *truthy*: con
    `oauth_allowed_emails == [""]` la guardia non scatterebbe, e un token con `sub`
    vuoto — `claims.get("sub", "")` — combacerebbe con `''` e **passerebbe**.

    Non è raggiungibile, e la ragione sta a monte: `settings._csv_list` filtra le
    stringhe vuote (`if x.strip()`), quindi `ADMIN_EMAIL=` e `ADMIN_EMAIL=,` danno
    entrambi `[]`, non `[""]`.

    🔑 Questo test presidia **la premessa, non il ramo**: se un giorno qualcuno
    togliesse quel filtro, il fail-closed tornerebbe aggirabile e nessun test di
    `proxy.py` se ne accorgerebbe — perché il difetto non sarebbe in `proxy.py`.
    """
    spec = importlib.util.spec_from_file_location(
        "settings_reale", str(APP_DIR / "settings.py"))
    # `settings.py` importa pydantic: se non c'è, la premessa non è verificabile da
    # qui e il test lo DICE invece di passare in silenzio.
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except ImportError as exc:
        pytest.skip(f"settings.py non importabile in questo ambiente ({exc}): "
                    f"la premessa resta da verificare in CI")
    assert mod._csv_list("") == []
    assert mod._csv_list(",") == []
    assert mod._csv_list(" , ") == []
    assert mod._csv_list("a@b.c, ,d@e.f") == ["a@b.c", "d@e.f"]


def test_lista_vuota_in_qualunque_forma_vuota_rifiuta():
    """La forma che la config produce davvero."""
    _SETTINGS.oauth_allowed_emails = []
    ok, err = proxy._check_bearer(_Req("Bearer t"))
    assert (ok, err) == (False, "owner_not_configured")


# ───────────── polarità: ciò che deve continuare a passare ─────────────

def test_owner_configurato_e_token_suo_passa():
    """La controprova che conta: una guardia che blocca anche il legittimo si
    finisce per disattivarla."""
    _SETTINGS.oauth_allowed_emails = ["Neo@Example.invalid"]
    _CLAIMS["sub"] = "neo@example.invalid"
    assert proxy._check_bearer(_Req("Bearer t")) == (True, None)


def test_il_confronto_e_insensibile_al_MAIUSCOLO():
    _SETTINGS.oauth_allowed_emails = ["neo@example.invalid"]
    _CLAIMS["sub"] = "NEO@EXAMPLE.INVALID"
    assert proxy._check_bearer(_Req("Bearer t")) == (True, None)


def test_oauth_non_richiesto_passa_senza_guardare_niente():
    """`OAUTH_REQUIRED=False` esce prima di tutto: la cura non deve aver spostato
    la guardia sopra questa uscita, o romperebbe le istanze che non usano OAuth."""
    _SETTINGS.oauth_required = False
    _SETTINGS.oauth_allowed_emails = []
    assert proxy._check_bearer(_Req(None)) == (True, None)


# ───────────── gli altri rami, che nessuno copriva ─────────────

def test_senza_header_authorization():
    ok, err = proxy._check_bearer(_Req(None))
    assert (ok, err) == (False, "missing_bearer")


@pytest.mark.parametrize("header", ["", "Basic abc", "Token abc", "bearer", "Bearerabc"])
def test_schema_sbagliato_o_malformato(header):
    ok, err = proxy._check_bearer(_Req(header))
    assert (ok, err) == (False, "missing_bearer"), header


def test_bearer_minuscolo_e_accettato():
    """RFC 7235: lo schema è case-insensitive. `.lower().startswith("bearer ")`
    lo copre — e questo test lo presidia, così non torna indietro."""
    _SETTINGS.oauth_allowed_emails = ["neo@example.invalid"]
    _CLAIMS["sub"] = "neo@example.invalid"
    assert proxy._check_bearer(_Req("bearer t")) == (True, None)


def test_token_non_verificabile_riporta_il_motivo():
    global _ERRORE_VERIFY
    _ERRORE_VERIFY = _JWTError("scaduto")
    _SETTINGS.oauth_allowed_emails = ["neo@example.invalid"]
    ok, err = proxy._check_bearer(_Req("Bearer t"))
    assert ok is False and "scaduto" in str(err)


def test_claims_senza_sub_non_passano():
    """`claims.get("sub", "")` → stringa vuota. Con la lista piena non combacia con
    nessuno; ma se un giorno la lista contenesse "" combacerebbe — vedi il test
    sulle stringhe vuote."""
    _SETTINGS.oauth_allowed_emails = ["neo@example.invalid"]
    _CLAIMS.pop("sub", None)
    ok, err = proxy._check_bearer(_Req("Bearer t"))
    assert (ok, err) == (False, "subject_not_allowed")
