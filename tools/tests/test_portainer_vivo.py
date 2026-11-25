"""Portainer non può avere un healthcheck (immagine col solo binario): lo si interroga dall'host (25/11/2026).

`tools/portainer-vivo.sh` è il sostituto dichiarato in `applicabilita.yml` (SIC-06), e `vps1777 check`
lo lancia quando la feature è dichiarata. Qui: lo script nei suoi tre esiti, con un `curl` finto; la
sorveglianza che si arma, non ripete, si disarma, e tace quando la feature non c'è.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = _ROOT / "tools" / "portainer-vivo.sh"
_spec = importlib.util.spec_from_file_location("vps1777_cli_portainer", _ROOT / "tools" / "vps1777.py")
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)


def _con_curl_finto(tmp_path: Path, corpo: str) -> subprocess.CompletedProcess:
    finti = tmp_path / "bin"
    finti.mkdir(exist_ok=True)
    (finti / "curl").write_text("#!/bin/sh\n" + corpo + "\n", encoding="utf-8")
    (finti / "curl").chmod(0o755)
    env = {**os.environ, "PATH": f"{finti}:/usr/bin:/bin"}
    return subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env, timeout=30, check=False)


@pytest.mark.parametrize("corpo,esito", [("printf 200", 0), ("printf 503", 1), ("printf 000; exit 7", 1)])
def test_lo_script_dice_vivo_solo_su_un_200(tmp_path, corpo, esito):
    r = _con_curl_finto(tmp_path, corpo)
    assert r.returncode == esito, r.stdout + r.stderr


def test_senza_curl_non_ha_guardato(tmp_path):
    vuoto = tmp_path / "vuoto"
    vuoto.mkdir()
    bash = subprocess.run(["bash", "-c", "command -v bash"], capture_output=True, text=True, check=True).stdout.strip()
    r = subprocess.run([bash, str(SCRIPT)], capture_output=True, text=True, env={"PATH": str(vuoto)},
                       timeout=30, check=False)
    assert r.returncode == 2 and "non ho potuto guardare" in r.stdout


def test_l_eccezione_dichiarata_nomina_uno_script_che_esiste_e_il_check_lo_lancia():
    dichiarazione = (_ROOT / "applicabilita.yml").read_text(encoding="utf-8")
    assert "sostituto: tools/portainer-vivo.sh" in dichiarazione and SCRIPT.is_file()
    sorgente = (_ROOT / "tools" / "vps1777.py").read_text(encoding="utf-8")
    corpo = sorgente[sorgente.index("def cmd_check("):]
    assert "_sorveglia_portainer(repo, st," in corpo[:corpo.index("\ndef ")]
    assert "healthcheck:" not in (_ROOT / "compose.ops.portainer.yaml").read_text(encoding="utf-8").replace(
        "# Niente healthcheck", ""), "se un giorno l'immagine lo permette, togli l'eccezione"


def test_la_sorveglianza_si_arma_non_ripete_e_si_disarma(tmp_path, monkeypatch):
    (tmp_path / "tools").mkdir()
    script = tmp_path / "tools" / "portainer-vivo.sh"
    mandati: list[str] = []
    monkeypatch.setattr(v, "telegram_notify", lambda _repo, testo, **_k: mandati.append(testo))
    funzioni = {"portainer"}
    monkeypatch.setattr(v, "enabled_features", lambda _repo: funzioni)

    def scrivi(esito: int) -> None:
        script.write_text(f"echo detto\nexit {esito}\n", encoding="utf-8")

    st: dict = {}
    scrivi(0)
    v._sorveglia_portainer(tmp_path, st, True)
    assert st == {} and mandati == []
    scrivi(1)
    v._sorveglia_portainer(tmp_path, st, True)
    v._sorveglia_portainer(tmp_path, st, True)
    assert st.get("portainer_giu_da") and len(mandati) == 1 and "non risponde" in mandati[0]
    scrivi(2)                                                # non ha potuto guardare: né arma né disarma
    v._sorveglia_portainer(tmp_path, st, True)
    assert st.get("portainer_giu_da") and len(mandati) == 1
    scrivi(0)
    v._sorveglia_portainer(tmp_path, st, True)
    assert "portainer_giu_da" not in st and len(mandati) == 2 and "tornato" in mandati[1]
    scrivi(1)
    funzioni.clear()                                         # feature non dichiarata: silenzio
    v._sorveglia_portainer(tmp_path, st, True)
    assert st == {} and len(mandati) == 2
