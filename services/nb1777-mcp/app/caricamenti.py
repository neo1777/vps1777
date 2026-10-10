"""Il caricamento monouso di una fonte (P15, seconda metà, 10/10/2026).

`source_add_file` legge un path sul SERVER: da claude.ai o dal telefono un file non
aveva una strada per arrivarci, se non il pannello. Ora `source_upload_link` apre un
link `/carica/<gettone>` del gateway, valido 15 minuti e UNA volta sola (come
notebooklm-py, ADR-0024); il gateway passa il corpo in streaming a `/internal/nlm/carica`
e qui il file si scrive a pezzi, diventa una fonte e si cancella.

Il gettone è casuale (192 bit) e il registro sta solo nella memoria di questo processo,
legato al notebook e al titolo scelti da chi ha aperto il link: chi lo usa non può
cambiarli. Un riavvio (un update) chiude i link aperti. Il gateway non sa niente: passa.
"""
from __future__ import annotations

import os
import secrets
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

DURATA_S = 15 * 60
TETTO_BYTE = 200 * 1024 * 1024      # il limite di NotebookLM per una fonte caricata
MARGINE_DISCO = 512 * 1024 * 1024   # oltre al file, quanto deve restare libero
MAX_APERTI = 50

# gettone → (notebook_id, titolo, scade). Solo memoria: niente si conserva.
_APERTI: dict[str, tuple[str, str, float]] = {}


class TroppoGrande(ValueError):
    pass


class SenzaSpazio(OSError):
    pass


def _pota(ora: float) -> None:
    for t in [t for t, (_, _, scade) in _APERTI.items() if ora > scade]:
        del _APERTI[t]


def apri(nb_id: str, titolo: str, *, ora: float | None = None) -> str:
    adesso = time.time() if ora is None else ora
    _pota(adesso)
    if len(_APERTI) >= MAX_APERTI:
        raise ValueError(f"troppi link di caricamento aperti ({MAX_APERTI}): aspetta che "
                         "scadano (15 minuti) o usa quelli che hai")
    t = secrets.token_urlsafe(24)
    _APERTI[t] = (nb_id, titolo, adesso + DURATA_S)
    return t


def scade_di(t: str) -> float:
    return _APERTI[t][2]


def consuma(t: str, *, ora: float | None = None) -> tuple[str, str] | str:
    """(notebook_id, titolo) e il gettone non vale più; oppure il motivo, in una stringa."""
    voce = _APERTI.pop(t, None)
    if voce is None:
        return ("il link di caricamento non vale (già usato, inventato, o nb1777 è "
                "ripartito): chiedine uno nuovo con source_upload_link")
    nb_id, titolo, scade = voce
    if (time.time() if ora is None else ora) > scade:
        return "il link di caricamento è scaduto (15 minuti): chiedine uno nuovo"
    return nb_id, titolo


def link(t: str, scade: float) -> dict:
    base = os.environ.get("GATEWAY_PUBLIC_BASE", "").rstrip("/")
    return {"url": f"{base}/carica/{t}",
            "scade_il": datetime.fromtimestamp(int(scade), timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ")}


async def scrivi(pezzi: AsyncIterator[bytes], dest: Path) -> int:
    """Scrive lo stream in `dest` a pezzi, contando: oltre TETTO_BYTE si ferma e cancella.
    Prima di cominciare controlla che sul disco ci stiano il tetto e un margine."""
    if shutil.disk_usage(dest.parent).free < TETTO_BYTE + MARGINE_DISCO:
        raise SenzaSpazio("spazio su disco insufficiente sul server per ricevere il file")
    scritti = 0
    try:
        with open(dest, "wb") as fh:
            async for pezzo in pezzi:
                scritti += len(pezzo)
                if scritti > TETTO_BYTE:
                    raise TroppoGrande(f"il file supera {TETTO_BYTE // (1024 * 1024)} MB, il "
                                       "limite di NotebookLM per una fonte")
                fh.write(pezzo)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return scritti
