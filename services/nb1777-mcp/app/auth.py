"""
AUTH gate — check del profilo nlm (profiles/default/cookies.json) + AUTH_PENDING.flag.

Il controllo vero vive in `server._check_auth_or_raise` (qui c'era un doppione mai
chiamato, tolto il 05/10/2026). Qui resta l'allineamento di HOME al volume.
"""
from __future__ import annotations

import os
from pathlib import Path

from .settings import get_settings


def ensure_nlm_home_in_env() -> None:
    """
    Sia server.py sia nlm CLI cercano il profilo (profiles/default/cookies.json)
    in `Path.home() / ".notebooklm-mcp-cli"`. Forziamo HOME=NLM_HOME e creiamo
    il symlink interno per allineare entrambi al volume montato.
    """
    home = get_settings().nlm_home
    # Forza HOME (sovrascrive il default del container)
    os.environ["HOME"] = home
    Path(home).mkdir(parents=True, exist_ok=True)
    link = Path(home) / ".notebooklm-mcp-cli"
    if not link.exists():
        try:
            link.symlink_to(home, target_is_directory=True)
        except (OSError, FileExistsError):
            pass
