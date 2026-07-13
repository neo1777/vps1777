"""
Redazione dei segreti dai log — stdlib-only, testabile senza il runtime.

Il gateway espone il reverse-proxy MCP su `/<GATEWAY_SECRET>/<service>/…`: il
secret è nel PATH, e quindi finisce nella request line dell'access-log di
uvicorn (e a valle in Caddy/Cloudflare). Un log d'accesso con dentro il secret
è un leak continuo — ogni chiamata MCP legittima lo deposita in chiaro.

Questo filtro di logging lo sostituisce con `***` in ogni record che passa
dagli handler a cui è agganciato. È una difesa a valle: NON sostituisce la
rotazione del secret, ma smette di produrne di nuovi in chiaro.
"""
from __future__ import annotations

import logging


class RedactSecrets(logging.Filter):
    """Sostituisce le stringhe-segreto con `***` nel testo formattato del record.

    Riceve la lista dei segreti (già risolti). I vuoti sono ignorati. Il replace
    avviene sul messaggio già interpolato (`record.getMessage()`), poi si azzerano
    gli args perché il messaggio è ora una stringa letterale."""

    def __init__(self, secrets: list[str]) -> None:
        super().__init__()
        # ordina per lunghezza decrescente: se un segreto è prefisso di un altro,
        # il più lungo va sostituito prima (evita redazioni parziali).
        self._secrets = sorted({s for s in secrets if s}, key=len, reverse=True)

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._secrets:
            return True
        msg = record.getMessage()
        red = msg
        for sec in self._secrets:
            if sec in red:
                red = red.replace(sec, "***")
        if red != msg:
            record.msg = red
            record.args = ()
        return True  # non scarta mai: reda e lascia passare


def install(secrets: list[str]) -> None:
    """Aggancia RedactSecrets a tutti gli handler del root logger (dove uvicorn
    con log_config=None emette anche l'access-log). Idempotente per handler."""
    filt = RedactSecrets(secrets)
    root = logging.getLogger()
    for h in root.handlers:
        if not any(isinstance(f, RedactSecrets) for f in h.filters):
            h.addFilter(filt)
