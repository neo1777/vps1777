"""Revoke-list dei `jti` — pura stdlib, zero dipendenze di terze parti.

Isolata qui (fuori da admin.py, che importa starlette, e fuori da jwt_helpers.py,
che importa PyJWT) così è importabile e testabile stdlib-only, come miniapp_core /
ratelimit / logredact: la CI gira i test del gateway con `uvx pytest` senza
installare le deps pesanti.

PERCHÉ (H20). Il cookie admin è un JWT verificato *stateless*: finché la firma
regge e `exp` non è passato, VALE — anche dopo il logout, che lato server non
faceva nulla (cancellava il cookie nel browser). Un token rubato restava quindi
buono fino a 8h. Con un `jti` per token e questa lista, il logout REVOCA davvero:
`verify_admin_cookie` rifiuta un jti revocato, e la revoca sopravvive ai restart
perché sta su disco.

È la gemella della revoke-list dei refresh OAuth (oauth.py → `oauth_revoked.json`,
`_revoked_refresh`), con una differenza deliberata: qui ogni voce porta la propria
SCADENZA. Un jti conta solo finché il token non sarebbe scaduto da sé — dopo, la
verifica JWT lo rifiuta comunque per `exp` e tenerne memoria non aggiunge
sicurezza, solo byte. Quindi si pota: la lista non cresce all'infinito.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path


def prune(entries: dict[str, float], now: float) -> dict[str, float]:
    """Toglie le voci già scadute (`exp <= now`): il loro token è morto da sé."""
    return {jti: exp for jti, exp in entries.items() if exp > now}


class RevocationList:
    """`jti` revocati → epoch di scadenza del token. Persistita su JSON.

    Best-effort come la gemella OAuth: se il disco non è scrivibile la revoca
    resta in memoria (vale per questo processo) e `revoke()` ritorna False, così
    il chiamante può auditarlo invece di crederla durevole.

    Il file viene ri-letto quando cambia l'mtime: la lista resta corretta anche
    se un domani il gateway girasse con più worker (oggi è un processo solo).
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._entries: dict[str, float] = {}
        self._mtime: float = -1.0
        self.reload()

    # ───── I/O ─────

    def _stat_mtime(self) -> float:
        try:
            return self._path.stat().st_mtime
        except OSError:
            return -1.0

    def _read(self) -> dict[str, float]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        out: dict[str, float] = {}
        for jti, exp in raw.items():
            try:
                out[str(jti)] = float(exp)
            except (TypeError, ValueError):
                continue  # voce corrotta: si scarta quella, non il file
        return out

    def reload(self, now: float | None = None) -> None:
        """Rilegge il file da zero (e pota)."""
        self._entries = prune(self._read(), time.time() if now is None else now)
        self._mtime = self._stat_mtime()

    def _sync(self, now: float | None = None) -> None:
        """Ricarica solo se il file è cambiato sotto di noi (stat, non read)."""
        if self._stat_mtime() != self._mtime:
            self.reload(now)

    def save(self) -> bool:
        """Scrive in modo atomico (tmp + replace): un crash a metà non lascia un
        JSON troncato — che, essendo illeggibile, farebbe *dimenticare* le revoche."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(self._path.parent),
                                       prefix=".revoked-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(self._entries, fh)
                os.chmod(tmp, 0o600)
                os.replace(tmp, self._path)
            except OSError:
                os.unlink(tmp)
                raise
        except OSError:
            return False
        self._mtime = self._stat_mtime()
        return True

    # ───── API ─────

    def revoke(self, jti: str, expires_at: float, now: float | None = None) -> bool:
        """Revoca `jti` fino alla scadenza del token. True se persistita su disco."""
        if not jti:
            return False
        now = time.time() if now is None else now
        self._sync(now)
        self._entries = prune(self._entries, now)
        self._entries[str(jti)] = float(expires_at)
        return self.save()

    def is_revoked(self, jti: str, now: float | None = None) -> bool:
        if not jti:
            return False
        self._sync(now)
        return str(jti) in self._entries

    def __len__(self) -> int:
        return len(self._entries)


# ───── il `next` del login: relativo vero o same-origin, niente altro (H30) ─────
# Sta QUI, e non in admin.py, perché admin.py importa starlette e la CI non può
# testarlo. Un bypass di open-redirect è tornato una volta in un rilievo che
# risultava CHIUSO: senza test, tornerà ancora.

def safe_next_url(next_url: str, public_base: str, fallback: str = "/admin/setup") -> str:
    """
    Ritorna `next_url` se è un redirect lecito, altrimenti `fallback`.

    Lecito = path relativo VERO, oppure stessa ORIGINE di public_base.

    Le tre trappole, tutte incontrate sul campo:
    - `//evil.com` e `/\\evil.com` cominciano per "/" ma sono protocol-relative:
      il browser li manda FUORI.
    - `startswith(base)` è un match di PREFISSO, non di ORIGINE: con base
      `https://host`, l'URL `https://host.evil.com/` lo supera. Dopo la base ci
      DEVE essere la fine dell'URL o un separatore (`/`, `?`, `#`).
    - I browser CANCELLANO tab/CR/LF dagli URL: `/\\t/evil.com` ridiventa
      `//evil.com` DOPO il nostro controllo. Un `next` con caratteri di controllo
      non è comunque un URL lecito.
    """
    if not next_url:
        return fallback
    if any(ord(c) < 0x20 or ord(c) == 0x7f for c in next_url):
        return fallback
    if next_url.startswith("/") and not next_url.startswith(("//", "/\\")):
        return next_url
    base = (public_base or "").rstrip("/")
    if base and next_url.startswith(base):
        rest = next_url[len(base):]
        if rest == "" or rest[0] in "/?#":
            return next_url
    return fallback
