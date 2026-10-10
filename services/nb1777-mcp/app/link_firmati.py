"""Link firmati per scaricare un artefatto senza il pannello (P15, 10/10/2026).

`studio_download` metteva il file sul server e diceva «scaricalo da /admin/nlm»: da
claude.ai o dal telefono serviva la password del pannello. Ora ritorna anche un link
pubblico del gateway, `/scarica/<nome>?t=<gettone>`, riusabile per 30 minuti (come
notebooklm-py, ADR-0024).

Il gettone è un HMAC su (nome, scadenza) con una chiave nata col processo, come quello
della conferma: non si conserva niente, e un riavvio di nb1777 (un update) invalida i
link aperti. La chiave sta SOLO qui: il gateway non la conosce, passa nome e gettone a
`/internal/nlm/link` e questo servizio verifica. Quindi un `gateway_secret` trapelato non
basta a forgiare un link.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import quote

DURATA_S = 30 * 60
_CHIAVE = secrets.token_bytes(32)


def _firma(nome: str, scade: int) -> str:
    msg = "\x1f".join(("scarica", nome, str(scade))).encode()
    return hmac.new(_CHIAVE, msg, hashlib.sha256).hexdigest()[:32]


def gettone(nome: str, *, ora: float | None = None) -> str:
    scade = int(time.time() if ora is None else ora) + DURATA_S
    return f"{scade}.{_firma(nome, scade)}"


def verifica(valore: str, nome: str, *, ora: float | None = None) -> str | None:
    """None se il gettone vale per questo nome ed è in tempo; altrimenti il motivo."""
    try:
        scade_txt, firma = str(valore).split(".", 1)
        scade = int(scade_txt)
    except ValueError:
        return "il link non vale: chiedi un link nuovo con studio_download"
    if not hmac.compare_digest(firma, _firma(nome, scade)):
        return ("il link non vale (altro file, link modificato, o nb1777 è ripartito): "
                "chiedi un link nuovo con studio_download")
    if (time.time() if ora is None else ora) > scade:
        return "il link è scaduto (30 minuti): chiedi un link nuovo con studio_download"
    return None


def _base() -> str:
    # la stessa variabile del bot: l'indirizzo pubblico del gateway. Vuota = link relativo.
    return os.environ.get("GATEWAY_PUBLIC_BASE", "")


def link(nome: str, *, ora: float | None = None) -> dict:
    """{url, scade_il}: l'URL del gateway col gettone, e quando smette di valere."""
    t = gettone(nome, ora=ora)
    scade = int(t.split(".", 1)[0])
    return {"url": f"{_base().rstrip('/')}/scarica/{quote(nome)}?t={t}",
            "scade_il": datetime.fromtimestamp(scade, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
