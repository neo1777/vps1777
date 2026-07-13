"""Test del middleware header di sicurezza (stdlib-only, offline).

asgi_security è puro stdlib: lo importo come modulo singolo, senza tirare dentro
il pacchetto app/ (che avrebbe deps pesanti) — come test_archive_indexer.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import asgi_security  # noqa: E402


def _run(path: str, hsts: bool, start_headers=None):
    """Fa passare una risposta finta attraverso il middleware e ritorna gli
    header (dict lowercase) emessi su http.response.start."""
    downstream_headers = start_headers or []

    async def dummy_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": list(downstream_headers)})
        await send({"type": "http.response.body", "body": b"ok"})

    mw = asgi_security.SecurityHeadersASGI(dummy_app, hsts=hsts)
    captured = {}

    async def send(message):
        if message["type"] == "http.response.start":
            for k, v in message["headers"]:
                captured[k.decode().lower()] = v.decode()

    async def receive():
        return {"type": "http.request"}

    scope = {"type": "http", "path": path, "method": "GET"}
    asyncio.run(mw(scope, receive, send))
    return captured


def test_admin_get_no_store():
    h = _run("/admin/", hsts=True)
    assert h.get("cache-control") == "no-store"
    assert h.get("x-content-type-options") == "nosniff"
    assert h.get("referrer-policy") == "no-referrer"
    assert "strict-transport-security" in h


def test_permissions_policy_and_coop_globali():
    # su OGNI risposta (anche non-admin): Permissions-Policy + COOP
    h = _run("/app", hsts=True)
    assert "camera=()" in h.get("permissions-policy", "")
    assert h.get("cross-origin-opener-policy") == "same-origin"
    # anche sul proxy MCP (path arbitrario)
    h2 = _run("/SECRET/nb1777/mcp", hsts=False)
    assert "permissions-policy" in h2
    assert h2.get("cross-origin-opener-policy") == "same-origin"


def test_admin_exact_path_no_store():
    # /admin senza slash finale è comunque admin
    assert _run("/admin", hsts=True).get("cache-control") == "no-store"


def test_non_admin_has_no_cache_control():
    # la pagina /app NON deve avere no-store (statica, cacheabile)
    h = _run("/app", hsts=True)
    assert "cache-control" not in h
    assert h.get("x-content-type-options") == "nosniff"  # gli header globali restano


def test_miniapp_api_no_store():
    # le API della Mini App (dati di controllo) non vanno mai cacheate
    assert _run("/app/api/overview", hsts=True).get("cache-control") == "no-store"
    assert _run("/app/api/update/state", hsts=True).get("cache-control") == "no-store"
    assert _run("/app/auth", hsts=True).get("cache-control") == "no-store"


def test_health_and_proxy_not_no_store():
    assert "cache-control" not in _run("/health", hsts=True)
    assert "cache-control" not in _run("/SECRET/nb1777/mcp", hsts=True)


def test_admin_prefix_not_greedy():
    # un ipotetico /administrator NON è admin → niente no-store
    assert "cache-control" not in _run("/administrator", hsts=True)


def test_hsts_only_when_enabled():
    assert "strict-transport-security" not in _run("/admin/", hsts=False)


def test_does_not_duplicate_existing_header():
    # se il downstream ha già messo nosniff, non lo si duplica
    h_pairs = []

    async def dummy_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"x-content-type-options", b"nosniff")]})
        await send({"type": "http.response.body", "body": b"ok"})

    mw = asgi_security.SecurityHeadersASGI(dummy_app, hsts=False)

    async def send(message):
        if message["type"] == "http.response.start":
            h_pairs.extend(message["headers"])

    async def receive():
        return {"type": "http.request"}

    asyncio.run(mw({"type": "http", "path": "/admin/"}, receive, send))
    nosniff = [p for p in h_pairs if p[0].lower() == b"x-content-type-options"]
    assert len(nosniff) == 1
