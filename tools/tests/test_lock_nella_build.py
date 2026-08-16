"""Il lock non basta che ESISTA: deve entrare nella build — round-16, `23cc4783`.

🔴 LO STATO PRIMA, misurato e non ricordato: **nessuno dei quattro Dockerfile
   copiava `uv.lock`, e nessuno usava `--frozen`.** Due servizi il lock ce
   l'avevano nel repo (`nb1777-mcp`, `nb1777-bot`) e **la build lo ignorava**:
   versionato e mai usato. *Il file esisteva, la garanzia no.* È «l'ultimo metro»
   — «versionato» ≠ «in esecuzione» — su un file che sembra la prova di sé stesso.

🔑 E `--frozen` è la metà che conta: senza, `uv sync` **riscrive** il lock quando
   non combacia col pyproject, e la build torna a decidere da sé. Con `--frozen`
   fallisce e lo dice — che è ciò che un lock deve fare.

⚠️ Questo test legge i Dockerfile: dice che il lock è CABLATO, non che la build
   sia riproducibile. *Un verde qui è «il comando è scritto giusto».*
"""
from __future__ import annotations

from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parents[2]
SERVIZI = sorted(p.parent for p in (RADICE / "services").glob("*/Dockerfile"))


def test_ci_sono_servizi_da_guardare():
    """Se questa lista fosse vuota i test sotto passerebbero senza guardare niente."""
    assert SERVIZI, "nessun servizio con Dockerfile: il test non ha misurato nulla"


@pytest.mark.parametrize("servizio", SERVIZI, ids=lambda p: p.name)
def test_ogni_servizio_ha_il_lock(servizio: Path):
    assert (servizio / "uv.lock").is_file(), (
        f"{servizio.name} non ha uv.lock: ogni ricostruzione risolve le "
        "dipendenze da capo e può prendere una minore nuova senza che nessuno "
        "lo veda. È il rilievo 23cc4783.")


@pytest.mark.parametrize("servizio", SERVIZI, ids=lambda p: p.name)
def test_il_Dockerfile_COPIA_il_lock(servizio: Path):
    """Averlo nel repo e non copiarlo è il caso che abbiamo trovato: due su quattro."""
    testo = (servizio / "Dockerfile").read_text(encoding="utf-8")
    assert "uv.lock" in testo, (
        f"{servizio.name}: il Dockerfile non copia uv.lock. Il file c'è e la "
        "build lo ignora — versionato e mai usato.")


@pytest.mark.parametrize("servizio", SERVIZI, ids=lambda p: p.name)
def test_uv_sync_e_FROZEN(servizio: Path):
    """Senza --frozen, `uv sync` riscrive il lock e la build torna a decidere."""
    righe = [r for r in (servizio / "Dockerfile").read_text(encoding="utf-8").splitlines()
             if "uv sync" in r and not r.lstrip().startswith("#")]
    assert righe, f"{servizio.name}: nessun `uv sync` trovato — il test non ha guardato niente"
    nudi = [r.strip() for r in righe if "--frozen" not in r]
    assert not nudi, (
        f"{servizio.name}: `uv sync` senza --frozen ⇒ il lock verrebbe RISCRITTO "
        f"invece di rispettato. Righe: {nudi}")


def test_la_sonda_SA_DIRE_DI_NO():
    """Controprova: su un Dockerfile finto senza lock, gli assert devono fallire."""
    finto = "FROM python:3.12-slim\nCOPY pyproject.toml ./\nRUN uv sync --no-dev\n"
    assert "uv.lock" not in finto
    assert [r for r in finto.splitlines() if "uv sync" in r and "--frozen" not in r]
