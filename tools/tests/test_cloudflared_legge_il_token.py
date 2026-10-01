"""L'ingresso Cloudflare deve poter leggere il suo token (01/10/2026).

Dal 23/06 non poteva: cloudflared 2024.12.0 ignorava TUNNEL_TOKEN_FILE, e l'immagine
gira come `nonroot` mentre il token è 600 dell'UID 1000. Le misure sono nel commento di
compose.ingress.cloudflared.yaml. Questi test tengono ferme le due condizioni: una
versione che legge il file, e lo stesso UID dei segreti.
"""
from __future__ import annotations

import re
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]
TESTO = (RADICE / "compose.ingress.cloudflared.yaml").read_text(encoding="utf-8")


def test_il_token_passa_da_file_e_non_per_valore() -> None:
    assert "TUNNEL_TOKEN_FILE: /run/secrets/cloudflared_token" in TESTO
    assert not re.search(r"^\s*TUNNEL_TOKEN:", TESTO, re.M)


def test_cloudflared_gira_con_l_uid_dei_segreti() -> None:
    assert re.search(r'^\s*user:\s*"1000:1000"\s*$', TESTO, re.M), (
        "cloudflared gira come nonroot (UID 65532): senza user 1000 non legge il token "
        "600 dell'operatore — «Failed to read token file: permission denied»")


def test_la_versione_conosce_tunnel_token_file() -> None:
    m = re.search(r"image:\s*cloudflare/cloudflared:(\d{4})\.(\d+)\.(\d+)@sha256:", TESTO)
    assert m, "immagine cloudflared non trovata o non fissata per digest"
    assert tuple(int(x) for x in m.groups()) >= (2026, 9, 3), (
        "la 2024.12.0 ignorava TUNNEL_TOKEN_FILE; la 2026.9.3 lo legge (misurato il 01/10)")
