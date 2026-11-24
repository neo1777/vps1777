"""Le schermate del README: esistono, hanno un testo alternativo, e non invecchiano in silenzio.

Una schermata è un'affermazione su com'è fatto il prodotto, e nessun test del codice la tocca. Qui si
presidia ciò che si può: i file ci sono e non pesano, i due README mostrano le stesse immagini con un
testo alternativo vero, e `docs/img/schermate.json` dice su quale versione sono state fatte. Se
l'installatore cambia, o la versione sale di un gradino, il test diventa rosso: o si rifanno
(`tools/schermate/LEGGIMI.md`), o si conferma guardandole che valgono ancora.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]
IMG = RADICE / "docs" / "img"
REGISTRO = json.loads((IMG / "schermate.json").read_text(encoding="utf-8"))
_TAG = re.compile(r'<img src="docs/img/([\w.-]+)"[^>]*alt="([^"]*)"')


def test_le_immagini_registrate_esistono_e_sono_leggere():
    for nome in REGISTRO["immagini"]:
        f = IMG / nome
        assert f.is_file(), f"{nome} è nel registro ma non in docs/img/"
        assert f.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", f"{nome} non è un PNG"
        assert f.stat().st_size < 300_000, f"{nome} pesa {f.stat().st_size} byte: il repo si clona, va ridotta"
    extra = {p.name for p in IMG.glob("*.png")} - set(REGISTRO["immagini"])
    assert not extra, f"immagini in docs/img/ fuori dal registro: {sorted(extra)}"


def test_i_due_readme_mostrano_le_stesse_schermate_con_un_testo_alternativo():
    viste = {}
    for nome in ("README.md", "README.it.md"):
        trovate = _TAG.findall((RADICE / nome).read_text(encoding="utf-8"))
        assert trovate, f"{nome} non mostra nessuna schermata"
        for immagine, alt in trovate:
            assert (IMG / immagine).is_file(), f"{nome} mostra {immagine}, che non c'è"
            assert len(alt) > 40, f"{nome}: il testo alternativo di {immagine} è troppo corto per descriverla"
        viste[nome] = [i for i, _ in trovate]
    assert viste["README.md"] == viste["README.it.md"]
    assert set(viste["README.md"]) <= set(REGISTRO["immagini"])


def test_le_schermate_non_sono_piu_vecchie_di_un_gradino_di_versione():
    adesso = (RADICE / "VERSION").read_text(encoding="utf-8").strip().split(".")[:2]
    allora = REGISTRO["versione"].split(".")[:2]
    assert adesso == allora, (
        f"le schermate sono della {REGISTRO['versione']}, il repo è alla {'.'.join(adesso)}.x: rifalle "
        "(tools/schermate/LEGGIMI.md) o, se guardandole valgono ancora, aggiorna `versione` in docs/img/schermate.json")


def test_l_installatore_non_e_cambiato_dopo_lo_scatto():
    ora = hashlib.sha256((RADICE / "installer" / "ui.html").read_bytes()).hexdigest()
    assert ora == REGISTRO["installer_ui_sha256"], (
        "installer/ui.html è cambiato dopo la schermata dell'installatore: rifalla (tools/schermate/LEGGIMI.md) "
        "o, se la differenza non si vede, aggiorna `installer_ui_sha256` in docs/img/schermate.json")


def test_gli_script_che_le_rifanno_ci_sono_e_usano_dati_inventati():
    cartella = RADICE / "tools" / "schermate"
    for nome in ("avvia.sh", "scatta.py", "finto_upstream.py", "anteprima.html", "LEGGIMI.md"):
        assert (cartella / nome).is_file(), nome
    testi = "".join((cartella / n).read_text(encoding="utf-8") for n in ("avvia.sh", "scatta.py", "finto_upstream.py"))
    assert "example.invalid" in testi and "203.0.113.10" in testi
    assert "@gmail" not in testi and ".ts.net" not in testi
