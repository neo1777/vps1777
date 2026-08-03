"""«Non c'è nessuna release» e «non ho potuto chiedere» non sono lo stesso fatto.

I tre installer (`setup.sh`, `deploy.sh`, `installer/engine.py`) chiedevano a GitHub
qual è l'ultima release e trattavano **ogni** esito non-riuscito come *«nessuna release
pubblicata»*. Da lì `DEV_BUILD=1`, cioè **build locale** — che non passa dalla verifica
della firma `cosign`, valida sul bundle di release e non sul sorgente compilato in loco.

⇒ un blip di rete, un proxy, un 403 di rate-limit (60 req/h per IP non autenticato)
degradavano l'installazione da «immagine firmata e verificata» a «build da quel che c'è
sul disco» — **e il messaggio a schermo dava la colpa a GitHub**, affermando un fatto sul
mondo che nessuno aveva misurato.

Questi test coprono la parte Python. La parte shell è provata da
`tools/tests/test-install-version-shell.sh`, che esercita i due script veri con un
`curl` finto.

`paramiko` è stubbato come in `test_installer_funnel.py`: è l'unica dipendenza esterna
dell'installer e in CI non c'è.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
import urllib.error
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_ENGINE = _ROOT / "installer" / "engine.py"

sys.modules.setdefault("paramiko", types.ModuleType("paramiko"))
_spec = importlib.util.spec_from_file_location("installer_engine_ver", _ENGINE)
eng = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eng)


def _con_http_json(monkey):
    vecchio = eng._http_json
    eng._http_json = monkey
    return vecchio


# ───────────── quello che DEVE fermarsi: la domanda senza risposta ─────────────

@pytest.mark.parametrize("errore", [
    urllib.error.URLError("Name or service not known"),          # DNS / rete giù
    urllib.error.HTTPError("u", 403, "rate limit exceeded", {}, None),  # 60 req/h
    urllib.error.HTTPError("u", 502, "Bad Gateway", {}, None),   # GitHub in avaria
    OSError("timed out"),                                        # timeout socket
    json.JSONDecodeError("Expecting value", "", 0),              # risposta non JSON
])
def test_la_domanda_senza_risposta_non_diventa_una_risposta(errore):
    def esplode(*a, **k):
        raise errore
    v = _con_http_json(esplode)
    try:
        with pytest.raises(eng.ReleaseNonInterrogabile):
            eng.latest_release_version()
    finally:
        _con_http_json(v)


def test_il_nome_dell_errore_originale_finisce_nel_messaggio():
    """Chi legge deve poter distinguere un 403 di rate-limit da una rete giù:
    sono due rimedi diversi (aspettare, o sistemare la rete)."""
    def esplode(*a, **k):
        raise urllib.error.HTTPError("u", 403, "rate limit exceeded", {}, None)
    v = _con_http_json(esplode)
    try:
        with pytest.raises(eng.ReleaseNonInterrogabile, match="403"):
            eng.latest_release_version()
    finally:
        _con_http_json(v)


def test_risposta_malformata_non_e_assenza_di_release():
    """`releases?per_page=1` che torna una lista di oggetti senza `tag_name`:
    prima il KeyError diventava '' ⇒ «nessuna release»."""
    v = _con_http_json(lambda *a, **k: ([{"nome": "senza tag_name"}], {}))
    try:
        with pytest.raises(eng.ReleaseNonInterrogabile):
            eng.latest_release_version(prerelease=True)
    finally:
        _con_http_json(v)


# ──────── quello che DEVE passare: la risposta che dice davvero «nessuna» ────────

def test_github_risponde_e_non_ci_sono_release_resta_stringa_vuota():
    """Questo è l'UNICO caso che può ancora portare alla build locale — e adesso
    è l'unico che lo dichiara con verità."""
    v = _con_http_json(lambda *a, **k: ({}, {}))
    try:
        assert eng.latest_release_version() == ""
    finally:
        _con_http_json(v)


def test_lista_prerelease_vuota_resta_stringa_vuota():
    v = _con_http_json(lambda *a, **k: ([], {}))
    try:
        assert eng.latest_release_version(prerelease=True) == ""
    finally:
        _con_http_json(v)


# ───────── controprove di polarità: il caso buono non si è rotto ─────────

def test_release_trovata_torna_la_versione_senza_la_v():
    v = _con_http_json(lambda *a, **k: ({"tag_name": "v0.41.0"}, {}))
    try:
        assert eng.latest_release_version() == "0.41.0"
    finally:
        _con_http_json(v)


def test_prerelease_trovata_torna_la_versione():
    v = _con_http_json(lambda *a, **k: ([{"tag_name": "v0.42.0-rc.1"}], {}))
    try:
        assert eng.latest_release_version(prerelease=True) == "0.42.0-rc.1"
    finally:
        _con_http_json(v)


def test_il_docstring_non_dichiara_piu_la_conflazione():
    """La conflazione era **scritta**: «'' se nessuna». Un limite dichiarato viene
    letto, da chi l'ha scritto, come un limite gestito — e questo è il caso in cui
    la frase era proprio la descrizione del difetto."""
    doc = eng.latest_release_version.__doc__ or ""
    assert "ReleaseNonInterrogabile" in doc
    assert "SOLO quando GitHub ha risposto" in doc
