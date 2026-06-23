from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import BeforeValidator, Field
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _csv(value: str | list[str] | None) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return value
    return [x.strip() for x in value.split(",") if x.strip()]


# NoDecode: niente json.loads sul valore env prima del validator (è CSV).
CSVList = Annotated[list[str], NoDecode, BeforeValidator(_csv)]


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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
