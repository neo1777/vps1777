"""`cmd_bootstrap`: il passaggio di un'installazione vecchia (immagini costruite in loco) al canale
degli aggiornamenti, strada per strada (25/11/2026).

Prima di spezzarla (QUA-04) nessuna prova la chiamava. È un salto che si fa una volta sola e su una
macchina vera, quindi ogni uscita ha la sua prova: lucchetto occupato, già a regime, pacchetto che
non si trova, Docker spento, il no di chi lancia, scaricamento fallito (niente è stato fermato),
cutover non sano (torna lo stack di prima). I collaboratori sono finti e scrivono in `ev`.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("vps1777_cli_bootstrap", _ROOT / "tools" / "vps1777.py")
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)

BASE = "registro.example.invalid/casa"


@pytest.fixture
def banco(tmp_path, monkeypatch):
    repo, bundle = tmp_path / "repo", tmp_path / "bundle"
    (repo / "tools").mkdir(parents=True)
    (bundle / "tools").mkdir(parents=True)
    (bundle / "tools" / "vps1777.py").write_text("# cli\n")
    (bundle / "tools" / "backup.sh").write_text("# backup del bundle\n")
    (bundle / "VERSION").write_text("v2.0.0\n")
    (bundle / "bundle-manifest.json").write_text("{}")
    (bundle / "images.lock").write_text(json.dumps({"gateway": f"{BASE}/vps1777-gateway@sha256:aa"}))
    (repo / "compose.yaml").write_text("di prima")
    b = SimpleNamespace(repo=repo, bundle=bundle, ev=[], st={"history": []}, env={}, lock=object(),
                        rc={}, sano=(True, ""), risposta="s", reg={"applied": []}, scritti={},
                        args=SimpleNamespace(bundle=str(bundle), yes=True))

    def run(cmd, **kw):
        chi = ("info" if cmd[:2] == ["docker", "info"] else "backup" if cmd[0] == "bash"
               else cmd[-1] if cmd[-1] in ("pull", "down") else "up")
        b.ev.append((chi, cmd, kw.get("env")))
        return SimpleNamespace(returncode=b.rc.get(chi, 0))

    def sync(repo_, _bundle):
        b.ev.append(("sync",))
        (repo_ / "compose.yaml").write_text("del pacchetto")

    def nota(nome, ritorno=None):
        return lambda *a, **_k: (b.ev.append((nome, *a)), ritorno() if callable(ritorno) else ritorno)[1]

    monkeypatch.setattr(v, "acquire_lock", lambda _r: b.lock)
    monkeypatch.setattr(v, "state_load", lambda _r: b.st)
    monkeypatch.setattr(v, "current_version", lambda _r: "dev")
    monkeypatch.setattr(v, "run", run)
    monkeypatch.setattr(v, "sudo", lambda cmd, **_k: b.ev.append(("sudo", cmd[0])))
    monkeypatch.setattr(v, "sync_managed_files", sync)
    monkeypatch.setattr(v, "install_systemd_units", nota("units"))
    monkeypatch.setattr(v, "env_read", lambda _r: dict(b.env))
    monkeypatch.setattr(v, "env_set", nota("env_set"))
    monkeypatch.setattr(v, "versione_set", nota("versione_set"))
    monkeypatch.setattr(v, "versione_env", lambda tag, rif: {"TAG": tag, "PIN": bool(rif)})
    monkeypatch.setattr(v, "compose_cmd", lambda _r, **_k: ["docker", "compose"])
    monkeypatch.setattr(v, "verify_digests", nota("digests"))
    monkeypatch.setattr(v, "immagini_attive", lambda *_a, **_k: {"gateway"})
    monkeypatch.setattr(v, "permessi_servizi", nota("permessi"))
    monkeypatch.setattr(v, "health_gate", nota("health", lambda: b.sano))
    monkeypatch.setattr(v, "telegram_notify", nota("telegram", True))
    monkeypatch.setattr(v, "registry_read", lambda: json.loads(json.dumps(b.reg)))
    monkeypatch.setattr(v, "_registry_write", lambda dati: b.scritti.__setitem__("reg", dati))
    monkeypatch.setattr(v, "state_save", lambda _r, st: b.scritti.__setitem__("st", json.loads(json.dumps(st))))
    monkeypatch.setattr(v, "now_iso", lambda: "ORA")
    monkeypatch.setattr("builtins.input", lambda _p="": (b.ev.append(("input",)), b.risposta)[1])
    for nome in ("log", "ok", "warn"):
        monkeypatch.setattr(v, nome, lambda t, _n=nome: b.ev.append((_n, str(t))))
    b.gira = lambda: v.cmd_bootstrap(repo, b.args)
    b.passi = lambda: [e[0] for e in b.ev if e[0] not in ("log", "ok", "warn")]
    return b


def _esce(b, codice):
    with pytest.raises(SystemExit) as e:
        b.gira()
    assert e.value.code == codice


def test_il_buon_fine_va_in_ordine_e_lascia_stato_e_paracadute(banco):
    assert banco.gira() == 0
    assert banco.passi() == [
        "info", "backup", "sudo", "sudo", "sync", "units", "env_set", "versione_set",
        "pull", "digests", "versione_set", "permessi", "up", "health", "telegram"]
    # il paracadute tiene i compose di PRIMA, non quelli che il pacchetto ha appena portato
    assert (banco.repo / "releases" / "pre-bootstrap" / "compose.yaml").read_text() == "di prima"
    assert (banco.repo / "compose.yaml").read_text() == "del pacchetto"
    for cartella in ("onboarding", "var", "backups", "releases"):
        assert (banco.repo / cartella).is_dir()
    assert (banco.repo / "var").stat().st_mode & 0o777 == 0o700
    st = banco.scritti["st"]
    assert (st["current"], st["previous"], st["bootstrap"]) == ("2.0.0", None, True)
    assert st["history"] == [{"event": "bootstrap", "from": "dev", "to": "2.0.0", "at": "ORA"}]


def test_lo_scaricamento_va_per_tag_e_l_avvio_col_pin(banco):
    banco.gira()
    per_passo = {e[0]: e for e in banco.ev if e[0] in ("pull", "up")}
    assert per_passo["pull"][2] == {"TAG": "2.0.0", "PIN": False}
    assert per_passo["up"][2] == {"TAG": "2.0.0", "PIN": True}
    versioni = [e[2:] for e in banco.ev if e[0] == "versione_set"]
    assert versioni[0] == ("2.0.0", None) and versioni[1][0] == "2.0.0" and versioni[1][1]


def test_il_backup_di_prima_e_completo_e_usa_lo_script_del_repo_se_c_e(banco):
    banco.gira()
    comando = next(e[1] for e in banco.ev if e[0] == "backup")
    assert comando == ["bash", str(banco.bundle / "tools" / "backup.sh"), "--archivio"]
    banco.ev.clear()
    banco.st = {"history": []}
    (banco.repo / "tools" / "backup.sh").write_text("# backup del repo\n")
    banco.gira()
    assert next(e[1] for e in banco.ev if e[0] == "backup")[1] == str(banco.repo / "tools" / "backup.sh")


def test_la_base_delle_immagini_si_deduce_dal_lock_solo_se_manca(banco):
    banco.gira()
    assert [e[2:] for e in banco.ev if e[0] == "env_set"] == [("VPS1777_IMAGE_BASE", BASE)]
    banco.ev.clear()
    banco.st, banco.env = {"history": []}, {"VPS1777_IMAGE_BASE": "già.scritta.example.invalid"}
    banco.gira()
    assert "env_set" not in banco.passi()


def test_un_secondo_tentativo_non_riscrive_il_paracadute(banco):
    pre = banco.repo / "releases" / "pre-bootstrap"
    pre.mkdir(parents=True)
    (pre / "compose.yaml").write_text("del primo tentativo")
    (banco.repo / "compose.yaml").write_text("già mutato dal primo tentativo")
    banco.gira()
    assert (pre / "compose.yaml").read_text() == "del primo tentativo"
    assert any(e[0] == "log" and "ri-tentativo" in e[1] for e in banco.ev)


def test_un_paracadute_vuoto_si_riempie(banco):
    (banco.repo / "releases" / "pre-bootstrap").mkdir(parents=True)
    banco.gira()
    assert (banco.repo / "releases" / "pre-bootstrap" / "compose.yaml").read_text() == "di prima"


def test_le_migrazioni_del_pacchetto_entrano_come_gia_applicate_una_volta_sola(banco):
    mig = banco.repo / "migrations"
    for nome in ("001-a", "002-b"):
        (mig / nome).mkdir(parents=True)
        (mig / nome / "migration.json").write_text(json.dumps({"id": nome}))
        (mig / nome / "run.py").write_text(f"# {nome}\n")
    (mig / "senza-scheda").mkdir()
    (mig / "LEGGIMI.md").write_text("non è una migrazione")
    banco.reg = {"applied": [{"id": "001-a"}]}
    banco.gira()
    assert banco.scritti["reg"]["applied"] == [
        {"id": "001-a"},
        {"id": "002-b", "version": "2.0.0", "applied_at": "ORA", "baseline": True,
         "checksum": hashlib.sha256(b"# 002-b\n").hexdigest()}]


def test_senza_cartella_delle_migrazioni_il_registro_resta_com_era(banco):
    banco.reg = {"applied": [{"id": "x"}]}
    banco.gira()
    assert banco.scritti["reg"] == {"applied": [{"id": "x"}]}


def test_gia_a_regime_non_tocca_niente(banco):
    banco.st = {"current": "1.0.0", "history": []}
    assert banco.gira() == 0
    assert banco.passi() == [] and banco.scritti == {}


def test_il_lucchetto_occupato_esce_col_suo_codice(banco):
    banco.lock = None
    _esce(banco, v.ESITO_LOCK_OCCUPATO)
    assert banco.passi() == []


def test_il_pacchetto_che_non_si_trova_ferma_prima_di_tutto(banco, monkeypatch, tmp_path):
    monkeypatch.setattr(v, "__file__", str(tmp_path / "altrove" / "tools" / "vps1777.py"))
    banco.args.bundle = None
    _esce(banco, 1)
    banco.args.bundle = str(tmp_path / "vuota")
    _esce(banco, 1)
    assert banco.passi() == []


def test_senza_bundle_passato_vale_la_cartella_da_cui_gira_lo_script(banco, monkeypatch):
    monkeypatch.setattr(v, "__file__", str(banco.bundle / "tools" / "vps1777.py"))
    banco.args.bundle = None
    assert banco.gira() == 0
    assert banco.scritti["st"]["current"] == "2.0.0"


def test_docker_spento_ferma_prima_del_backup(banco):
    banco.rc["info"] = 1
    _esce(banco, 1)
    assert banco.passi() == ["info"]


@pytest.mark.parametrize("risposta, prosegue", [("s", True), (" SI ", True), ("yes", True), ("y", True),
                                                ("n", False), ("", False), ("forse", False)])
def test_senza_yes_si_chiede_e_solo_un_si_prosegue(banco, risposta, prosegue):
    banco.args.yes, banco.risposta = False, risposta
    if prosegue:
        assert banco.gira() == 0
    else:
        _esce(banco, 1)
        assert banco.passi() == ["info", "input"]


def test_con_yes_non_si_chiede(banco):
    banco.gira()
    assert "input" not in banco.passi()


def test_lo_scaricamento_fallito_non_ferma_niente(banco):
    banco.rc["pull"] = 1
    _esce(banco, 1)
    assert banco.passi()[-1] == "pull"
    assert "st" not in banco.scritti and "reg" not in banco.scritti


def test_il_cutover_non_sano_rimette_lo_stack_di_prima(banco):
    banco.sano = (False, "gateway non risponde")
    _esce(banco, 2)
    coda = banco.passi()[banco.passi().index("health"):]
    assert coda == ["health", "down", "versione_set", "permessi", "up", "telegram"]
    assert (banco.repo / "compose.yaml").read_text() == "di prima"
    assert [e[2:] for e in banco.ev if e[0] == "versione_set"][-1] == ("dev", None)
    assert [e for e in banco.ev if e[0] == "up"][-1][2] == {"TAG": "dev", "PIN": False}
    assert "gateway non risponde" in next(e[2] for e in banco.ev if e[0] == "telegram")
    assert banco.scritti == {}


def test_l_avvio_fallito_non_interroga_la_salute_e_ripristina(banco):
    banco.rc["up"] = 1
    _esce(banco, 2)
    assert "health" not in banco.passi()
    assert "down" in banco.passi()
    assert "up fallito" in next(e[2] for e in banco.ev if e[0] == "telegram")
