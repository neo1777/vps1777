"""La coda degli avvisi del gateway per il proprietario, che il bot preleva.

Il gateway non parla con Telegram, per scelta: il token del bot non lo monta (H54) e
nel suo codice non c'è `api.telegram.org`. Quando ha qualcosa da dire al proprietario,
oggi un connettore OAuth appena autorizzato, lo mette in questa coda su disco; il bot la
preleva da `GET /internal/notifications` del gateway, come già fa con quella di
nb1777-mcp, e la manda. Un avviso prelevato esce dalla coda; la coda tiene al massimo
gli ultimi 50.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .audit import audit
from .settings import get_settings

_MAX = 50


def _file() -> Path:
    # accanto all'audit log, sul volume persistente /var/lib/gateway
    return Path(get_settings().audit_log_path).parent / "notifiche.json"


def _leggi() -> list[dict[str, Any]]:
    try:
        dati = json.loads(_file().read_text())
    except (OSError, ValueError):
        return []
    return [x for x in dati if isinstance(x, dict)] if isinstance(dati, list) else []


def _scrivi(items: list[dict[str, Any]]) -> None:
    f = _file()
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False))
        os.replace(tmp, f)
    except OSError as exc:  # non fatale: l'avviso si perde, l'audit lo dice
        audit({"event": "notifiche_persist_error", "error": str(exc)})


def accoda(kind: str, text: str) -> None:
    items = _leggi()
    items.append({"kind": kind, "text": text, "ts": int(time.time())})
    _scrivi(items[-_MAX:])


def preleva() -> list[dict[str, Any]]:
    items = _leggi()
    if items:
        _scrivi([])
    return items
