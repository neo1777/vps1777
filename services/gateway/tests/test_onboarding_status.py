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


def test_la_sonda_dell_host_arriva_al_pannello_ma_il_dubbio_resta_quando_manca():
    # 20/09/2026: il «passo successivo, dichiarato e NON fatto» del commento è fatto.
    # Il file lo scrive `vps1777 check` sull'host (funnel_ok esce su Internet e
    # rientra); il gateway lo legge e dice DI CHI è la misura e DI QUANDO. Senza il
    # file la riga resta «non verificato»: la cura non trasforma l'assenza in verde.
    corpo = _corpo()
    assert "raggiungibilita.json" in corpo
    assert "CHECK_STALE_H" in corpo, "una sonda vecchia deve smettere di valere, con la soglia del timer"
    assert "non verificato" in corpo.lower()


def test_i_due_lati_del_canale_nominano_lo_stesso_file():
    # Il writer (tools/vps1777.py) e il reader (onboarding.py) sono in due pacchetti
    # che non si importano: l'unico contratto è il NOME del file. Se uno lo cambia
    # e l'altro no, la pagina torna gialla in silenzio.
    cli = (Path(__file__).resolve().parents[3] / "tools" / "vps1777.py").read_text(encoding="utf-8")
    assert '_scrivi_telemetria(repo, "raggiungibilita.json"' in cli
    assert '"raggiungibilita.json"' in _corpo()
