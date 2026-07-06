"""
app.statecard — upsert della "state card" vps1777 in un notebook NotebookLM.

Una card è una fonte testuale, dal titolo stabile, che riassume lo stato del
gateway (versione + contratto tool + principio) per i contesti che leggono un
notebook ma NON chiamano l'MCP (biblioteca, masterIndex, …). La verità viva
resta il tool `doctor`: la card lo dice esplicitamente e si data, così se è
vecchia si autodenuncia.

Chiamato dall'hook post-update del CLI host (`tools/vps1777.py`) via:
    docker compose exec -T nb1777-mcp python -m app.statecard \\
        --notebook <NOTEBOOK_ID> --version <X.Y.Z>

Idempotente: rimpiazza la card esistente (match per titolo → delete + add).
Single-writer (solo il flusso update, serializzato). Best-effort: il chiamante
ignora il fallimento perché l'update è già riuscito.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from . import core

CARD_TITLE = "vps1777-state-card"


def render_card(version: str, *, nlm_pin: str = "0.7.7", date: str | None = None) -> str:
    """Markdown della card. Puro (nessun I/O) → testabile offline."""
    date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return (
        "# vps1777 — state card (auto-generata, NON modificare a mano)\n"
        f"versione: {version} · nlm pin: {nlm_pin} · aggiornata: {date}\n"
        "\n"
        "Verità viva: chiama il tool `doctor` (nb1777) → `vps1777_version` + `contract_note`.\n"
        "I contratti dei tool source/studio sono pinnati a nlm 0.7.x e verificati da un\n"
        "contract-test in CI.\n"
        "\n"
        "- `nb_get` ritorna title + url + fonti.\n"
        "- `cross_notebook_query` NON esiste: usa `notebook_query` con `source_ids`.\n"
        "- `archive1777` nasce vuoto (0 DB = stato normale).\n"
        "\n"
        f"⚠️ Se questa card è più vecchia della release corrente ({version}), fidati di "
        "`doctor`, non di qui.\n"
    )


def upsert(notebook_id: str, version: str, *, nlm_pin: str = "0.7.7") -> str:
    """Rimpiazza la card nel notebook. Ritorna l'id della nuova fonte.

    Rimuove prima tutte le fonti col titolo della card (idempotenza: mai
    duplicati), poi aggiunge quella corrente. `wait=False`: non blocca
    sull'indicizzazione — la card è testo, la ricerca la può indicizzare con
    calma.
    """
    for s in core.source_list(notebook_id):
        if (s.get("title") or "").strip() == CARD_TITLE:
            sid = core._source_id_of(s)
            if sid:
                core.source_delete(notebook_id, sid)
    card = render_card(version, nlm_pin=nlm_pin)
    return core.source_add_text(notebook_id, card, CARD_TITLE, wait=False)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="app.statecard")
    ap.add_argument("--notebook", required=True, help="id del notebook target")
    ap.add_argument("--version", required=True, help="versione vps1777 corrente")
    ap.add_argument("--nlm-pin", default="0.7.7")
    args = ap.parse_args(argv)
    try:
        sid = upsert(args.notebook, args.version, nlm_pin=args.nlm_pin)
        print(f"state-card upserted: {sid}")
        return 0
    except Exception as exc:  # best-effort: segnala ed esce non-zero, il chiamante logga
        print(f"state-card upsert failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
