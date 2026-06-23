"""
JSONL audit log writer.

Ogni evento è una riga JSON con ts, event, e attributi arbitrari. Append-only.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .settings import get_settings


def audit(event: dict[str, Any]) -> None:
    """Append evento al log JSONL. Non solleva mai eccezioni."""
    try:
        s = get_settings()
        path = Path(s.audit_log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **event,
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        # mai bloccare la response per un audit fail
        pass


def read_recent(limit: int = 200) -> list[dict[str, Any]]:
    """Legge gli ultimi N eventi dal log. Tollera righe corrotte."""
    s = get_settings()
    path = Path(s.audit_log_path)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()[-limit:]
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return events
