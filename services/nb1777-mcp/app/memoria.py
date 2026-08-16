"""Stato e notifiche della memoria 1777 (issue #30, parti ②③).

Vive nel server (nb1777-mcp): è l'unico servizio con volume scrivibile
persistente (`/var/lib/nlm`) — il bot ha rootfs read-only. Il bot fa solo da
trasporto: preleva le notifiche pronte (`drain`) e le manda a Neo, e rimanda qui
l'ack del bottone (`set_ack`).

Tre pezzi:
- **verdetto** (`compare`): la versione che una sessione porta è più vecchia del
  canonico? È ② della issue.
- **coda drift** (in memoria) + rate-limit persistito: i ping «una sessione gira
  vecchia», max 1 per coppia versione/giorno. È ③.1.
- **promemoria cloud** (`maybe_cloud_reminder`): quando il canonico supera l'ack,
  ricorda a Neo di aggiornare a mano le superfici cloud (claude.ai). L'ack è il
  bottone Telegram O una fonte `cloud-ack vX.Y` nel notebook. È ③.2. Il poll del
  bot È il tick: niente scheduler separato (sul VPS non c'è cron).
"""
from __future__ import annotations

import datetime
import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

from . import canonical
from .settings import get_settings

log = logging.getLogger("nb1777.memoria")

_VER_RE = re.compile(r"v?(\d+)\.(\d+)")
_REMINDER_INTERVAL_S = 86400.0  # promemoria cloud: max 1 al giorno

# Coda transiente delle notifiche che il bot deve mandare. Si perde al restart
# (accettabile: i ping drift sono effimeri; l'ack e il rate-limit, che NON vanno
# persi, stanno invece nel file di stato).
_outbox: list[dict] = []


def parse_version(s: str) -> Optional[tuple[int, int]]:
    """'v2.4' / '2.4' / 'Memoria 1777 (v2.4 · ...)' → (2, 4). None se assente."""
    m = _VER_RE.search(s or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def _vstr(t: tuple[int, int]) -> str:
    return f"v{t[0]}.{t[1]}"


# ── stato persistito su /var/lib/nlm ─────────────────────────────────────────

def _state_path() -> Path:
    return Path(get_settings().nlm_home) / "nb1777-state" / "memoria.json"


def _load() -> dict:
    try:
        return json.loads(_state_path().read_text())
    except (OSError, ValueError):
        return {}


def _save(state: dict) -> None:
    p = _state_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(state))
    except OSError as exc:  # volume non scrivibile: non rompere, prosegui in RAM
        log.warning("stato memoria non scrivibile (%s)", exc)


# ── ② il verdetto ────────────────────────────────────────────────────────────

def compare(versione_portata: str) -> dict:
    """La versione portata da una sessione è più vecchia del canonico? Fail-open:
    se il canonico non è disponibile, `stale: None` con la via di fallback."""
    canon = canonical.get_canonical()
    if not canon:
        return {"canonico": None, "stale": None,
                "nota": "canonico non disponibile ora — fallback: notebook_query su claudemd1777"}
    pv = parse_version(versione_portata)
    cv = (canon["major"], canon["minor"])
    if pv is None:
        return {"canonico": canon["version"], "data": canon.get("date"), "stale": None,
                "nota": f"versione portata non riconosciuta: {versione_portata!r}"}
    stale = pv < cv
    if not stale:
        delta = "allineato" if pv == cv else f"avanti (porti {_vstr(pv)}, canonico {canon['version']})"
    elif pv[0] == cv[0]:
        delta = f"indietro di {cv[1] - pv[1]} minor ({_vstr(pv)} → {canon['version']})"
    else:
        delta = f"indietro ({_vstr(pv)} → {canon['version']})"
    return {
        "canonico": canon["version"], "data": canon.get("date"),
        "portata": _vstr(pv), "stale": stale, "delta": delta,
        "note": canon.get("note") if stale else None,
    }


# ── ③.1 il ping drift, con rate-limit ────────────────────────────────────────

def note_drift(versione_portata: str, canonico_version: str) -> bool:
    """Accoda un ping drift SOLO se non già mandato oggi per questa coppia
    (rate-limit persistito). Ritorna True se ha accodato."""
    pv = parse_version(versione_portata)
    porta = _vstr(pv) if pv else "?"
    key = f"{porta}->{canonico_version}"
    today = datetime.date.today().isoformat()
    st = _load()
    sent = st.setdefault("drift_sent", {})
    if sent.get(key) == today:
        return False
    sent[key] = today
    _save(st)
    _outbox.append({
        "kind": "drift",
        "text": (f"⚠️ Una sessione gira con memoria {porta}, il canonico è "
                 f"{canonico_version}. Il blocco portato va aggiornato."),
    })
    return True


# ── ③.2 l'ack e il promemoria cloud ──────────────────────────────────────────

def set_ack(version: str) -> str:
    """Registra l'ack del bottone Telegram: «superfici cloud aggiornate a vX.Y»."""
    pv = parse_version(version)
    norm = _vstr(pv) if pv else version
    st = _load()
    st["acked_version"] = norm
    _save(st)
    return norm


def _effective_ack() -> Optional[tuple[int, int]]:
    """La versione a cui Neo si è allineato: max fra l'ack del bottone (stato) e
    una fonte `cloud-ack vX.Y` nel notebook (l'automatismo file-simile)."""
    acks = []
    btn = parse_version(_load().get("acked_version") or "")
    if btn:
        acks.append(btn)
    src = canonical.get_cloud_ack()
    if src:
        acks.append(src)
    return max(acks) if acks else None


def maybe_cloud_reminder() -> Optional[dict]:
    """Item promemoria (col bottone) se il canonico supera l'ack ed è passato
    l'intervallo; altrimenti None. Segna il timestamp per il rate-limit."""
    canon = canonical.get_canonical()
    if not canon:
        return None
    cv = (canon["major"], canon["minor"])
    ack = _effective_ack()
    if ack is not None and ack >= cv:
        return None  # già allineato → niente promemoria
    st = _load()
    last = st.get("last_reminder_ts", 0.0)
    now = time.time()
    if last and (now - last) < _REMINDER_INTERVAL_S:
        return None
    st["last_reminder_ts"] = now
    _save(st)
    return {
        "kind": "cloud",
        "ack_version": canon["version"],
        "text": (f"📌 Il canonico è {canon['version']} ({canon.get('date')}). Le "
                 f"superfici cloud (claude.ai) vanno aggiornate a mano. Quando fatto, "
                 f"tocca «✓ Fatto» qui sotto (oppure aggiungi una fonte "
                 f"'cloud-ack {canon['version']}' al notebook claudemd1777)."),
    }


def drain(*, include_reminder: bool = True) -> list[dict]:
    """Svuota la coda drift; se dovuto, accoda il promemoria cloud. Chiamato dal
    poll del bot."""
    items = list(_outbox)
    _outbox.clear()
    if include_reminder:
        rem = maybe_cloud_reminder()
        if rem:
            items.append(rem)
    return items
