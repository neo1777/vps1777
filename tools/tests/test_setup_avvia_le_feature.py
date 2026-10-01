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
    # Il blocco finisce con il `case` di caddy-dns01 (01/10/2026), l'ultima feature con un
    # overlay: prima finiva alla riga di watchtower, e il caso nuovo sarebbe rimasto fuori
    # dal test senza che niente fallisse.
    righe = SETUP.read_text(encoding="utf-8").splitlines()
    inizio = next(i for i, r in enumerate(righe) if r.startswith("COMPOSE_FILES=("))
    dns01 = next(i for i, r in enumerate(righe[inizio:], inizio) if "*,caddy-dns01,*" in r)
    fine = next(i for i, r in enumerate(righe[dns01:], dns01) if r.strip() == "esac")
    return "\n".join(righe[inizio:fine + 1])


def _esegui(tmp_path: Path, env: str | None, ingresso: str = "ingress.caddy",
            avvisi: list[str] | None = None) -> tuple[list[str], list[str]]:
    if env is not None:
        (tmp_path / ".env").write_text(env)
    script = (f'set -u; INGRESS_PROFILE={ingresso}; DEV_BUILD=0\n'
              'warn() { printf "%s\\n" "$*" >&2; }\n' + _blocco() +
              '\nprintf "%s\\n" "${COMPOSE_FILES[*]}"; printf "%s\\n" "${OPS_PROFILI[*]}"')
    r = subprocess.run(["bash", "-c", script], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    if avvisi is not None:
        avvisi.extend(r.stderr.splitlines())
    files, profili = r.stdout.split("\n")[:2]
    return files.split(), profili.split()


@pytest.mark.parametrize("env, file_attesi, profili_attesi", [
    pytest.param(None, {"compose.ops.backup.yaml"}, {"ops.backup"}, id="default: backup acceso"),
    pytest.param("VPS1777_FEATURES=backup,portainer\n",
                 {"compose.ops.backup.yaml", "compose.ops.portainer.yaml"},
                 {"ops.backup", "ops.portainer"}, id="backup e portainer"),
    pytest.param("VPS1777_FEATURES=backup,watchtower\n", {"compose.ops.backup.yaml"}, {"ops.backup"},
                 id="watchtower (tolta nella 0.67.0): ignorata, le altre restano"),
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


def test_caddy_dns01_con_caddy_e_token_monta_l_overlay_senza_profilo(tmp_path):
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "cf_api_token.txt").write_text("x" * 40)
    files, profili = _esegui(tmp_path, "VPS1777_FEATURES=caddy-dns01\n")
    assert "compose.ops.caddy-dns01.yaml" in files
    # nessun profilo nuovo: il servizio `caddy` vive in ingress.caddy, già acceso
    assert {p for p in profili if p != "--profile"} == set(), profili


@pytest.mark.parametrize("ingresso, con_token", [
    ("ingress.tailscale", True), ("ingress.cloudflared", True), ("ingress.caddy", False)])
def test_caddy_dns01_fuori_posto_avvisa_e_non_monta(tmp_path, ingresso, con_token):
    """Ingresso diverso, o token assente: l'installer lo DICE e prosegue senza overlay."""
    if con_token:
        (tmp_path / "secrets").mkdir()
        (tmp_path / "secrets" / "cf_api_token.txt").write_text("x" * 40)
    avvisi: list[str] = []
    files, _ = _esegui(tmp_path, "VPS1777_FEATURES=caddy-dns01\n", ingresso, avvisi)
    assert "compose.ops.caddy-dns01.yaml" not in files
    assert any("caddy-dns01" in a for a in avvisi), avvisi


def test_watchtower_dichiarata_avvisa_e_non_monta(tmp_path):
    """Tolta nella 0.67.0: una riga vecchia del .env la nomina ancora. setup.sh lo DICE
    (come la CLI) invece di ignorarla in silenzio, e non cerca un overlay che non c'è."""
    avvisi: list[str] = []
    files, profili = _esegui(tmp_path, "VPS1777_FEATURES=watchtower\n", avvisi=avvisi)
    assert not any("watchtower" in f for f in files) and "ops.autoupdate" not in profili
    assert any("watchtower" in a and "0.67.0" in a and "autoupdate" in a for a in avvisi), avvisi


@pytest.mark.parametrize("dichiarate, attese", [
    ("backup,watchtower,autoupdate", "backup,autoupdate"),
    ("watchtower,portainer", "portainer"),
    ("watchtower", "none"),        # vuoto varrebbe «i default» qui e «tutto spento» nella CLI
    ("backup,autoupdate", "backup,autoupdate"),
])
def test_deploy_toglie_watchtower_dal_valore_che_persiste(dichiarate, attese):
    """deploy.sh SCRIVE $FEATURES nel .env della VPS: lì la feature tolta non deve
    tornare. Si esegue il blocco vero, estratto dal file."""
    righe = (RADICE / "deploy.sh").read_text(encoding="utf-8").splitlines()
    inizio = next(i for i, r in enumerate(righe) if r.startswith("WATCHTOWER_DICHIARATA=0"))
    fine = next(i for i, r in enumerate(righe[inizio:], inizio) if r.strip() == "esac")
    script = (f'set -u; FEATURES="{dichiarate}"\nwarn() {{ printf "%s\\n" "$*" >&2; }}\n'
              + "\n".join(righe[inizio:fine + 1]) + '\nprintf "%s %s" "$FEATURES" "$WATCHTOWER_DICHIARATA"')
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    valore, ricordata = r.stdout.split()
    assert valore == attese
    assert ricordata == ("1" if "watchtower" in dichiarate else "0")
    assert ("0.67.0" in r.stderr) == ("watchtower" in dichiarate)
