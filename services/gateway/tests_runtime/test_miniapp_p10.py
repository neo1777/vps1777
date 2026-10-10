"""P10 (10/10/2026): gli endpoint della Mini App per la domanda che si ritrova e l'archivio.

Deps del lock, come gli altri test di questa cartella: miniapp vero, upstream MCP finti.
① `api_ask` aspetta un giro breve; «in corso» non scrive una seconda riga d'audit alla
  ripresa; la risposta pronta porta le fonti col titolo e si ritrova senza richiamare nb1777.
② `api_archive_search` col modo 'senso' chiama search_ibrida e restituisce le righe, non
  l'oggetto intero; `api_archive_context` chiama get_context troncato.
"""
from __future__ import annotations

import asyncio
import json

from starlette.requests import Request

from app import miniapp
from app.miniapp_core import RisposteRecenti


def _richiesta(path: str, corpo: dict) -> Request:
    dati = json.dumps(corpo).encode()

    async def ricevi():
        return {"type": "http.request", "body": dati, "more_body": False}

    return Request({"type": "http", "method": "POST", "path": path, "headers": [],
                    "query_string": b""}, ricevi)


def _prepara(monkeypatch, risposte: dict[str, list]):
    chiamate: list[tuple[str, dict]] = []
    audit: list[dict] = []

    async def finto_call_tool(servizio, tool, args=None, *, timeout=60.0):
        chiamate.append((tool, dict(args or {}), timeout))
        return risposte[tool].pop(0)

    monkeypatch.setattr(miniapp, "call_tool", finto_call_tool)
    monkeypatch.setattr(miniapp, "_bearer_claims", lambda request: {"sub": "774"})
    monkeypatch.setattr(miniapp, "audit", audit.append)
    monkeypatch.setattr(miniapp, "_RISPOSTE", RisposteRecenti())
    return chiamate, audit


def _json(resp) -> dict:
    return json.loads(resp.body)


def test_la_domanda_in_corso_poi_pronta_poi_ritrovata(monkeypatch):
    in_corso = json.dumps({"stato": "in_corso", "query_id": "q1", "nota": "dopo"})
    pronta = json.dumps({"answer": "Due giga [1].", "references": [
        {"citation_number": 1, "source_id": "s-a", "anteprima": "mem 2g"}]})
    fonti = [json.dumps({"id": "s-a", "title": "compose.yaml"})]
    chiamate, audit = _prepara(monkeypatch, {"notebook_query": [[in_corso], [pronta]],
                                             "source_list": [fonti]})
    corpo = {"notebook_id": "nb-1", "question": "quanta memoria?"}

    d1 = _json(asyncio.run(miniapp.api_ask(_richiesta("/app/api/ask", corpo))))
    assert d1 == {"stato": "in_corso"}
    assert chiamate[0][1]["attesa_max"] == miniapp.ASK_ATTESA_S
    assert chiamate[0][2] < 60, "un giro deve stare sotto i timeout delle webview"

    d2 = _json(asyncio.run(miniapp.api_ask(_richiesta("/app/api/ask", {**corpo, "ripresa": True}))))
    assert d2["stato"] == "pronta" and d2["answer"] == "Due giga [1]."
    assert d2["fonti"] == [{"n": 1, "titolo": "compose.yaml", "anteprima": "mem 2g"}]
    assert len(audit) == 1, "la ripresa non è una domanda nuova"

    d3 = _json(asyncio.run(miniapp.api_ask(_richiesta("/app/api/ask", {**corpo, "ripresa": True}))))
    assert d3 == d2
    assert [c[0] for c in chiamate] == ["notebook_query", "notebook_query", "source_list"], \
        "la risposta già arrivata si ritrova senza richiamare nb1777"


def test_titoli_delle_fonti_illeggibili_non_fanno_cadere_la_risposta(monkeypatch):
    pronta = json.dumps({"answer": "x [1]", "references": [{"citation_number": 1, "source_id": "s"}]})
    _prepara(monkeypatch, {"notebook_query": [[pronta]], "source_list": []})

    async def rotto(servizio, tool, args=None, *, timeout=60.0):
        if tool == "source_list":
            raise miniapp.MCPCallError("nb1777 lento")
        return [pronta]

    monkeypatch.setattr(miniapp, "call_tool", rotto)
    d = _json(asyncio.run(miniapp.api_ask(_richiesta(
        "/app/api/ask", {"notebook_id": "nb", "question": "q"}))))
    assert d["fonti"] == [{"n": 1, "titolo": "", "anteprima": ""}]


def test_ricerca_per_senso_restituisce_le_righe(monkeypatch):
    ibrida = json.dumps({"righe": [{"db": "a", "uuid": "u1", "origine": "vettori", "pezzo": 2}],
                         "indici": [], "parametri": {},
                         "saltati": [{"db": "b", "ramo": "vettori", "motivo": "assente"}]})
    chiamate, _ = _prepara(monkeypatch, {"search_ibrida": [[ibrida]]})
    d = _json(asyncio.run(miniapp.api_archive_search(_richiesta(
        "/app/api/archive/search", {"query": "quando ho deciso", "modo": "senso"}))))
    assert chiamate[0][0] == "search_ibrida" and chiamate[0][1]["db_name"] == ""
    assert chiamate[0][2] >= 60, "il primo giro carica il modello di embedding"
    assert d["modo"] == "senso" and d["results"][0]["pezzo"] == 2
    assert d["saltati"][0]["db"] == "b"


def test_ricerca_per_parole_resta_quella_di_prima(monkeypatch):
    chiamate, _ = _prepara(monkeypatch, {"search": [[json.dumps({"db": "a", "uuid": "u1"})]]})
    d = _json(asyncio.run(miniapp.api_archive_search(_richiesta(
        "/app/api/archive/search", {"query": "gateway"}))))
    assert chiamate[0][0] == "search" and d["results"] == [{"db": "a", "uuid": "u1"}]
    assert "saltati" not in d


def test_contesto_di_un_risultato(monkeypatch):
    righe = [json.dumps({"uuid": "u0", "content": "prima"}),
             json.dumps({"uuid": "u1", "content": "questa", "is_match": True})]
    chiamate, _ = _prepara(monkeypatch, {"get_context": [righe]})
    d = _json(asyncio.run(miniapp.api_archive_context(_richiesta(
        "/app/api/archive/context", {"db": "a", "uuid": "u1"}))))
    assert chiamate[0][1] == {"uuid": "u1", "db_name": "a", "before": 3, "after": 3,
                              "max_chars": 2000}
    assert [r["uuid"] for r in d["righe"]] == ["u0", "u1"]


def test_contesto_senza_uuid(monkeypatch):
    _prepara(monkeypatch, {})
    resp = asyncio.run(miniapp.api_archive_context(_richiesta("/app/api/archive/context", {})))
    assert resp.status_code == 400
