"""GAMBA 2 della garanzia «l'IP client non è spoofabile»: quella di TERZI, finora scoperta.

`test_xff_trust_list.py` (accanto a questo) copre la **gamba 1** — la trust-list è nostra,
si legge con `ast`, e quei test girano ovunque. E dichiara onestamente il buco:

    «GAMBA 2 — DI TERZI   uvicorn «cammina da destra»   ⇐ NON testabile qui»

Non era testabile **lì**: la suite del gateway gira con `uvx pytest`, che porta pytest e
basta. Ma è testabile — basta eseguirla dove le dipendenze del servizio ci sono. Questo
file lo fa, e per questo NON deve stare nella suite `uvx`: va lanciato con le deps del
LOCK, come `services/nb1777-mcp/tests/` (ci.yml:161-166):

    uv sync --frozen && uv run --with pytest pytest tests_runtime/ -v

## Le due gambe si toccano: la trust-list NON è scritta qui

I casi usano `gateway_forwarded_allow_ips` **letto da `app/settings.py` con `ast`**, non
una costante comoda. La prima versione di questo file provava con `"127.0.0.1"` — che è
più STRETTO del default di produzione (`+ 10/8, 172.16/12, 192.168/16`): sarebbe stata una
prova su una configurazione che non gira, cioè la risposta giusta alla domanda vicina.
⇒ gamba 1 verifica *che la trust-list non sia `"*"`*; gamba 2 verifica *che con QUELLA
trust-list il comportamento regga*. Se il default cambia, questi test lo seguono.

## Le due clausole, e perché il file è scritto così

⭐ **CLAUSOLA-SKIP** — questo test **fallisce** quando non può misurare, mai `skip`. Gli
import sono in testa, nudi: se `uvicorn` manca, pytest dà *collection error* ed esce **2**
(misurato, non dedotto). *Un presidio saltabile in silenzio è verde senza aver guardato.*

⭐ **CLAUSOLA-LOCK** (df446a42) — misura la uvicorn **che il lock installa**: gli import
sono normali, quindi risolvono nell'ambiente del servizio. Un test che si portasse la
propria copia ripeterebbe il buco della #114: verde su un ambiente che non è quello vero.

## Perché serve, in una riga
`uvicorn` è `0.x` con vincolo `>=0.32.0` e il lock è già a **0.52.1**; `starlette>=0.45.0`
ha perfino attraversato la **1.0** (lock 1.3.1) — in silenzio, gateway healthy, nessun
sintomo. E «cammina da destra» **è storicamente cambiato**: le versioni vecchie prendevano
il primo elemento da sinistra, cioè la parte che un client può iniettare.

## ⚠️ COSA QUESTO FILE NON DIFENDE (limite noto, agli atti — non un difetto da fixare qui)
La trust-list include TUTTE le reti private, per coprire le subnet Docker dinamiche. Un
**container interno compromesso** è quindi fidato e può iniettare un XFF: misurato, con la
trust-list reale un `X-Forwarded-For: 1.2.3.4` da `172.18.0.9` viene creduto. Col modello
attuale (bridge privata, un solo proxy) è accettato e documentato — rilievo di `df446a42`,
09/08. Volutamente NON c'è un test che lo asserisca: codificarlo trasformerebbe una
debolezza accettata in un invariante da difendere, e farebbe fallire chi un giorno
restringesse la trust-list al solo IP del reverse-proxy. *Se quel giorno arriva, la
modifica giusta è qui sopra, in prosa, non un assert da cancellare.*
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

# Import NUDI e voluti: se mancano, questo file deve ROMPERE la suite (clausola-skip).
from starlette.requests import Request
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

_SETTINGS = Path(__file__).resolve().parents[1] / "app" / "settings.py"

# L'XFF che un client pubblico si scrive da solo, e l'IP vero che il proxy APPENDE dopo.
SPOOF = "6.6.6.6"
VERO = "203.0.113.7"


def _trust_list_di_produzione() -> str:
    """Il default di `gateway_forwarded_allow_ips`, letto dal codice — non riscritto qui.

    Stessa tecnica di `test_xff_trust_list.py`: `ast`, nessun import di pydantic.
    """
    albero = ast.parse(_SETTINGS.read_text(encoding="utf-8"))
    for nodo in ast.walk(albero):
        if isinstance(nodo, ast.AnnAssign) and isinstance(nodo.target, ast.Name):
            if nodo.target.id == "gateway_forwarded_allow_ips" and isinstance(nodo.value, ast.Constant):
                return nodo.value.value
    raise AssertionError(
        "gateway_forwarded_allow_ips non trovato in app/settings.py: la trust-list è "
        "stata spostata o rinominata, e questo test stava per misurare un default "
        "inventato invece di quello che gira."
    )


def _ip_visto_dall_app(trusted: str | list[str], xff: str, client=("127.0.0.1", 5555)) -> str:
    """L'IP che il codice del gateway leggerebbe: `request.client.host`.

    Non `scope["client"]`: si percorre la catena intera (uvicorn → starlette), perché è
    starlette che `ratelimit.py` interroga, ed è starlette che ha cambiato major.
    """
    visto = {}

    async def app(scope, receive, send):
        visto["ip"] = Request(scope).client.host

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "root_path": "",
        "scheme": "http",
        "client": client,
        "server": ("127.0.0.1", 8080),
        "headers": [(b"x-forwarded-for", xff.encode()), (b"host", b"vps1777")],
    }
    asyncio.run(ProxyHeadersMiddleware(app, trusted_hosts=trusted)(scope, None, None))
    return visto["ip"]


# ───────── i casi, con la trust-list VERA letta da settings.py ─────────

def test_un_xff_iniettato_non_vince_quando_il_proxy_sta_su_loopback():
    """Il client mente, il proxy appende la verità in coda: vince la coda."""
    assert _ip_visto_dall_app(_trust_list_di_produzione(), f"{SPOOF}, {VERO}") == VERO


def test_un_xff_iniettato_non_vince_nemmeno_col_proxy_in_una_rete_docker():
    """Il caso di PRODUZIONE: Caddy non sta su 127.0.0.1, sta in una subnet 172.x."""
    ip = _ip_visto_dall_app(_trust_list_di_produzione(), f"{SPOOF}, {VERO}", ("172.18.0.5", 5555))
    assert ip == VERO


def test_un_client_pubblico_diretto_non_viene_creduto():
    """Chi colpisce la porta senza passare dal proxy NON è fidato: il suo XFF si ignora."""
    ip = _ip_visto_dall_app(_trust_list_di_produzione(), SPOOF, ("203.0.113.9", 5555))
    assert ip == "203.0.113.9"


def test_i_proxy_fidati_in_catena_vengono_saltati():
    """Più hop fidati in coda: si risale fino al primo NON fidato."""
    ip = _ip_visto_dall_app(_trust_list_di_produzione(), f"{SPOOF}, {VERO}, 10.0.0.1")
    assert ip == VERO


def test_la_prova_sa_distinguere_una_configurazione_spoofabile():
    """CONTROPROVA NEGATIVA — senza, un test che passa non distingue «regge» da «non guarda».

    Con `trusted_hosts="*"` (l'era-«*», rimossa da noi) l'XFF del client DEVE vincere. Se
    anche questo desse l'IP giusto, il test non starebbe misurando il cammino da destra:
    passerebbe per sempre senza guardare niente.
    """
    assert _ip_visto_dall_app("*", f"{SPOOF}, {VERO}") == SPOOF


def test_starlette_non_reinterpreta_lo_scope_scritto_da_uvicorn():
    """La giunzione fra le due librerie — il punto che ha attraversato la 1.0 in silenzio.

    `Request.client` legge `scope["client"]` (identico in 0.45.0 e 1.3.1, verificato):
    questo test è ciò che se ne accorgerebbe se smettesse di essere vero.
    """
    assert _ip_visto_dall_app(_trust_list_di_produzione(), VERO) == VERO
