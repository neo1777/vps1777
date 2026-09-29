"""Il backup dall'host salva anche i volumi degli overlay attivi (29/09/2026).

`backup.sh` chiedeva la lista a `docker compose config --volumes` SENZA `-f`, cioè al solo
compose.yaml, mentre il suo commento prometteva «segue gli overlay attivi (se caddy è su, i
suoi volumi ci sono)». Misurato sulla VPS: 5 volumi, gli stessi con o senza l'ingress. Con
Caddy i certificati, con Portainer i suoi dati, non entravano in nessun backup. Qui si
esegue il blocco vero di backup.sh con un `docker` finto che risponde come un host con
l'ingress Caddy attivo.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]

FINTO = r'''
docker() {
  case "$*" in
    "compose config --volumes") printf 'gateway-data\narchive-data\ngateway-uploads\nnlm-artifacts\n' ;;
    "volume ls -q --filter label=com.docker.compose.project=vps1777")
      printf 'vps1777_gateway-data\nvps1777_archive-data\nvps1777_gateway-uploads\nvps1777_nlm-artifacts\nvps1777_caddy-data\nvps1777_caddy-config\n' ;;
    *) return 1 ;;
  esac
}
die() { echo "DIE $*"; exit 3; }
'''


def _blocco() -> str:
    righe = (RADICE / "tools" / "backup.sh").read_text(encoding="utf-8").splitlines()
    i = next(n for n, r in enumerate(righe) if ">>> volumi-del-progetto" in r)
    f = next(n for n, r in enumerate(righe) if "<<< volumi-del-progetto" in r)
    return "\n".join(righe[i:f + 1])


def _esegui(env_extra: str = "") -> set[str]:
    script = f"set -u; COMPOSE_PROJECT_NAME=vps1777\n{env_extra}\n{FINTO}\n{_blocco()}\nprintf '%s\\n' $VOLS_LOGICI"
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return set(r.stdout.split())


def test_i_volumi_di_caddy_entrano_nella_lista():
    vols = _esegui()
    assert {"caddy-data", "caddy-config"} <= vols, vols


def test_i_volumi_del_base_restano():
    vols = _esegui()
    assert {"gateway-data", "archive-data", "gateway-uploads", "nlm-artifacts"} <= vols, vols


def test_nessun_doppione():
    script_out = _esegui()
    assert len(script_out) == 6, script_out
