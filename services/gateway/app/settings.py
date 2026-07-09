"""
Configuration via pydantic-settings.

Carica da env var + (per i secret) da file. Mai mette i secret in env.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, BeforeValidator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _read_secret_file(value: str | None) -> str:
    """
    Validator per i campi *_FILE: legge il contenuto del file e ritorna la
    stringa (strippata). Se il file non esiste, ritorna stringa vuota.
    """
    if not value:
        return ""
    p = Path(value)
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8").strip()


SecretFromFile = Annotated[str, BeforeValidator(_read_secret_file)]


def _csv_list(value: str | list[str] | None) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return value
    return [x.strip() for x in value.split(",") if x.strip()]


# NoDecode: impedisce a pydantic-settings di fare json.loads() sul valore env
# prima del validator (i nostri campi sono CSV, non JSON).
CSVList = Annotated[list[str], NoDecode, BeforeValidator(_csv_list)]


def _int_or_zero(value: object) -> int:
    """TELEGRAM_OWNER_ID="" (env non settata) → 0, invece di ValidationError."""
    if value is None or value == "":
        return 0
    try:
        return int(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return 0


IntOrZero = Annotated[int, BeforeValidator(_int_or_zero)]


def _parse_upstreams(value: str | dict[str, str] | None) -> dict[str, str]:
    """
    Parsa "archive=archive-mcp:8002,nb1777=nb1777-mcp:8003" in
    {"archive": "archive-mcp:8002", "nb1777": "nb1777-mcp:8003"}.
    Supporta anche `name:host:port` (legacy stack-1777 style).
    """
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    out: dict[str, str] = {}
    for spec in value.split(","):
        spec = spec.strip()
        if not spec:
            continue
        if "=" in spec:
            name, target = spec.split("=", 1)
        elif spec.count(":") >= 2:
            name, host, port = spec.split(":", 2)
            target = f"{host}:{port}"
        else:
            # malformato — skip
            continue
        out[name.strip()] = target.strip()
    return out


Upstreams = Annotated[dict[str, str], NoDecode, BeforeValidator(_parse_upstreams)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,         # .env è gestito da compose, non da qui
        case_sensitive=False,  # GATEWAY_HOST = gateway_host
        extra="ignore",
    )

    # ───── server ─────
    gateway_host: str = "0.0.0.0"
    gateway_port: int = 8080
    gateway_public_base: str = ""
    log_level: str = "INFO"

    # ───── routing ─────
    gateway_upstreams: Upstreams = Field(default_factory=dict)
    gateway_secret_file: SecretFromFile = ""
    gateway_secret: str = ""  # override via env in dev

    # ───── OAuth ─────
    oauth_required: bool = True
    oauth_access_token_lifetime: int = 900
    oauth_refresh_token_lifetime: int = 2_592_000
    oauth_admin_cookie_lifetime: int = 8 * 3600  # 8h
    oauth_miniapp_token_lifetime: int = 3600     # 1h
    oauth_allowed_emails: CSVList = Field(default_factory=list)
    oauth_cors_origins: CSVList = Field(default_factory=lambda: ["https://claude.ai"])
    oauth_signing_secret_file: SecretFromFile = ""
    oauth_signing_secret: str = ""
    oauth_pwd_hash_file: SecretFromFile = ""
    oauth_pwd_hash: str = ""

    # ───── Telegram (per Mini App) ─────
    telegram_bot_token_file: SecretFromFile = ""
    telegram_bot_token: str = ""
    # owner-only: la Mini App emette un token solo per QUESTO utente Telegram
    # (0 = non configurato → nessuna restrizione, come il bot). Difesa in
    # profondità: il bot mostra il bottone solo all'owner, ma il server verifica
    # comunque l'id — non ci si fida del solo client.
    telegram_owner_id: IntOrZero = 0

    # ───── Storage ─────
    audit_log_path: str = "/var/lib/gateway/audit.jsonl"
    nlm_auth_dir: str = "/var/lib/nlm"
    onboarding_dir: str = "/var/lib/onboarding"  # bind-mount condiviso col PC (deploy.sh --apply)
    # dir dei DB di archive-mcp: il gateway scrive qui i .db indicizzati da
    # /admin/archive; archive-mcp li scopre (scan-mode). Volume condiviso.
    archive_db_dir: str = "/var/lib/archive/db"

    # ───── helpers ─────

    @property
    def effective_gateway_secret(self) -> str:
        return self.gateway_secret or self.gateway_secret_file

    @property
    def effective_signing_secret(self) -> str:
        return self.oauth_signing_secret or self.oauth_signing_secret_file

    @property
    def effective_pwd_hash(self) -> str:
        return self.oauth_pwd_hash or self.oauth_pwd_hash_file

    @property
    def effective_bot_token(self) -> str:
        return self.telegram_bot_token or self.telegram_bot_token_file

    @property
    def admin_email(self) -> str:
        return self.oauth_allowed_emails[0].lower() if self.oauth_allowed_emails else ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
