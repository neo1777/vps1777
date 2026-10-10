"""Contract-test di P7 contro l'`nlm` installato (anti-drift, come test_source_cli_contract).

`core` costruisce a mano gli argv di `nlm note …` e `nlm chats …`, e `app/ricerca_nlm.py`
chiama `notebooklm_tools.services.research` per nome e parola chiave. Un bump di nlm che
cambia una firma deve FALLIRE qui, non rompersi in produzione. Senza nlm il test si salta.

Mappa contratto → codice:
  note list NOTEBOOK_ID --json            → core.note_list
  note create NOTEBOOK_ID -c … [-t …]     → core.note_create (l'id esce nel testo)
  note update NOTEBOOK_ID NOTE_ID [-c] [-t] → core.note_update
  note delete NOTEBOOK_ID NOTE_ID -y      → core.note_delete
  chats list NOTEBOOK --json              → core.chat_cronologia
  chats get NOTEBOOK [CONVERSATION_ID] --json → core.chat_cronologia(conversation_id)
  services.research.start_research(client, notebook_id, query, source=, mode=)
  services.research.poll_research(client, notebook_id, task_id=, compact=, max_wait=)
  services.research.import_research(client, notebook_id, task_id, source_indices=, cited_only=)
"""
from __future__ import annotations

import inspect
import re
import shutil
import subprocess

import pytest

NLM = shutil.which("nlm")
pytestmark = pytest.mark.skipif(NLM is None, reason="nlm non installato sul PATH")

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _help(*argv: str) -> str:
    p = subprocess.run([NLM, *argv, "--help"], capture_output=True, text=True, timeout=30)
    txt = _ANSI.sub("", (p.stdout or "") + "\n" + (p.stderr or ""))
    txt = re.sub(r"[│─╭╮╰╯├┤┌┐└┘|]", " ", txt)
    return re.sub(r"\s+", " ", txt)


def test_note_list_e_json() -> None:
    h = _help("note", "list")
    assert "NOTEBOOK_ID" in h and "--json" in h, h


def test_note_create_contenuto_e_titolo() -> None:
    h = _help("note", "create")
    assert "NOTEBOOK_ID" in h and "--content" in h and "-c" in h and "--title" in h and "-t" in h, h


def test_note_update_due_id_posizionali() -> None:
    h = _help("note", "update")
    assert "NOTEBOOK_ID" in h and "NOTE_ID" in h and "--content" in h and "--title" in h, h


def test_note_delete_senza_domanda() -> None:
    h = _help("note", "delete")
    assert "NOTE_ID" in h and "--confirm" in h and "-y" in h, h


def test_chats_list_e_get() -> None:
    assert "--json" in _help("chats", "list")
    h = _help("chats", "get")
    assert "NOTEBOOK" in h and "CONVERSATION_ID" in h and "--json" in h, h


def test_le_firme_di_services_research() -> None:
    from notebooklm_tools.cli.utils import get_client  # noqa: F401 — ricerca_nlm lo importa
    from notebooklm_tools.services import research as r
    assert {"source", "mode"} <= set(inspect.signature(r.start_research).parameters)
    assert {"task_id", "compact", "max_wait"} <= set(inspect.signature(r.poll_research).parameters)
    assert {"source_indices", "cited_only"} <= set(inspect.signature(r.import_research).parameters)
