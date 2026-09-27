"""restore.sh trova la chiave age dove la mettono gli installer.

Audit della documentazione (27/09/2026): `deploy.sh` e l'installer grafico creano la
chiave privata in `~/.config/vps1777/age-key.txt`; `restore.sh` la cercava solo in
`~/.config/age/keys.txt`. Con i default il ripristino si fermava con «chiave age non
trovata» — il giorno in cui serve, e quando non si rimedia più con calma.

`restore.sh --chiave` stampa la chiave che userebbe ed esce, senza toccare niente: è ciò
che questo test interroga (lanciare un restore vero fermerebbe lo stack).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESTORE = ROOT / "tools" / "restore.sh"


def _chiave(home: Path, **env: str) -> subprocess.CompletedProcess:
    ambiente = {k: v for k, v in os.environ.items()
                if k not in ("AGE_KEY", "XDG_CONFIG_HOME")}
    ambiente.update({"HOME": str(home), **env})
    return subprocess.run(["bash", str(RESTORE), "--chiave"], capture_output=True,
                          text=True, env=ambiente, check=False)


def _scrivi(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("AGE-SECRET-KEY-1FINTA\n")
    return p


def test_la_chiave_degli_installer_viene_trovata(tmp_path: Path) -> None:
    k = _scrivi(tmp_path / ".config" / "vps1777" / "age-key.txt")
    r = _chiave(tmp_path)
    assert r.returncode == 0 and r.stdout.strip() == str(k), (r.stdout, r.stderr)


def test_il_percorso_di_age_resta_valido(tmp_path: Path) -> None:
    k = _scrivi(tmp_path / ".config" / "age" / "keys.txt")
    r = _chiave(tmp_path)
    assert r.returncode == 0 and r.stdout.strip() == str(k), (r.stdout, r.stderr)


def test_age_key_esplicita_vince(tmp_path: Path) -> None:
    _scrivi(tmp_path / ".config" / "vps1777" / "age-key.txt")
    k = _scrivi(tmp_path / "altrove.txt")
    r = _chiave(tmp_path, AGE_KEY=str(k))
    assert r.returncode == 0 and r.stdout.strip() == str(k)


def test_senza_chiave_lo_dice_e_dove_ha_cercato(tmp_path: Path) -> None:
    r = _chiave(tmp_path)
    assert r.returncode != 0
    assert "vps1777/age-key.txt" in r.stderr and "age/keys.txt" in r.stderr


def test_il_comando_di_riavvio_rimette_su_le_feature(tmp_path: Path) -> None:
    """Audit della doc (27/09): dopo `down --remove-orphans` il comando stampato
    riavviava solo compose.yaml + ingress, e il backup notturno restava spento."""
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "restore.sh").write_text(RESTORE.read_text(encoding="utf-8"))
    (tmp_path / ".env").write_text("INGRESS_PROFILE=ingress.caddy\nVPS1777_FEATURES=backup\n")
    r = subprocess.run(["bash", str(tmp_path / "tools" / "restore.sh"), "--comando-riavvio"],
                       capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    assert "compose.ingress.caddy.yaml" in r.stdout
    assert "-f compose.ops.backup.yaml --profile ops.backup" in r.stdout
    (tmp_path / ".env").unlink()                     # senza .env: default, e exit 0
    r = subprocess.run(["bash", str(tmp_path / "tools" / "restore.sh"), "--comando-riavvio"],
                       capture_output=True, text=True, check=False)
    assert r.returncode == 0 and "ops.backup" in r.stdout, r.stdout + r.stderr
