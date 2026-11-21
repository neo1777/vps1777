"""Risposte in streaming che chiudono ciò che hanno aperto, comunque finiscano."""
from __future__ import annotations

from typing import Any

from starlette.responses import StreamingResponse


class RispostaChiusa(StreamingResponse):
    """Una risposta in streaming con una `chiusura` che gira SEMPRE alla fine. Messa solo nel
    `finally` del generatore, la chiusura non girava se il client se ne andava prima che il
    generatore partisse: connessione e client verso l'upstream restavano aperti. `chiusura` deve
    reggere due chiamate (dal generatore e da qui)."""

    def __init__(self, *args: Any, chiusura: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._chiusura = chiusura

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self._chiusura()
