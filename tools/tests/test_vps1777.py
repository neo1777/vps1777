"""Test di logica pura per tools/vps1777.py (nessun docker/systemd richiesto).

Copre i fix H14 (esclusione nlm-auth dallo snapshot in chiaro) e H43
(templatizzazione delle unit systemd). Solo stdlib; eseguibile sia con pytest
sia direttamente: `python3 tools/tests/test_vps1777.py`.
"""
from __future__ import annotations

import importlib.util
import os
import pwd
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("vps1777_cli", _ROOT / "tools" / "vps1777.py")
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)


# ─────────────────────────────── H14: snapshot pre-update ───────────────────

def test_nlm_auth_excluded_from_snapshot_but_known_to_restore():
    # nlm-auth NON entra nello snapshot in chiaro…
    assert "nlm-auth" not in v.SNAPSHOT_VOLUMES
    assert v.SNAPSHOT_EXCLUDED_VOLUMES == ["nlm-auth"]
    assert v.SNAPSHOT_VOLUMES == ["gateway-data", "archive-data"]
    # …ma resta in DATA_VOLUMES: backup.sh (age, cifrato) e restore.sh lo trattano.
    assert "nlm-auth" in v.DATA_VOLUMES


def test_snapshot_stale_excluded_finds_only_excluded_tars():
    with tempfile.TemporaryDirectory() as d:
        base = Path(d) / "backups" / "pre-update"
        s1 = base / "0.31.0-a"
        s1.mkdir(parents=True)
        (s1 / "gateway-data.tar").write_text("x")
        (s1 / "archive-data.tar").write_text("x")
        (s1 / "nlm-auth.tar").write_text("SECRET")  # residuo di una CLI pre-fix
        s2 = base / "0.30.0-b"
        s2.mkdir(parents=True)
        (s2 / "gateway-data.tar").write_text("x")   # snapshot già pulito
        stale = v.snapshot_stale_excluded(base)
        assert stale == [s1 / "nlm-auth.tar"]


def test_snapshot_purge_removes_only_excluded():
    with tempfile.TemporaryDirectory() as d:
        base = Path(d) / "backups" / "pre-update"
        s1 = base / "0.31.0-a"
        s1.mkdir(parents=True)
        (s1 / "gateway-data.tar").write_text("keep")
        (s1 / "nlm-auth.tar").write_text("SECRET")
        removed = v.snapshot_purge_excluded(Path(d))
        assert removed == 1
        assert not (s1 / "nlm-auth.tar").exists()
        assert (s1 / "gateway-data.tar").exists()


def test_snapshot_stale_missing_base_is_empty():
    with tempfile.TemporaryDirectory() as d:
        assert v.snapshot_stale_excluded(Path(d) / "nope") == []


# ─────────────────────────────── H43: render_unit ──────────────────────────

def test_render_unit_substitutes_all_placeholders():
    pw = pwd.getpwuid(os.getuid())
    txt = ("User=@OPERATOR_USER@\nGroup=@OPERATOR_USER@\n"
           "Environment=VPS1777_HOME=@REPO@\nWorkingDirectory=@REPO@\n"
           "ExecStart=/usr/local/bin/vps1777 update "
           "--from-intent @REPO@/onboarding/update_pending_update.json\n")
    out = v.render_unit(txt, Path("/opt/vps1777"))
    assert "@OPERATOR_USER@" not in out
    assert "@REPO@" not in out
    assert f"User={pw.pw_name}" in out
    assert "VPS1777_HOME=/opt/vps1777" in out
    assert "/opt/vps1777/onboarding/update_pending_update.json" in out


def test_render_unit_idempotent_on_placeholderless_text():
    plain = "[Timer]\nOnCalendar=daily\nPersistent=true\n"
    assert v.render_unit(plain, Path("/opt/vps1777")) == plain


# ─────────────────────────────── H37: secret policy ────────────────────────

def test_secret_policy_covers_cloudflared_token():
    names = {row[0] for row in v._SECRET_POLICY}
    assert "cloudflared_token" in names
    # i 4 storici restano coperti
    assert {"oauth_signing_secret", "admin_password",
            "gateway_secret", "telegram_bot_token"} <= names


def test_nlm_cookie_constants_present():
    assert v.NLM_COOKIE_MAX_DAYS > 0
    assert callable(v.nlm_cookie_status)


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except Exception as exc:  # noqa: BLE001
                fails += 1
                print(f"FAIL {name}: {exc}")
    raise SystemExit(1 if fails else 0)
