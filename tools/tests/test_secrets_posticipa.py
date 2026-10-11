"""P18 (11/10/2026): il promemoria dei secret apre la vista giusta e si può posticipare.

`secrets-status --notify` gira ogni giorno e, finché un secret resta da ruotare, ripete lo
stesso messaggio ogni giorno: chi ha già deciso «lo faccio sabato» non aveva modo di
dirlo. Ora la Mini App scrive `onboarding/secrets_posticipa.json` (il gateway monta
onboarding in scrittura; il bot no) e il CLI, finché il posticipo vale, non manda il
messaggio. E il messaggio porta un bottone che apre la Mini App sulla scheda Sistema
(`?vista=sistema`: il fragment lo usa Telegram per l'initData).
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import urllib.parse
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("vps1777_posticipa", _ROOT / "tools" / "vps1777.py")
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)


def _repo(tmp_path: Path, base: str = "https://vps.example.invalid") -> Path:
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "telegram_bot_token.txt").write_text("123456:finto\n")
    (tmp_path / ".env").write_text(f"TELEGRAM_OWNER_ID=42\nPUBLIC_BASE={base}\n")
    return tmp_path


def _spia_urlopen(monkeypatch) -> list[dict]:
    mandati: list[dict] = []

    class _R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def finto(req, timeout=10):
        mandati.append(dict(urllib.parse.parse_qsl(req.data.decode())))
        return _R()
    monkeypatch.setattr(v.urllib.request, "urlopen", finto)
    return mandati


def test_la_notifica_con_vista_porta_il_bottone_della_mini_app(tmp_path, monkeypatch):
    mandati = _spia_urlopen(monkeypatch)
    v.telegram_notify(_repo(tmp_path), "ciao", vista="sistema")
    tastiera = json.loads(mandati[0]["reply_markup"])
    (bottone,) = tastiera["inline_keyboard"][0]
    assert bottone["web_app"]["url"] == "https://vps.example.invalid/app?vista=sistema"


def test_senza_https_niente_bottone(tmp_path, monkeypatch):
    mandati = _spia_urlopen(monkeypatch)
    v.telegram_notify(_repo(tmp_path, "http://10.0.0.1:8080"), "ciao", vista="sistema")
    assert "reply_markup" not in mandati[0]


def test_senza_vista_come_prima(tmp_path, monkeypatch):
    mandati = _spia_urlopen(monkeypatch)
    v.telegram_notify(_repo(tmp_path), "ciao")
    assert "reply_markup" not in mandati[0] and mandati[0]["text"] == "ciao"


def test_il_posticipo_valido_si_legge_e_quello_scaduto_no(tmp_path):
    ora = dt.datetime(2026, 10, 11, 12, 0, tzinfo=dt.timezone.utc)
    ob = tmp_path / "onboarding"
    ob.mkdir()
    (ob / "secrets_posticipa.json").write_text(json.dumps({"fino_a": "2026-10-18T12:00:00+00:00"}))
    assert v.posticipo_secrets(tmp_path, ora=ora) == "2026-10-18T12:00:00+00:00"
    assert v.posticipo_secrets(tmp_path, ora=ora + dt.timedelta(days=8)) is None
    (ob / "secrets_posticipa.json").write_text("rotto")
    assert v.posticipo_secrets(tmp_path, ora=ora) is None


def _secrets_vecchi(repo: Path) -> None:
    f = repo / "secrets" / "gateway_secret.txt"
    f.write_text("x")
    vecchio = dt.datetime(2024, 1, 1).timestamp()
    import os
    os.utime(f, (vecchio, vecchio))


def test_secrets_status_tace_finche_vale_il_posticipo(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _secrets_vecchi(repo)
    mandati: list[tuple] = []
    monkeypatch.setattr(v, "telegram_notify", lambda r, t, **k: mandati.append((t, k)))
    monkeypatch.setattr(v, "posticipo_secrets", lambda r, **k: "2099-01-01T00:00:00+00:00")
    v.cmd_secrets_status(repo, argparse.Namespace(notify=True, json=False))
    assert mandati == []
    monkeypatch.setattr(v, "posticipo_secrets", lambda r, **k: None)
    v.cmd_secrets_status(repo, argparse.Namespace(notify=True, json=False))
    testo, k = mandati[0]
    assert k.get("vista") == "sistema" and "Posticipa" in testo
