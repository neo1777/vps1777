"""L'ELENCO DEGLI ELENCHI — che ogni `type` del ledger abbia il suo verificatore.

🔑 PERCHÉ ESISTE, e perché non è il solito test di copertura.
Proposto da `71d540e6` il 02/08 mentre curavo la **sesta** istanza di un pattern che
si ripete da giorni:

    ledger           enumerava 3 categorie   → `tools/` era una CARTELLA, fuori
    gate anti-leak   esenzioni da 2 elenchi  → i 2 scoperti erano `set`, non `dict`
    gate R1          3 forme di nome file    → `secrets/` è una CARTELLA
    _SECRET_POLICY   4 segreti su 5          → l'assente mai digitato da un umano
    check_findings   per SUFFISSO            → `.env.example` ha la forma sbagliata
    ledger (di nuovo) 3 categorie enumerate  → i comandi CLI sono una QUARTA forma

⭐ **La parte scoperta non è mai casuale: è quella con la FORMA DIVERSA dalle altre**,
perché un presidio nasce dove è facile metterlo. Curare la sesta istanza a mano lascia
in piedi la settima — questo test gira sull'ELENCO invece che sui casi.

🛡️ CONTROLLA I DUE VERSI, e il secondo è quello che nessuno pensa a guardare:
  · un `type` usato in `features.yaml` che il verificatore NON sa trattare
    → la voce si dichiara verificata e non lo è: nasce cieca
  · un `type` che il verificatore sa trattare e che NESSUNA voce usa
    → codice di verifica morto, che si legge come copertura
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[2]
_VERIF = _ROOT / "tools" / "verify-features.py"
_LEDGER = _ROOT / "features.yaml"

# Non è un `type`: è la parola con cui una voce dichiara che la verifica è a mano.
# Sta qui e non nel codice perché è una convenzione del ledger, non un verificatore —
# e va esclusa da ENTRAMBI i lati del confronto, o il verso 2 la conta morta.
_MANUALI = {"manual"}


def _tipi_trattati() -> set[str]:
    """I `kind` che il verificatore riconosce, letti dall'ALBERO SINTATTICO.

    Non da una lista scritta a mano: una lista a mano diverge dal codice, ed è
    esattamente il difetto che questo test esiste per prendere. Si cercano i
    confronti `kind == "..."` dentro `verify-features.py`.
    """
    albero = ast.parse(_VERIF.read_text(errors="replace"))
    tipi: set[str] = set()
    for n in ast.walk(albero):
        if (isinstance(n, ast.Compare) and isinstance(n.left, ast.Name)
                and n.left.id == "kind" and len(n.comparators) == 1
                and isinstance(n.comparators[0], ast.Constant)
                and isinstance(n.comparators[0].value, str)):
            tipi.add(n.comparators[0].value)
    return tipi


def _tipi_usati() -> set[str]:
    """I `type` che le voci del ledger usano davvero, da `verify` e `follow_up.verify`."""
    doc = yaml.safe_load(_LEDGER.read_text(errors="replace")) or {}
    voci = doc.get("features") or doc.get("voci") or []
    if not isinstance(voci, list):
        voci = [v for v in doc.values() if isinstance(v, list) for v in v]
    usati: set[str] = set()
    for e in voci:
        if not isinstance(e, dict):
            continue
        for spec in (e.get("verify"), (e.get("follow_up") or {}).get("verify")):
            if isinstance(spec, dict):
                usati |= set(spec.keys())
            elif isinstance(spec, str):
                usati.add(spec)
    return usati - _MANUALI


def test_ogni_tipo_del_ledger_ha_il_suo_verificatore():
    """Verso 1 — un `type` usato e non trattato nasce CIECO.

    La voce si dichiara verificata, il verificatore non la riconosce, e a seconda
    di com'è scritto il dispatcher o la ignora o cade. In entrambi i casi il ledger
    dice verde su una feature che nessuno ha guardato.
    """
    trattati, usati = _tipi_trattati() - _MANUALI, _tipi_usati()
    assert trattati, "zero `kind ==` trovati: il parser del test è rotto, non il codice"
    orfani = usati - trattati
    assert not orfani, (
        f"`type` usati in features.yaml che il verificatore NON sa trattare: "
        f"{sorted(orfani)}.\nAggiungi il ramo `if kind == \"<tipo>\"` in "
        f"tools/verify-features.py, oppure correggi la voce. Una voce con un tipo "
        f"sconosciuto si dichiara verificata e non lo è.")


def test_nessun_verificatore_e_INTROVABILE():
    """Verso 2 — un `type` trattato, mai usato E non documentato: nessuno sa che c'è.

    🔻 LA PRIMA STESURA DI QUESTO TEST ERA SBAGLIATA, e vale la pena dirlo qui perché
    l'errore è della famiglia che il test cura. Chiedeva «trattato ⇒ usato», e cadeva
    su `cmd`, `grep_count`, `path_exists`. Sono andata a guardare **dove** stavano
    invece di credere al mio stesso rosso: sono descritti in `_schema`, cioè sono
    **strumenti dichiarati e disponibili**, non codice morto. Un verificatore che
    nessuno usa OGGI ma che è documentato è uno strumento nello strumentario; uno che
    nessuno usa e nessuno può scoprire è un ramo che nessuno toglierà mai.
    ⭐ La distinzione giusta non è «usato / non usato»: è **«conoscibile / no»**.

    ⇒ cade solo su un tipo che non è né usato da una voce né descritto in `_schema`.
    """
    trattati, usati = _tipi_trattati() - _MANUALI, _tipi_usati()
    documentati = set((yaml.safe_load(_LEDGER.read_text(errors="replace"))
                       or {}).get("_schema", {}).get("verify", {}) or {})
    if not documentati:                      # lo schema descrive i tipi altrove
        documentati = set(re.findall(r"^\s{4}([a-z_]+):",
                                     str((yaml.safe_load(_LEDGER.read_text()) or {})
                                         .get("_schema", "")), re.M))
    introvabili = trattati - usati - documentati
    assert not introvabili, (
        f"verificatori né usati né documentati in `_schema`: {sorted(introvabili)}.\n"
        f"Nessuno sa che esistono, quindi nessuno li userà e nessuno li toglierà. "
        f"O descrivili nello schema, o togli il ramo.")


def test_le_categorie_enumerate_e_quelle_seminate_sono_coerenti():
    """`CATEGORIE_IN_SEMINA` non può nominare una categoria che non si enumera.

    🔴 Il caso concreto: una semina scritta per una categoria mai aggiunta a
    `enum_reality` non segnala niente e sembra una protezione attiva. È la stessa
    forma di sopra su un terzo oggetto — un elenco che nomina cose di un altro elenco.
    """
    src = _VERIF.read_text(errors="replace")
    m = re.search(r"CATEGORIE_IN_SEMINA\s*=\s*\{([^}]*)\}", src)
    assert m, "CATEGORIE_IN_SEMINA non trovata: il test guarda un nome che non c'è più"
    seminate = set(re.findall(r'"([a-z_]+)"', m.group(1)))
    m2 = re.search(r'real:\s*dict\[str,\s*set\[str\]\]\s*=\s*\{(.*?)\}', src, re.S)
    assert m2, "il dizionario delle categorie reali non è più riconoscibile"
    enumerate_ = set(re.findall(r'"([a-z_]+)":\s*set\(\)', m2.group(1)))
    assert seminate <= enumerate_, (
        f"in semina ma MAI enumerate: {sorted(seminate - enumerate_)} — "
        f"una semina su una categoria che nessuno enumera non protegge niente")
