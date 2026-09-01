"""Le traduzioni inglesi non possono mentire: o sono fresche, o la CI lo dice.

Perché esiste (01/09/2026, decisione dell'owner: «la CI che verifica anche la
doc … è la mia firma»): una doc bilingue ha un modo solo di morire — le due
copie divergono IN SILENZIO, e la copia stantia continua a sembrare buona. È la
stessa classe del «README ha detto 35 tool per due release», al quadrato,
perché qui il lettore della copia inglese non ha nemmeno l'originale davanti.

Il contratto: docs/en/MANIFEST.json registra, per ogni pagina inglese, lo
sha256 del sorgente italiano al momento della traduzione. Chi tocca l'italiano
di una pagina tradotta DEVE aggiornare la traduzione e poi riallineare l'hash
(`tools/aggiorna-traduzioni.py`). Stdlib-only, come il resto della suite."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]
MANIFEST = RADICE / "docs" / "en" / "MANIFEST.json"
DATI = json.loads(MANIFEST.read_text(encoding="utf-8"))
TRADUZIONI = DATI["traduzioni"]


def test_ogni_pagina_inglese_e_nel_manifest():
    """Una traduzione fuori manifest è una copia senza sorveglianza: il buco
    esatto che il manifest esiste per chiudere."""
    fuori = [p.name for p in (RADICE / "docs" / "en").glob("*.md")
             if f"docs/en/{p.name}" not in TRADUZIONI]
    assert not fuori, (
        f"pagine in docs/en/ non registrate nel MANIFEST: {fuori} — "
        "aggiungi la coppia (sorgente, sha256) o la copia invecchierà in silenzio")


def test_sorgenti_e_traduzioni_esistono():
    for en, voce in TRADUZIONI.items():
        assert (RADICE / en).is_file(), f"traduzione registrata ma assente: {en}"
        assert (RADICE / voce["sorgente"]).is_file(), (
            f"{en}: sorgente {voce['sorgente']} sparito — se il doc italiano è stato "
            "rinominato, la voce del manifest segue")


def test_le_traduzioni_sono_fresche():
    """IL verso che morde: l'italiano si è mosso dopo la traduzione → rosso,
    con l'elenco esatto e la cura. Niente warning: un warning schedulato non lo
    legge nessuno (lezione del trivy-verde-che-non-scansiona)."""
    stantie = []
    for en, voce in TRADUZIONI.items():
        reale = hashlib.sha256((RADICE / voce["sorgente"]).read_bytes()).hexdigest()
        if reale != voce["sorgente_sha256"]:
            stantie.append(f"{en} (sorgente {voce['sorgente']} cambiato)")
    assert not stantie, (
        "traduzioni STANTIE — l'originale italiano si è mosso dopo la traduzione:\n  "
        + "\n  ".join(stantie)
        + "\nCura: aggiorna la pagina inglese, POI `python3 tools/aggiorna-traduzioni.py`."
          " Aggiornare solo l'hash senza la traduzione è mentire al presidio.")


def test_l_aggiornatore_esiste_e_il_manifest_lo_nomina():
    """Il messaggio d'errore manda a uno strumento: deve esistere davvero."""
    assert (RADICE / "tools" / "aggiorna-traduzioni.py").is_file()
    assert "aggiorna-traduzioni" in DATI["_nota"]
