"""`archive-ingest`: le strade che le altre prove non percorrevano (25/11/2026).

Misurate prima di spezzare `cmd_archive_ingest` (QUA-04): il file che non c'è, l'artefatto testuale
letto da nb1777-mcp, `--verify`, la trascrizione che fallisce senza un aiuto da dare, l'uscita che
non è JSON, il testo vuoto, il lavoro che supera le sei ore. `run` è finto e risponde per comando.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("vps1777_cli_ingest_rare", _ROOT / "tools" / "vps1777.py")
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)

BUONA = '{"text": "parole trascritte", "metodo": "contenuto"}'


@pytest.fixture
def banco(tmp_path, monkeypatch):
    b = SimpleNamespace(chiamate=[], ingressi=[], detti=[], trascrizione=(0, BUONA, ""),
                        letto="testo dell'artefatto", scade=False)

    def run(cmd, **kw):
        b.chiamate.append(list(cmd))
        b.ingressi.append(kw.get("input"))
        if "app.ingest" in cmd:
            rc, out, err = b.trascrizione
            return SimpleNamespace(returncode=rc, stdout=out, stderr=err)
        if "coda" in cmd:
            if b.scade:
                raise subprocess.TimeoutExpired(cmd, 1)
            return SimpleNamespace(returncode=0, stdout='{"righe": 2, "totale": 2}', stderr="")
        if "cat" in cmd:
            return SimpleNamespace(returncode=0, stdout=b.letto, stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(v, "run", run)
    monkeypatch.setattr(v, "compose_cmd", lambda _repo: ["docker", "compose"])
    for nome in ("log", "ok"):
        monkeypatch.setattr(v, nome, lambda t, _n=nome: b.detti.append(str(t)))
    b.pdf = tmp_path / "scansione.pdf"
    b.pdf.write_bytes(b"%PDF finto")
    b.args = lambda **kw: SimpleNamespace(**{"file": str(b.pdf), "artefatto": None, "db": "prova", "project": None,
                                             "verify": False, "nlm": False, **kw})
    b.gira = lambda **kw: v.cmd_archive_ingest(tmp_path, b.args(**kw))
    return b


def _esce(b, capsys, frammento, **kw):
    with pytest.raises(SystemExit) as e:
        b.gira(**kw)
    assert e.value.code == 1
    errore = capsys.readouterr().err
    assert frammento in errore
    return errore


def test_un_file_che_non_c_e_si_dice_prima_di_ogni_comando(banco, capsys, tmp_path):
    _esce(banco, capsys, "file non trovato", file=str(tmp_path / "assente.md"))
    assert banco.chiamate == []


def test_un_artefatto_testuale_si_legge_da_nb1777_e_va_diretto(banco):
    assert banco.gira(file=None, artefatto="appunti.md") == 0
    assert ["docker", "compose", "exec", "-T", "nb1777-mcp", "cat",
            f"{v._DIR_ARTEFATTI}/appunti.md"] in banco.chiamate
    assert "testo dell'artefatto" in banco.ingressi          # entra nel volume dell'archivio per stdin
    assert not any("app.ingest" in c for c in banco.chiamate)
    assert not any("nb1777-mcp" in c and "rm" in c for c in banco.chiamate)   # non è nostro: resta


def test_verify_arriva_alla_trascrizione_e_la_verifica_si_dice(banco):
    banco.trascrizione = (0, '{"text": "parole", "metodo": "domanda", "verification": "combacia"}', "")
    assert banco.gira(verify=True) == 0
    (comando,) = [c for c in banco.chiamate if "app.ingest" in c]
    assert comando[-1] == "--verify"
    assert any("verifica NotebookLM: combacia" in d for d in banco.detti)
    banco.chiamate.clear()
    banco.gira()
    assert "--verify" not in next(c for c in banco.chiamate if "app.ingest" in c)


def test_una_trascrizione_fallita_per_altro_motivo_non_consiglia_il_percorso_diretto(banco, capsys):
    banco.trascrizione = (1, "", "quota finita")
    errore = _esce(banco, capsys, "trascrizione fallita: quota finita")
    assert "--nlm" not in errore
    assert not any("coda" in c for c in banco.chiamate)


@pytest.mark.parametrize("uscita", ["", "\n", "non è JSON", 'rumore\n{"text": '])
def test_un_uscita_che_non_e_json_si_dice(banco, capsys, uscita):
    banco.trascrizione = (0, uscita, "")
    _esce(banco, capsys, "output trascrizione non interpretabile")
    assert not any("coda" in c for c in banco.chiamate)


@pytest.mark.parametrize("uscita", ['{"text": "   "}', '{"metodo": "contenuto"}', '{"text": null}'])
def test_una_trascrizione_senza_testo_non_si_indicizza(banco, capsys, uscita):
    banco.trascrizione = (0, uscita, "")
    _esce(banco, capsys, "non ha restituito testo")
    assert not any("coda" in c for c in banco.chiamate)


def test_il_lavoro_che_supera_le_sei_ore_si_dice_e_il_file_si_toglie(banco, capsys, tmp_path):
    banco.scade = True
    md = tmp_path / "nota.md"
    md.write_text("x")
    _esce(banco, capsys, "ha superato le 6 ore", file=str(md))
    assert banco.chiamate[-1][:6] == ["docker", "compose", "exec", "-T", "gateway", "rm"]


def test_la_copia_in_nb1777_si_toglie_anche_se_la_trascrizione_fallisce(banco, capsys):
    banco.trascrizione = (1, "", "boom")
    _esce(banco, capsys, "trascrizione fallita")
    assert "nb1777-mcp" in banco.chiamate[-1] and "rm" in banco.chiamate[-1]
