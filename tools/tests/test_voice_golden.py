"""Il golden set del voice-tagging È il test di accettazione della taratura.

PERCHÉ QUESTO TEST (27/08/2026): le soglie di `classify_voice` sono nate come
proposte (02/08) e la prima misura vera — campione cieco da 46 messaggi, 37
giudizi confidenti dell'owner — le ha giudicate: accordo 20/37, `character`
0/8 con 4 falsi CARI (own→character), `pasted_ai` mai emessa contro 8 casi
veri. La taratura ha portato l'accordo a 30/37 con 0 falsi cari, e QUESTO test
inchioda quei numeri: chi ritocca l'euristica deve ripassare di qui.

DOVE VIVE IL GOLD, e perché il test SKIPPA in CI: il gold porta giudizi su
messaggi PRIVATI dell'owner (db+uuid+etichette, senza testi) e i testi stanno
nei DB dell'archivio — niente di tutto questo entra nel repo. Si arma con:

    VPS1777_GOLDEN_VOICE=/path/golden-voice-YYYY-MM-DD.json
    VPS1777_GOLDEN_DB_DIR=/path/dei/db

Uno skip qui NON è un verde: dice «non misurato su questa macchina». La CI lo
skippa per costruzione; la misura vale dove l'archivio c'è.

⚠️ Le soglie asserite sono MINIMI, non uguaglianze: un ritocco che migliora
passa senza toccare il test; uno che peggiora cade. L'unica uguaglianza è
sui falsi cari (== 0): lì il principio della spec non ammette scambi.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

GOLD = os.environ.get("VPS1777_GOLDEN_VOICE", "")
DBDIR = os.environ.get("VPS1777_GOLDEN_DB_DIR", "")

pytestmark = pytest.mark.skipif(
    not (GOLD and Path(GOLD).is_file() and DBDIR and Path(DBDIR).is_dir()),
    reason="golden set non presente (VPS1777_GOLDEN_VOICE / VPS1777_GOLDEN_DB_DIR): "
           "vive fuori dal repo, la misura vale solo dove l'archivio c'è",
)

# Minimi misurati alla taratura del 27/08/2026 (46 voci, 37 confidenti).
ACCORDO_MIN = 35          # accordo totale sui giudizi confidenti (30 dalla
                          # taratura del 27/08; 35 dal 28/08 col confine
                          # mixed↔transcript: cornice_propria + senza_cornice.
                          # I 2 mancanti sono DICHIARATI: l'incollato emotivo
                          # senza segnali formali e il riepilogo-GDR senza
                          # marcatori — curarli creerebbe falsi cari.)
OWN_MIN = 21              # own veri riconosciuti (erano 21/21)
PASTED_AI_MIN = 6         # pasted_ai veri riconosciuti (erano 6/7: il settimo è
                          # un testo emotivo senza alcun segnale formale —
                          # falso negativo accettabile per principio)


def _classify_voice():
    spec = importlib.util.spec_from_file_location(
        "archive_indexer", REPO / "services/gateway/app/archive_indexer.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.classify_voice


def _casi():
    voci = json.load(open(GOLD, encoding="utf-8"))["voci"]
    conns: dict = {}
    for v in voci:
        db = v["db"]
        if db not in conns:
            conns[db] = sqlite3.connect(f"file:{Path(DBDIR) / db}.db?mode=ro", uri=True)
        row = conns[db].execute(
            "SELECT content, sender, project FROM messages WHERE uuid=?",
            (v["uuid"],)).fetchone()
        assert row is not None, f"uuid del gold non trovato in {db}: il DB non è quello del campione"
        neo = v["neo"]
        # confidente = senza punto interrogativo e non «non_so»: gli incerti
        # dell'owner non giudicano nessuno (9 su 46 alla nascita del gold)
        yield row, neo, ("?" not in neo and neo != "non_so")


def test_golden_accettazione():
    classify = _classify_voice()
    accordo = tot = own_ok = own_tot = pai_ok = pai_tot = 0
    cari = []
    for (content, sender, project), neo, confidente in _casi():
        voice, _, _, _ = classify(content or "", sender or "", project or "")
        if not confidente:
            continue
        tot += 1
        accordo += (voice == neo)
        if neo == "own":
            own_tot += 1
            own_ok += (voice == "own")
            if voice in ("pasted_ai", "pasted_transcript", "character"):
                cari.append((neo, voice))
        if neo == "pasted_ai":
            pai_tot += 1
            pai_ok += (voice == "pasted_ai")
    assert not cari, f"falsi CARI (own vero marcato altrui): {cari} — il principio li vieta"
    assert accordo >= ACCORDO_MIN, f"accordo {accordo}/{tot}: sotto il minimo tarato ({ACCORDO_MIN})"
    assert own_ok >= OWN_MIN, f"own {own_ok}/{own_tot}: la classe più popolosa è regredita"
    assert pai_ok >= PASTED_AI_MIN, f"pasted_ai {pai_ok}/{pai_tot}: la taratura del 27/08 è regredita"
