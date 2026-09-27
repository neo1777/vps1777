"""L'immagine di nb1777-mcp non installa un browser.

Fino alla 0.60.0 il Dockerfile installava `chromium` più le librerie di Playwright «per
nlm headless». Misurato il 27/09/2026: il server non lancia mai il browser (lo usa solo
il refresh headless di nlm, che da #333 è spento con
`NOTEBOOKLM_DISABLE_HEADLESS_REFRESH=1`, e che in ogni caso ha bisogno di un profilo di
browser salvato che nel container non c'è: da `/admin/nlm` arrivano solo i cookie), e
col rootfs in sola lettura `docker diff` non mostra una sola scrittura da browser.
Chromium pesava 376 MB su 902 MB dell'immagine, ed era superficie d'attacco senza uso.

Se un giorno servisse davvero un browser nel container, questo test va cambiato insieme
alla ragione, non aggirato.
"""
from __future__ import annotations

import re
from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[2] / "services" / "nb1777-mcp" / "Dockerfile"


def _istruzioni() -> str:
    # solo le istruzioni, senza commenti: il perché di una rimozione si può scrivere
    return "\n".join(r for r in DOCKERFILE.read_text().splitlines()
                     if not r.lstrip().startswith("#"))


def test_nessun_browser_installato():
    trovati = re.findall(r"\b(chromium|chrome|firefox|playwright)\b", _istruzioni(), re.I)
    assert not trovati, f"il Dockerfile di nb1777-mcp installa di nuovo un browser: {trovati}"


def test_restano_tini_e_i_certificati():
    istr = _istruzioni()
    assert "tini" in istr and "ca-certificates" in istr
