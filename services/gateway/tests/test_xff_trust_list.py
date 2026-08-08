"""La garanzia «l'IP client non è più spoofabile» ha DUE gambe, e una non era presidiata.

`docs/ARCHITECTURE.md` §«IP client e header proxy» afferma:

    «L'X-Forwarded-For è fidato SOLO dai range privati + loopback … uvicorn cammina
    l'XFF da DESTRA e prende il primo host non fidato, quindi un X-Forwarded-For
    iniettato da un client pubblico viene scartato. Conseguenza: l'IP client non è
    più spoofabile e rate-limit, lockout e audit non sono più evadibili.»

```
  GAMBA 1 — NOSTRA        la trust-list non è "*"          ⇐ questi test
  GAMBA 2 — DI TERZI      uvicorn «cammina da destra»      ⇐ ../tests_runtime/ (dal 09/08)
```

**La gamba 2 è un dettaglio di implementazione di una libreria di terzi, ed è
storicamente cambiato**: versioni più vecchie di `ProxyHeadersMiddleware` prendevano
il primo elemento **da sinistra**, cioè esattamente quello che un client può iniettare.
Il vincolo in `pyproject.toml` è `>=`, quindi aperto verso l'alto — e `uvicorn` è
`0.x`, dove anche un minor può cambiare comportamento.

⭐ **Perché questi test leggono i FILE invece di importare i moduli.** In CI questa suite
gira con `uvx pytest`, che porta pytest e basta: `pydantic`, `starlette` e `uvicorn`
**non ci sono** (è la ragione per cui `test_oauth_consent.py` stubba tutto). Un test che
importasse `settings` o `uvicorn` **romperebbe questa suite**: l'import fallisce in fase
di raccolta e `pytest` esce **2**. ⇒ qui si legge il testo con `ast`, che non ha
dipendenze e gira ovunque.

📐 *Rettifica misurata il 09/08: qui c'era scritto che un test simile «non verrebbe
raccolto, e una suite che non raccoglie un test è verde». **Non è così** — provato su un
caso costruito apposta: un `import` mancante dà `ERROR … Interrupted: 1 error during
collection`, exit **2**, non verde. La conclusione (leggere con `ast`) resta giusta, ma
la ragione è l'opposta: non «passerebbe in silenzio», bensì «farebbe fallire una suite
che deve restare stdlib-only». La differenza conta per chi progetta il prossimo test:
un import nudo è un presidio che si fa sentire, non uno che tace.*

✅ **La gamba 2 non è più scoperta** (voce di registro `39b5a89d`, chiusa il 09/08):
`../tests_runtime/test_gamba2_xff_da_destra.py` ESEGUE `ProxyHeadersMiddleware` con la
trust-list letta da qui, in un job CI che gira con le deps del lock. *Questi test
coprono ciò che è NOSTRO; quelli coprono ciò che non lo è.*
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[1] / "app"
_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _default_di(nome: str, sorgente: Path) -> str | None:
    """Il valore letterale assegnato a `nome:` in un corpo di classe, via ast."""
    albero = ast.parse(sorgente.read_text(encoding="utf-8"))
    for nodo in ast.walk(albero):
        if isinstance(nodo, ast.AnnAssign) and isinstance(nodo.target, ast.Name):
            if nodo.target.id == nome and isinstance(nodo.value, ast.Constant):
                return nodo.value.value
    return None


# ───────────────────────── gamba 1: la trust-list ─────────────────────────

def test_la_trust_list_esiste_e_non_e_una_stringa_vuota():
    """Guardia sulla sonda prima che sull'oggetto: se il campo cambiasse nome, i test
    qui sotto passerebbero su `None` senza accorgersene — e un `not in None` non è
    un controllo, è un TypeError o un falso verde a seconda di come lo scrivi."""
    valore = _default_di("gateway_forwarded_allow_ips", _APP / "settings.py")
    assert valore, ("campo `gateway_forwarded_allow_ips` non trovato in settings.py: "
                    "se è stato rinominato, questi test non stanno più guardando niente")


@pytest.mark.parametrize("veleno", ["*", "0.0.0.0/0", "::/0"])
def test_la_trust_list_non_si_fida_di_chiunque(veleno):
    """`forwarded_allow_ips="*"` disattiva la garanzia SENZA togliere nulla: uvicorn
    accetta l'XFF da qualunque peer, e l'IP client torna spoofabile. Era davvero il
    valore di partenza — `settings.py` lo racconta — e un `*` rimesso «per debug»
    non lascerebbe nessun altro segno."""
    valore = _default_di("gateway_forwarded_allow_ips", _APP / "settings.py")
    voci = [v.strip() for v in str(valore).split(",")]
    assert veleno not in voci, (
        f"la trust-list contiene «{veleno}»: l'XFF torna fidato da chiunque e la "
        f"garanzia «l'IP client non è più spoofabile» diventa falsa")


def test_la_trust_list_contiene_il_loopback():
    """Controprova di polarità: una trust-list troppo stretta rompe il caso legittimo —
    il proxy d'ingresso parla al gateway da loopback o da rete privata. Un test che
    controlla solo il «non deve» finisce per benedire una lista vuota."""
    valore = str(_default_di("gateway_forwarded_allow_ips", _APP / "settings.py"))
    assert "127.0.0.1" in valore, valore


def test_proxy_headers_e_acceso_e_la_lista_arriva_da_settings():
    """La trust-list serve a qualcosa solo se `proxy_headers=True`; e il valore deve
    venire dalle settings, non essere riscritto a mano nella chiamata."""
    testo = (_APP / "__main__.py").read_text(encoding="utf-8")
    assert re.search(r"proxy_headers\s*=\s*True", testo)
    assert re.search(r"forwarded_allow_ips\s*=\s*s\.gateway_forwarded_allow_ips", testo), (
        "forwarded_allow_ips non arriva più da settings: se è un letterale nella "
        "chiamata, i test qui sopra guardano un campo che nessuno usa")


# ───────────── gamba 2: il rischio che NON copriamo, reso visibile ─────────────

def test_il_vincolo_su_uvicorn_e_dichiarato_e_non_e_sparito():
    """Non impone un upper bound — quello è una decisione che richiede di sapere quale
    versione è collaudata, e non la prendo da un test. Impone che il vincolo **esista
    con un lower bound**: la garanzia poggia sul comportamento «cammina da destra», e
    le versioni più vecchie di `ProxyHeadersMiddleware` camminavano da sinistra.

    🔑 Se un giorno il vincolo diventasse `uvicorn[standard]` nudo, questo test cade —
    ed è il solo posto del repo dove quella dipendenza è nominata come *portante di una
    garanzia di sicurezza* invece che come una riga di build.
    """
    testo = _PYPROJECT.read_text(encoding="utf-8")
    riga = next((r for r in testo.splitlines() if "uvicorn" in r), "")
    assert riga, "uvicorn non è più fra le dipendenze del gateway"
    assert re.search(r"uvicorn\[standard\]\s*>=\s*\d+\.\d+", riga), (
        f"il vincolo su uvicorn ha perso il lower bound: «{riga.strip()}». "
        f"La garanzia sull'XFF dipende dal comportamento di ProxyHeadersMiddleware, "
        f"che nelle versioni più vecchie leggeva l'XFF da SINISTRA — cioè la parte "
        f"che un client può iniettare.")


def test_la_doc_dichiara_su_cosa_poggia_la_garanzia():
    """Il presidio dell'ultimo miglio: la garanzia più forte del documento poggia su un
    dettaglio di una libreria di terzi, e chi legge deve saperlo. Se la nota sparisce,
    la frase resta e sembra autoportante."""
    doc = (Path(__file__).resolve().parents[3] / "docs" / "ARCHITECTURE.md").read_text(
        encoding="utf-8")
    assert "uvicorn" in doc and "ProxyHeadersMiddleware" in doc, (
        "docs/ARCHITECTURE.md non nomina più ProxyHeadersMiddleware: la garanzia "
        "sull'XFF torna a sembrare una proprietà della nostra configurazione")
