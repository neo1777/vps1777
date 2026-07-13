"""Test del rate-limiter per-IP (stdlib-only, offline)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import ratelimit  # noqa: E402


def test_ammette_fino_alla_soglia_poi_blocca():
    rl = ratelimit.RateLimiter(max_calls=3, window_s=60)
    assert rl.allow("1.1.1.1", now=0) is True
    assert rl.allow("1.1.1.1", now=1) is True
    assert rl.allow("1.1.1.1", now=2) is True
    assert rl.allow("1.1.1.1", now=3) is False   # 4a nella finestra → bloccata


def test_finestra_scorrevole_libera_dopo_window():
    rl = ratelimit.RateLimiter(max_calls=2, window_s=10)
    assert rl.allow("ip", now=0) is True
    assert rl.allow("ip", now=1) is True
    assert rl.allow("ip", now=5) is False        # ancora nella finestra
    assert rl.allow("ip", now=11) is True         # la prima (t=0) è uscita


def test_ip_indipendenti():
    rl = ratelimit.RateLimiter(max_calls=1, window_s=60)
    assert rl.allow("a", now=0) is True
    assert rl.allow("a", now=0) is False
    assert rl.allow("b", now=0) is True           # b ha la sua quota


def test_sweep_rimuove_ip_inattivi():
    rl = ratelimit.RateLimiter(max_calls=5, window_s=10)
    rl.allow("vecchio", now=0)
    rl.allow("nuovo", now=100)
    rl.sweep(now=105)
    assert "vecchio" not in rl._hits
    assert "nuovo" in rl._hits
