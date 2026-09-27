"""La chiave della Mini App segue il token del bot anche fuori dall'update.

Audit della documentazione (27/09/2026): `telegram_webapp_secret` è HMAC_SHA256 con chiave
«WebAppData» sul token del bot, e il gateway verifica la Mini App SOLO con lei (H54).
Si riallineava al token in due posti (lo step 13 di un update che installa davvero, e
l'auto-rollback): ruotando il token con `tools/rotate-secret.sh`, o dopo un rollback
manuale, la chiave restava quella vecchia e la Mini App rifiutava ogni accesso — con il
bot che rispondeva, cioè il sintomo che fa cercare il guasto dalla parte sbagliata.
"""
from __future__ import annotations

import ast
import hashlib
import hmac
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_rotate_secret_rideriva_la_chiave_col_token_nuovo(tmp_path: Path) -> None:
    """Si esegue il ramo vero di rotate-secret.sh su una copia, con `docker` finto."""
    repo = tmp_path / "repo"
    (repo / "tools").mkdir(parents=True)
    (repo / "secrets").mkdir()
    (repo / "tools" / "rotate-secret.sh").write_text(
        (ROOT / "tools" / "rotate-secret.sh").read_text(encoding="utf-8"))
    (repo / "secrets" / "telegram_webapp_secret.txt").write_text("vecchia")
    finto = tmp_path / "bin"
    finto.mkdir()
    (finto / "docker").write_text("#!/bin/sh\nexit 0\n")
    (finto / "docker").chmod(0o755)
    token = "123456789:" + "A" * 35
    env = {**os.environ, "PATH": f"{finto}:{os.environ['PATH']}"}
    r = subprocess.run(["bash", str(repo / "tools" / "rotate-secret.sh"), "telegram_bot_token"],
                       input=token + "\n", capture_output=True, text=True, env=env, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    atteso = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).hexdigest()
    assert (repo / "secrets" / "telegram_webapp_secret.txt").read_text().strip() == atteso
    assert oct((repo / "secrets" / "telegram_webapp_secret.txt").stat().st_mode & 0o777) == "0o600"


def test_il_rollback_manuale_riallinea_la_chiave_prima_di_up() -> None:
    sorgente = (ROOT / "tools" / "vps1777.py").read_text(encoding="utf-8")
    albero = ast.parse(sorgente)
    f = next(n for n in albero.body if isinstance(n, ast.FunctionDef) and n.name == "cmd_rollback")
    corpo = ast.get_source_segment(sorgente, f)
    i_chiave = corpo.find("assicura_webapp_secret(")
    i_up = [m.start() for m in re.finditer(r'"up", "-d"', corpo)]
    assert i_chiave != -1, "cmd_rollback non riallinea la chiave della Mini App"
    assert i_up and i_chiave < i_up[-1], "la chiave va riallineata PRIMA di `up -d`"
