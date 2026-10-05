"""P11 (05/10/2026): la pagina Salute — ogni sorveglianza in un posto, con «misurato il».

Le sorveglianze del timer giornaliero (raggiungibilità, backup notturno e d'archivio,
copertura, disco) vivevano in `var/state.json` e arrivavano solo come messaggi Telegram
quando cambiavano: lo stato non si vedeva da nessuna parte. Ora `vps1777 check` scrive
`onboarding/salute.json`, una riga per voce con stato e data della misura, più la sessione
Google (la sonda di nb1777) e la memoria dei container (picco e OOM del cgroup, non un
`docker stats` una volta al giorno). `/admin/salute` la legge.
"""
from __future__ import annotations

import importlib.util
import json
from collections import namedtuple
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("vps1777_cli_salute", _ROOT / "tools" / "vps1777.py")
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)

_Disco = namedtuple("_Disco", "total used free")


def _prepara(monkeypatch, tmp_path, **kw):
    (tmp_path / "onboarding").mkdir()
    (tmp_path / "onboarding" / "raggiungibilita.json").write_text(json.dumps(
        {"ok": kw.get("raggiungibile", True), "dettaglio": "porta e funnel ok",
         "checked_at": "2026-10-05T03:00:00Z"}))
    monkeypatch.setattr(v, "onboarding_dir", lambda repo: tmp_path / "onboarding")
    monkeypatch.setattr(v, "eta_backup_notturno", lambda repo: kw.get("notturno", 0))
    monkeypatch.setattr(v, "eta_backup_archivio", lambda repo: kw.get("archivio", 3))
    monkeypatch.setattr(v.shutil, "disk_usage", lambda p: _Disco(100, 100 - kw.get("libero", 50), kw.get("libero", 50)))
    monkeypatch.setattr(v, "_sessione_da_nb1777", lambda repo: kw.get("sessione", {
        "nata_il": "2026-10-02T10:19:07Z", "ultimo_refresh": "2026-10-05T00:34:00Z",
        "sonda": {"quando": "2026-10-05T17:12:13Z", "esito": "ok"}}))
    monkeypatch.setattr(v, "memoria_container", lambda repo: kw.get("memoria", [
        {"nome": "vps1777-gateway-1", "picco_mb": 180, "tetto_mb": None, "oom_kill": 0}]))


def _voci(tmp_path) -> dict:
    dati = json.loads((tmp_path / "onboarding" / "salute.json").read_text())
    assert dati["checked_at"]
    return {r["voce"]: r for r in dati["righe"]}


def test_tutto_bene_e_ogni_riga_ha_la_sua_data(monkeypatch, tmp_path):
    _prepara(monkeypatch, tmp_path)
    v.scrivi_salute(tmp_path, {})
    voci = _voci(tmp_path)
    assert set(voci) >= {"raggiungibilità", "backup notturno", "backup archivio",
                         "copertura dei backup", "disco", "sessione Google",
                         "memoria vps1777-gateway-1"}
    assert all(r["stato"] == "ok" for r in voci.values()), voci
    assert all(r["misurato_il"] for r in voci.values())
    assert voci["raggiungibilità"]["misurato_il"] == "2026-10-05T03:00:00Z"
    assert voci["sessione Google"]["misurato_il"] == "2026-10-05T17:12:13Z"


def test_i_guasti_si_vedono(monkeypatch, tmp_path):
    _prepara(monkeypatch, tmp_path, raggiungibile=False, notturno=5, libero=4,
             sessione={"nata_il": "2026-10-02T10:19:07Z", "ultimo_refresh": "x",
                       "sonda": {"quando": "2026-10-05T17:12:13Z", "esito": "auth_scaduta"}},
             memoria=[{"nome": "vps1777-archive-mcp-1", "picco_mb": 2040, "tetto_mb": 2048,
                       "oom_kill": 2}])
    v.scrivi_salute(tmp_path, {"copertura_scesa_da": "2026-10-04T03:00:00Z"})
    voci = _voci(tmp_path)
    assert voci["raggiungibilità"]["stato"] == "guasto"
    assert voci["backup notturno"]["stato"] == "guasto"
    assert voci["disco"]["stato"] == "guasto"
    assert voci["sessione Google"]["stato"] == "guasto"
    assert voci["copertura dei backup"]["stato"] == "attenzione"
    m = voci["memoria vps1777-archive-mcp-1"]
    assert m["stato"] == "attenzione" and "OOM" in m["dettaglio"]


def test_cio_che_non_si_misura_lo_dice(monkeypatch, tmp_path):
    _prepara(monkeypatch, tmp_path, notturno=None, archivio=None, sessione=None, memoria=None)
    (tmp_path / "onboarding" / "raggiungibilita.json").unlink()
    v.scrivi_salute(tmp_path, {})
    voci = _voci(tmp_path)
    for nome in ("raggiungibilità", "backup notturno", "sessione Google", "memoria dei container"):
        assert voci[nome]["stato"] == "non_misurato", nome
