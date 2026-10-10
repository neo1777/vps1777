"""P7 (10/10/2026): ricerca approfondita, note e cronologia della chat di Gemini Notebook.

Le forme vengono dalla prova dal vivo del 10/10 su un notebook di prova (poi cancellato):
- la ricerca passa da `notebooklm_tools.services.research`, che ritorna dati strutturati,
  mentre `nlm research` stampa solo testo. Le fonti trovate sono {index, url, title,
  description, result_type_name, cited}; in modo `fast` il report è vuoto;
- il primo `research_status` SUBITO dopo l'avvio dice `no_research`: Google non mostra
  ancora il compito. Va detto, non letto come «nessuna ricerca»;
- `note list --json` dà {notes: [{id, title, content, preview}]}; `note create` stampa
  l'id solo nel testo («✓ Note created: <uuid>»);
- `chats list --json` dà {sessions: [{conversation_id, turn_count, preview, is_active}]},
  `chats get --json` dà {transcript: [{turn, query, answer}]}.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import types

import pytest

from app import core, ricerca_nlm, server

NB = "f04fdd13-a235-4d65-be25-f33f9bcdb24a"


# ── la ricerca ────────────────────────────────────────────────────────────────

def test_research_start_passa_dall_aiutante_e_valida_prima(monkeypatch):
    chiamate = []
    monkeypatch.setattr(core, "_run_ricerca", lambda args, **k: chiamate.append(args) or
                        {"task_id": "t-1", "notebook_id": NB, "mode": "fast"})
    assert core.research_start(NB, "server MCP", mode="fast")["task_id"] == "t-1"
    assert chiamate == [["start", NB, "server MCP", "--source", "web", "--mode", "fast"]]
    with pytest.raises(core.NLMError):
        core.research_start(NB, "x", mode="lentissimo")
    with pytest.raises(core.NLMError):
        core.research_start(NB, "x", source="drive", mode="deep")   # deep è solo web
    assert len(chiamate) == 1, "un argomento sbagliato non deve lanciare niente"


def _stato(**kw):
    base = {"status": "completed", "notebook_id": NB, "task_id": "t-1", "sources_found": 2,
            "report": "", "message": None,
            "sources": [
                {"index": 0, "url": "https://example.invalid/a", "title": "A",
                 "description": "prima", "result_type": 1, "result_type_name": "web",
                 "cited": False},
                {"index": 1, "url": "https://example.invalid/b", "title": "B",
                 "description": "seconda", "result_type": 1, "result_type_name": "web",
                 "cited": True},
            ]}
    base.update(kw)
    return base


def test_research_status_compatto(monkeypatch):
    monkeypatch.setattr(core, "_run_ricerca", lambda args, **k: _stato())
    out = core.research_status(NB, "t-1")
    assert out["status"] == "completed" and out["sources_found"] == 2
    assert out["sources"][1] == {"index": 1, "title": "B", "url": "https://example.invalid/b",
                                 "tipo": "web", "cited": True}
    assert "research_import" in out["nota"]
    assert "report" not in out, "il report vuoto (modo fast) non si porta"


def test_research_status_subito_dopo_l_avvio(monkeypatch):
    monkeypatch.setattr(core, "_run_ricerca", lambda args, **k: _stato(
        status="no_research", task_id=None, sources=[], sources_found=0))
    out = core.research_status(NB, "t-1")
    assert out["status"] == "no_research"
    assert "riprova" in out["nota"], "subito dopo l'avvio no_research non vuol dire «niente»"


def test_research_status_report_lungo_troncato_se_non_verbose(monkeypatch):
    monkeypatch.setattr(core, "_run_ricerca", lambda args, **k: _stato(report="x" * 5000))
    assert len(core.research_status(NB, "t-1")["report"]) < 1700
    assert core.research_status(NB, "t-1", verbose=True)["report"] == "x" * 5000


def test_research_import_argomenti(monkeypatch):
    chiamate = []
    monkeypatch.setattr(core, "_run_ricerca", lambda args, **k: chiamate.append(args) or
                        {"imported_count": 2, "imported_sources": [{"id": "s1"}, {"id": "s2"}],
                         "message": "ok"})
    out = core.research_import(NB, "t-1", indices=[0, 3])
    assert chiamate[-1] == ["import", NB, "t-1", "--indices", "0,3"]
    assert out["imported_count"] == 2
    core.research_import(NB, "t-1", cited_only=True)
    assert chiamate[-1] == ["import", NB, "t-1", "--cited-only"]


def test_l_aiutante_stampa_json_del_servizio(monkeypatch, capsys):
    """`python -m app.ricerca_nlm` chiama il livello services di nlm e stampa JSON."""
    visti = []

    class _Client:
        def __enter__(self):
            return "client"

        def __exit__(self, *a):
            return False

    servizio = types.SimpleNamespace(
        start_research=lambda c, nb, q, source, mode: visti.append(("start", nb, q, source, mode))
        or {"task_id": "t-9", "notebook_id": nb, "query": q, "source": source, "mode": mode,
            "message": "ok"},
        poll_research=lambda c, nb, task_id, compact, max_wait: visti.append(
            ("status", nb, task_id, compact, max_wait)) or _stato(),
        import_research=lambda c, nb, t, source_indices, cited_only: visti.append(
            ("import", nb, t, source_indices, cited_only)) or {"imported_count": 1},
    )
    monkeypatch.setattr(ricerca_nlm, "_servizi", lambda: (lambda profilo: _Client(), servizio))
    assert ricerca_nlm.main(["start", NB, "domanda", "--mode", "deep"]) == 0
    assert json.loads(capsys.readouterr().out)["task_id"] == "t-9"
    assert ricerca_nlm.main(["status", NB, "--task-id", "t-9"]) == 0
    assert ricerca_nlm.main(["import", NB, "t-9", "--indices", "1,2"]) == 0
    capsys.readouterr()
    assert visti == [("start", NB, "domanda", "web", "deep"),
                     ("status", NB, "t-9", False, 0),
                     ("import", NB, "t-9", [1, 2], False)]


def test_l_aiutante_un_errore_va_su_stderr_con_exit_1(monkeypatch, capsys):
    def rotto(profilo):
        raise RuntimeError("Authentication expired")
    monkeypatch.setattr(ricerca_nlm, "_servizi", lambda: (rotto, None))
    assert ricerca_nlm.main(["status", NB]) == 1
    err = capsys.readouterr().err
    assert "Authentication expired" in err


def test_run_ricerca_classifica_l_auth_scaduta(monkeypatch):
    monkeypatch.setattr(core.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0], 1, stdout="", stderr="RuntimeError: Authentication expired, run nlm login"))
    monkeypatch.setattr(core, "classifica_errore", lambda msg: "auth_scaduta")
    with pytest.raises(core.NLMAuthError):
        core._run_ricerca(["status", NB], timeout=10)


def test_run_ricerca_lancia_il_modulo_col_python_del_servizio(monkeypatch):
    visti = {}

    def finto(cmd, **k):
        visti["cmd"], visti["cwd"] = cmd, k.get("cwd")
        return subprocess.CompletedProcess(cmd, 0, stdout='{"status": "completed"}', stderr="")
    monkeypatch.setattr(core.subprocess, "run", finto)
    assert core._run_ricerca(["status", NB], timeout=10) == {"status": "completed"}
    assert visti["cmd"][:3] == [sys.executable, "-m", "app.ricerca_nlm"]
    assert visti["cwd"], "il modulo si trova solo dalla radice del servizio"


# ── le note ───────────────────────────────────────────────────────────────────

def test_note_list_compatta_e_verbose(monkeypatch):
    monkeypatch.setattr(core, "_run_json", lambda args, **k: {"notebook_id": NB, "count": 1, "notes": [
        {"id": "n1", "title": "T", "content": "c" * 500, "preview": "c" * 100}]})
    assert core.note_list(NB) == [{"id": "n1", "title": "T", "preview": "c" * 100}]
    assert core.note_list(NB, verbose=True)[0]["content"] == "c" * 500


def test_note_create_legge_l_id_dal_testo(monkeypatch):
    chiamate = []

    def finto(args, **k):
        chiamate.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=(
            "✓ Note created: 1c6976ac-7a4a-4bdc-8369-3a1d9ea2ad85\n  Title: t\n"), stderr="")
    monkeypatch.setattr(core, "_run", finto)
    assert core.note_create(NB, "testo", title="t") == "1c6976ac-7a4a-4bdc-8369-3a1d9ea2ad85"
    assert chiamate[0] == ["note", "create", NB, "-c", "testo", "-t", "t"]


def test_note_create_senza_id_non_finge(monkeypatch):
    monkeypatch.setattr(core, "_run", lambda args, **k: subprocess.CompletedProcess(
        args, 0, stdout="fatto\n", stderr=""))
    with pytest.raises(core.NLMError):
        core.note_create(NB, "testo")


def test_note_update_vuole_qualcosa_da_cambiare(monkeypatch):
    chiamate = []
    monkeypatch.setattr(core, "_run", lambda args, **k: chiamate.append(args))
    with pytest.raises(core.NLMError):
        core.note_update(NB, "n1")
    core.note_update(NB, "n1", title="nuovo")
    assert chiamate == [["note", "update", NB, "n1", "-t", "nuovo"]]


@pytest.fixture
def nb_finto(monkeypatch):
    monkeypatch.setattr(server, "_check_auth_or_raise", lambda: None)
    fatti: list = []
    monkeypatch.setattr(core, "note_list", lambda nb, verbose=False: [
        {"id": "n1", "title": "Nota", "preview": "anteprima", "content": "testo intero"}])
    monkeypatch.setattr(core, "note_delete", lambda nb, nid: fatti.append(("del", nb, nid)))
    monkeypatch.setattr(core, "note_create", lambda nb, c, title="": fatti.append(("new", c, title)) or "n9")
    monkeypatch.setattr(core, "note_update", lambda nb, nid, content=None, title=None:
                        fatti.append(("upd", nid, content, title)))
    return fatti


def test_note_delete_in_due_tempi(nb_finto):
    primo = asyncio.run(server.note_delete(NB, "n1"))
    assert primo["cancellato"] is False and primo["anteprima"]["title"] == "Nota"
    assert nb_finto == [], "la prima chiamata non cancella"
    with pytest.raises(Exception):
        asyncio.run(server.note_delete(NB, "n2", conferma=primo["conferma"]))
    secondo = asyncio.run(server.note_delete(NB, "n1", conferma=primo["conferma"]))
    assert secondo["cancellato"] is True and nb_finto == [("del", NB, "n1")]


def test_note_save_crea_o_modifica(nb_finto):
    assert asyncio.run(server.note_save(NB, "testo", title="t")) == {"note_id": "n9", "creata": True}
    assert asyncio.run(server.note_save(NB, "altro", note_id="n1")) == {"note_id": "n1", "creata": False}
    assert nb_finto == [("new", "testo", "t"), ("upd", "n1", "altro", None)]


# ── la cronologia della chat ──────────────────────────────────────────────────

def test_chat_cronologia_elenca_senza_id_e_trascrive_con_l_id(monkeypatch):
    chiamate = []

    def finto(args, **k):
        chiamate.append(args)
        if args[1] == "list":
            return {"notebook_id": NB, "notebook_title": "T", "sessions": [
                {"conversation_id": "c1", "turn_count": 2, "preview": "p", "is_active": True}]}
        return {"notebook_id": NB, "conversation_id": "c1", "turn_count": 1,
                "transcript": [{"turn": 1, "query": "q" * 50, "answer": "a" * 3000}]}
    monkeypatch.setattr(core, "_run_json", finto)
    assert core.chat_cronologia(NB)["sessions"][0]["conversation_id"] == "c1"
    out = core.chat_cronologia(NB, "c1", max_chars=1000)
    assert chiamate == [["chats", "list", NB], ["chats", "get", NB, "c1"]]
    risposta = out["transcript"][0]["answer"]
    assert risposta.startswith("a" * 1000) and "troncat" in risposta
    assert core.chat_cronologia(NB, "c1")["transcript"][0]["answer"] == "a" * 3000


# ── il registro dei tool ──────────────────────────────────────────────────────

def test_i_tool_nuovi_hanno_le_annotazioni_giuste():
    a = server.ANNOTAZIONI
    for nome in ("research_status", "note_list", "chat_cronologia"):
        assert a[nome][1].get("readOnlyHint") is True, nome
    assert a["note_delete"][1]["destructiveHint"] is True
    for nome in ("research_start", "research_import", "note_save"):
        assert a[nome][1]["readOnlyHint"] is False and a[nome][1]["destructiveHint"] is False, nome
