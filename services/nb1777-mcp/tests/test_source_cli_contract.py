"""
Contract-test wrapper ↔ CLI `nlm` (anti-drift).

Il wrapper in `app/core.py` costruisce a mano gli `argv` dei sottocomandi
`nlm source …`. `nlm` (notebooklm-mcp-cli) è una dipendenza terza a evoluzione
rapida: fra le versioni ha già spostato il notebook da posizionale a opzione
`-n/--notebook` per alcuni comandi. Questo test fotografa il CONTRATTO su cui il
wrapper si appoggia, leggendolo dal binario reale (`--help`), così un bump di
`nlm` che cambia una firma FALLISCE qui invece di rompere in silenzio in
produzione (com'è successo con 0.7.7: content/rename/delete tutti disallineati).

Gira ovunque ci sia `nlm` sul PATH (container nb1777-mcp, o CI che installa il
pin). Se `nlm` non c'è, il test si salta — non finge di aver verificato.

Mappa contratto → costruzione argv in core.py:
  source content SOURCE_ID              → ["source","content",source_id]
  source rename -n NB SOURCE_ID TITLE   → ["source","rename","-n",nb,source_id,title]
  source delete SOURCE_IDS... --confirm → ["source","delete",source_id,"--confirm"]
  source add NOTEBOOK_ID …              → ["source","add",nb,…]
  source list NOTEBOOK_ID               → ["source","list",nb]
"""
from __future__ import annotations

import re
import shutil
import subprocess

import pytest

NLM = shutil.which("nlm")

pytestmark = pytest.mark.skipif(NLM is None, reason="nlm non installato sul PATH")

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _help_of(*argv: str) -> str:
    """Testo `--help` di `nlm <argv...>`, normalizzato.

    Rimuove ANSI e i box-drawing di typer/rich, comprime gli spazi: così le
    asserzioni sui token reggono anche se il layout della tabella cambia.
    """
    p = subprocess.run(
        [NLM, *argv, "--help"],
        capture_output=True, text=True, timeout=30,
    )
    raw = (p.stdout or "") + "\n" + (p.stderr or "")
    txt = _ANSI.sub("", raw)
    # rimuove i caratteri di cornice, poi comprime spazi
    txt = re.sub(r"[│─╭╮╰╯├┤┌┐└┘|]", " ", txt)
    return re.sub(r"\s+", " ", txt)


def _help(subcmd: str) -> str:
    """Scorciatoia per `nlm source <subcmd> --help`."""
    return _help_of("source", subcmd)


def test_source_content_takes_only_source_id() -> None:
    h = _help("content")
    # Un solo posizionale SOURCE_ID; nessun notebook (né posizionale né opzione).
    assert "SOURCE_ID" in h, h
    assert "NOTEBOOK_ID" not in h, "content non deve prendere un NOTEBOOK_ID posizionale"
    assert "--notebook" not in h, "content non deve richiedere --notebook"


def test_source_rename_requires_notebook_option() -> None:
    h = _help("rename")
    # rename vuole SOURCE_ID + TITLE posizionali e --notebook come OPZIONE.
    assert "SOURCE_ID" in h, h
    assert "TITLE" in h, h
    assert "--notebook" in h, "rename deve esporre l'opzione --notebook"
    # euristica 'required': typer marca gli obbligatori con un asterisco nella
    # riga dell'opzione. Se cambia il modo di segnalarlo, resta il check di
    # presenza sopra; questa è una guardia in più, non bloccante se assente.


def test_source_delete_is_source_ids_plus_confirm() -> None:
    h = _help("delete")
    assert "SOURCE_IDS" in h, h
    assert "--confirm" in h, h
    assert "NOTEBOOK_ID" not in h, "delete non deve prendere un NOTEBOOK_ID posizionale"


def test_source_add_takes_notebook_id_positional() -> None:
    h = _help("add")
    assert "NOTEBOOK_ID" in h, h


def test_source_list_takes_notebook_id_positional() -> None:
    h = _help("list")
    assert "NOTEBOOK_ID" in h, h


def test_download_report_shape() -> None:
    # studio_download costruisce `download report NOTEBOOK_ID -o PATH [--id ..]`.
    # nlm 0.7.7 NON ha `--no-progress`: passarlo fa fallire il download. Questo
    # asserisce la firma reale e l'ASSENZA del flag inesistente (il bug trovato
    # verificando studio_download live).
    h = _help_of("download", "report")
    assert "NOTEBOOK_ID" in h, h
    assert "--output" in h, h
    assert "--id" in h, h
    assert "--no-progress" not in h, "download NON espone --no-progress in 0.7.7"


# ── studio: la trappola rename-vs-delete ──
# `studio delete` VUOLE il notebook (NOTEBOOK_ID ARTIFACT_ID); `studio rename` NO
# (ARTIFACT_ID NEW_TITLE): l'artifact id è già globale. La CLI è incoerente fra i
# due, e il wrapper le trattava uguali → studio_rename passava nb_id come
# posizionale ed era inutilizzabile ("unexpected extra argument"). Questi due
# test bloccano proprio quella asimmetria.

def test_studio_rename_takes_no_notebook() -> None:
    h = _help_of("studio", "rename")
    assert "ARTIFACT_ID" in h, h
    assert "NEW_TITLE" in h or "TITLE" in h, h
    assert "NOTEBOOK_ID" not in h, "studio rename NON prende un NOTEBOOK_ID posizionale"
    assert "--notebook" not in h, "studio rename NON richiede --notebook"


def test_studio_delete_takes_notebook_positional() -> None:
    h = _help_of("studio", "delete")
    assert "NOTEBOOK_ID" in h, h
    assert "ARTIFACT_ID" in h, h
