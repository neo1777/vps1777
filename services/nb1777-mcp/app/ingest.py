"""
app.ingest — entrypoint CLI: estrae il testo di un file via NotebookLM.

Chiamato dal comando host `vps1777 archive-ingest`:
    docker compose exec -T nb1777-mcp python -m app.ingest --file /tmp/x.pdf [--verify]

Stampa su stdout un JSON {text, chars, verification?}. NotebookLM fa la lettura
multimodale (anche immagini/scansioni); qui si orchestra soltanto (scratch
notebook usa-e-getta con cleanup incluso).
"""
from __future__ import annotations

import argparse
import json
import sys

from . import core


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="app.ingest")
    ap.add_argument("--file", required=True, help="path del file dentro il container")
    ap.add_argument("--title", default=None)
    ap.add_argument("--verify", action="store_true", help="chiedi a NotebookLM di verificare la trascrizione")
    args = ap.parse_args(argv)
    try:
        out = core.transcribe_document(args.file, title=args.title, verify=args.verify)
    except core.NLMError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
