"""Il compose non regredisce sulle due cure del vaglio corso1777 (03/09).

① tmpfs: un rootfs read-only con una tmpfs eseguibile è un caveau blindato con
   la cassaforte aperta — noexec,nosuid,size sono PARTE del controllo, non
   rifinitura. ② healthcheck: la sonda socket-only («la porta è aperta») fa
   passare per sano un processo con l'app rotta, e su quei verdi si appoggia il
   health-gate dell'updater. Il presidio guarda il FILE, non il comportamento:
   è il posto dove una regressione entrerebbe."""
from __future__ import annotations

import re
from pathlib import Path

COMPOSE = Path(__file__).resolve().parents[2] / "compose.yaml"


def test_ogni_tmpfs_porta_noexec_nosuid_e_size():
    testo = COMPOSE.read_text(encoding="utf-8")
    tmpfs_righe = [r for r in testo.splitlines() if re.match(r"\s*-\s*/tmp\b", r.strip().lstrip("- ")) or r.strip().startswith("- /tmp")]
    assert tmpfs_righe, "nessuna riga tmpfs trovata: il parser di questo test è rotto, non il compose"
    for r in tmpfs_righe:
        for opzione in ("noexec", "nosuid", "size="):
            assert opzione in r, f"tmpfs senza {opzione!r}: {r.strip()!r}"


def test_nessun_healthcheck_socket_only():
    testo = COMPOSE.read_text(encoding="utf-8")
    assert "create_connection" not in testo, (
        "healthcheck socket-only nel compose: porta aperta ≠ app sana — "
        "usare l'endpoint /health del servizio (vaglio corso1777, 03/09)")


def test_i_due_mcp_interrogano_health():
    testo = COMPOSE.read_text(encoding="utf-8")
    for porta in ("8002", "8003"):
        pattern = f"127.0.0.1:{porta}/health"
        assert pattern in testo, (
            f"il servizio sulla porta {porta} non interroga /health: "
            "il health-gate dell'updater si appoggia a questa sonda")
