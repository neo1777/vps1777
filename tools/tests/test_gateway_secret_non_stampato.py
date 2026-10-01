"""H77: il gateway_secret si consegna come la password admin di H75.

Il 30/09 (H76) il gateway_secret IN USO è stato trovato in chiaro nell'archivio: righe
`RESULT_SECRET=…` di deploy.sh e URL dei connettori, incollate in chat. E
`rotate-secret.sh gateway_secret` lo stampava di nuovo con `ok "Nuovo gateway_secret: …"`:
lanciato da un agente, il segreto nuovo sarebbe finito nel transcript, e da lì
nell'archivio, la sera stessa della rotazione. Stessa cura di H75: davanti a un terminale
si stampa; altrimenti va in un file 600 e si stampa il percorso.
"""
from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]
SCRIPT = {"deploy.sh": RADICE / "deploy.sh", "rotate-secret.sh": RADICE / "tools" / "rotate-secret.sh"}
FINTO = "Gw" + "Fin7o" + "Segre7o" + "Lungo" + "42xyz"


def _funzione(testo: str) -> str:
    m = re.search(r"^consegna_gateway_secret\(\) \{\n.*?^\}\n", testo, re.M | re.S)
    assert m, "consegna_gateway_secret non trovata"
    return m.group(0)


def test_la_funzione_e_la_stessa_nei_due_script() -> None:
    corpi = {nome: _funzione(p.read_text()) for nome, p in SCRIPT.items()}
    assert len(set(corpi.values())) == 1, "consegna_gateway_secret diverge fra gli script"


def test_fuori_dal_terminale_il_segreto_va_in_un_file_600_con_le_url(tmp_path: Path) -> None:
    for nome, p in SCRIPT.items():
        casa = tmp_path / nome
        casa.mkdir()
        prologo = ("set -euo pipefail\nC_B=; C_R=\n"
                   "warn() { printf '[!] %s\\n' \"$*\"; }\n")
        ambiente = {k: v for k, v in os.environ.items() if k != "XDG_CONFIG_HOME"}
        ambiente["HOME"] = str(casa)
        r = subprocess.run(
            ["bash", "-c", prologo + _funzione(p.read_text())
             + f"consegna_gateway_secret '{FINTO}' 'https://vps.example.invalid'\n"
             + 'printf "mostrato=%s\\nfile=%s\\n" "$GW_SEGRETO_MOSTRATO" "$GW_SEGRETO_FILE"\n'],
            capture_output=True, text=True, env=ambiente, check=False)
        assert r.returncode == 0, (nome, r.stderr)
        assert FINTO not in r.stdout + r.stderr, f"{nome}: il segreto è uscito sull'output"
        file = list((casa / ".config" / "vps1777").glob("gateway-secret-*.txt"))
        assert len(file) == 1, (nome, r.stdout)
        corpo = file[0].read_text()
        assert FINTO in corpo
        assert f"https://vps.example.invalid/{FINTO}/archive/mcp" in corpo
        assert f"https://vps.example.invalid/{FINTO}/nb1777/mcp" in corpo
        assert stat.S_IMODE(file[0].stat().st_mode) == 0o600, nome
        assert f"file={file[0]}" in r.stdout, f"{nome}: il percorso va detto"


def test_nessuno_script_stampa_il_segreto_fuori_dalla_funzione() -> None:
    chiaro = re.compile(r"\$\{?(GATEWAY_SECRET|NEW)\}?(?!\w)")
    stampa = re.compile(r"^\s*(\[.*\]\s*&&\s*)?(log|warn|ok|echo|printf)\b|^\s*\d\.\s|<URL>/")
    for nome, p in SCRIPT.items():
        testo = p.read_text().replace(_funzione(p.read_text()), "")
        # `echo -n "$NEW" > "$FILE"` scrive il file del segreto: non è una stampa
        colpevoli = [r for r in testo.splitlines() if stampa.search(r) and chiaro.search(r)
                     and not re.search(r'>\s*"\$', r)]
        assert not colpevoli, (nome, colpevoli)
