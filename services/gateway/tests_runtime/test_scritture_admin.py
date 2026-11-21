"""Giro di revisione del 21/11/2026: le scritture delle pagine admin sono tutto-o-niente.
Deps del lock (admin vero)."""
from __future__ import annotations

import json
import stat

from app import admin


def test_scrive_e_mette_i_permessi_prima_di_rinominare(tmp_path):
    f = tmp_path / "update_pending_update.json"
    assert admin._scrivi_json(f, {"nonce": "x"}, modo=0o640) is True
    assert json.loads(f.read_text()) == {"nonce": "x"}
    assert stat.S_IMODE(f.stat().st_mode) == 0o640
    assert [p.name for p in tmp_path.iterdir()] == [f.name]      # nessun temporaneo lasciato


def test_cartella_non_scrivibile_torna_false_e_non_solleva(tmp_path):
    assert admin._scrivi_json(tmp_path / "manca" / "stato.json", {"a": 1}) is False


def test_un_json_che_non_e_un_oggetto_vale_vuoto(tmp_path):
    f = tmp_path / "marchi.json"
    f.write_text("[1, 2]")
    assert admin._read_json(f) == {}
    assert admin._marchi_leggibili(f) is False
    f.write_text('{"3": "riservato"}')
    assert admin._marchi_leggibili(f) is True
    f.write_text("{rotto")
    assert admin._marchi_leggibili(f) is False


# ───── 21/11/2026: le cure della seconda fetta riletta col catalogo ─────

def test_il_login_non_tiene_gli_ip_per_sempre(monkeypatch):
    from app import admin
    monkeypatch.setattr(admin, "_LOGIN_FAILS", {"vecchio": [1.0], "vuoto": []})
    monkeypatch.setattr(admin, "_LOGIN_LOCK", {"scaduto": 2.0})
    admin._login_record_fail("192.0.2.9")
    assert set(admin._LOGIN_FAILS) == {"192.0.2.9"} and admin._LOGIN_LOCK == {}
    monkeypatch.setattr(admin, "_LOGIN_MAX_IP", 3)
    for i in range(10):
        admin._login_record_fail(f"198.51.100.{i}")
    assert len(admin._LOGIN_FAILS) <= 3


def test_il_setup_scrive_i_segreti_gia_chiusi_e_tutto_o_niente(tmp_path, monkeypatch):
    import asyncio
    import os
    import stat
    from app import onboarding

    async def admin_ok(_r):
        return "a@example.invalid", None

    monkeypatch.setattr(onboarding, "_require_admin", admin_ok)
    monkeypatch.setattr(onboarding, "_pending_path", lambda: tmp_path / "pending.json")
    monkeypatch.setattr(onboarding, "audit", lambda e: None)
    viste: list[int] = []
    vero = os.replace

    def spia(a, b):
        viste.append(stat.S_IMODE(os.stat(a).st_mode))
        return vero(a, b)

    monkeypatch.setattr(onboarding.os, "replace", spia)

    class Richiesta:
        method = "POST"

        async def form(self):
            return {"public_base": "https://gw.example.invalid"}

    asyncio.run(onboarding.setup_view(Richiesta()))
    assert viste == [0o600], "il file coi segreti deve nascere a 0600, prima della rinomina"
    assert stat.S_IMODE(os.stat(tmp_path / "pending.json").st_mode) == 0o600
    assert [p.name for p in tmp_path.iterdir()] == ["pending.json"]


def test_una_scadenza_non_cancellata_non_si_registra_come_avvenuta(tmp_path, monkeypatch):
    from app import onboarding
    pp = tmp_path / "pending.json"
    pp.write_text('{"submitted_at": "2000-01-01T00:00:00+00:00"}')
    eventi: list[dict] = []
    monkeypatch.setattr(onboarding, "_pending_path", lambda: pp)
    monkeypatch.setattr(onboarding, "audit", eventi.append)
    monkeypatch.setattr(type(pp), "unlink", lambda self, *a, **k: (_ for _ in ()).throw(OSError("no")))
    assert onboarding._read_pending() == {}
    assert [e["event"] for e in eventi] == ["onboarding_pending_expire_err"]


def test_il_controllo_non_dice_eseguito_se_non_ha_scritto(monkeypatch):
    import inspect
    from app import admin
    src = inspect.getsource(admin.update_check)
    assert src.count("if not _scrivi_json(sf, prev):") == 2
    monkeypatch.setattr(admin, "audit", lambda e: None)
    r = admin._stato_non_scritto("a@example.invalid")
    assert r.status_code == 303 and "kind=err" in r.headers["location"]
