from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import BeforeValidator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _read_secret_file(value: str | None) -> str:
    """Campi *_FILE: legge il file (Docker secret) e ritorna il contenuto strippato."""
    if not value:
        return ""
    p = Path(value)
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8").strip()


# (27/09, audit della doc: tolta `nb1777_allowed_origins`, con il suo tipo CSV. Era
#  dichiarata qui, in compose.yaml e nel README, e nessun codice la leggeva: una CORS
#  che sembra configurata e non lo è. Il servizio non è mai esposto: da fuori si
#  passa dal gateway, che ha la sua CORS scoped, H31.)
SecretFromFile = Annotated[str, BeforeValidator(_read_secret_file)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    nb1777_host: str = "0.0.0.0"
    nb1777_port: int = 8003
    nb1777_transport: str = "streamable-http"
    nlm_home: str = "/var/lib/nlm"
    fastmcp_stateless_http: bool = True
    log_level: str = "INFO"
    # S8: ogni quante ore la sonda viva prova la sessione Google (0 = spenta).
    nb1777_sonda_ore: float = 4.0

    # Segreto condiviso col gateway (e col bot) per gli endpoint INTERNI
    # /internal/nlm/*: fra i servizi in esercizio nb1777-mcp è l'unico a montare il
    # volume dei cookie Google (H6), gli altri chiedono qui. Si riusa il `gateway_secret` — che
    # esiste già su ogni installazione — invece di introdurre un secret nuovo,
    # che mancherebbe agli update esistenti (compose non parte se il file non
    # c'è). Fail-closed: senza segreto, gli endpoint interni negano tutti.
    gateway_secret_file: SecretFromFile = ""
    gateway_secret: str = ""   # override via env in dev

    @property
    def effective_gateway_secret(self) -> str:
        return self.gateway_secret or self.gateway_secret_file


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
