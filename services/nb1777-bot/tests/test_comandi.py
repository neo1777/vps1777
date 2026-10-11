"""P12 (11/10/2026): /lista, /chiedi e i bottoni, con un MCP finto.

Importa python-telegram-bot: salta nello step stdlib e gira in quello con le deps del lock
(ci.yml e tools/check.sh lo nominano). Update e contesto sono finti e minimi: i comandi
usano solo `effective_user`, `effective_message`, `callback_query`, `args`, `user_data`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("telegram")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import bot, formato  # noqa: E402
from app.settings import get_settings  # noqa: E402

NEO = 4242
NB = "0f6c2a8e-1b2c-4d5e-8f90-123456789abc"
NB2 = "1f6c2a8e-1b2c-4d5e-8f90-123456789abc"
ELENCO = [json.dumps({"id": NB, "title": "Libro Flame"}),
          json.dumps({"id": NB2, "title": "Vps1777"})]


class _Msg:
    chat_id = 1

    def __init__(self) -> None:
        self.inviati: list[tuple[str, dict]] = []

    async def reply_text(self, text: str, **k) -> "_Msg":
        self.inviati.append((text, k))
        return self


class _Utente:
    def __init__(self, uid: int) -> None:
        self.id = uid


class _Query:
    def __init__(self, data: str, msg: _Msg, uid: int = NEO) -> None:
        self.data, self.message, self.from_user = data, msg, _Utente(uid)
        self.risposte: list[str] = []
        self.modifiche: list[tuple[str, dict]] = []

    async def answer(self, text: str = "", **_k) -> None:
        self.risposte.append(text)

    async def edit_message_text(self, text: str, **k) -> None:
        self.modifiche.append((text, k))

    async def edit_message_reply_markup(self, reply_markup=None, **_k) -> None:
        self.modifiche.append(("<tastiera>", {"reply_markup": reply_markup}))


class _Update:
    def __init__(self, msg: _Msg | None = None, query: _Query | None = None,
                 uid: int = NEO) -> None:
        self.effective_message = msg if msg is not None else (query.message if query else None)
        self.effective_user = _Utente(uid)
        self.callback_query = query


class _Bot:
    async def send_chat_action(self, **_k) -> None:
        return None


class _Ctx:
    def __init__(self, args: list[str] | None = None, user_data: dict | None = None) -> None:
        self.args = args or []
        self.user_data = user_data if user_data is not None else {}
        self.bot = _Bot()


@pytest.fixture(autouse=True)
def proprietario(monkeypatch):
    monkeypatch.setenv("TELEGRAM_OWNER_ID", str(NEO))
    monkeypatch.setenv("BOT_RAG_COMMANDS", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def mcp(monkeypatch):
    """Il registro delle chiamate e le risposte, per nome del tool."""
    stato = {"chiamate": [], "risposte": {}}

    async def finto(tool, args=None, *, timeout=300.0):
        stato["chiamate"].append((tool, args or {}))
        r = stato["risposte"].get(tool)
        if isinstance(r, Exception):
            raise r
        if isinstance(r, list) and r and isinstance(r[0], list):
            return r.pop(0)                 # risposte in sequenza
        return r if r is not None else []

    monkeypatch.setattr(bot, "chiama_tool", finto)
    return stato


def _testi(msg: _Msg) -> str:
    return "\n".join(t for t, _ in msg.inviati)


def _risposta(answer: str = "Risposta **vera** [1].") -> list[str]:
    return [json.dumps({"answer": answer,
                        "references": [{"citation_number": 1, "source_id": "s1"}]})]


async def test_un_errore_del_tool_arriva_a_neo_non_risposta_vuota(mcp):
    mcp["risposte"]["notebook_query"] = formato.ErroreMCP("Auth NotebookLM scaduta")
    msg = _Msg()
    await bot.cmd_chiedi(_Update(msg), _Ctx([NB, "che", "dice?"]))
    assert "Auth NotebookLM scaduta" in _testi(msg)
    assert "Risposta vuota" not in _testi(msg)


async def test_lista_mostra_i_notebook_come_bottoni(mcp):
    mcp["risposte"]["nb_list"] = ELENCO
    msg = _Msg()
    ctx = _Ctx()
    await bot.cmd_lista(_Update(msg), ctx)
    testo, k = msg.inviati[-1]
    bottoni = [b for riga in k["reply_markup"].inline_keyboard for b in riga]
    assert [b.text for b in bottoni] == ["Libro Flame", "Vps1777"]
    assert bottoni[0].callback_data == f"nb:{NB}"
    assert ctx.user_data["elenco"][0]["id"] == NB


async def test_lista_errore_lo_dice(mcp):
    mcp["risposte"]["nb_list"] = formato.ErroreMCP("nb1777 non raggiungibile")
    msg = _Msg()
    await bot.cmd_lista(_Update(msg), _Ctx())
    assert "nb1777 non raggiungibile" in _testi(msg)


async def test_chiedi_senza_notebook_scelto_chiede_quale_e_ricorda_la_domanda(mcp):
    mcp["risposte"]["nb_list"] = ELENCO
    msg = _Msg()
    ctx = _Ctx(["di", "cosa", "parla?"])
    await bot.cmd_chiedi(_Update(msg), ctx)
    assert ctx.user_data["in_attesa"] == "di cosa parla?"
    assert "reply_markup" in msg.inviati[-1][1]
    assert not [c for c in mcp["chiamate"] if c[0] == "notebook_query"]


async def test_il_tocco_sceglie_il_notebook_e_risponde_alla_domanda_in_attesa(mcp):
    mcp["risposte"]["notebook_query"] = _risposta()
    mcp["risposte"]["source_list"] = [json.dumps({"id": "s1", "title": "Cap. 4"})]
    msg = _Msg()
    ctx = _Ctx(user_data={"in_attesa": "di cosa parla?",
                          "elenco": [{"id": NB, "title": "Libro Flame"}]})
    q = _Query(f"nb:{NB}", msg)
    await bot.cmd_scelta(_Update(query=q), ctx)
    assert ctx.user_data["notebook"] == {"id": NB, "title": "Libro Flame"}
    assert "in_attesa" not in ctx.user_data
    assert ("notebook_query", {"notebook_id": NB, "question": "di cosa parla?",
                               "attesa_max": 270}) in mcp["chiamate"]
    testo, k = msg.inviati[-1]
    assert "<b>vera</b>" in testo and "[1] Cap. 4" in testo and k.get("parse_mode") == "HTML"


async def test_col_notebook_scelto_chiedi_usa_quello(mcp):
    mcp["risposte"]["notebook_query"] = _risposta()
    msg = _Msg()
    ctx = _Ctx(["e", "poi?"], {"notebook": {"id": NB2, "title": "Vps1777"}})
    await bot.cmd_chiedi(_Update(msg), ctx)
    assert mcp["chiamate"][0] == ("notebook_query", {"notebook_id": NB2, "question": "e poi?",
                                                     "attesa_max": 270})
    assert "Vps1777" in msg.inviati[0][0]


async def test_l_id_esplicito_vale_come_prima(mcp):
    mcp["risposte"]["notebook_query"] = _risposta()
    msg = _Msg()
    await bot.cmd_chiedi(_Update(msg), _Ctx([NB, "domanda"]))
    assert mcp["chiamate"][0][1]["notebook_id"] == NB
    assert mcp["chiamate"][0][1]["question"] == "domanda"


async def test_in_corso_si_ritira_con_l_esito(mcp):
    mcp["risposte"]["notebook_query"] = [json.dumps({"stato": "in_corso", "query_id": "q1"})]
    mcp["risposte"]["notebook_query_esito"] = _risposta("arrivata")
    msg = _Msg()
    await bot.cmd_chiedi(_Update(msg), _Ctx([NB, "lenta"]))
    assert ("notebook_query_esito", {"query_id": "q1", "attesa_max": 270}) in mcp["chiamate"]
    assert "arrivata" in _testi(msg)


async def test_risposta_lunga_in_piu_messaggi(mcp):
    lunga = "\n\n".join("p" * 1500 for _ in range(6))
    mcp["risposte"]["notebook_query"] = _risposta(lunga)
    msg = _Msg()
    await bot.cmd_chiedi(_Update(msg), _Ctx([NB, "tutto"]))
    risposte = [t for t, k in msg.inviati if k.get("parse_mode") == "HTML"]
    assert len(risposte) >= 3 and all(len(t) <= 4096 for t in risposte)


async def test_pagina_successiva_della_tastiera(mcp):
    elenco = [{"id": f"id-{i}", "title": f"N{i}"} for i in range(20)]
    q = _Query("nbp:1", _Msg())
    await bot.cmd_scelta(_Update(query=q), _Ctx(user_data={"elenco": elenco}))
    (_, k), = q.modifiche
    primo = k["reply_markup"].inline_keyboard[0][0]
    assert primo.text == f"N{formato.PER_PAGINA}"


async def test_un_estraneo_non_sceglie(mcp):
    q = _Query(f"nb:{NB}", _Msg(), uid=1)
    ctx = _Ctx(user_data={})
    await bot.cmd_scelta(_Update(query=q, uid=1), ctx)
    assert "notebook" not in ctx.user_data and q.risposte == ["non autorizzato"]
