"""H41 — i contenuti personali non finiscono in argv né negli errori.

Si mocka il confine subprocess (`_add_and_resolve_id`, e per _safe_cmd niente
mock) per verificare, SENZA nlm né auth:
  - un testo lungo passa da un file temp `--file` (0600), non da `--text`;
  - il file esiste durante la chiamata e viene ripulito dopo;
  - un testo corto resta in argv (è come un titolo, superficie già inevitabile);
  - `_safe_cmd` tronca gli argomenti lunghi nel messaggio d'errore.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

from app import core


def test_source_add_text_lungo_usa_file_temp_non_argv(monkeypatch) -> None:
    captured: dict = {}

    def fake(nb_id, args, *, timeout):
        captured["args"] = args
        i = args.index("--file")
        p = Path(args[i + 1])
        # il file col contenuto personale esiste ORA (durante la add) ed è 0600
        captured["exists_during"] = p.is_file()
        captured["mode"] = stat.S_IMODE(p.stat().st_mode)
        captured["content"] = p.read_text(encoding="utf-8")
        captured["path"] = p
        return "sid-1"

    monkeypatch.setattr(core, "_add_and_resolve_id", fake)
    text = "P" * (core.TEXT_ARGV_MAX + 100)
    sid = core.source_add_text("nb-1", text, "Titolo Fonte", wait=False)

    assert sid == "sid-1"
    assert "--text" not in captured["args"]          # il corpo NON è in argv
    assert "--file" in captured["args"]
    assert "--title" in captured["args"] and "Titolo Fonte" in captured["args"]
    assert captured["content"] == text               # il file ha il testo intero
    assert captured["exists_during"] is True
    assert captured["mode"] == 0o600                 # non leggibile da altri utenti
    assert not captured["path"].exists()             # ripulito dopo la add


def test_source_add_text_corto_resta_in_argv(monkeypatch) -> None:
    captured: dict = {}

    def fake(nb_id, args, *, timeout):
        captured["args"] = args
        return "sid"

    monkeypatch.setattr(core, "_add_and_resolve_id", fake)
    core.source_add_text("nb-1", "ciao breve", "T", wait=False)
    assert "--text" in captured["args"]
    assert "ciao breve" in captured["args"]
    assert "--file" not in captured["args"]


def test_source_add_text_file_temp_pulito_anche_se_add_esplode(monkeypatch) -> None:
    seen: dict = {}

    def boom(nb_id, args, *, timeout):
        i = args.index("--file")
        seen["path"] = Path(args[i + 1])
        raise core.NLMError("add fallita")

    monkeypatch.setattr(core, "_add_and_resolve_id", boom)
    try:
        core.source_add_text("nb-1", "Q" * (core.TEXT_ARGV_MAX + 10), "T", wait=False)
    except core.NLMError:
        pass
    assert not seen["path"].exists()   # il finally ripulisce anche in errore


def test_safe_cmd_tronca_i_contenuti_lunghi() -> None:
    segreto = "x" * 5000
    out = core._safe_cmd(["nlm", "source", "add", "nb", "--text", segreto, "--title", "t"])
    assert segreto not in out                     # il corpo non trapela nell'errore
    assert len(out) <= core._ERR_CMD_MAX + 1      # +1 per l'ellissi
    assert out.startswith("nlm source add nb")    # la FORMA del comando resta leggibile


def test_run_timeout_non_versa_argv(monkeypatch) -> None:
    # un timeout deve dire COSA è andato in timeout senza ristampare il --text intero
    segreto = "S" * 4000

    class _FakeTimeout(Exception):
        pass

    def fake_run(cmd, **kw):
        raise __import__("subprocess").TimeoutExpired(cmd, kw.get("timeout", 1))

    monkeypatch.setattr(core.subprocess, "run", fake_run)
    try:
        core._run(["source", "add", "nb", "--text", segreto, "--title", "t"], timeout=1)
        raise AssertionError("doveva sollevare")
    except core.NLMError as e:
        assert segreto not in str(e)
        assert "timeout" in str(e)


def test_os_module_disponibile() -> None:
    # sanity: il fix usa os/tempfile — se un refactor li togliesse, salta qui
    assert hasattr(os, "fdopen")
