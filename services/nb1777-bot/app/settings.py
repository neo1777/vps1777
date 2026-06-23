from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import BeforeValidator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _read_file(value: str | None) -> str:
    if not value:
        return ""
    p = Path(value)
    return p.read_text(encoding="utf-8").strip() if p.is_file() else ""


SecretFromFile = Annotated[str, BeforeValidator(_read_file)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    telegram_bot_token_file: SecretFromFile = ""
    telegram_bot_token: str = ""
    telegram_owner_id: int = 0
    gateway_public_base: str = ""
    nb1777_mcp_url: str = "http://nb1777-mcp:8003/mcp"
    nlm_home: str = "/var/lib/nlm"
    log_level: str = "INFO"

    @property
    def effective_token(self) -> str:
        return self.telegram_bot_token or self.telegram_bot_token_file


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
