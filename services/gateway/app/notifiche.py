"""La coda degli avvisi del gateway per il proprietario, che il bot preleva.

Il gateway non parla con Telegram, per scelta: il token del bot non lo monta (H54) e
nel suo codice non c'è `api.telegram.org`. Quando ha qualcosa da dire al proprietario,
oggi un connettore OAuth appena autorizzato, lo mette in questa coda su disco; il bot la
preleva da `GET /internal/notifications` del gateway, come già fa con quella di
nb1777-mcp, e la manda. Un avviso prelevato esce dalla coda; la coda tiene al massimo
gli ultimi 50.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .audit import audit
from .settings import get_settings

_MAX = 50


def _file() -> Path:
    # accanto all'audit log, sul volume persistente /var/lib/gateway
    return Path(get_settings().audit_log_path).parent / "notifiche.json"


def _leggi() -> list[dict[str, Any]]:
    """La coda. Un file ASSENTE è una coda vuota; un file che c'è ma non si legge, o che non è
    una lista, NON lo è: si dice nell'audit e si mette da parte (`.illeggibile`), perché la
    prossima scrittura lo cancellerebbe senza traccia."""
    f = _file()
    try:
        testo = f.read_text()
    except FileNotFoundError:
        return []
    except OSError as exc:
        audit({"event": "notifiche_unreadable", "error": str(exc)})
        return []
    try:
        dati = json.loads(testo)
        if not isinstance(dati, list):
            raise ValueError("la coda non è una lista")
    except ValueError as exc:
        try:
            os.replace(f, f.with_name(f.name + ".illeggibile"))
            esito = "messa da parte"
        except OSError as exc2:
            esito = f"non messa da parte ({exc2})"
        audit({"event": "notifiche_unreadable", "error": f"{exc}; {esito}"})
        return []
    return [x for x in dati if isinstance(x, dict)]


def _scrivi(items: list[dict[str, Any]]) -> bool:
    """True se la coda è su disco. Il file provvisorio si porta su disco (fsync) PRIMA della
    rinomina: senza, dopo un crash il nome nuovo poteva puntare a un file vuoto, che `_leggi`
    metteva da parte come illeggibile, e gli avvisi in coda erano persi."""
    f = _file()
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(items, ensure_ascii=False))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, f)
        return True
    except OSError as exc:  # non fatale: l'avviso si perde, l'audit lo dice
        audit({"event": "notifiche_persist_error", "error": str(exc)})
        return False


def accoda(kind: str, text: str) -> None:
    items = _leggi()
    items.append({"kind": kind, "text": text, "ts": int(time.time())})
    _scrivi(items[-_MAX:])


# Gli avvisi già consegnati che NON si è riusciti a togliere dal disco (disco pieno, permessi).
# Senza questo elenco restavano in coda e il bot li rimandava a ogni prelievo, per sempre.
_consegnati_non_tolti: list[dict[str, Any]] = []


def preleva() -> list[dict[str, Any]]:
    global _consegnati_non_tolti
    items = _leggi()
    if _consegnati_non_tolti:
        gia = list(_consegnati_non_tolti)
        nuovi = []
        for x in items:                 # si toglie UNA copia per ogni avviso già consegnato
            if x in gia:
                gia.remove(x)
            else:
                nuovi.append(x)
        items_su_disco, items = items, nuovi
    else:
        items_su_disco = items
    if items_su_disco:
        _consegnati_non_tolti = [] if _scrivi([]) else items_su_disco
    return items
