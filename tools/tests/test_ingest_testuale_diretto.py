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

🔴 12/10/2026: «diretto» non vuol più dire «nel gateway». L'indexer girava con `exec`
   nel gateway, che dalla 0.84 ha un tetto di 512 MB: un file grande faceva uccidere il
   servizio pubblico. Ora il file va nel volume dell'archivio e lo indicizza il servizio
   compose `ingest` (2g, modo «coda»), sia il testo sia la trascrizione di NotebookLM.
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
        # il lavoro `ingest` "riesce" e stampa la sua riga d'esito
        return SimpleNamespace(returncode=0, stdout='{"righe": 3, "totale": 3}', stderr="")

    monkeypatch.setattr(mod, "run", run_finto)
    monkeypatch.setattr(mod, "compose_cmd", lambda repo: ["docker", "compose"])
    return mod, chiamate


INGEST = ["docker", "compose", "--profile", "ingest", "run", "--rm", "-T", "ingest"]


def _lavoro(chiamate: list[list[str]]) -> list[str]:
    """La chiamata che indicizza: il servizio `ingest`, modo «coda». Una sola."""
    (lavoro,) = [c for c in chiamate if c[:8] == INGEST]
    assert lavoro[8] == "coda", lavoro
    return lavoro


def _dest(lavoro: list[str]) -> str:
    jid = lavoro[lavoro.index("--id") + 1]
    return f"/var/lib/archive/coda/{jid}{lavoro[lavoro.index('--suffisso') + 1]}"


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
    lavoro = _lavoro(chiamate)
    # il file viaggia con la SUA estensione (il parser si sceglie dal suffisso);
    # e viaggia via exec+stdin, MAI con `docker cp`: il rootfs del gateway è
    # read-only per hardening e cp fallirebbe (misurato 06/09, #285 bis)
    assert lavoro[lavoro.index("--suffisso") + 1] == ".md"
    dest = _dest(lavoro)
    assert any(dest in c and "cat >" in c for c in piatto), \
        f"il file non è arrivato nel volume dell'archivio: {piatto}"
    assert not any(c.startswith("docker compose cp") and "gateway" in c for c in piatto), \
        f"docker cp verso il gateway read-only: {piatto}"


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


def test_il_file_non_testuale_entra_in_nb1777_senza_docker_cp(cli, tmp_path):
    """H43 (27/09/2026): nb1777-mcp ha il rootfs read-only, e `docker cp` verso un
    container così rifiuta («container rootfs is marked read-only», misurato sul gateway
    il 06/09, #285 bis). Il file viaggia su stdin di un `exec`, e atterra nel volume
    degli artefatti (sotto-cartella `ingest/`, che `artifact_list` non elenca), non in
    /tmp: la tmpfs ha un tetto di 64 MB, un audio o un PDF lo superano."""
    mod, chiamate = cli
    f = tmp_path / "scan.pdf"
    f.write_bytes(b"%PDF finto")

    def run_con_esito(cmd, **kw):
        chiamate.append(list(cmd))
        if "app.ingest" in cmd:
            return SimpleNamespace(returncode=0, stdout='{"text": "testo trascritto"}', stderr="")
        return SimpleNamespace(returncode=0, stdout='{"righe": 1, "totale": 1}', stderr="")

    mod.run = run_con_esito
    assert mod.cmd_archive_ingest(tmp_path, _args(str(f))) == 0
    assert not any(c[:3] == ["docker", "compose", "cp"] for c in chiamate), chiamate
    ingresso = next(c for c in chiamate if "nb1777-mcp" in c and "cat >" in " ".join(c))
    dest = next(c for c in chiamate if "app.ingest" in c)
    percorso = dest[dest.index("--file") + 1]
    assert percorso.startswith("/var/lib/nlm-artifacts/ingest/"), percorso
    assert percorso in " ".join(ingresso)
    rm = [c for c in chiamate if "nb1777-mcp" in c and "rm" in c and percorso in c]
    assert rm, "il file in ingresso va tolto alla fine"
    # Misurato sulla VPS il 27/09 (0.58.0): `exec -u root … rm` falliva con «Permission
    # denied». Con cap_drop ALL root non ha CAP_DAC_OVERRIDE, e il file (e la cartella)
    # sono di `app`: lo crea l'exec come `app`, lo deve togliere `app`.
    assert all("-u" not in c for c in rm), rm


def test_il_testo_non_si_indicizza_nel_gateway(cli, tmp_path):
    """Il gateway ha un tetto di 512 MB: indicizzarci un file grande faceva uccidere il
    servizio pubblico. Il gateway fa solo da tramite (un `cat`), mai l'indexer."""
    mod, chiamate = cli
    f = tmp_path / "grande.jsonl"
    f.write_text('{"type": "user"}\n', encoding="utf-8")
    assert mod.cmd_archive_ingest(tmp_path, _args(str(f))) == 0
    nel_gateway = [c for c in chiamate if "gateway" in c and "exec" in c]
    assert not [c for c in nel_gateway if "python" in c or "archive_indexer" in " ".join(c)], \
        nel_gateway
    lavoro = _lavoro(chiamate)
    assert lavoro[lavoro.index("--db") + 1] == "prova-285"
    assert lavoro[lavoro.index("--project") + 1] == "video:prova"
    # il file NON va nella tmpfs da 64 MB del gateway, ma nel volume dell'archivio
    assert not any("/tmp/" in " ".join(c) for c in chiamate), chiamate


def test_il_file_nel_volume_si_toglie_sempre(cli, tmp_path, capsys):
    """Un lavoro ucciso dal tetto (137) non arriva al suo `finally`: il file lo toglie la
    CLI, come utente del gateway (senza `-u root`: con cap_drop ALL root non può)."""
    mod, chiamate = cli

    def run_ucciso(cmd, **kw):
        chiamate.append(list(cmd))
        if cmd[:8] == INGEST:
            return SimpleNamespace(returncode=137, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    mod.run = run_ucciso
    f = tmp_path / "doc.md"
    f.write_text("testo", encoding="utf-8")
    with pytest.raises(SystemExit):
        mod.cmd_archive_ingest(tmp_path, _args(str(f)))
    dest = _dest(_lavoro(chiamate))
    rm = [c for c in chiamate if "rm" in c and dest in c]
    assert rm and "gateway" in rm[0] and "-u" not in rm[0], rm
    assert "tetto di memoria" in capsys.readouterr().err


def test_l_indicizzazione_tiene_il_lucchetto_dell_archivio(cli, tmp_path):
    import fcntl
    mod, chiamate = cli
    preso = []

    def run_guarda(cmd, **kw):
        chiamate.append(list(cmd))
        if cmd[:8] == INGEST:
            with open(tmp_path / "var" / "archivio.lock", "a") as fh:
                try:
                    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    preso.append(False)
                except BlockingIOError:
                    preso.append(True)
        return SimpleNamespace(returncode=0, stdout='{"righe": 1, "totale": 1}', stderr="")

    mod.run = run_guarda
    f = tmp_path / "doc.md"
    f.write_text("testo", encoding="utf-8")
    assert mod.cmd_archive_ingest(tmp_path, _args(str(f))) == 0
    assert preso == [True]


@pytest.mark.parametrize("nome", ["note.rst", "server.log", "tabella.csv", "a.markdown"])
def test_il_testo_che_l_indexer_non_conosce_viaggia_come_txt(cli, tmp_path, nome):
    """L'indexer legge come testo solo .md e .txt: questi prima arrivavano col loro
    suffisso e venivano rifiutati («formato non supportato»)."""
    mod, chiamate = cli
    f = tmp_path / nome
    f.write_text("testo", encoding="utf-8")
    assert mod.cmd_archive_ingest(tmp_path, _args(str(f))) == 0
    lavoro = _lavoro(chiamate)
    assert lavoro[lavoro.index("--suffisso") + 1] == ".txt"


def test_un_nome_di_db_troppo_lungo_si_dice_prima(cli, tmp_path, capsys):
    mod, chiamate = cli
    f = tmp_path / "doc.md"
    f.write_text("testo", encoding="utf-8")
    with pytest.raises(SystemExit):
        mod.cmd_archive_ingest(tmp_path, _args(str(f), db="x" * 80))
    assert "--db" in capsys.readouterr().err
    assert not chiamate


def test_la_trascrizione_si_indicizza_nel_servizio_ingest(cli, tmp_path):
    """Il PDF (o l'audio) passa da NotebookLM, ma il testo che torna si indicizza come
    tutto il resto: nel servizio `ingest`, come .txt."""
    mod, chiamate = cli

    def run_con_esito(cmd, **kw):
        chiamate.append(list(cmd))
        if "app.ingest" in cmd:
            return SimpleNamespace(returncode=0, stdout='{"text": "testo trascritto"}', stderr="")
        return SimpleNamespace(returncode=0, stdout='{"righe": 1, "totale": 1}', stderr="")

    mod.run = run_con_esito
    f = tmp_path / "scan.pdf"
    f.write_bytes(b"%PDF finto")
    assert mod.cmd_archive_ingest(tmp_path, _args(str(f))) == 0
    lavoro = _lavoro(chiamate)
    assert lavoro[lavoro.index("--suffisso") + 1] == ".txt"
    assert not [c for c in chiamate if "gateway" in c and "python" in c]


# ── P17 (11/10/2026): `--artefatto`, un podcast dello Studio in un gesto ──────────────

def _args_artefatto(nome: str, **kw):
    base = dict(file=None, artefatto=nome, db="podcast", project="studio", verify=False,
                nlm=False)
    base.update(kw)
    return SimpleNamespace(**base)


def test_un_artefatto_non_si_copia_e_non_si_cancella(cli, tmp_path):
    """Il file è già nel volume degli artefatti (studio_download): niente `cat >` in
    nb1777, la trascrizione legge quel percorso, e alla fine l'artefatto resta lì."""
    mod, chiamate = cli

    def run_con_esito(cmd, **kw):
        chiamate.append(list(cmd))
        if "app.ingest" in cmd:
            return SimpleNamespace(returncode=0, stderr="", stdout=(
                '{"text": "trascrizione", "metodo": "contenuto", "fonte_tipo": "audio"}'))
        return SimpleNamespace(returncode=0, stdout='{"righe": 1, "totale": 1}', stderr="")

    mod.run = run_con_esito
    assert mod.cmd_archive_ingest(tmp_path, _args_artefatto("prova-p15.m4a")) == 0
    percorso = "/var/lib/nlm-artifacts/prova-p15.m4a"
    dest = next(c for c in chiamate if "app.ingest" in c)
    assert dest[dest.index("--file") + 1] == percorso
    assert not any("nb1777-mcp" in c and "cat >" in " ".join(c) for c in chiamate), chiamate
    assert not any("nb1777-mcp" in c and "rm" in c for c in chiamate), \
        "l'artefatto è di chi l'ha scaricato: non si cancella"


@pytest.mark.parametrize("nome", ["../nlm/profiles/default/cookies.json", "/etc/passwd",
                                  "ingest/x.m4a", ".nascosto", ""])
def test_un_nome_di_artefatto_non_e_un_percorso(cli, tmp_path, nome):
    mod, chiamate = cli
    with pytest.raises(SystemExit):
        mod.cmd_archive_ingest(tmp_path, _args_artefatto(nome))
    assert not any("app.ingest" in c for c in chiamate)


def test_file_e_artefatto_insieme_no(cli, tmp_path):
    mod, _ = cli
    f = tmp_path / "a.md"
    f.write_text("x")
    with pytest.raises(SystemExit):
        mod.cmd_archive_ingest(tmp_path, _args_artefatto("a.m4a", file=str(f)))


def test_un_artefatto_che_non_c_e_lo_dice(cli, tmp_path, capsys):
    mod, chiamate = cli

    def run_manca(cmd, **kw):
        chiamate.append(list(cmd))
        if "test" in cmd:
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    mod.run = run_manca
    with pytest.raises(SystemExit):
        mod.cmd_archive_ingest(tmp_path, _args_artefatto("manca.m4a"))
    assert "studio_download" in capsys.readouterr().err
