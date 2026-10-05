"""Conferma in due tempi per le cancellazioni di nb1777 (05/10/2026, Neo).

Un notebook, una fonte o un artefatto cancellati su NotebookLM non tornano. Come fa
notebooklm-py, la prima chiamata non cancella: dice cosa sparirebbe e dà un gettone; la
seconda cancella solo con quel gettone. Il gettone è un HMAC su (azione, id, scadenza)
con una chiave nata col processo: non si conserva niente, vale 5 minuti, e un riavvio
lo invalida (si richiede l'anteprima, nient'altro si perde).
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time

DURATA_S = 300
_CHIAVE = secrets.token_bytes(32)


def _firma(azione: str, ids: tuple[str, ...], scade: int) -> str:
    msg = "\x1f".join((azione, *ids, str(scade))).encode()
    return hmac.new(_CHIAVE, msg, hashlib.sha256).hexdigest()[:24]


def gettone(azione: str, *ids: str, ora: float | None = None) -> str:
    scade = int(time.time() if ora is None else ora) + DURATA_S
    return f"{scade}.{_firma(azione, ids, scade)}"


def verifica(valore: str, azione: str, *ids: str, ora: float | None = None) -> str | None:
    """None se il gettone vale per questa azione e questi id; altrimenti il motivo."""
    try:
        scade_txt, firma = str(valore).split(".", 1)
        scade = int(scade_txt)
    except ValueError:
        return "il gettone di conferma non vale: richiedi l'anteprima senza `conferma`"
    if not hmac.compare_digest(firma, _firma(azione, ids, scade)):
        return ("il gettone di conferma non vale per questa cancellazione (altri id, "
                "altra azione, o il server è ripartito): richiedi l'anteprima senza `conferma`")
    if (time.time() if ora is None else ora) > scade:
        return "il gettone di conferma è scaduto (5 minuti): richiedi di nuovo l'anteprima"
    return None
