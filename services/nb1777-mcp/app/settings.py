from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import BeforeValidator, Field
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _csv(value: str | list[str] | None) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return value
    return [x.strip() for x in value.split(",") if x.strip()]


def _read_secret_file(value: str | None) -> str:
    """Campi *_FILE: legge il file (Docker secret) e ritorna il contenuto strippato."""
    if not value:
        return ""
    p = Path(value)
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8").strip()


# NoDecode: niente json.loads sul valore env prima del validator (è CSV).
CSVList = Annotated[list[str], NoDecode, BeforeValidator(_csv)]
SecretFromFile = Annotated[str, BeforeValidator(_read_secret_file)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    nb1777_host: str = "0.0.0.0"
    nb1777_port: int = 8003
    nb1777_transport: str = "streamable-http"
    nb1777_allowed_origins: CSVList = Field(
        default_factory=lambda: ["https://claude.ai", "https://web.telegram.org"],
    )
    nlm_home: str = "/var/lib/nlm"
    fastmcp_stateless_http: bool = True
    log_level: str = "INFO"

    # Segreto condiviso col gateway (e col bot) per gli endpoint INTERNI
    # /internal/nlm/*: nb1777-mcp è l'unico a montare il volume dei cookie
    # Google (H6), gli altri chiedono qui. Si riusa il `gateway_secret` — che
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
