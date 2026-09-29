"""setup.sh avvia le feature dichiarate al PRIMO giro (residui dell'audit, 29/09/2026).

`backup` è acceso di default su tutte e tre le vie d'installazione, ma vive in un overlay
(`compose.ops.backup.yaml`, profilo `ops.backup`). deploy.sh ed engine.py lo passavano a
`docker compose`; setup.sh avviava solo il profilo d'ingress, e il container del backup
partiva soltanto al primo `vps1777 update`, che legge le feature. Qui si esegue il blocco
VERO di setup.sh, con `.env` diversi, e si guarda cosa passa a compose.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parents[2]
SETUP = RADICE / "setup.sh"


def _blocco() -> str:
    righe = SETUP.read_text(encoding="utf-8").splitlines()
    inizio = next(i for i, r in enumerate(righe) if r.startswith("COMPOSE_FILES=("))
    fine = next(i for i, r in enumerate(righe[inizio:], inizio) if "OPS_PROFILI+=(\"--profile\" \"ops.autoupdate\")" in r)
    return "\n".join(righe[inizio:fine + 1])


def _esegui(tmp_path: Path, env: str | None) -> tuple[list[str], list[str]]:
    if env is not None:
        (tmp_path / ".env").write_text(env)
    script = ('set -u; INGRESS_PROFILE=ingress.caddy; DEV_BUILD=0\n' + _blocco() +
              '\nprintf "%s\\n" "${COMPOSE_FILES[*]}"; printf "%s\\n" "${OPS_PROFILI[*]}"')
    r = subprocess.run(["bash", "-c", script], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    files, profili = r.stdout.split("\n")[:2]
    return files.split(), profili.split()


@pytest.mark.parametrize("env, file_attesi, profili_attesi", [
    pytest.param(None, {"compose.ops.backup.yaml"}, {"ops.backup"}, id="default: backup acceso"),
    pytest.param("VPS1777_FEATURES=backup,portainer\n",
                 {"compose.ops.backup.yaml", "compose.ops.portainer.yaml"},
                 {"ops.backup", "ops.portainer"}, id="backup e portainer"),
    pytest.param("VPS1777_FEATURES=watchtower\n", {"compose.ops.watchtower.yaml"}, {"ops.autoupdate"},
                 id="watchtower: file e profilo diversi"),
    pytest.param("VPS1777_FEATURES=\n", set(), set(), id="valore vuoto: tutto spento"),
    pytest.param("VPS1777_FEATURES= backup , autoupdate\n", {"compose.ops.backup.yaml"}, {"ops.backup"},
                 id="spazi tolti come nella CLI"),
])
def test_le_feature_dichiarate_diventano_overlay_e_profili(tmp_path, env, file_attesi, profili_attesi):
    files, profili = _esegui(tmp_path, env)
    ops_file = {f for f in files if f.startswith("compose.ops.")}
    ops_prof = {p for p in profili if p != "--profile"}
    assert ops_file == file_attesi and ops_prof == profili_attesi, (files, profili)


def test_ogni_avvio_di_setup_passa_i_profili_delle_feature():
    # tutte le chiamate reali a `docker compose … --profile "$INGRESS_PROFILE"` portano anche le feature
    testo = SETUP.read_text(encoding="utf-8")
    chiamate = re.findall(r'docker compose "\$\{COMPOSE_FILES\[@\]\}" --profile "\$INGRESS_PROFILE"[^\n]*', testo)
    assert chiamate, "nessuna chiamata a docker compose trovata: il test va aggiornato"
    senza = [c for c in chiamate if '"${OPS_PROFILI[@]}"' not in c]
    assert not senza, senza
