"""Le prove empiriche e il loro lanciatore non danno un verde senza una misura.

Nascono dalla rilettura di `tools/prove-empiriche/` contro un catalogo di requisiti (novembre
2026). Il filo comune dei rilievi veri: uno strumento che STAMPA «non concludo», «non visto»,
«assenti» e poi esce 0. Qui ogni caso gira davvero, con un `docker`, un `curl` o un `systemctl`
finti messi davanti nel PATH, in un albero provvisorio: non serve la macchina vera.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROVE = ROOT / "tools" / "prove-empiriche"
RIGA_REPO = 'REPO="${VPS1777_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]:-.}")/../.." 2>/dev/null && pwd)}"'


def _eseguibile(p: Path, testo: str) -> None:
    p.write_text(testo, encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IXUSR)


def _lancia(script: Path, *args: str, env: dict[str, str] | None = None, cwd: Path | None = None):
    e = {**os.environ, **(env or {})}
    return subprocess.run(["bash", str(script), *args], capture_output=True, text=True, env=e,
                          cwd=cwd, timeout=120, check=False)


def _albero(tmp: Path, prove: dict[str, str], elenco: list[str] | None) -> Path:
    """Un repo finto (senza git) col lanciatore vero e delle prove finte."""
    qui = tmp / "repo" / "tools" / "prove-empiriche"
    qui.mkdir(parents=True)
    for n in ("lancia-tutte.sh", "onesta-a-macchina-nuda.sh"):
        shutil.copy(PROVE / n, qui / n)
    for nome, corpo in prove.items():
        _eseguibile(qui / nome, "#!/usr/bin/env bash\n" + corpo + "\n")
    if elenco is not None:
        (qui / "prove.elenco").write_text("\n".join(elenco) + "\n", encoding="utf-8")
    return qui


def _referto(qui: Path, suffisso: str = "") -> dict:
    return json.loads((qui.parents[1] / "onboarding" / f"prove-empiriche{suffisso}.json").read_text("utf-8"))


SENZA_GIT = {"GIT_DIR": "/nonexistent", "GIT_CEILING_DIRECTORIES": "/"}


# ── l'elenco che viaggia col pacchetto ─────────────────────────────────────────

def test_l_elenco_delle_prove_coincide_coi_file() -> None:
    elenco = [r for r in (PROVE / "prove.elenco").read_text("utf-8").splitlines() if r.strip()]
    file = sorted(p.name for p in PROVE.glob("prova-*.sh"))
    assert elenco == file, "prove.elenco e i file prova-*.sh non coincidono: aggiorna l'elenco"


# ── il lanciatore ──────────────────────────────────────────────────────────────

def test_tutte_verdi_e_complete_esce_zero_col_referto_riletto(tmp_path: Path) -> None:
    qui = _albero(tmp_path, {"prova-1-a.sh": "exit 0", "prova-2-b.sh": "exit 0"},
                  ["prova-1-a.sh", "prova-2-b.sh"])
    r = _lancia(qui / "lancia-tutte.sh", env=SENZA_GIT)
    assert r.returncode == 0, r.stdout + r.stderr
    d = _referto(qui)
    assert (d["atteso"], d["totale"], d["ok"]) == (2, 2, 2)
    assert not list((qui.parents[1] / "onboarding").glob("*.tmp.*")), "resta un file provvisorio"


def test_un_fail_resta_rosso_anche_se_il_testo_dice_non_eseguibile(tmp_path: Path) -> None:
    qui = _albero(tmp_path, {"prova-1-a.sh": 'echo "prova non eseguibile"; exit 1'}, ["prova-1-a.sh"])
    r = _lancia(qui / "lancia-tutte.sh", env=SENZA_GIT)
    assert r.returncode == 1, r.stdout
    assert _referto(qui)["prove"][0]["esito"] == "ROSSA"


def test_un_pass_resta_verde_anche_se_il_testo_dice_non_eseguibile(tmp_path: Path) -> None:
    """Così il gate di onestà lo vede: prima il testo lo declassava e il falso verde spariva."""
    qui = _albero(tmp_path, {"prova-1-a.sh": 'echo "prova non eseguibile"; exit 0'}, ["prova-1-a.sh"])
    _lancia(qui / "lancia-tutte.sh", env=SENZA_GIT)
    assert _referto(qui)["prove"][0]["esito"] == "verde"


def test_una_prova_appesa_scade_e_non_e_un_verdetto(tmp_path: Path) -> None:
    qui = _albero(tmp_path, {"prova-1-a.sh": "sleep 30", "prova-2-b.sh": "exit 0"},
                  ["prova-1-a.sh", "prova-2-b.sh"])
    r = _lancia(qui / "lancia-tutte.sh", env={**SENZA_GIT, "PROVE_TIMEOUT_S": "1"})
    assert r.returncode == 2, r.stdout
    p = {x["prova"]: x for x in _referto(qui)["prove"]}
    assert p["prova-1-a"]["esito"] == "NON-ESEGUITA" and "scaduta" in p["prova-1-a"]["motivo"]
    assert p["prova-2-b"]["esito"] == "verde", "la prova appesa non deve fermare le altre"


def test_una_prova_mancante_dal_pacchetto_non_e_un_pass(tmp_path: Path) -> None:
    qui = _albero(tmp_path, {"prova-1-a.sh": "exit 0"}, ["prova-1-a.sh", "prova-2-b.sh"])
    r = _lancia(qui / "lancia-tutte.sh", env=SENZA_GIT)
    assert r.returncode == 2, r.stdout
    assert "prova-2-b.sh" in r.stdout
    assert _referto(qui)["atteso"] == 2


def test_senza_git_e_senza_elenco_il_numero_atteso_e_ignoto_e_non_e_un_pass(tmp_path: Path) -> None:
    qui = _albero(tmp_path, {"prova-1-a.sh": "exit 0"}, None)
    r = _lancia(qui / "lancia-tutte.sh", env=SENZA_GIT)
    assert r.returncode == 2, r.stdout
    assert _referto(qui)["atteso"] is None


def test_il_motivo_con_una_tabulazione_non_rompe_il_referto(tmp_path: Path) -> None:
    qui = _albero(tmp_path, {"prova-1-a.sh": "printf 'prova non eseguibile:\\tmanca \"x\"\\n'; exit 2"},
                  ["prova-1-a.sh"])
    _lancia(qui / "lancia-tutte.sh", env=SENZA_GIT)
    assert "manca" in _referto(qui)["prove"][0]["motivo"]


def test_se_il_referto_non_si_puo_scrivere_quello_di_prima_resta_e_non_e_un_pass(tmp_path: Path) -> None:
    if os.geteuid() == 0:
        return      # root scrive anche nelle cartelle in sola lettura: il caso non si costruisce
    qui = _albero(tmp_path, {"prova-1-a.sh": "exit 0"}, ["prova-1-a.sh"])
    onb = qui.parents[1] / "onboarding"
    onb.mkdir()
    (onb / "prove-empiriche.json").write_text('{"quando":"2026-01-01T00:00:00Z","ok":1,"totale":1}', "utf-8")
    onb.chmod(0o555)
    try:
        r = _lancia(qui / "lancia-tutte.sh", env=SENZA_GIT)
    finally:
        onb.chmod(0o755)
    assert r.returncode == 2, r.stdout + r.stderr
    assert json.loads((onb / "prove-empiriche.json").read_text("utf-8"))["quando"].startswith("2026-01-01")


# ── il gate di onestà ──────────────────────────────────────────────────────────

def _referto_ci(qui: Path, contenuto: dict) -> None:
    onb = qui.parents[1] / "onboarding"
    onb.mkdir(exist_ok=True)
    (onb / "prove-empiriche-ci-macchina-nuda.json").write_text(json.dumps(contenuto), "utf-8")


def test_il_gate_non_legge_il_referto_di_un_giro_precedente(tmp_path: Path) -> None:
    qui = _albero(tmp_path, {}, [])
    _referto_ci(qui, {"atteso": 1, "prove": [{"prova": "prova-1-a", "esito": "NON-ESEGUITA"}]})
    _eseguibile(qui / "lancia-tutte.sh", "#!/usr/bin/env bash\nexit 0\n")     # un lanciatore che non scrive
    r = _lancia(qui / "onesta-a-macchina-nuda.sh", env=SENZA_GIT)
    assert r.returncode == 2, r.stdout + r.stderr


def _gate_con(tmp_path: Path, referto: dict):
    qui = _albero(tmp_path, {}, [])
    _eseguibile(qui / "lancia-tutte.sh",
                "#!/usr/bin/env bash\ncat > \"$(dirname \"$0\")/../../onboarding/prove-empiriche-ci-macchina-nuda.json\" <<'J'\n"
                + json.dumps(referto) + "\nJ\n")
    (qui.parents[1] / "onboarding").mkdir()
    return _lancia(qui / "onesta-a-macchina-nuda.sh", env=SENZA_GIT)


def test_il_gate_senza_numero_atteso_non_ha_un_verdetto(tmp_path: Path) -> None:
    r = _gate_con(tmp_path, {"atteso": None, "prove": [{"prova": "p", "esito": "NON-ESEGUITA"}]})
    assert r.returncode == 2, r.stdout + r.stderr


def test_il_gate_rifiuta_un_esito_che_non_conosce(tmp_path: Path) -> None:
    r = _gate_con(tmp_path, {"atteso": 1, "prove": [{"prova": "p", "esito": "boh"}]})
    assert r.returncode == 2, r.stdout + r.stderr


def test_il_gate_sano_resta_verde_e_il_falso_verde_resta_rosso(tmp_path: Path) -> None:
    r = _gate_con(tmp_path, {"atteso": 1, "prove": [{"prova": "p", "esito": "NON-ESEGUITA", "motivo": "x"}]})
    assert r.returncode == 0, r.stdout + r.stderr
    r = _gate_con(tmp_path / "b", {"atteso": 1, "prove": [{"prova": "p", "esito": "verde", "rc": 0}]})
    assert r.returncode == 1


# ── le prove, con gli strumenti finti ──────────────────────────────────────────

def _finti(tmp: Path, **comandi: str) -> dict[str, str]:
    b = tmp / "bin"
    b.mkdir(parents=True, exist_ok=True)
    for nome, corpo in comandi.items():
        _eseguibile(b / nome, "#!/usr/bin/env bash\n" + corpo + "\n")
    repo = tmp / "finto"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "compose.yaml").write_text("services: {}\n", "utf-8")
    return {"PATH": f"{b}:{os.environ['PATH']}", "VPS1777_REPO": str(repo)}


DOCKER_MUTO = 'case "$*" in *"ps --status running -q gateway"*) echo abc ;; *) exit 1 ;; esac'


def test_prova_1_con_l_exec_muto_non_dichiara_un_pass(tmp_path: Path) -> None:
    r = _lancia(PROVE / "prova-1-gateway-non-esce.sh", env=_finti(tmp_path, docker=DOCKER_MUTO))
    assert r.returncode == 2, r.stdout
    assert "PASS" not in r.stdout


def test_prova_1_col_socket_chiuso_e_un_pass_misurato(tmp_path: Path) -> None:
    docker = ('case "$*" in *"ps --status running -q gateway"*) echo abc ;; '
              '*python3*) echo "CHIUSO TimeoutError" ;; *) echo NOCURL ;; esac')
    r = _lancia(PROVE / "prova-1-gateway-non-esce.sh", env=_finti(tmp_path, docker=docker))
    assert r.returncode == 0, r.stdout


def _prova_3(tmp_path: Path, codice_da_fuori: str):
    docker = 'case "$*" in *"ps --status running -q gateway"*) echo abc ;; *python3*) echo "200 DEEP" ;; esac'
    env = _finti(tmp_path, docker=docker, curl=f'printf %s "{codice_da_fuori}"')
    return _lancia(PROVE / "prova-3-health-deep-solo-interni.sh", env=env)


def test_prova_3_giudica_la_risposta_data_a_un_indirizzo_pubblico(tmp_path: Path) -> None:
    assert _prova_3(tmp_path / "a", "403").returncode == 0
    r = _prova_3(tmp_path / "b", "200")
    assert r.returncode == 1 and "FAIL" in r.stdout, r.stdout
    assert _prova_3(tmp_path / "c", "000").returncode == 2


def test_prova_3_rifiuta_una_porta_che_non_e_un_numero(tmp_path: Path) -> None:
    env = _finti(tmp_path, docker=DOCKER_MUTO) | {"GATEWAY_PORT": "8080'); import os; os.system('id"}
    r = _lancia(PROVE / "prova-3-health-deep-solo-interni.sh", env=env)
    assert r.returncode == 2 and "non è un numero" in r.stdout


def test_prova_8_senza_controprova_non_dichiara_un_pass(tmp_path: Path) -> None:
    """Un systemd che risponde «yes» a tutto: ogni direttiva torna, ma lo strumento non sa dire no."""
    env = _finti(tmp_path, systemctl='case "$1" in show) [ "$2" = --version ] || echo yes ;; esac; exit 0')
    repo = Path(env["VPS1777_REPO"])
    (repo / "systemd").mkdir()
    (repo / "systemd" / "x.service").write_text("[Service]\nNoNewPrivileges=true\n", "utf-8")
    r = _lancia(PROVE / "prova-8-le-unit-si-comportano-come-dichiarano.sh", env=env)
    assert r.returncode == 2, r.stdout
    assert "✅ PASS" not in r.stdout


def test_prova_8_con_la_controprova_passa(tmp_path: Path) -> None:
    sysctl = ('case "$1" in show) case "$*" in *NoNewPrivileges*) echo yes ;; *--version*) ;; *) echo no ;; esac ;; '
              'esac; exit 0')
    env = _finti(tmp_path, systemctl=sysctl)
    repo = Path(env["VPS1777_REPO"])
    (repo / "systemd").mkdir()
    (repo / "systemd" / "x.service").write_text("[Service]\nNoNewPrivileges=true\n", "utf-8")
    r = _lancia(PROVE / "prova-8-le-unit-si-comportano-come-dichiarano.sh", env=env)
    assert r.returncode == 0, r.stdout


# ── ancoraggi statici ──────────────────────────────────────────────────────────

def test_il_repo_si_trova_con_la_stessa_riga_in_tutte_le_prove() -> None:
    for p in sorted(PROVE.glob("prova-*.sh")):
        righe = [r for r in p.read_text("utf-8").splitlines() if r.startswith("REPO=")]
        assert all(r == RIGA_REPO for r in righe), f"{p.name}: la riga che trova il repo è diversa dalle altre"


def test_le_prove_datano_in_utc() -> None:
    for p in sorted(PROVE.glob("prova-*.sh")):
        assert "$(date '+" not in p.read_text("utf-8"), f"{p.name}: data in ora locale"


def test_la_frase_che_prova_9_cerca_nel_log_esiste_nel_codice() -> None:
    """prova-9 riconosce il rifiuto del gate da una frase del log: se la CLI la cambia, lo si vede qui."""
    frase = "collaudo: fallimento forzato"
    assert frase in (PROVE / "prova-9-il-fail-closed-torna-indietro-davvero.sh").read_text("utf-8")
    assert frase in (ROOT / "tools" / "vps1777.py").read_text("utf-8")


def test_prova_6_non_copia_il_volume_intero() -> None:
    """Il dump serve a distinguere «dati» da «vuoto»: ha un tetto, non copia gigabyte in /tmp."""
    testo = (PROVE / "prova-6-sandbox-strict-regge-sul-kernel.sh").read_text("utf-8")
    assert "head -c 1048576" in testo
    assert "tar cf /dst/dump.tar ." not in testo
