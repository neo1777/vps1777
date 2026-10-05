"""`source_add_file` non può caricare i cookie in un notebook (S5, 05/10/2026).

Fino alla 0.73 `NOTEBOOKLM_ALLOWED_FILE_DIRS` non era impostata, e `nlm` accetta allora
qualunque percorso del container: `source_add_file` poteva mettere dentro un notebook anche
`/var/lib/nlm/profiles/default/cookies.json`, cioè la sessione Google intera. Ora sono
consentite solo le due cartelle dei flussi veri: gli artefatti (dove arrivano anche i file
di ingest) e /tmp, dove `source_add_text` scrive il suo file temporaneo.

Il test usa il controllo VERO di `nlm` (quello della versione pinnata), non una copia.
"""
from __future__ import annotations

import os
from pathlib import Path

import re

import pytest
from notebooklm_tools.services.errors import ValidationError
from notebooklm_tools.services.sources import _validate_file_path_allowlist

COMPOSE = Path(__file__).resolve().parents[3] / "compose.yaml"


def _valore() -> str:
    # regex e non yaml: questa suite gira con le sole dipendenze del lock di nb1777
    m = re.findall(r'^\s+NOTEBOOKLM_ALLOWED_FILE_DIRS:\s*"([^"]*)"\s*$',
                   COMPOSE.read_text(encoding="utf-8"), re.M)
    assert len(m) == 1, "NOTEBOOKLM_ALLOWED_FILE_DIRS: attesa una riga sola nel compose"
    return m[0]


def test_il_compose_consente_solo_artefatti_e_tmp() -> None:
    assert _valore().split(os.pathsep) == ["/var/lib/nlm-artifacts", "/tmp"]


@pytest.mark.parametrize("percorso, consentito", [
    ("/var/lib/nlm-artifacts/ingest/documento.pdf", True),
    ("/tmp/nb1777-src-abc.txt", True),
    ("/var/lib/nlm/profiles/default/cookies.json", False),
    ("/var/lib/nlm/nb1777-state/sonda-nlm.jsonl", False),
    ("/etc/passwd", False),
    ("/var/lib/nlm-artifacts/../nlm/profiles/default/cookies.json", False),
])
def test_il_controllo_di_nlm_con_questo_valore(monkeypatch, percorso: str, consentito: bool) -> None:
    monkeypatch.setenv("NOTEBOOKLM_ALLOWED_FILE_DIRS", _valore())
    if consentito:
        _validate_file_path_allowlist(percorso)
    else:
        with pytest.raises(ValidationError):
            _validate_file_path_allowlist(percorso)
