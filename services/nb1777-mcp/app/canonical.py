"""Il canonico del blocco di memoria 1777 (issue #30).

nb1777 CONOSCE e DICHIARA la versione corrente del blocco di memoria, così una
sessione può accorgersi che la copia che porta è vecchia (la regola FRESCHEZZA,
finalmente applicata al blocco stesso).

La verità sta nel notebook `claudemd1777`: ogni update del canonico è una FONTE
nuova e datata, col titolo `canonico vX.Y — <data> — <cosa cambia>` (protocollo a
strati: le vecchie non si riscrivono). → la versione corrente è il titolo con la
`vX.Y` più alta.

Due proprietà non negoziabili:
- **Fail-open**: se il notebook non risponde, nb1777 funziona lo stesso e
  semplicemente non dichiara nulla. La regola client v2.4 prevede questo caso
  (fallback con una `notebook_query` su claudemd1777).
- **Cache**: non si interroga NotebookLM a ogni chiamata (TTL sotto).
"""
from __future__ import annotations

import logging
import re
import time
from typing import Optional

from . import core

log = logging.getLogger("nb1777.canonical")

# Notebook claudemd1777 — la fonte di verità del canonico.
CANON_NOTEBOOK_ID = "90b60dda-6af6-4437-be63-196d6a8166d9"

# `canonico v2.4 — 2026-07-13 — regola CANONICO (...)`. Il separatore reale è un
# em-dash con spazi; accettiamo anche en-dash e hyphen per robustezza. La data
# (ISO) è opzionale. Tutto ciò che segue è il "cosa cambia".
_CANON_RE = re.compile(
    r"^\s*canonico\s+v(\d+)\.(\d+)\s*[—–-]+\s*"
    r"(\d{4}-\d{2}-\d{2})?\s*[—–-]*\s*(.*)$",
    re.IGNORECASE,
)

# `cloud-ack v2.4` — una fonte che Neo aggiunge al notebook per dire «superfici
# cloud aggiornate a questa versione» (issue #30 ③.2: l'automatismo file-simile,
# alternativo al bottone Telegram).
_CLOUD_ACK_RE = re.compile(r"^\s*cloud-ack\s+v(\d+)\.(\d+)\b", re.IGNORECASE)

# 15 min: il canonico cambia di rado (una fonte nuova ogni tanto), ma un refresh
# periodico costa poco. Il deploy riavvia il processo → cache fredda comunque.
_CACHE_TTL_S = 900.0
_cache: dict = {"data": None, "ts": 0.0}
_ack_cache: dict = {"data": None, "ts": 0.0}


def highest_canonical(sources: list[dict]) -> Optional[dict]:
    """Trova la versione canonica più alta fra i titoli delle fonti.

    PURA (niente I/O): prende la lista restituita da `source_list` e ritorna
    `{version, major, minor, date, note}` per la vX.Y più alta, o `None` se
    nessun titolo è nella forma `canonico vX.Y`. Il confronto è NUMERICO
    (v2.10 > v2.9), non lessicale."""
    best: Optional[dict] = None
    for s in sources or []:
        title = (s.get("title") or "").strip()
        m = _CANON_RE.match(title)
        if not m:
            continue
        major, minor = int(m.group(1)), int(m.group(2))
        if best is None or (major, minor) > (best["major"], best["minor"]):
            best = {
                "version": f"v{major}.{minor}",
                "major": major,
                "minor": minor,
                "date": (m.group(3) or "").strip() or None,
                "note": (m.group(4) or "").strip() or None,
            }
    return best


def get_canonical(*, force: bool = False) -> Optional[dict]:
    """Versione canonica corrente, con cache TTL.

    Fail-open: su qualsiasi errore ritorna l'ultimo valore in cache (se c'è) o
    `None`, senza mai sollevare — il canonico non deve poter rompere il server."""
    now = time.monotonic()
    cached = _cache["data"]
    if not force and cached is not None and (now - _cache["ts"]) < _CACHE_TTL_S:
        return cached
    try:
        data = highest_canonical(core.source_list(CANON_NOTEBOOK_ID))
    except Exception as exc:  # noqa: BLE001 — fail-open volutamente ampio
        log.warning("canonico: fetch fallito (%s) — fail-open, uso la cache", exc)
        return cached
    if data is not None:
        _cache["data"] = data
        _cache["ts"] = now
        return data
    # notebook raggiungibile ma nessuna fonte `canonico vX.Y`: tieni la cache.
    return cached


def highest_cloud_ack(sources: list[dict]) -> Optional[tuple[int, int]]:
    """Versione più alta fra le fonti `cloud-ack vX.Y` (PURA). Ritorna la tupla
    (major, minor) o None. È la controparte file-simile del bottone «Fatto»: Neo
    aggiunge `cloud-ack v2.4` al notebook e il promemoria si spegne."""
    best: Optional[tuple[int, int]] = None
    for s in sources or []:
        m = _CLOUD_ACK_RE.match((s.get("title") or "").strip())
        if not m:
            continue
        cand = (int(m.group(1)), int(m.group(2)))
        if best is None or cand > best:
            best = cand
    return best


def get_cloud_ack(*, force: bool = False) -> Optional[tuple[int, int]]:
    """Ultimo `cloud-ack` dal notebook, con cache TTL propria. Fail-open."""
    now = time.monotonic()
    if not force and _ack_cache["ts"] > 0 and (now - _ack_cache["ts"]) < _CACHE_TTL_S:
        return _ack_cache["data"]
    try:
        data = highest_cloud_ack(core.source_list(CANON_NOTEBOOK_ID))
    except Exception as exc:  # noqa: BLE001 — fail-open
        log.warning("cloud-ack: fetch fallito (%s) — uso la cache", exc)
        return _ack_cache["data"]
    _ack_cache["data"] = data
    _ack_cache["ts"] = now
    return data


def public_view(data: Optional[dict]) -> dict:
    """Proiezione per i tool MCP: niente major/minor interni. Se `data` è None
    (fail-open), dichiara `available: false` con la via di fallback."""
    if not data:
        return {
            "available": False,
            "nota": ("canonico non raggiungibile ora — fai il fallback con una "
                     "notebook_query su claudemd1777 (regola client v2.4)."),
        }
    return {
        "available": True,
        "version": data["version"],
        "date": data.get("date"),
        "note": data.get("note"),
    }


def declaration_text() -> str:
    """Testo per `FastMCP(instructions=...)` — Veicolo A del canale involontario.

    STATICO di proposito: vale anche prima di qualsiasi fetch, quindi non dipende
    dall'auth nlm al boot. Non porta il numero di versione (che è dinamico) ma
    dice alla sessione che nb1777 lo conosce e come confrontarsi — il numero vivo
    lo dà il tool `canonico`."""
    return (
        "MEMORIA 1777 — nb1777 conosce il canonico del blocco di memoria 1777. "
        "Se la versione in testa al blocco che porti potrebbe essere vecchia, "
        "chiama il tool `canonico`: ti dà la versione canonica attuale e la data. "
        "Confrontala con la tua — se sei più vecchio sei disallineato: dillo a Neo "
        "prima di procedere. (nb1777 · canale A/instructions)"
    )
