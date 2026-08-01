"""Test della riga più delicata di `onboarding.py` — il pannello «cosa manca».

Perché esiste: `onboarding.py` non aveva alcun test, e dichiarava «Funnel attivo»
deducendolo da `.ts.net` in `PUBLIC_BASE` — una stringa del `.env` che non cambia
mai se l'auth-key scade, se il nodo esce dal tailnet o se qualcuno spegne il Funnel
per manutenzione. È il gemello del difetto curato in `90fd647` sull'installer,
sopravvissuto in un secondo file: **la cura non si era propagata.**

📌 PERCHÉ È UN TEST SUL SORGENTE E NON SUL COMPORTAMENTO, ed è una scelta e non una
resa: `onboarding.py` usa import relativi e vuole starlette, mentre questa suite è
**stdlib-only per progetto** — il job che la lancia si chiama «(gateway, stdlib-only)»
e non installa le dipendenze del servizio. La prima stesura di questo file provava
il comportamento e girava `2 skipped`: cioè **silenzio**, che è esattamente la classe
che ci è costata cinque giorni di CI spenta. Meglio una domanda più piccola a cui si
può rispondere sempre, che una grande a cui non risponde nessuno.
"""
from __future__ import annotations

from pathlib import Path

_MOD = Path(__file__).resolve().parents[1] / "app" / "onboarding.py"


def _corpo() -> str:
    """Il sorgente senza le righe di commento: i commenti CITANO la forma vecchia."""
    return "\n".join(
        r for r in _MOD.read_text(encoding="utf-8").splitlines()
        if not r.lstrip().startswith("#")
    )


def test_il_pannello_non_dichiara_ATTIVO_cio_che_ha_solo_dedotto():
    # Era esattamente questa coppia, ed è la riga che l'utente legge quando apre
    # /admin/setup per sapere che cosa gli manca ancora.
    assert '("ok", "Funnel attivo")' not in _corpo(), (
        "il pannello torna a dichiarare ATTIVO il Funnel sulla base di PUBLIC_BASE: "
        "è una stringa del .env, non una misura"
    )


def test_la_deduzione_e_dichiarata_a_chi_legge_la_pagina():
    # Non basta togliere il verde: l'utente deve sapere PERCHÉ è giallo, altrimenti
    # legge «warn» come «qualcosa è rotto» e va a cercare un guasto che non c'è.
    corpo = _corpo()
    assert "non verificato" in corpo.lower(), (
        "il testo mostrato deve dire che non è stato misurato da qui"
    )


def test_il_ramo_negativo_resta_distinto_dal_dubbio():
    # Il verso opposto: la cura non deve trasformare «assente» in «forse».
    # Tre stati e non due — configurato-e-verificato, configurato-e-non-verificato,
    # non configurato — è la stessa distinzione di `prova-8` (PASS/FAIL/non eseguibile).
    assert '("off", "non configurato")' in _corpo(), (
        "senza URL .ts.net lo stato deve restare «non configurato», non «dubbio»"
    )
