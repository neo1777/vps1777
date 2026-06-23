"""
AUTH gate — check del file auth.json + AUTH_PENDING.flag prima di ogni tool.

Se auth è assente, ogni tool MCP raise `RuntimeError` con istruzioni per
l'admin panel /admin/nlm. Il client (claude.ai, Mini App, bot) riceve un
messaggio di errore leggibile.
"""
from __future__ import annotations

import os
from pathlib import Path

from .settings import get_settings


def _paths() -> tuple[Path, Path]:
    home = Path(get_settings().nlm_home)
    return home / "auth.json", home / "AUTH_PENDING.flag"


def check_or_raise() -> None:
    auth_json, pending = _paths()
    if pending.exists():
        raise RuntimeError(
            "Auth NotebookLM mancante (AUTH_PENDING). Apri /admin/nlm sul tuo "
            "gateway, login admin, carica auth.json. Sul TUO PC: `uv tool install "
            "notebooklm-mcp-cli --python 3.12 && nlm login` per generarlo."
        )
    if not auth_json.exists():
        raise RuntimeError(
            f"auth.json non presente in {auth_json}. Apri /admin/nlm sul gateway "
            "per caricarlo."
        )


def ensure_nlm_home_in_env() -> None:
    """
    Sia server.py (legacy) sia nlm CLI cercano auth.json in
    `Path.home() / ".notebooklm-mcp-cli"`. Forziamo HOME=NLM_HOME e creiamo
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
