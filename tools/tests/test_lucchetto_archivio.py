"""Il lucchetto comune dell'archivio (`var/archivio.lock`, 12/10/2026).

Prima `ingest-coda` prendeva solo il suo lucchetto (un giro della coda alla volta) e
`indice-notturno` nessuno: un'indicizzazione dalla coda e l'aggiornamento dell'indice
semantico potevano girare insieme sullo stesso DB, e sommare i due tetti di memoria
(2g + 1300m) su una VPS piccola. Ora chi lavora sui DB dell'archivio passa da
`lucchetto_archivio`. Qui: il secondo ASPETTA (processi veri, non finti), il tetto
d'attesa, il turno (chi aspetta entra fra un lavoro e l'altro), e i comandi che lo
prendono davvero attorno al lavoro.
"""
from __future__ import annotations

import fcntl
import importlib.util
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

RADICE = Path(__file__).resolve().parents[2]
CLI = RADICE / "tools" / "vps1777.py"
JID = "20261012T090000Z-0a1b2c3d"

# un altro processo che tiene il lucchetto: `giri` volte, `secondi` per volta, e lo
# riprende subito (come la coda fra un lavoro e l'altro)
_TIENI = r"""
import importlib.util, sys, time
from pathlib import Path
spec = importlib.util.spec_from_file_location("cli_tieni", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
repo, chi, secondi, giri = Path(sys.argv[2]), sys.argv[3], float(sys.argv[4]), int(sys.argv[5])
for i in range(giri):
    with mod.lucchetto_archivio(repo, chi):
        print(f"preso {i} {time.monotonic()}", flush=True)
        time.sleep(secondi)
print("finito", flush=True)
"""


def _carica():
    spec = importlib.util.spec_from_file_location("vps1777_cli_lucchetto", CLI)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["vps1777_cli_lucchetto"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def cli():
    return _carica()


def _tieni(repo: Path, chi: str, secondi: float, giri: int = 1) -> subprocess.Popen:
    """Lancia il processo che tiene il lucchetto e aspetta che l'abbia preso."""
    p = subprocess.Popen([sys.executable, "-c", _TIENI, str(CLI), str(repo), chi,
                          str(secondi), str(giri)], stdout=subprocess.PIPE, text=True)
    riga = p.stdout.readline()
    assert riga.startswith("preso"), riga
    return p


def _occupato(repo: Path) -> bool:
    with open(repo / "var" / "archivio.lock", "a") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(fh, fcntl.LOCK_UN)
        return False


def test_libero_si_prende_si_scrive_chi_e_si_lascia(cli, tmp_path):
    with cli.lucchetto_archivio(tmp_path, "archive-retag"):
        assert _occupato(tmp_path)
        assert (tmp_path / "var" / "archivio.lock").read_text().startswith("archive-retag (pid ")
    assert not _occupato(tmp_path)
    # chi arriva dopo non deve leggere il nome di chi se n'è andato
    assert (tmp_path / "var" / "archivio.lock").read_text() == ""


def test_il_secondo_aspetta_e_lo_dice(cli, tmp_path, capsys):
    tenuto = _tieni(tmp_path, "indice-notturno", 1.0)
    visto = []
    t0 = time.monotonic()
    with cli.lucchetto_archivio(tmp_path, "ingest-coda", in_attesa=visto.append):
        atteso = time.monotonic() - t0
    tenuto.wait(timeout=10)
    assert atteso > 0.5, f"non ha aspettato: {atteso:.2f}s"
    assert visto and visto[0].startswith("indice-notturno (pid ")
    out = capsys.readouterr().out
    assert "aspetto: indice-notturno" in out and "sta lavorando sull'archivio" in out


def test_il_tetto_d_attesa_si_rispetta(cli, tmp_path):
    tenuto = _tieni(tmp_path, "ingest-coda", 3.0)
    try:
        t0 = time.monotonic()
        with pytest.raises(cli.ArchivioOccupato, match="ingest-coda"):
            with cli.lucchetto_archivio(tmp_path, "indice-notturno", attesa_max=0.3,
                                        passo=0.05):
                pytest.fail("non doveva entrare")
        assert time.monotonic() - t0 < 2.0
    finally:
        tenuto.kill()
        tenuto.wait()
    # rinunciare non lascia niente di preso
    assert not _occupato(tmp_path)


def test_chi_aspetta_entra_fra_un_lavoro_e_l_altro(cli, tmp_path):
    """Il turno: flock non fa la fila, e senza il turno chi lascia e riprende subito il
    lucchetto (la coda con dieci file) lo riprenderebbe prima di chi aspetta, ogni volta."""
    tenuto = _tieni(tmp_path, "ingest-coda", 0.2, giri=15)
    try:
        t0 = time.monotonic()
        with cli.lucchetto_archivio(tmp_path, "indice-notturno", attesa_max=10, passo=0.02):
            atteso = time.monotonic() - t0
    finally:
        tenuto.wait(timeout=20)
    # quindici giri da 0,2 s sono tre secondi: entra dopo il primo, non alla fine
    assert atteso < 1.5, f"chi aspettava è entrato solo dopo {atteso:.2f}s"


# ── chi lo prende ─────────────────────────────────────────────────────────────────


def test_tutti_i_comandi_sull_archivio_lo_prendono():
    src = CLI.read_text(encoding="utf-8")
    for nome in ("def cmd_archive_migra(", "def _archive_migra_telegram(",
                 "def cmd_archive_retag(", "def _indicizza_nel_lavoro(",
                 "def cmd_indice_notturno(", "def cmd_ingest_coda("):
        i = src.index(nome)
        corpo = src[i:src.index("\ndef ", i + 10)]
        assert "lucchetto_archivio(" in corpo, nome


def test_retag_lavora_col_lucchetto_in_mano(cli, tmp_path, monkeypatch):
    visti = []

    def run_finto(cmd, **kw):
        if "ls" in " ".join(cmd):
            return SimpleNamespace(returncode=0, stdout="/var/lib/archive/db/note.db\n", stderr="")
        visti.append(_occupato(tmp_path))
        return SimpleNamespace(returncode=0, stderr="", stdout=json.dumps(
            {"righe": 1, "cambiate": 0, "prima": {}, "dopo": {}, "scritto": False}))

    monkeypatch.setattr(cli, "run", run_finto)
    monkeypatch.setattr(cli, "compose_cmd", lambda repo: ["docker", "compose"])
    assert cli.cmd_archive_retag(tmp_path, SimpleNamespace(db=None, scrivi=False)) == 0
    assert visti == [True]


@pytest.fixture()
def notturno(cli, tmp_path, monkeypatch):
    lanciati = []

    def run_finto(cmd, **kw):
        if "exec" in cmd:
            return SimpleNamespace(returncode=0, stdout="200 100 note\n200 100 diario\n", stderr="")
        lanciati.append((cmd[cmd.index("--db") + 1], _occupato(tmp_path)))
        return SimpleNamespace(returncode=0, stdout="fatto\n", stderr="")

    monkeypatch.setattr(cli, "run", run_finto)
    monkeypatch.setattr(cli, "compose_cmd", lambda repo: ["docker", "compose"])
    return cli, tmp_path, lanciati


def _args_notturno(**kw):
    base = dict(abilita=False, disabilita=False, tutti=False, db=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_il_notturno_prende_il_lucchetto_per_ogni_db(notturno):
    cli, repo, lanciati = notturno
    assert cli.cmd_indice_notturno(repo, _args_notturno()) == 0
    assert lanciati == [("/var/lib/archive/db/note.db", True),
                        ("/var/lib/archive/db/diario.db", True)]


def test_il_notturno_lascia_la_notte_se_l_archivio_resta_occupato(notturno, monkeypatch, capsys):
    cli, repo, lanciati = notturno
    monkeypatch.setattr(cli, "ATTESA_INDICE_S", 0.3)
    tenuto = _tieni(repo, "ingest-coda", 3.0)
    try:
        # un'attesa troppo lunga non è un guasto: niente esito 1, niente notifica
        assert cli.cmd_indice_notturno(repo, _args_notturno()) == 0
    finally:
        tenuto.kill()
        tenuto.wait()
    assert lanciati == [], "con l'archivio occupato il costruttore non deve partire"
    out = capsys.readouterr()
    assert "note, diario" in out.out + out.err and "prossimo giro" in out.out + out.err


# ── la coda aspetta, e non consuma l'intent prima di avere il lucchetto ──────────


@pytest.fixture()
def coda(cli, tmp_path, monkeypatch):
    lavori = []

    def run_finto(cmd, **kw):
        if "coda" in cmd and "ingest" in cmd:
            lavori.append(_occupato(tmp_path))
            return SimpleNamespace(returncode=0, stdout='{"righe": 2, "totale": 2}', stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cli, "run", run_finto)
    monkeypatch.setattr(cli, "compose_cmd", lambda repo: ["docker", "compose"])
    cartella = tmp_path / "onboarding" / cli.INGEST_CODA
    cartella.mkdir(parents=True)
    (cartella / f"{JID}.json").write_text(json.dumps({
        "id": JID, "db": "note", "suffisso": ".md", "file": "n.md", "project": "",
        "description": "", "by": "owner@example.invalid", "accodato": "2026-10-12T09:00:00Z"}))
    return cli, tmp_path, cartella, lavori


def test_la_coda_lavora_col_lucchetto_in_mano(coda):
    cli, repo, cartella, lavori = coda
    assert cli.cmd_ingest_coda(repo, SimpleNamespace()) == 0
    assert lavori == [True]


def test_la_coda_aspetta_senza_consumare_e_la_pagina_lo_sa(coda):
    """Uscire lasciando l'intent farebbe ripartire la path unit in giro continuo:
    la coda ASPETTA. E mentre aspetta l'intent resta in coda (un'attesa interrotta non lo
    perde), e c'è il segno d'attesa che la pagina legge al posto di «nessuno l'ha preso»."""
    cli, repo, cartella, lavori = coda
    segno = repo / "onboarding" / cli.INGEST_ESITI / cli.INGEST_ATTESA
    tenuto = _tieni(repo, "indice-notturno", 1.5)
    esito = {}
    t = threading.Thread(target=lambda: esito.setdefault(
        "rc", cli.cmd_ingest_coda(repo, SimpleNamespace())))
    t.start()
    scadenza = time.monotonic() + 1.0
    while not segno.exists() and time.monotonic() < scadenza:
        time.sleep(0.02)
    assert segno.exists(), "aspettando, la coda deve lasciare il segno d'attesa"
    assert json.loads(segno.read_text())["chi"] == "indice-notturno"
    assert (cartella / f"{JID}.json").exists(), "l'intent si consuma solo col lucchetto"
    assert lavori == []
    t.join(timeout=10)
    tenuto.wait(timeout=10)
    assert esito.get("rc") == 0 and lavori == [True]
    assert not segno.exists() and not list(cartella.iterdir())


def test_il_nome_del_segno_d_attesa_e_lo_stesso_del_gateway(cli):
    spec = importlib.util.spec_from_file_location(
        "coda_ingest_lucchetto", RADICE / "services/gateway/app/coda_ingest.py")
    gw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gw)
    assert gw.ATTESA == cli.INGEST_ATTESA
    # e non ha la forma di un id: la pagina non lo mostra come un lavoro, la potatura lo
    # lascia stare
    assert not re.match(gw.ID_RE, Path(gw.ATTESA).stem)
