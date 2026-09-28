"""La password admin generata non si stampa quando l'output non va a un terminale (H75).

28/09/2026: misurando la redazione su 58.886 snippet veri dell'archivio è ricomparsa, in
chiaro, una password admin stampata da `setup.sh`. Non c'era un buco nella redazione: lo
script la scriveva sull'output, l'output l'ha letto un agente, il transcript dell'agente è
finito nell'archivio. Un installer che mostra la password una volta va bene a un umano
davanti al terminale; quando l'output va altrove (un agente, una pipe, un log) diventa una
copia della password che nessuno ricorda di avere.

Ora `consegna_password` la stampa solo se lo stdout è un terminale; altrimenti la scrive in
un file 600 sotto `~/.config/vps1777/` e stampa il percorso. La funzione è la stessa nei
tre script che generano una password admin: questo test la estrae da ognuno e la lancia
con lo stdout in pipe (cioè come la lancia un agente).
"""
from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = {
    "setup.sh": ROOT / "setup.sh",
    "deploy.sh": ROOT / "deploy.sh",
    "rotate-secret.sh": ROOT / "tools" / "rotate-secret.sh",
}
FINTA = "Xq7-pass-FINTA-9vLr2mWz"


def _funzione(testo: str) -> str:
    m = re.search(r"^consegna_password\(\) \{\n.*?^\}\n", testo, re.M | re.S)
    assert m, "consegna_password() non c'è"
    return m.group(0)


def test_la_funzione_e_la_stessa_nei_tre_script() -> None:
    corpi = {nome: _funzione(p.read_text()) for nome, p in SCRIPT.items()}
    assert len(set(corpi.values())) == 1, "consegna_password diverge fra gli script"


def test_fuori_dal_terminale_la_password_va_in_un_file_600(tmp_path: Path) -> None:
    for nome, p in SCRIPT.items():
        casa = tmp_path / nome
        casa.mkdir()
        prologo = ("set -euo pipefail\nC_B=; C_R=\n"
                   "warn() { printf '[!] %s\\n' \"$*\"; }\n")
        ambiente = {k: v for k, v in os.environ.items() if k != "XDG_CONFIG_HOME"}
        ambiente["HOME"] = str(casa)
        r = subprocess.run(
            ["bash", "-c", prologo + _funzione(p.read_text()) + f"consegna_password '{FINTA}'\n"],
            capture_output=True, text=True, env=ambiente, check=False)
        assert r.returncode == 0, (nome, r.stderr)
        assert FINTA not in r.stdout + r.stderr, f"{nome}: la password è uscita sull'output"
        file = list((casa / ".config" / "vps1777").glob("admin-password-*.txt"))
        assert len(file) == 1, (nome, r.stdout)
        assert file[0].read_text().strip() == FINTA, nome
        assert stat.S_IMODE(file[0].stat().st_mode) == 0o600, nome
        assert str(file[0]) in r.stdout, f"{nome}: il percorso va detto"


def test_nessuno_script_stampa_la_password_fuori_dalla_funzione() -> None:
    # Le variabili che portano il chiaro in ciascuno script: nessuna riga che stampa
    # (log/warn/ok/echo/printf) le interpola, fuori da consegna_password.
    chiaro = re.compile(r"\$\{?(ADMIN_PWD|ADMIN_PWD_PLAIN|GENERATED_PWD|PWD)\}?(?!\w)")
    stampa = re.compile(r"^\s*(\[.*\]\s*&&\s*)?(log|warn|ok|echo|printf)\b")
    for nome, p in SCRIPT.items():
        testo = p.read_text().replace(_funzione(p.read_text()), "")
        colpevoli = [r for r in testo.splitlines() if stampa.search(r) and chiaro.search(r)]
        assert not colpevoli, (nome, colpevoli)
