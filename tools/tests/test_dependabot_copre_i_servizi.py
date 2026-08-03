"""Ogni servizio Python è sorvegliato da Dependabot — o il test lo nomina.

🔓 Round-16, rilievo `23cc4783`. `dependabot.yml` copriva github-actions, docker
   e docker-compose: **nessun ecosystem per Python**. Le dipendenze che il
   gateway IMPORTA — non l'immagine base, quelle dentro — non le guardava
   nessuno.

⚠️ E non è igiene: `docs/ARCHITECTURE.md` fa poggiare una delle garanzie più
   forti del prodotto (*l'IP del client non è falsificabile*) sul comportamento
   di `ProxyHeadersMiddleware`, che è un dettaglio interno di **uvicorn** — e
   `services/gateway/pyproject.toml` lo dichiara `>=0.32.0`, senza tetto, su un
   pacchetto in 0.x.

🔑 Il test guarda la RELAZIONE, non una lista: «esiste un servizio con un
   pyproject che nessun ecosystem copre?». Una lista scritta a mano invecchia
   in silenzio al primo servizio nuovo; questa domanda no.
"""
from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip(
    "yaml",
    reason="pyyaml assente: il test NON è stato eseguito. In CI c'è "
           "(`uv run --with pyyaml`), e uno skip qui non è un verde.",
)

RADICE = Path(__file__).resolve().parents[2]
DEPENDABOT = RADICE / ".github" / "dependabot.yml"
SERVIZI = RADICE / "services"


def _coperte() -> set[str]:
    """Le directory coperte da un ecosystem Python, normalizzate."""
    cfg = yaml.safe_load(DEPENDABOT.read_text(encoding="utf-8"))
    fuori: set[str] = set()
    for u in cfg.get("updates", []):
        if u.get("package-ecosystem") not in ("uv", "pip"):
            continue
        for d in (u.get("directories") or ([u["directory"]] if u.get("directory") else [])):
            fuori.add(str(d).strip("/"))
    return fuori


def test_ogni_servizio_con_pyproject_e_sorvegliato():
    servizi = {f"services/{p.parent.name}"
               for p in SERVIZI.glob("*/pyproject.toml")}
    assert servizi, "nessun servizio con pyproject trovato: il test non ha guardato niente"
    scoperti = sorted(servizi - _coperte())
    assert not scoperti, (
        f"servizi Python che NESSUN ecosystem Dependabot copre: {scoperti}. "
        "Le loro dipendenze possono avanzare senza che nessuno lo veda — ed è "
        "il rilievo 23cc4783."
    )


def test_la_sonda_SA_DIRE_DI_NO():
    """Controprova: se la copertura sparisse, il test sopra fallirebbe?

    Senza questa, `_coperte()` potrebbe restituire tutto e il verde non
    distinguerebbe «coperti» da «la sonda non guarda».
    """
    coperte = _coperte()
    assert coperte, "zero directory coperte: o la config è vuota, o la sonda è cieca"
    assert "services/inventato-che-non-esiste" not in coperte


def test_i_major_NON_entrano_da_soli():
    """Un major che entra da solo in un servizio che regge una garanzia di
    sicurezza è esattamente ciò che non vogliamo — la stessa scelta già fatta
    per le action (#48/#49) e per le immagini."""
    cfg = yaml.safe_load(DEPENDABOT.read_text(encoding="utf-8"))
    py = [u for u in cfg.get("updates", []) if u.get("package-ecosystem") in ("uv", "pip")]
    assert py, "nessun ecosystem Python: vedi il test sopra"
    for u in py:
        tipi = {t for ig in (u.get("ignore") or []) for t in (ig.get("update-types") or [])}
        assert "version-update:semver-major" in tipi, (
            "l'ecosystem Python non ignora i major: entrerebbero da soli")
