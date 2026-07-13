"""Test della redazione segreti nei log (stdlib-only, offline)."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import logredact  # noqa: E402


def _record(msg, *args):
    return logging.LogRecord("t", logging.INFO, __file__, 1, msg, args, None)


def test_reda_il_secret_nel_messaggio():
    f = logredact.RedactSecrets(["S3CR3T"])
    r = _record('GET /S3CR3T/nb1777/mcp HTTP/1.1 200')
    assert f.filter(r) is True
    assert "S3CR3T" not in r.getMessage()
    assert "***" in r.getMessage()


def test_reda_anche_con_args_interpolati():
    f = logredact.RedactSecrets(["abc123"])
    r = _record('path=%s status=%d', "/abc123/archive/mcp", 200)
    f.filter(r)
    assert "abc123" not in r.getMessage()
    assert r.args == ()  # azzerati dopo la redazione


def test_ignora_segreti_vuoti_e_non_scarta_mai():
    f = logredact.RedactSecrets(["", None])  # type: ignore[list-item]
    r = _record("niente da redigere qui")
    assert f.filter(r) is True
    assert r.getMessage() == "niente da redigere qui"


def test_piu_segreti_ordine_per_lunghezza():
    # "abcdef" contiene "abc": il più lungo va sostituito prima, o resterebbe "***def"
    f = logredact.RedactSecrets(["abc", "abcdef"])
    r = _record("token=abcdef")
    f.filter(r)
    assert r.getMessage() == "token=***"


def test_install_idempotente_sugli_handler():
    root = logging.getLogger()
    h = logging.StreamHandler()
    root.addHandler(h)
    try:
        logredact.install(["xyz"])
        logredact.install(["xyz"])  # 2a volta: non deve raddoppiare il filtro
        n = sum(isinstance(f, logredact.RedactSecrets) for f in h.filters)
        assert n == 1
    finally:
        root.removeHandler(h)
