"""
JSONL audit log writer.

Ogni evento è una riga JSON con ts, event, e attributi arbitrari. Append-only.

Due principi, imparati come findings (H17):

1. **Un audit muto è peggio di un audit assente.** Se la scrittura fallisce in
   silenzio, il pannello mostra una lista vuota e nessuno distingue "non è
   successo niente" da "non sto più registrando niente": è l'illusione della
   tracciabilità. Qui un fallimento incrementa un contatore ESPOSTO
   (`audit_health()`), finisce nei log del container, e quando la scrittura
   riparte lascia una riga `audit_write_recovered` nel log stesso.

2. **Non si legge un file dalla testa per mostrarne la coda.** `readlines()[-N:]`
   carica in RAM tutto il file per tenerne 200 righe: su un audit da centinaia di
   MB il pannello se lo porta dietro tutto. Si legge dalla FINE, a blocchi.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("gateway.audit")


def _settings() -> Any:
    """Accesso LAZY alle settings.

    Importare `.settings` a livello di modulo tira dentro pydantic (dipendenza
    pesante) e lega questo file al pacchetto `app`. Tenendolo lazy, `audit` resta
    importabile stdlib-only — la logica pura (`_tail_lines`, `_prune`) si testa
    senza il gateway, e un test può sostituire questo seam con un finto."""
    from .settings import get_settings
    return get_settings()

# sopra questa dimensione il log viene POTATO (righe oltre la retention). Il
# controllo è su st_size (economico) → la potatura è rara, non a ogni scrittura.
_PRUNE_SIZE = 5 * 1024 * 1024  # 5 MB

# Dopo una potatura, non si ri-pota finché il file non è ricresciuto di tanto.
# Senza questa isteresi, un log di 5 MB tutto DENTRO la retention (niente da
# potare) fa ripartire una riscrittura completa a OGNI evento: l'audit diventa
# O(dimensione-del-log) per richiesta — un amplificatore, non un registro.
_PRUNE_GROWTH = 1 * 1024 * 1024  # 1 MB
_next_prune_at = _PRUNE_SIZE

# Lettura tail-like: blocchi dalla coda, e un tetto oltre il quale si smette di
# risalire (un file con righe patologicamente lunghe non deve finirci tutto in RAM).
_TAIL_BLOCK = 64 * 1024
_TAIL_MAX_BYTES = 8 * 1024 * 1024
MAX_READ_LIMIT = 1000  # tetto su `limit`: nessun chiamante può farsi dare tutto il file

# Salute del writer — un audit che smette di scrivere deve poterlo DIRE.
_write_failures = 0
_last_error = ""
_last_failure_ts = ""


def audit_health() -> dict[str, Any]:
    """Stato del writer di audit, per chi lo vuole mostrare o allarmare.

    `write_failures` è il numero di scritture fallite dall'ultimo successo: se è
    > 0, il registro NON è affidabile in questo momento e chi guarda il pannello
    deve saperlo. Vedi la nota nel report: l'aggancio alla UI vive in admin.py.
    """
    return {
        "write_failures": _write_failures,
        "last_error": _last_error,
        "last_failure_ts": _last_failure_ts,
        "healthy": _write_failures == 0,
    }


def _prune(path: Path, retention_days: int) -> None:
    """Riscrive il log tenendo solo le righe entro `retention_days` (per `ts`
    ISO, confronto lessicografico). Le righe senza ts leggibile si scartano.

    Streaming riga-per-riga su un file temporaneo: memoria costante anche su un
    log grande (prima si faceva `read_text()` dell'intero file).
    """
    if retention_days <= 0:
        return
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    tmp = path.with_suffix(path.suffix + ".tmp")
    with path.open("r", encoding="utf-8", errors="replace") as src, \
            tmp.open("w", encoding="utf-8") as dst:
        for raw in src:
            line = raw.strip()
            if not line:
                continue
            try:
                ts = str(json.loads(line).get("ts", ""))
            except json.JSONDecodeError:
                continue
            if ts >= cutoff:
                dst.write(line + "\n")
    tmp.replace(path)  # atomico: un lettore concorrente vede il vecchio o il nuovo


def audit(event: dict[str, Any]) -> None:
    """Append evento al log JSONL. Non solleva mai eccezioni — ma non è più MUTO."""
    global _write_failures, _last_error, _last_failure_ts, _next_prune_at

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        s = _settings()
        path = Path(s.audit_log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"ts": now, **event}
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001 — mai bloccare la response per un audit fail
        _write_failures += 1
        _last_error = f"{type(exc).__name__}: {exc}"
        _last_failure_ts = now
        # il canale che resta quando il file non è scrivibile: i log del container.
        log.warning("audit: scrittura FALLITA (%d dall'ultimo successo): %s",
                    _write_failures, _last_error)
        return

    # La scrittura è passata. Se veniva da una serie di fallimenti, la serie va
    # dichiarata NEL log — è lì che guarda chi indaga, non nei contatori in RAM.
    if _write_failures:
        dropped, err = _write_failures, _last_error
        _write_failures, _last_error, _last_failure_ts = 0, "", ""
        try:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(
                    {"ts": now, "event": "audit_write_recovered",
                     "dropped": dropped, "last_error": err},
                    ensure_ascii=False) + "\n")
        except OSError as exc:
            log.warning("audit: record di ripristino non scritto: %s", exc)

    # potatura opportunistica: solo quando il file è grande (raro) e solo se è
    # ricresciuto dall'ultima volta (vedi _PRUNE_GROWTH).
    try:
        size = path.stat().st_size
        if size > _next_prune_at:
            _prune(path, s.audit_retention_days)
            _next_prune_at = max(_PRUNE_SIZE, path.stat().st_size + _PRUNE_GROWTH)
    except (OSError, ValueError, TypeError) as exc:
        log.warning("audit: potatura fallita: %s", exc)


def _tail_lines(path: Path, limit: int) -> list[str]:
    """Ultime `limit` righe di `path`, risalendo dalla CODA a blocchi.

    Non carica mai più di `_TAIL_MAX_BYTES` (né più di quanto serva a trovare
    `limit` a-capo). Il primo blocco letto — cioè il più VECCHIO — comincia quasi
    sempre a metà riga: quella riga parziale si scarta, a meno di essere arrivati
    all'inizio del file.
    """
    with path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        pos = fh.tell()
        chunks: list[bytes] = []
        newlines = 0
        read = 0
        while pos > 0 and newlines <= limit and read < _TAIL_MAX_BYTES:
            step = min(_TAIL_BLOCK, pos)
            pos -= step
            fh.seek(pos)
            block = fh.read(step)
            chunks.append(block)
            newlines += block.count(b"\n")
            read += step
        data = b"".join(reversed(chunks))

    lines = data.decode("utf-8", errors="replace").splitlines()
    if pos > 0 and lines:
        lines = lines[1:]  # riga tagliata a metà dal blocco più vecchio
    return lines[-limit:]


def read_recent(limit: int = 200) -> list[dict[str, Any]]:
    """Legge gli ultimi N eventi dal log. Tollera righe corrotte.

    `limit` è clampato a MAX_READ_LIMIT: nessun chiamante (né un `?n=` in query
    string) può trasformare questa funzione in "carica tutto il file".
    """
    try:
        limit = max(0, min(int(limit), MAX_READ_LIMIT))
    except (TypeError, ValueError):
        limit = 200
    if not limit:
        return []

    path = Path(_settings().audit_log_path)
    events: list[dict[str, Any]] = []
    try:
        for line in _tail_lines(path, limit):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:  # file assente o illeggibile → nessun evento, mai un'eccezione
        pass
    return events
