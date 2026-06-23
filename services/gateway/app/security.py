"""
Wrapper bcrypt per verifica password admin. Funzione separata per testabilità.
"""
from __future__ import annotations

import bcrypt

from .settings import get_settings


def verify_admin_password(plain: str) -> bool:
    """
    Verifica `plain` contro il bcrypt hash configurato.

    Hash atteso in formato `$2[aby]$<rounds>$<salt><hash>`.
    Ritorna False se hash mancante o malformato (fail-safe).
    """
    s = get_settings()
    hashed = s.effective_pwd_hash
    if not hashed or not hashed.startswith("$2"):
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False
