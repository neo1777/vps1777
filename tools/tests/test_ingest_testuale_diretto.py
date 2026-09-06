"""archive-ingest: il testo va DIRETTO all'indexer, mai da NotebookLM (#285).

🔴 IL FATTO CHE L'HA GENERATO, misurato il 2026-09-06: tre .md (lo standard
   ingest-video) hanno girato ORE nel canale NotebookLM per poi fallire 3/3 con
   «Could not add file source» — quando l'indexer del gateway li avrebbe
   indicizzati in un secondo. Doppio difetto: il giro OCR su testo puro è
   overhead gratuito, E l'upload-file del client nlm era rotto (regressione
   upstream: nb_create/add_text funzionavano, add-da-file falliva con QUALUNQUE
   estensione — diagnosi sul vivo, stessa sera).

⭐ Il test è COMPORTAMENTALE, non testuale: intercetta le chiamate `run` e
   verifica CHI viene invocato. Un grep sul sorgente direbbe «il ramo c'è»;
   qui si prova che il ramo MORDE — il .md non tocca mai nb1777-mcp, il
   --nlm ce lo rimanda, il .pdf resta sul giro vecchio.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

RADICE = Path(__file__).resolve().parents[2]


def _carica_cli():
    spec = importlib.util.spec_from_file_location("vps1777_cli", RADICE / "tools" / "vps1777.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["vps1777_cli"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def cli(monkeypatch):
    mod = _carica_cli()
    chiamate: list[list[str]] = []

    def run_finto(cmd, **kw):
        chiamate.append(list(cmd))
        # l'exec dell'indexer "riesce" e stampa un esito plausibile
        return SimpleNamespace(returncode=0, stdout='{"indicizzate": 3}', stderr="")

    monkeypatch.setattr(mod, "run", run_finto)
    monkeypatch.setattr(mod, "compose_cmd", lambda repo: ["docker", "compose"])
    return mod, chiamate


def _args(file: str, **kw):
    base = dict(file=file, db="prova-285", project="video:prova", verify=False, nlm=False)
    base.update(kw)
    return SimpleNamespace(**base)


def test_md_va_diretto_e_non_tocca_notebooklm(cli, tmp_path):
    mod, chiamate = cli
    f = tmp_path / "doc1.md"
    f.write_text("# titolo\ntelavevodettismo di prova\n", encoding="utf-8")
    rc = mod.cmd_archive_ingest(tmp_path, _args(str(f)))
    assert rc == 0
    piatto = [" ".join(c) for c in chiamate]
    assert not any("nb1777-mcp" in c for c in piatto), \
        f"un file testuale è passato da NotebookLM: {piatto}"
    assert any("gateway" in c and "archive_indexer" in c for c in piatto), \
        f"l'indexer del gateway non è stato invocato: {piatto}"
    # il file viaggia con la SUA estensione (il parser si sceglie dal suffisso)
    assert any(".md" in c for c in piatto if "cp" in c), \
        f"l'estensione testuale è andata persa nel viaggio: {piatto}"


def test_nlm_forza_il_giro_notebooklm_anche_su_testo(cli, tmp_path, monkeypatch):
    mod, chiamate = cli
    f = tmp_path / "doc1.md"
    f.write_text("testo", encoding="utf-8")
    # il giro nlm nel mock non produce un JSON di trascrizione: basta vedere CHI chiama
    with pytest.raises(SystemExit):
        mod.cmd_archive_ingest(tmp_path, _args(str(f), nlm=True))
    piatto = [" ".join(c) for c in chiamate]
    assert any("nb1777-mcp" in c for c in piatto), \
        f"--nlm non ha forzato il giro NotebookLM: {piatto}"


def test_pdf_resta_sul_giro_notebooklm(cli, tmp_path):
    mod, chiamate = cli
    f = tmp_path / "scan.pdf"
    f.write_bytes(b"%PDF-1.4 finto")
    with pytest.raises(SystemExit):
        mod.cmd_archive_ingest(tmp_path, _args(str(f)))
    piatto = [" ".join(c) for c in chiamate]
    assert any("nb1777-mcp" in c for c in piatto), \
        f"un PDF non è passato da NotebookLM: {piatto}"


def test_errore_nlm_parla_e_indica_la_via(monkeypatch, tmp_path, capsys):
    """Quando nlm fallisce con «Could not add», l'errore deve spiegare e indicare
    il percorso diretto — non lasciare l'utente con quattro parole mute."""
    mod = _carica_cli()

    def run_rotto(cmd, **kw):
        if "nb1777-mcp" in cmd and "app.ingest" in " ".join(cmd):
            return SimpleNamespace(returncode=1, stdout="",
                                   stderr="nlm exit 1: Error: Could not add file source.")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mod, "run", run_rotto)
    monkeypatch.setattr(mod, "compose_cmd", lambda repo: ["docker", "compose"])
    f = tmp_path / "scan.pdf"
    f.write_bytes(b"%PDF finto")
    with pytest.raises(SystemExit):
        mod.cmd_archive_ingest(tmp_path, _args(str(f)))
    err = capsys.readouterr().err
    assert "Could not add" in err
    assert "upstream" in err and "diretto" in err, \
        f"l'errore non spiega la causa misurata né la via d'uscita: {err[:300]}"
