"""Il registro dei lavori lunghi di nb1777 (P6, 10/10/2026).

`source_add_*` con attesa, `studio_download` e `studio_create_all_9` possono durare minuti, e
da claude.ai una chiamata cade verso i 30 s («MCP tool call failed»): il lavoro andava
avanti sul server, ma chi chiamava perdeva il risultato. Qui si fa come `notebook_query`
dalla 0.72: il lavoro parte in un task, si aspetta al massimo `attesa_max`, e se non è finito
si risponde {stato: "in_corso", job_id}. Si ritira con `lavoro_esito(job_id)`, oppure
rilanciando la stessa chiamata con gli stessi argomenti, che si aggancia.

Due tetti. Al più POSTI lavori insieme (ognuno è un `nlm` che parla con Google). E uno alla
volta per notebook: `source_add_*` ricava l'id della fonte nuova per DIFFERENZA fra la lista
prima e dopo (`core._add_and_resolve_id`), quindi due aggiunte parallele sullo stesso
notebook potrebbero scambiarsi gli id. Il registro sta in memoria: un riavvio lo perde.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Callable

POSTI = 3
TTL_S = 1800.0                 # un risultato non ritirato 30 minuti dopo la FINE si butta
ATTESA_MAX_TETTO = 270.0

_LAVORI: dict[str, dict[str, Any]] = {}       # job_id → {task, nato, nome}
_PER_CHIAVE: dict[tuple, str] = {}            # (tool, argomenti…) → job_id
_LOCK_NB: dict[str, asyncio.Lock] = {}
_posti: asyncio.Semaphore | None = None


def _semaforo() -> asyncio.Semaphore:
    global _posti
    if _posti is None:
        _posti = asyncio.Semaphore(POSTI)
    return _posti


def lucchetto(nb_id: str) -> asyncio.Lock:
    """Il lucchetto delle scritture di un notebook (anche il caricamento monouso lo usa)."""
    return _LOCK_NB.setdefault(nb_id, asyncio.Lock())


def _dimentica(jid: str) -> None:
    _LAVORI.pop(jid, None)
    for chiave in [c for c, j in _PER_CHIAVE.items() if j == jid]:
        del _PER_CHIAVE[chiave]


def _pulisci() -> None:
    # I 30 minuti contano da quando il lavoro è FINITO, non da quando è partito (12/10/2026):
    # contati dalla partenza, un censimento da 40 minuti perdeva il risultato appena un altro
    # lavoro chiamava _pulisci, e rilanciarlo lo faceva ripartire da capo.
    ora = time.monotonic()
    for jid, voce in list(_LAVORI.items()):
        finito = voce.get("finito")
        if voce["task"].done() and finito is not None and ora - finito > TTL_S:
            _dimentica(jid)


def avvia(nome: str, chiave: tuple, nb_id: str, fn: Callable[..., Any], *args, **kw) -> str:
    """Il job_id del lavoro: nuovo, o quello già in corso (o finito e non ritirato) per la
    stessa chiamata."""
    _pulisci()
    jid = _PER_CHIAVE.get(chiave)
    if jid in _LAVORI:
        return jid

    async def corsa():
        async with _semaforo():
            async with lucchetto(nb_id):
                return await asyncio.to_thread(fn, *args, **kw)

    jid = uuid.uuid4().hex[:12]
    task = asyncio.create_task(corsa())
    _LAVORI[jid] = {"task": task, "nato": time.monotonic(), "nome": nome}

    def segna_fine(_t, voce=_LAVORI[jid]) -> None:
        voce["finito"] = time.monotonic()

    task.add_done_callback(segna_fine)
    _PER_CHIAVE[chiave] = jid
    return jid


async def aspetta(jid: str, attesa_max: float) -> Any:
    voce = _LAVORI.get(jid)
    if voce is None:
        raise ValueError(f"job_id {jid!r} sconosciuto: già ritirato, scaduto (30 minuti) o perso "
                         "a un riavvio del servizio. Controlla lo stato (es. source_list) e, se "
                         "serve, rilancia la chiamata.")
    attesa = min(max(float(attesa_max), 1.0), ATTESA_MAX_TETTO)
    try:
        r = await asyncio.wait_for(asyncio.shield(voce["task"]), attesa)
    except asyncio.TimeoutError:
        return {"stato": "in_corso", "job_id": jid, "lavoro": voce["nome"],
                "nota": (f"non ancora finito dopo {attesa:.0f} s: il lavoro continua sul server. "
                         "Chiama lavoro_esito(job_id) per ritirarlo, oppure rilancia la stessa "
                         "chiamata con gli stessi argomenti: si aggancia invece di ripartire.")}
    except Exception:
        _dimentica(jid)
        raise
    _dimentica(jid)
    return r
