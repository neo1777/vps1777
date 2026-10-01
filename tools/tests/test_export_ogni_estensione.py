"""Un export di sessione resta un export qualunque estensione abbia.

Perché esiste: fino alla 0.67.0 il `.gitignore` e la regola R1 del gate
(`security/check_no_leaks.py`) riconoscevano l'export di `/export` solo come
`AAAA-MM-GG-HHMMSS-<slug>.txt`. Lo stesso transcript salvato come `.md` (chi
esporta sceglie il nome) passava tutte e due le reti, e il repo è pubblico.
La forma che conta è nel NOME; l'estensione no.

Le due reti si controllano qui insieme, sugli stessi casi: se un giorno una
delle due cambia da sola, il test lo dice.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "check_no_leaks", _ROOT / "security" / "check_no_leaks.py")
g = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(g)

EXPORT = (
    "2026-10-01-205536-this-session-is-being-continued.txt",
    "2026-10-01-205536-this-session-is-being-continued.md",
    "2026-10-01-205536-sessione.html",
    "2026-10-01-205536-sessione",
    "docs/2026-10-01-205536-sessione.md",
)

# La metà che impedisce il falso rosso: nomi datati SENZA l'ora a sei cifre, o
# con la data non in testa al nome. Un gate che grida al lupo viene disattivato.
NON_EXPORT = (
    "docs/2026-10-01-note.md",
    "CHANGELOG.md",
    "docs/note-2026-10-01-205536.md",
    "backup-2026-10-01-205536.md",
)


def _ignorato(path: str) -> bool:
    esito = subprocess.run(["git", "check-ignore", "-q", "--no-index", path],
                           cwd=_ROOT, check=False)
    return esito.returncode == 0


def test_il_gate_riconosce_l_export_in_ogni_estensione():
    for path in EXPORT:
        assert g.SESSION_EXPORT.search(path), path


def test_il_gitignore_esclude_l_export_in_ogni_estensione():
    for path in EXPORT:
        assert _ignorato(path), path


def test_ne_il_gate_ne_il_gitignore_scattano_su_un_nome_datato_qualunque():
    for path in NON_EXPORT:
        assert not g.SESSION_EXPORT.search(path), path
        assert not _ignorato(path), path
