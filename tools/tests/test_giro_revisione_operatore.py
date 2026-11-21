"""Giro di revisione del 21/11/2026, strumenti dell'operatore: tre difetti che non devono tornare.

- `rotate-secret.sh` leggeva la password nuova nella variabile `PWD`, che in bash è la cartella
  corrente: senza terminale «vuoto = la genero io» non scattava mai, e il percorso del repo
  veniva giudicato (e in certi percorsi ACCETTATO) come password dell'admin.
- `vps1777 rollback` scambiava `current` e `previous` ma lasciava `previous_images` com'era: il
  secondo rollback scriveva il tag di una versione coi digest dell'altra.
- `restore.sh` fermava lo stack prima di sapere se l'input si poteva leggere.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _senza_commenti(testo: str) -> str:
    return "\n".join(r for r in testo.splitlines() if not r.lstrip().startswith("#"))


def test_rotate_secret_non_usa_la_variabile_PWD() -> None:
    codice = re.sub(r"#.*", "", (ROOT / "tools" / "rotate-secret.sh").read_text(encoding="utf-8"))
    assert not re.search(r"\bread\b[^\n]*\bPWD\b", codice), "la password si legge in PWD"
    assert not re.search(r"(^|[\s;])PWD=", codice), "PWD viene assegnata: è la cartella corrente"
    assert not re.search(r"\$\{?PWD\b", codice), "PWD usata come valore"


def test_il_rollback_scambia_anche_i_digest() -> None:
    sorgente = (ROOT / "tools" / "vps1777.py").read_text(encoding="utf-8")
    f = next(n for n in ast.parse(sorgente).body
             if isinstance(n, ast.FunctionDef) and n.name == "cmd_rollback")
    corpo = ast.get_source_segment(sorgente, f)
    i_cattura = corpo.find("capture_current_images(repo, cur)")
    assert i_cattura != -1, "cmd_rollback non cattura i digest della versione che lascia"
    assert i_cattura < corpo.find('"down"'), "i digest vanno presi PRIMA di `down`"
    i_scambio = corpo.find('st["previous"] = cur')
    assert 'st["previous_images"] = cur_img' in corpo[i_scambio:corpo.find("state_save", i_scambio)], \
        "previous_images non segue lo scambio current/previous"


def test_il_restore_controlla_l_input_prima_di_fermare_lo_stack() -> None:
    codice = _senza_commenti((ROOT / "tools" / "restore.sh").read_text(encoding="utf-8"))
    i_down = codice.index("docker compose down")
    prima = codice[:i_down]
    assert "age -d -i" in prima, "la decifratura di prova viene dopo il `down`"
    assert re.search(r'ls "\$ARCHIVE"/\*\.tar', prima), "i tar dello snapshot si cercano dopo il `down`"
    assert 'cp -a "$ARCHIVE"' not in codice, "lo snapshot viene ancora copiato in /tmp"


def test_il_rollback_automatico_protegge_ogni_passo() -> None:
    sorgente = (ROOT / "tools" / "vps1777.py").read_text(encoding="utf-8")
    f = next(n for n in ast.parse(sorgente).body
             if isinstance(n, ast.FunctionDef) and n.name == "_rollback_routine")
    corpo = _senza_commenti(ast.get_source_segment(sorgente, f))
    # nessun passo che può sollevare sta fuori da `_passo`: un restore fallito non deve
    # impedire `up`, l'health-gate e l'avviso «intervento manuale»
    for chiamata in ("snapshot_restore(repo, snap)", "install_systemd_units(repo, enable=False)",
                     "restore_rollback_files(repo, rollback_dir, bundle)"):
        assert f"lambda: {chiamata}" in corpo, f"{chiamata} fuori da _passo"
    assert corpo.index('"up", "-d"') > corpo.index("snapshot_restore"), "`up` deve restare dopo il restore"
    assert "passi falliti" in corpo, "i passi falliti non arrivano nel messaggio"
