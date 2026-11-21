"""
Rate-limit per-IP a finestra scorrevole — stdlib-only, testabile.

Difesa best-effort (in-memory, si azzera al restart) sugli endpoint di
autenticazione pubblici — `/token`, `/register`, `/app/auth` — che finora
avevano solo il lockout del login admin. Non è l'unica difesa (PKCE, initData
firmata, password forte), ma ferma la raffica da singola sorgente.

Nota: l'IP è quello che il gateway vede (`request.client.host`). Da quando
`forwarded_allow_ips` è ristretto al proxy locale (default 127.0.0.1), l'XFF è
attendibile: uno spoof da un peer non fidato viene ignorato → il limiter conta
sull'IP reale. `now` è iniettabile per i test.
"""
from __future__ import annotations

from collections import defaultdict

# Tetto alle chiavi tenute in memoria. Dentro la finestra c'è una voce per ogni IP visto, e con
# IPv6 gli indirizzi non finiscono: oltre il tetto si fa pulizia e, se non basta, un IP NUOVO
# si rifiuta (fail-closed) finché la finestra non scorre. Chi è già dentro non ne risente.
MAX_CHIAVI = 20_000


class RateLimiter:
    """Max `max_calls` richieste per IP entro `window_s` secondi."""

    def __init__(self, max_calls: int, window_s: float) -> None:
        self._max = max_calls
        self._window = window_s
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._chiamate = 0

    def allow(self, ip: str, now: float) -> bool:
        """True se la chiamata è ammessa (e la registra); False se oltre soglia."""
        # `sweep` non la chiamava nessuno: una voce per ogni IP visto, fino al riavvio.
        # Ogni 256 chiamate si tolgono le voci senza richieste nella finestra.
        self._chiamate += 1
        if self._chiamate % 256 == 0:
            self.sweep(now)
        if ip not in self._hits and len(self._hits) >= MAX_CHIAVI:
            self.sweep(now)
            if len(self._hits) >= MAX_CHIAVI:
                return False
        q = self._hits[ip]
        cutoff = now - self._window
        # pota le vecchie in-place (memoria limitata alla finestra)
        i = 0
        for t in q:
            if t > cutoff:
                break
            i += 1
        if i:
            del q[:i]
        if len(q) >= self._max:
            return False
        q.append(now)
        return True

    def sweep(self, now: float) -> None:
        """Rimuove gli IP senza hit recenti (housekeeping opzionale)."""
        cutoff = now - self._window
        for ip in [k for k, v in self._hits.items() if not v or v[-1] <= cutoff]:
            del self._hits[ip]
