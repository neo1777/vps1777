"""La ricerca approfondita di Gemini Notebook, in un sottoprocesso (P7, 10/10/2026).

`nlm research start/status/import` (0.12, e ancora la 0.15) stampano solo testo, senza `--json`, e
`--auto-import` sbaglia. Sotto la CLI c'è `notebooklm_tools.services.research`, che
ritorna dati strutturati (TypedDict): questo modulo lo chiama e stampa JSON, così
`core` lo lancia come lancia `nlm` — un sottoprocesso con timeout, che si può uccidere
se Google non risponde — invece di parsare un testo pensato per un terminale.

    python -m app.ricerca_nlm start  NOTEBOOK QUERY [--source web|drive] [--mode fast|deep]
    python -m app.ricerca_nlm status NOTEBOOK [--task-id ID]
    python -m app.ricerca_nlm import NOTEBOOK TASK_ID [--indices 0,2] [--cited-only]

Exit 0 e JSON su stdout; exit 1 e il messaggio dell'errore su stderr (lo classifica
`core`, come per `nlm`: un'auth scaduta diventa il messaggio con la cura vera).
"""
from __future__ import annotations

import argparse
import json
import sys


def _servizi():
    """(get_client, modulo research) di nlm. A parte, così i test li sostituiscono."""
    from notebooklm_tools.cli.utils import get_client
    from notebooklm_tools.services import research
    return get_client, research


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ricerca_nlm")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("notebook_id")
    s.add_argument("query")
    s.add_argument("--source", default="web")
    s.add_argument("--mode", default="fast")
    t = sub.add_parser("status")
    t.add_argument("notebook_id")
    t.add_argument("--task-id", default="")
    i = sub.add_parser("import")
    i.add_argument("notebook_id")
    i.add_argument("task_id")
    i.add_argument("--indices", default="")
    i.add_argument("--cited-only", action="store_true")
    a = ap.parse_args(argv)
    try:
        get_client, research = _servizi()
        with get_client(None) as client:
            if a.cmd == "start":
                out = research.start_research(client, a.notebook_id, a.query,
                                              source=a.source, mode=a.mode)
            elif a.cmd == "status":
                # una sola lettura (max_wait=0): ad aspettare è chi chiama, non questo processo
                out = research.poll_research(client, a.notebook_id, task_id=a.task_id or None,
                                             compact=False, max_wait=0)
            else:
                indici = [int(x) for x in a.indices.split(",") if x.strip()] or None
                out = research.import_research(client, a.notebook_id, a.task_id,
                                               source_indices=indici, cited_only=a.cited_only)
    except Exception as exc:                            # noqa: BLE001 — lo classifica core
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(out, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
