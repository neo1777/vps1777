"""SIC-15: il puntatore all'ultima release è firmato e ha una scadenza, e l'aggiornamento
automatico si ferma se non è fresco.

Le firme sono vere (openssl, chiave usa-e-getta generata da `tools/canale-genera.py prova`): qui non
si finge la crittografia. Ciò che si finge è la rete (chi scarica il canale) e Telegram.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import shutil
from pathlib import Path

import pytest
import yaml

RADICE = Path(__file__).resolve().parents[2]


def _carica(nome: str, file: str):
    spec = importlib.util.spec_from_file_location(nome, RADICE / "tools" / file)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


cli = _carica("vps1777_cli_canale", "vps1777.py")
genera = _carica("canale_genera", "canale-genera.py")
pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl assente")
ORA = dt.datetime.now(dt.timezone.utc)


@pytest.fixture(scope="module")
def prova(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("canale")
    genera.prova(d, adesso=ORA)
    return d


def _giudica(d: Path, nome: str, **kw):
    return cli.canale_verifica(d / nome, chiave_pubblica=d / "chiave.pub", **kw)


def _variante(d: Path, nome: str, cambia) -> str:
    """Un canale ricavato dal fresco, con la FIRMA DEL FRESCO copiata accanto (non rifirmato)."""
    dati = json.loads((d / "fresco.json").read_text(encoding="utf-8"))
    cambia(dati)
    (d / nome).write_text(json.dumps(dati) + "\n", encoding="utf-8")
    shutil.copy(d / "fresco.json.sig", d / (nome + ".sig"))
    return nome


def test_la_chiave_privata_di_prova_non_resta_sul_disco(prova):
    assert sorted(p.name for p in prova.iterdir() if p.name.startswith(("chiave", "fresco", "scaduto"))) == \
        ["chiave.pub", "fresco.json", "fresco.json.sig", "scaduto.json", "scaduto.json.sig"]


def test_il_fresco_e_accettato(prova):
    esito, motivo, dati = _giudica(prova, "fresco.json")
    assert esito is True and dati["latest"] == "9.9.9" and "valido fino al" in motivo


def test_lo_scaduto_e_rifiutato_e_lo_dice(prova):
    esito, motivo, dati = _giudica(prova, "scaduto.json")
    assert esito is False and dati is None and cli.CANALE_SCADUTO in motivo


def test_la_scadenza_allungata_senza_rifirmare_cade_sulla_firma(prova):
    """Dentro il tetto di vita, così non la ferma il controllo di forma: deve fermarla la FIRMA."""
    def piu_cinque(d):
        d["scade_il"] = (dt.datetime.fromisoformat(d["scade_il"]) + dt.timedelta(days=5)).isoformat()
    esito, motivo, _ = _giudica(prova, _variante(prova, "allungato.json", piu_cinque))
    assert esito is False and "firma non corrisponde" in motivo


def test_lo_scaduto_ringiovanito_senza_rifirmare_cade_sulla_firma(prova):
    dati = json.loads((prova / "scaduto.json").read_text(encoding="utf-8"))
    dati["firmato_il"] = (ORA - dt.timedelta(days=1)).replace(microsecond=0).isoformat()
    dati["scade_il"] = (ORA + dt.timedelta(days=30)).replace(microsecond=0).isoformat()
    (prova / "ringiovanito.json").write_text(json.dumps(dati) + "\n", encoding="utf-8")
    shutil.copy(prova / "scaduto.json.sig", prova / "ringiovanito.json.sig")
    esito, motivo, _ = _giudica(prova, "ringiovanito.json")
    assert esito is False and "firma" in motivo


def test_un_altra_versione_con_la_firma_del_fresco_cade_sulla_firma(prova):
    esito, _, _ = _giudica(prova, _variante(prova, "altra.json", lambda d: d.update(latest="0.0.1")))
    assert esito is False


@pytest.mark.parametrize("cambia, perche", [
    (lambda d: d.pop("scade_il"), "manca `scade_il`"),
    (lambda d: d.pop("firmato_il"), "manca `firmato_il`"),
    (lambda d: d.update(scade_il="domani"), "non è una data"),
    (lambda d: d.update(scade_il="2099-01-01T00:00:00"), "senza fuso"),
    (lambda d: d.update(scade_il="2999-01-01T00:00:00+00:00"), "oltre 60 giorni"),
    (lambda d: d.update(scade_il=d["firmato_il"]), "non viene dopo"),
    (lambda d: d.update(latest="l'ultima"), "non è una versione"),
    (lambda d: d.update(schema=2), "schema sconosciuto"),
])
def test_le_forme_sbagliate_sono_rifiutate_col_motivo(prova, cambia, perche):
    esito, motivo, _ = _giudica(prova, _variante(prova, "forma.json", cambia))
    assert esito is False and perche in motivo, motivo


def test_cio_che_non_e_un_oggetto_json_e_rifiutato(prova):
    for testo in ("[1, 2]", "non json", ""):
        (prova / "strano.json").write_text(testo, encoding="utf-8")
        shutil.copy(prova / "fresco.json.sig", prova / "strano.json.sig")
        assert _giudica(prova, "strano.json")[0] is False


def test_senza_firma_accanto_e_rifiutato(prova):
    shutil.copy(prova / "fresco.json", prova / "nudo.json")
    esito, motivo, _ = _giudica(prova, "nudo.json")
    assert esito is False and "manca la firma" in motivo


def test_un_file_che_non_c_e_e_non_ho_potuto_guardare(prova):
    assert _giudica(prova, "assente.json")[0] is None


def test_firmato_nel_futuro_e_rifiutato(prova):
    esito, motivo, _ = _giudica(prova, "fresco.json", adesso=ORA - dt.timedelta(days=3))
    assert esito is False and "nel futuro" in motivo


def test_senza_chiave_di_prova_si_pretende_la_firma_del_workflow(prova):
    """La via dell'updater: niente chiave, quindi certificato keyless e cosign. Il file di prova
    non ha il certificato: rifiutato. E l'identità attesa è il workflow del canale su main."""
    esito, motivo, _ = cli.canale_verifica(prova / "fresco.json")
    assert esito is False and "certificato" in motivo
    assert cli.CANALE_IDENTITA.endswith(r"/\.github/workflows/canale\.yml@refs/heads/main$")


def test_il_comando_esce_0_1_2(prova, capsys):
    def lancia(nome, chiave="chiave.pub"):
        return cli.cmd_canale_verifica(prova, argparse.Namespace(
            canale=str(prova / nome), chiave_pubblica=str(prova / chiave)))
    assert lancia("fresco.json") == 0
    assert lancia("scaduto.json") == 1
    assert cli.CANALE_SCADUTO in capsys.readouterr().out
    assert lancia("fresco.json", chiave="chiave-che-non-c-e.pub") == 2
    assert lancia("assente.json") == 2


# ── l'aggiornamento automatico ────────────────────────────────────────────────────────────────
def test_canale_per_update_riprova_una_volta_e_poi_dice_perche(prova, monkeypatch):
    chiamate = []

    def scarica(repo):
        chiamate.append(1)
        raise OSError("rete assente")
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    dati, perche = cli.canale_per_update(prova, scarica=scarica)
    assert dati is None and "non scaricabile" in perche and len(chiamate) == 2


def test_canale_per_update_non_riprova_uno_scaduto(prova, monkeypatch):
    chiamate = []
    monkeypatch.setattr(cli.time, "sleep", lambda s: chiamate.append("pausa"))
    monkeypatch.setattr(cli, "canale_verifica", lambda path, cosign=None: (False, cli.CANALE_SCADUTO + " il …", None))
    monkeypatch.setattr(cli.shutil, "which", lambda nome: "/usr/bin/" + nome)
    dati, perche = cli.canale_per_update(prova, scarica=lambda repo: prova / "scaduto.json")
    assert dati is None and cli.CANALE_SCADUTO in perche and chiamate == []


def test_l_update_automatico_guarda_il_canale_prima_di_dirsi_aggiornato():
    """Il congelamento è la risposta «l'ultima è quella che hai»: il controllo del canale deve stare
    PRIMA dell'uscita «già aggiornato», e solo sul percorso automatico e sul canale stabile."""
    testo = (RADICE / "tools" / "vps1777.py").read_text(encoding="utf-8")
    corpo = testo[testo.index("def cmd_update("):testo.index("# ─── PUNTO DI NON RITORNO ───")]
    assert corpo.index("canale_per_update(repo)") < corpo.index('ok(f"già aggiornato (v{target})")')
    riga = next(r for r in corpo.split("\n") if "canale_per_update" in corpo and 'getattr(args, "eta_minima", None)' in r
                and "release_channel" in r)
    assert "not target_req" in riga and '== "stable"' in riga
    fermo = corpo[corpo.index("if canale is None:"):corpo.index('st["canale"] = {"esito": "ok"')]
    assert "telegram_notify(" in fermo and "return 0" in fermo and "A mano resta possibile" in fermo


def test_il_giudizio_di_un_canale_non_manda_avvisi_di_guasto():
    testo = (RADICE / "tools" / "vps1777.py").read_text(encoding="utf-8")
    assert 'giudizio = len(sys.argv) > 1 and "canale-verifica" in sys.argv[1:3]' in testo
    assert "if codice != 0 and not sotto_systemd and not giudizio:" in testo


def test_il_canale_prerelease_non_scambia_la_release_fissa_per_una_versione():
    testo = (RADICE / "tools" / "vps1777.py").read_text(encoding="utf-8")
    assert 'if str(r.get("tag_name", "")).startswith("v")]' in testo


# ── chi firma ─────────────────────────────────────────────────────────────────────────────────
def test_il_canale_generato_passa_la_lettura_del_client(tmp_path):
    f = tmp_path / "canale.json"
    f.write_text(genera.canale("1.2.3", adesso=ORA), encoding="utf-8")
    dati = cli.canale_leggi(f)
    vita = dt.datetime.fromisoformat(dati["scade_il"]) - dt.datetime.fromisoformat(dati["firmato_il"])
    assert dati["latest"] == "1.2.3" and vita == dt.timedelta(days=45)


@pytest.mark.parametrize("latest, giorni", [("1.2", 45), ("1.2.3-rc.1", 45), ("1.2.3", 0), ("1.2.3", 61)])
def test_chi_genera_rifiuta_versioni_non_stabili_e_vite_fuori_misura(latest, giorni):
    with pytest.raises(ValueError):
        genera.canale(latest, adesso=ORA, giorni=giorni)
    assert genera.main(["genera", "--latest", latest, "--giorni", str(giorni)]) == 2


def test_il_workflow_firma_pubblica_e_rilegge():
    wf_testo = (RADICE / ".github" / "workflows" / "canale.yml").read_text(encoding="utf-8")
    wf = yaml.safe_load(wf_testo)
    on = wf[True]
    assert "schedule" in on and "workflow_dispatch" in on
    job = wf["jobs"]["firma"]
    assert wf["permissions"] == {} and job["permissions"] == {"contents": "write", "id-token": "write"}
    for pezzo in ("python3 tools/canale-genera.py genera --latest", "cosign sign-blob --yes",
                  "--exclude-pre-releases", "gh release upload canale", "--clobber",
                  "cosign verify-blob", "canale\\.yml@refs/heads/main"):
        assert pezzo in wf_testo, pezzo
    # un rinfresco a settimana contro 45 giorni di vita: ne possono saltare cinque
    assert on["schedule"][0]["cron"].split()[4] != "*"


def test_il_rilascio_rinfresca_il_canale_appena_pubblica():
    testo = (RADICE / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "gh workflow run canale.yml --ref main" in testo
