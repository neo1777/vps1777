"""Le immagini che i tool lanciano con `docker run` sono pinnate a digest, come quelle dei
compose (H66).

Audit della documentazione (27/09/2026): ARCHITECTURE diceva «immagini di terzi pinnate a
digest», ed era vero per i compose; ma snapshot, backup, restore e il check delle scadenze
lanciano `busybox:latest` coi volumi dei dati montati — un tag mobile, fuori dal presidio.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILE = [ROOT / "tools" / "vps1777.py", ROOT / "tools" / "backup.sh", ROOT / "tools" / "restore.sh"]
_BUSYBOX = re.compile(r"busybox:[\w.-]+(@sha256:[0-9a-f]{64})?")


def test_busybox_sempre_col_digest_e_lo_stesso_ovunque() -> None:
    digest: set[str] = set()
    for f in FILE:
        for m in _BUSYBOX.finditer(f.read_text(encoding="utf-8")):
            assert m.group(1), f"{f.relative_to(ROOT)}: {m.group(0)} senza digest"
            digest.add(m.group(0))
    assert len(digest) == 1, f"busybox con riferimenti diversi: {digest}"
