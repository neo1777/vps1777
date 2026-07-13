"""
JSONL audit log writer.

Ogni evento è una riga JSON con ts, event, e attributi arbitrari. Append-only.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .settings import get_settings

# sopra questa dimensione il log viene POTATO (righe oltre la retention). Il
# controllo è su st_size (economico) → la potatura è rara, non a ogni scrittura.
_PRUNE_SIZE = 5 * 1024 * 1024  # 5 MB


def _prune(path: Path, retention_days: int) -> None:
    """Riscrive il log tenendo solo le righe entro `retention_days` (per `ts`
    ISO, confronto lessicografico). Le righe senza ts leggibile si scartano."""
    if retention_days <= 0:
        return
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    kept: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ts = json.loads(line).get("ts", "")
        except json.JSONDecodeError:
            continue
        if ts >= cutoff:
            kept.append(line)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    tmp.replace(path)  # atomico: un lettore concorrente vede il vecchio o il nuovo


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
        # potatura opportunistica: solo quando il file è grande (raro)
        if path.stat().st_size > _PRUNE_SIZE:
            _prune(path, s.audit_retention_days)
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
