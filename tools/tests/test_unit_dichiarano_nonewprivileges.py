"""Ogni unit systemd DICHIARA `NoNewPrivileges`. Ometterlo non è una scelta.

🔓 PERCHÉ ESISTE — un guasto vero, non un'ipotesi. Il 03/08 alle 04:32 l'auto-update
   della VPS è fallito:

       sudo: The "no new privileges" flag is set, which prevents sudo from
       running as root.

   `vps1777-auto-update.service` NON impostava `NoNewPrivileges`. L'intenzione era
   scritta nel commento in testa al file — «Perciò NIENTE NoNewPrivileges
   (romperebbe sudo/setuid)» — ed era **giusta**. È stata realizzata **togliendo la
   riga**, e systemd ha riempito lo spazio da sé: con un filtro seccomp
   (`ProtectKernelModules`, `LockPersonality`, `RestrictRealtime`…) su un servizio
   che gira come utente NON privilegiato, `NoNewPrivileges` si accende di
   conseguenza. Nessuno l'aveva impostato.

   📏 Misurato con unit transitorie sulla VPS:
       le sei direttive, come root             -> NoNewPrivs: 0
       le sei + User=<operator> (la unit vera) -> NoNewPrivs: 1
       solo User=<operator>, senza hardening   -> NoNewPrivs: 0
     => né l'hardening da solo né l'utente da solo: la COMBINAZIONE.

   ⚠️ E `systemctl show -p NoNewPrivileges` rispondeva `no` mentre il processo aveva
   `1`: riporta il valore DICHIARATO, non l'effettivo. Due fonti (il commento e
   `systemctl show`) concordavano ed erano fuorvianti; l'unica vera era lo stderr di
   sudo. *Su una proprietà di runtime il verdetto sta nel processo.*

🔑 LA REGOLA CHE QUESTO TEST IMPONE, e non è sul VALORE:
   `NoNewPrivileges=true` va benissimo dove non serve sudo (`check-update`,
   `secrets-check` ce l'hanno, con la ragione accanto). `=no` va benissimo dove
   serve. **Ciò che non va bene è l'ASSENZA**, perché l'assenza si legge come «non
   ci interessa» mentre significa «decide systemd».
   ⇒ questo test non giudica la scelta: chiede che ce ne sia una, scritta.

⚠️ COSA NON FA: non verifica il valore EFFETTIVO su una macchina viva — qui non c'è
   una macchina. Verifica che la unit dica la sua. La misura sul vivo resta
   `grep NoNewPrivs /proc/<pid>/status`, e nessun test statico può sostituirla.
"""

from __future__ import annotations

from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parents[2]
UNIT_DIR = RADICE / "systemd"


def solo_codice(testo: str) -> str:
    """Le righe che systemd esegue — i commenti no.

    ⚠️ Serve davvero: «NoNewPrivileges» compare NEL COMMENTO in testa alle unit che
    l'hanno omesso, per dire che non lo si vuole. Uno script che cerca la stringa nel
    file intero lo trova lì e conclude che c'è. È successo mentre scrivevo questo
    fix, alla prima esecuzione — e la stessa cecità era stata trovata oggi in due
    presidi diversi del repo: *la cura, spiegandosi, scrive la stringa che il
    controllo cerca.*
    """
    return "\n".join(r for r in testo.splitlines() if not r.lstrip().startswith("#"))


def unit_di_servizio() -> list[Path]:
    return sorted(p for p in UNIT_DIR.glob("*.service"))


def test_ci_sono_unit_da_controllare() -> None:
    """Zero unit non è un verde: vorrebbe dire che questo test guarda altrove."""
    assert unit_di_servizio(), (
        f"nessun *.service in {UNIT_DIR} — questo test non ha guardato niente, "
        "e un ciclo su zero elementi passa in silenzio"
    )


@pytest.mark.parametrize("unit", unit_di_servizio(), ids=lambda p: p.name)
def test_ogni_unit_DICHIARA_nonewprivileges(unit: Path) -> None:
    codice = solo_codice(unit.read_text(encoding="utf-8"))
    righe = [r.strip() for r in codice.splitlines() if r.strip().startswith("NoNewPrivileges")]
    assert righe, (
        f"{unit.name} non dichiara NoNewPrivileges.\n"
        "  Non è un dettaglio di stile: con un filtro seccomp e User= non-root "
        "systemd lo accende da sé, e `sudo` smette di funzionare — è così che si è "
        "rotto l'auto-update il 03/08.\n"
        "  Scrivi `NoNewPrivileges=true` se il servizio non ha bisogno di elevare, "
        "`=no` se usa sudo. Con la ragione accanto, come fanno le altre unit."
    )


@pytest.mark.parametrize("unit", unit_di_servizio(), ids=lambda p: p.name)
def test_la_dichiarazione_ha_una_RAGIONE_accanto(unit: Path) -> None:
    """Un flag di sicurezza senza il perché è una riga che il prossimo toglie.

    Cerca un commento nelle 25 righe che precedono la direttiva: è la forma che le
    unit già usano ("Il check non ha bisogno di privilegi: niente sudo").
    """
    righe = unit.read_text(encoding="utf-8").splitlines()
    idx = [i for i, r in enumerate(righe)
           if r.strip().startswith("NoNewPrivileges") and not r.lstrip().startswith("#")]
    if not idx:
        pytest.skip("assenza già coperta dal test qui sopra — qui non aggiungerei nulla")
    i = idx[0]
    contesto = righe[max(0, i - 25):i]
    assert any(r.lstrip().startswith("#") and len(r.strip()) > 12 for r in contesto), (
        f"{unit.name}: NoNewPrivileges è dichiarato ma senza una ragione scritta sopra.\n"
        "  Un flag di sicurezza nudo è una riga che il prossimo toglie «per pulizia»."
    )
