from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import BeforeValidator, Field
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _parse_db_paths(value: str | dict[str, str] | None) -> dict[str, Path]:
    """
    Parsa "name:path,name:path,..." in {name: Path}.
    Compat con la v1 del vecchio stack 1777.
    """
    if not value:
        return {}
    if isinstance(value, dict):
        return {k: Path(v) for k, v in value.items()}
    out: dict[str, Path] = {}
    for spec in value.split(","):
        spec = spec.strip()
        if not spec or ":" not in spec:
            continue
        name, path = spec.split(":", 1)
        out[name.strip()] = Path(path.strip()).expanduser()
    return out


# NoDecode: niente json.loads sul valore env prima del validator (è CSV name:path).
DBPaths = Annotated[dict[str, Path], NoDecode, BeforeValidator(_parse_db_paths)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    archive_http_host: str = "0.0.0.0"
    archive_http_port: int = 8002
    archive_db_paths: DBPaths = Field(default_factory=dict)
    # Directory scansionata per *.db (name = nome file senza estensione). Un DB
    # caricato/indicizzato qui compare SENZA restart. ARCHIVE_DB_PATHS resta
    # come override per path espliciti fuori da questa dir.
    archive_db_dir: str = "/var/lib/archive/db"
    # Modello di embedding per la ricerca ibrida (ONNX + tokenizer): artefatto sul
    # volume, come i DB e gli indici — non nell'immagine. 449 MB che non pesano su
    # ogni pull dell'immagine, e che si aggiornano senza rilasciare una versione.
    archive_model_dir: str = "/var/lib/archive/models/e5-small"
    fastmcp_stateless_http: bool = True
    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
