"""P16 (11/10/2026): `vps1777 ingest-coda`, il lato host della coda di /admin/archive.

Il gateway scrive un intent in onboarding/ingest_coda/; la path unit lancia questo
comando, che lo consuma e fa girare il servizio compose `ingest`. Qui: la validazione
dell'intent (la CLI non si fida del servizio esposto), la lettura dell'esito, il giro
con `run` finto, e i pezzi di perimetro (unit, compose).
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

RADICE = Path(__file__).resolve().parents[2]
JID = "20261011T171500Z-0a1b2c3d"


def _carica(nome: str, percorso: Path):
    spec = importlib.util.spec_from_file_location(nome, percorso)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nome] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def cli():
    return _carica("vps1777_cli_p16", RADICE / "tools" / "vps1777.py")


def _intent(**kw):
    d = {"id": JID, "db": "note", "suffisso": ".md", "file": "n.md", "project": "",
         "description": "", "by": "owner@example.invalid", "accodato": "2026-10-11T17:15:00Z"}
    d.update(kw)
    return d


def test_le_regole_dei_nomi_sono_le_stesse_del_gateway(cli):
    """Ricopiate e non importate (la CLI gira sull'host, il gateway nel container):
    se divergono, il gateway accoda ciò che la CLI scarta, o il contrario."""
    gw = _carica("coda_ingest_p16", RADICE / "services/gateway/app/coda_ingest.py")
    assert gw.ID_RE.pattern == cli.INGEST_ID_RE.pattern
    assert gw.DB_RE.pattern == cli.INGEST_DB_RE.pattern
    assert gw.SUFFISSI == cli.INGEST_SUFFISSI
    assert gw.TESTO_MAX == cli.INGEST_TESTO_MAX
    assert (gw.CODA, gw.ESITI) == (cli.INGEST_CODA, cli.INGEST_ESITI)


def test_un_intent_buono_passa(cli):
    assert cli.valida_intent_ingest(f"{JID}.json", _intent()) == ""


@pytest.mark.parametrize("nome,d", [
    ("x.json", _intent()),
    (f"{JID}.json", "non un dict"),
    (f"{JID}.json", _intent(id="20261011T171500Z-ffffffff")),
    (f"{JID}.json", _intent(db="../etc")),
    (f"{JID}.json", _intent(db="a b")),
    (f"{JID}.json", _intent(suffisso=".db")),
    (f"{JID}.json", _intent(suffisso="/../../x")),
    (f"{JID}.json", _intent(project="x" * 501)),
    (f"{JID}.json", _intent(description=["non", "stringa"])),
])
def test_un_intent_storto_ha_un_motivo(cli, nome, d):
    assert cli.valida_intent_ingest(nome, d)


def test_l_esito_del_container(cli):
    assert cli.esito_lavoro_ingest(0, 'letti 3\n{"righe": 3, "totale": 9}\n') == \
        {"stato": "fatto", "righe": 3, "totale": 9}
    e = cli.esito_lavoro_ingest(3, '{"errore": "formato non supportato"}')
    assert e == {"stato": "errore", "errore": "formato non supportato"}
    e = cli.esito_lavoro_ingest(137, "")
    assert e["stato"] == "errore" and cli.INGEST_TETTO in e["errore"]
    assert cli.esito_lavoro_ingest(1, "Traceback…")["errore"] == "il lavoro è uscito con 1"
    # un'uscita 0 senza la riga JSON non è un successo
    assert cli.esito_lavoro_ingest(0, "")["stato"] == "errore"


@pytest.fixture()
def giro(cli, tmp_path, monkeypatch):
    chiamate: list[list[str]] = []
    risposte: list[SimpleNamespace] = []

    def run_finto(cmd, **kw):
        chiamate.append(list(cmd))
        if "coda" in cmd and "ingest" in cmd:
            return risposte.pop(0)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cli, "run", run_finto)
    monkeypatch.setattr(cli, "compose_cmd", lambda repo: ["docker", "compose"])
    coda = tmp_path / "onboarding" / cli.INGEST_CODA
    coda.mkdir(parents=True)
    return cli, tmp_path, coda, chiamate, risposte


def _esito(repo: Path, jid: str) -> dict:
    return json.loads((repo / "onboarding" / "ingest_esiti" / f"{jid}.json").read_text())


def test_il_giro_consuma_l_intent_e_scrive_l_esito(giro):
    cli, repo, coda, chiamate, risposte = giro
    (coda / f"{JID}.json").write_text(json.dumps(_intent(project="p", description="d")))
    risposte.append(SimpleNamespace(returncode=0, stdout='{"righe": 4, "totale": 4}', stderr=""))
    assert cli.cmd_ingest_coda(repo, SimpleNamespace()) == 0
    assert not list(coda.glob("*.json")), "l'intent va consumato"
    e = _esito(repo, JID)
    assert e["stato"] == "fatto" and e["righe"] == 4 and e["db"] == "note"
    (cmd,) = [c for c in chiamate if "coda" in c]
    assert cmd[:8] == ["docker", "compose", "--profile", "ingest", "run", "--rm", "-T", "ingest"]
    assert cmd[cmd.index("--id") + 1] == JID and cmd[cmd.index("--description") + 1] == "d"


def test_i_lavori_vanno_dal_piu_vecchio(giro):
    cli, repo, coda, chiamate, risposte = giro
    nuovo = "20261011T180000Z-ffffffff"
    (coda / f"{nuovo}.json").write_text(json.dumps(_intent(id=nuovo)))
    (coda / f"{JID}.json").write_text(json.dumps(_intent()))
    for _ in range(2):
        risposte.append(SimpleNamespace(returncode=0, stdout='{"righe": 1, "totale": 1}', stderr=""))
    assert cli.cmd_ingest_coda(repo, SimpleNamespace()) == 0
    ids = [c[c.index("--id") + 1] for c in chiamate if "coda" in c]
    assert ids == [JID, nuovo]


def test_un_intent_storto_si_consuma_e_si_dice(giro):
    cli, repo, coda, chiamate, risposte = giro
    (coda / f"{JID}.json").write_text(json.dumps(_intent(db="../x")))
    assert cli.cmd_ingest_coda(repo, SimpleNamespace()) == 1
    assert not list(coda.glob("*.json"))
    assert _esito(repo, JID)["stato"] == "errore"
    assert not [c for c in chiamate if "coda" in c], "un intent storto non lancia niente"


def test_un_rifiuto_parlante_non_e_un_guasto_della_unit(giro):
    cli, repo, coda, chiamate, risposte = giro
    (coda / f"{JID}.json").write_text(json.dumps(_intent()))
    risposte.append(SimpleNamespace(returncode=3, stdout='{"errore": "PDF senza testo"}', stderr=""))
    assert cli.cmd_ingest_coda(repo, SimpleNamespace()) == 0
    assert _esito(repo, JID)["errore"] == "PDF senza testo"


def test_un_lavoro_ucciso_dal_tetto_si_dice_e_si_pulisce(giro):
    cli, repo, coda, chiamate, risposte = giro
    (coda / f"{JID}.json").write_text(json.dumps(_intent(suffisso=".zip")))
    risposte.append(SimpleNamespace(returncode=137, stdout="", stderr=""))
    assert cli.cmd_ingest_coda(repo, SimpleNamespace()) == 1
    assert "tetto di memoria" in _esito(repo, JID)["errore"]
    rm = [c for c in chiamate if "rm" in c]
    assert rm and rm[0][-1] == f"/var/lib/archive/coda/{JID}.zip"


def test_gli_esiti_si_potano(giro):
    cli, repo, coda, chiamate, risposte = giro
    esiti = repo / "onboarding" / cli.INGEST_ESITI
    esiti.mkdir()
    for i in range(cli.INGEST_ESITI_MAX + 5):
        (esiti / f"20261011T{i:06d}Z-00000000.json").write_text("{}")
    cli.cmd_ingest_coda(repo, SimpleNamespace())
    assert len(list(esiti.glob("*.json"))) == cli.INGEST_ESITI_MAX


def test_la_path_unit_guarda_la_coda_e_lancia_il_comando():
    path = (RADICE / "systemd/vps1777-ingest.path").read_text(encoding="utf-8")
    righe = [r for r in path.splitlines() if not r.startswith("#")]
    assert "DirectoryNotEmpty=@REPO@/onboarding/ingest_coda" in righe
    assert "Unit=vps1777-ingest.service" in righe
    # creata da PID 1 sarebbe di root, e il gateway non ci scriverebbe più
    assert not [r for r in righe if r.startswith("MakeDirectory")]
    serv = (RADICE / "systemd/vps1777-ingest.service").read_text(encoding="utf-8")
    assert "ExecStart=/usr/local/bin/vps1777 ingest-coda" in serv
    assert "User=@OPERATOR_USER@" in serv


def test_la_cli_accende_la_path_unit_anche_a_chi_aggiorna(cli):
    src = (RADICE / "tools/vps1777.py").read_text(encoding="utf-8")
    corpo = src[src.index("def install_systemd_units("):src.index("INGEST_PATH = ")]
    assert "INGEST_PATH]" in corpo, "l'install la deve abilitare"
    assert '"enable", "--now", INGEST_PATH' in corpo, "e anche l'update"
    assert cli.INGEST_PATH == "vps1777-ingest.path"


def _servizi():
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load((RADICE / "compose.yaml").read_text(encoding="utf-8"))["services"]


def test_il_servizio_ingest_ha_il_suo_tetto_e_niente_segreti():
    s = _servizi()["ingest"]
    assert s["profiles"] == ["ingest"] and s["restart"] == "no"
    assert s["mem_limit"] == "2g" and s["memswap_limit"] == "2g"
    assert "secrets" not in s
    assert s["volumes"] == ["archive-data:/var/lib/archive:rw"], \
        "solo il volume dell'archivio: niente onboarding, niente audit del gateway"
    assert "ports" not in s
    assert s["entrypoint"][-1] == "app.ingest_worker"


def test_il_gateway_ha_un_tetto_e_la_coda_accesa():
    g = _servizi()["gateway"]
    assert g["mem_limit"] == "512m" and g["memswap_limit"] == "512m"
    assert g["environment"]["ARCHIVE_INGEST_CODA"] == "true"


def test_i_comandi_che_riscrivono_un_db_non_girano_nel_gateway():
    src = (RADICE / "tools/vps1777.py").read_text(encoding="utf-8")
    for nome in ("def cmd_archive_migra(", "def _archive_migra_telegram(", "def cmd_archive_retag("):
        i = src.index(nome)
        corpo = src[i:src.index("\ndef ", i + 10)]
        assert not re.search(r'"exec", "-T", "gateway", "python"', corpo), nome
        assert "INGEST_RUN" in corpo, nome


def test_quello_che_non_e_un_intent_esce_dalla_coda(giro):
    """La path unit scatta su «cartella non vuota»: un file estraneo lasciato lì la farebbe
    ripartire a vuoto senza fine."""
    cli, repo, coda, chiamate, risposte = giro
    (coda / ".orfano.json.tmp").write_text("{")
    (coda / "x.txt").write_text("?")
    assert cli.cmd_ingest_coda(repo, SimpleNamespace()) == 0
    assert not list(coda.iterdir())
