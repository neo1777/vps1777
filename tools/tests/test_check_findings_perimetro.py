"""Test del PERIMETRO di `security/check_findings.py` — quali file hanno commenti.

Perché esiste: `solo_in_commenti()` è la guardia che impedisce a un `contains:` di
essere soddisfatto da una riga commentata — cioè al gate di restare verde mentre il
codice che dovrebbe presidiare non c'è più. Ma decideva **per suffisso**, e
`Path(".env.example").suffix` è `".example"`: quel file restava fuori dal perimetro
benché `#` sia il suo carattere di commento.

🔴 CASO VIVO MISURATO il 02/08: H49 (`closed`) portava `VPS1777_REQUIRE_COSIGN` come
`contains:` su `.env.example`, dove compare su una riga sola ed è **commentata**. La
guardia non guardava, e nessuno poteva accorgersene.
⭐ La forma è quella misurata sei volte quella notte: **il presidio riconosceva i file
dalla FORMA DEL NOME**, e chi aveva una forma diversa (`.env.example`, `Dockerfile`,
`Caddyfile` — che un suffisso non ce l'hanno affatto) restava fuori senza che nessuno
l'avesse deciso.

📌 Vive in `tools/tests/` perché è lì che la CI lancia pytest; `check_findings.py`
gira in CI come script a sé (`ci.yml:89`) e non aveva test propri.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_GATE = _ROOT / "security" / "check_findings.py"

sys.path.insert(0, str(_ROOT / "security"))
_spec = importlib.util.spec_from_file_location("check_findings", _GATE)
cf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cf)


def test_i_file_che_usano_hash_come_commento_sono_nel_perimetro():
    for nome in (".env.example", ".env", "Dockerfile", "Caddyfile", "Makefile",
                 "compose.yaml", "deploy.sh", "vps1777.py", "unit.service",
                 "config.toml", "app.ini", "nginx.conf"):
        assert cf._ha_commenti_hash(Path(nome)), (
            f"{nome} usa `#` come commento ma resta fuori dal perimetro: un "
            f"`contains:` su questo file può essere soddisfatto da una riga commentata"
        )


def test_i_file_SENZA_commenti_restano_fuori():
    # Il verso opposto, e non è un dettaglio: nei `.md` un `contains` è SEMPRE una
    # citazione — trattarli come codice produrrebbe falsi rossi su tutta la doc,
    # e un gate che grida al lupo viene spento.
    for nome in ("SECURITY.md", "README.md", "dati.json", "archivio.db", "logo.png"):
        assert not cf._ha_commenti_hash(Path(nome)), nome


def test_il_caso_vivo_H49_ora_sarebbe_visto():
    """Sul file VERO del repo, non su un finto: la guardia deve accorgersene."""
    env = _ROOT / ".env.example"
    if not env.is_file():                      # pragma: no cover
        import pytest
        pytest.skip(".env.example assente")
    assert cf.solo_in_commenti(env, "VPS1777_REQUIRE_COSIGN"), (
        "l'ago compare solo su una riga commentata e la guardia non lo vede: "
        "è esattamente il buco che questo perimetro chiude"
    )


def test_il_gate_intero_resta_VERDE_sul_repo_vero():
    """Controprova d'insieme: estendere il perimetro non deve accendere falsi rossi.

    L'evidenza di H49 è stata spostata sotto `ricevute:` — il canale per gli aghi che
    DEVONO stare in un commento — che è quello che il messaggio d'errore del gate
    stesso prescrive. Se qualcuno la riportasse sotto `contains:`, questo test cade.
    """
    import subprocess
    res = subprocess.run([sys.executable, str(_GATE)], capture_output=True, text=True)
    assert res.returncode == 0, (
        f"il gate è rosso sul repo vero (exit {res.returncode}):\n{res.stdout[-1200:]}"
    )
    assert "PRESIDIO NEI COMMENTI" not in res.stdout, res.stdout[-600:]
