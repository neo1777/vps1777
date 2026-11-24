"""`applicabilita.yml`: ciò che il repo dichiara di sé allo standard 1777 non si stacca dal repo.

Il file lo leggono gli strumenti dello standard (ancora privato), che qui non girano. Ma la dichiarazione
nomina file, comandi e stringhe di QUESTO repo: se uno sparisce o cambia nome, la dichiarazione mente
senza che nessuna CI di qui se ne accorga, e il controllo dello standard va rosso (o, peggio, NON
MISURATO) settimane dopo. Qui si presidia il legame: ogni cosa nominata esiste.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

RADICE = Path(__file__).resolve().parents[2]
TESTO = (RADICE / "applicabilita.yml").read_text(encoding="utf-8")
D = yaml.safe_load(TESTO)


def test_dice_in_testa_che_lo_standard_e_ancora_privato():
    """Scelta dell'owner del 24/11/2026: il file sta nel repo pubblico, e lo dice a chi legge da fuori."""
    testa = "\n".join(TESTO.split("\n")[:6])
    assert "ancora PRIVATO" in testa and "non" in testa and "rilanciare i controlli" in testa


def test_ogni_componente_punta_a_una_cartella_che_esiste():
    for c in D["componenti"]:
        percorsi = c["percorso"] if isinstance(c["percorso"], list) else [c["percorso"]]
        for p in percorsi:
            assert (RADICE / p).is_dir(), f"componente {c['id']}: {p} non esiste"


def test_i_file_citati_accanto_alle_superfici_esistono():
    """Accanto a ogni «sì» rilevato c'è il file dove il rilevatore lo trova: deve esserci ancora."""
    mancanti = []
    for riga in TESTO.split("\n"):
        if "#" not in riga or ": sì" not in riga:
            continue
        for f in re.findall(r"((?:services|tools|security|installer|plugins|\.github)/[\w./-]+\.\w+)", riga.split("#", 1)[1]):
            if not (RADICE / f).is_file():
                mancanti.append(f)
    assert not mancanti, f"file citati che non esistono più: {mancanti}"


def test_il_registro_e_il_suo_controllo_esistono():
    assert (RADICE / D["controlli"]["registro"]).is_file()
    assert (RADICE / D["controlli"]["checker"].split()[-1]).is_file()


def _script_nei_comandi() -> list[str]:
    trovati: list[str] = []

    def visita(x):
        if isinstance(x, str):
            trovati.extend(re.findall(r"((?:tools|security|services)/[\w./-]+\.(?:sh|py|lock))", x))
        elif isinstance(x, dict):
            for v in x.values():
                visita(v)
        elif isinstance(x, list):
            for v in x:
                visita(v)
    visita(D["prove"])
    return trovati


def test_i_comandi_delle_prove_puntano_a_file_che_esistono():
    script = _script_nei_comandi()
    assert len(script) >= 8, script
    assert not [s for s in script if not (RADICE / s).is_file()]


def test_sta06_le_due_stringhe_cercate_nelle_corse_stanno_nel_workflow():
    """Il controllo dello standard cerca `prova` e `senza_rollback` come TESTO nelle corse di
    rollback.yml: se una delle due cambia nel workflow, deve cambiare anche qui."""
    p = D["prove"]["STA-06"]
    wf = (RADICE / p["lanciata_da"]["workflow"]).read_text(encoding="utf-8")
    assert p["prova"].split("/")[-1] in wf
    assert p["senza_rollback"] in wf
    job = yaml.safe_load(wf)["jobs"][p["lanciata_da"]["job"]]
    assert job["strategy"]["matrix"][p["lanciata_da"]["matrice"]] == [p["lanciata_da"]["sano"], p["lanciata_da"]["sabotato"]]
    assert p["tetto_giorni"] == 31


def test_sta08_il_referto_del_collaudo_c_e():
    assert list(RADICE.glob(D["prove"]["STA-08"]["referto"]))


def test_le_due_superfici_non_rilevabili_sono_confermate_dall_owner():
    s = D["default"]["superfici"]
    assert s["dati.personali"] == "sì" and s["llm.contenuto-non-fidato"] == "sì"
    assert TESTO.count("# confermata:") == 2
