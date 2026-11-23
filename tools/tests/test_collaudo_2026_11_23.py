"""I difetti trovati dal collaudo su macchina vergine del 23/11/2026, ognuno col suo test.

Il referto è docs/collaudi/2026-11-23.yml. Qui si tiene fermo ciò che quel giorno si è visto
rompersi su una macchina vera, perché nessun test lo esercitava.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parents[2]


@pytest.fixture()
def cli():
    spec = importlib.util.spec_from_file_location("vps1777_collaudo", RADICE / "tools" / "vps1777.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _installazione(tmp_path: Path, token: str | None, chiave: str | None) -> Path:
    repo = tmp_path / "repo"
    (repo / "secrets").mkdir(parents=True)
    (repo / "compose.yaml").write_text(
        "services:\n  bot:\n    image: x\n    secrets: [telegram_bot_token, telegram_webapp_secret, gateway_secret]\n"
        "secrets:\n  telegram_bot_token:\n    file: ./secrets/telegram_bot_token.txt\n"
        "  telegram_webapp_secret:\n    file: ./secrets/telegram_webapp_secret.txt\n"
        "  gateway_secret:\n    file: ./secrets/gateway_secret.txt\n", encoding="utf-8")
    (repo / "secrets" / "gateway_secret.txt").write_text("valore\n")
    for nome, v in (("telegram_bot_token", token), ("telegram_webapp_secret", chiave)):
        if v is not None:
            (repo / "secrets" / f"{nome}.txt").write_text(v)
    return repo


def test_il_bot_in_attesa_non_ferma_piu_l_update(cli, tmp_path):
    """Il difetto: installato senza token (caso ammesso dagli installatori), l'updater diceva
    «segreti VUOTI, lo stack non partirebbe» e si fermava a ogni update."""
    repo = _installazione(tmp_path, token="", chiave="\n")
    grezzi = cli._secrets_mancanti([repo / "compose.yaml"], repo)
    assert len(grezzi) == 2 and all("[VUOTO" in m for m in grezzi), grezzi   # è ciò che fermava
    veri, in_attesa = cli._senza_bot_in_attesa(grezzi)
    assert veri == [] and in_attesa is True


def test_solo_il_bot_e_solo_se_vuoto(cli, tmp_path):
    # un altro segreto vuoto resta un guasto, anche col bot in attesa
    repo = _installazione(tmp_path, token="", chiave="")
    (repo / "secrets" / "gateway_secret.txt").write_text("")
    veri, in_attesa = cli._senza_bot_in_attesa(cli._secrets_mancanti([repo / "compose.yaml"], repo))
    assert in_attesa is True and len(veri) == 1 and veri[0].startswith("gateway_secret")
    # il file del token che MANCA non è «in attesa»: è un segreto perso
    repo2 = _installazione(tmp_path / "b", token=None, chiave="")
    grezzi = cli._secrets_mancanti([repo2 / "compose.yaml"], repo2)
    veri, in_attesa = cli._senza_bot_in_attesa(grezzi)
    assert in_attesa is False and veri == grezzi and len(veri) == 2
    # token presente e chiave vuota: la chiave resta segnalata (non è l'installazione senza bot)
    repo3 = _installazione(tmp_path / "c", token="123456:" + "x" * 35, chiave="")
    veri, in_attesa = cli._senza_bot_in_attesa(cli._secrets_mancanti([repo3 / "compose.yaml"], repo3))
    assert in_attesa is False and len(veri) == 1 and veri[0].startswith("telegram_webapp_secret")
    # niente da togliere: la lista torna com'è
    assert cli._senza_bot_in_attesa([]) == ([], False)


def test_l_update_usa_il_filtro_nei_due_controlli(cli):
    import inspect
    src = inspect.getsource(cli.cmd_update)
    assert src.count("_senza_bot_in_attesa(") == 2, "il filtro va sia sul controllo che ferma sia sull'avviso"
    assert "il bot resta in attesa" in src


def test_l_aggancio_di_collaudo_scatta_una_volta_sola(cli, tmp_path, monkeypatch):
    """Il difetto: forzava a «no» anche il controllo DOPO il rollback, e l'update usciva 2
    («serve intervento») su un rollback riuscito."""
    monkeypatch.setenv("VPS1777_COLLAUDO_HEALTH_KO", "1")
    monkeypatch.setattr(cli, "_COLLAUDO_KO_USATO", False)
    sano = [{"Service": "gateway", "State": "running", "Health": "healthy"}]
    monkeypatch.setattr(cli, "compose_ps", lambda *a, **k: sano)
    monkeypatch.setattr(cli, "restart_counts", lambda *a, **k: {})
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    primo = cli.health_gate(tmp_path)
    assert primo[0] is False and "collaudo" in primo[1]
    secondo = cli.health_gate(tmp_path, window_s=1)
    assert "collaudo" not in secondo[1], "il secondo controllo deve misurare davvero, non ripetere il no forzato"


def test_dopo_un_auto_rollback_la_precedente_e_quella_di_prima(cli):
    """Il difetto: allo step 10 «precedente» diventa la versione corrente; tornando indietro
    restavano uguali (0.98.5 e 0.98.5) e la 0.98.4 era persa."""
    st = {"current": "0.98.5", "previous": "0.98.5", "previous_images": {"gateway": "img-0.98.5"},
          "update_in_progress": {"target": "0.98.6", "step": 10,
                                 "prima": {"previous": "0.98.4", "previous_images": {"gateway": "img-0.98.4"}}}}
    cli._rimetti_precedente(st)
    assert st["previous"] == "0.98.4" and st["previous_images"] == {"gateway": "img-0.98.4"}
    # un update interrotto di una versione che non teneva da parte niente: non si inventa
    vecchio = {"current": "0.98.5", "previous": "0.98.5", "update_in_progress": {"target": "0.98.6", "step": 10}}
    cli._rimetti_precedente(vecchio)
    assert vecchio["previous"] == "0.98.5"
    import inspect
    assert '"prima": prima' in inspect.getsource(cli.cmd_update)
    assert "_rimetti_precedente(st)" in inspect.getsource(cli._rollback_routine)


def test_il_referto_del_collaudo_ha_i_campi_che_servono():
    yaml = pytest.importorskip("yaml")
    referti = sorted((RADICE / "docs" / "collaudi").glob("*.yml"))
    assert referti, "nessun referto in docs/collaudi/"
    d = yaml.safe_load(referti[-1].read_text(encoding="utf-8"))
    for campo in ("data", "macchina", "non_misura", "rto", "rpo"):
        assert str(d.get(campo) or "").strip(), f"{referti[-1].name}: manca «{campo}»"
    assert referti[-1].stem == str(d["data"]), "il nome del file è la data del collaudo"
    testo = referti[-1].read_text(encoding="utf-8")
    import re
    assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", testo), "niente indirizzi IP nel referto pubblico"
    assert ".ts.net" not in testo


def test_il_referto_delle_prove_resta_del_proprietario_della_cartella():
    testo = (RADICE / "tools" / "prove-empiriche" / "lancia-tutte.sh").read_text(encoding="utf-8")
    assert 'chown --reference="$(dirname "$FUORI")" "$FUORI"' in testo
