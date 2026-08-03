"""Guardia sullo SPAZIO DISCO prima di accettare un upload d'archivio.

Perché esiste — e la storia conta, perché il difetto era scritto e non fatto.

`archive_indexer.py:105` porta da tre settimane questa riga:

    # Il disco della VPS deve avere spazio per upload + DB: verificare prima dei giganti.

**Nessuno lo verificava.** Misurato il 03/08 sul repo intero: zero `statvfs`, zero
`disk_usage` in tutto `services/`. È un difetto scritto come specifica — la riga
*descrive il rimedio*, e chi la legge non la sente come «da fare» perché ha la forma
di una cosa già decisa. (Trovato dall'audit del round-16, rilievo C⑤, e verificato.)

Il danno che previene non è l'upload fallito: è il **disco pieno**. Il loop di scrittura
si ferma solo al tetto di 4 GB — su un disco corto riempie tutto e muore a metà, e sulla
stessa partizione stanno il DB dell'archivio e i suoi journal. `archive-mcp` monta quel
volume in `:ro` (H46): a disco pieno non potrebbe nemmeno riparare il proprio journal.

Stile stdlib-only come il resto della suite del gateway: si ispeziona il sorgente, perché
la proprietà è *strutturale* (esiste un controllo, e sta PRIMA della scrittura).
"""
from __future__ import annotations

from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
SRC = (APP / "admin.py").read_text(encoding="utf-8")


def _solo_codice(testo: str) -> str:
    """Le righe eseguibili: il commento della cura NOMINA `disk_usage` per spiegarla,
    e un test ingenuo lo leggerebbe come la presenza del controllo."""
    fuori, dentro = [], False
    for riga in testo.splitlines():
        spoglia = riga.strip()
        if spoglia.count('"""') == 1:
            dentro = not dentro
            continue
        if dentro or spoglia.startswith("#"):
            continue
        fuori.append(riga.split("  #")[0])
    return "\n".join(fuori)


CODICE = _solo_codice(SRC)


def test_lo_spazio_si_misura_davvero():
    """Non «c'è una costante che parla di spazio»: c'è una CHIAMATA che lo misura."""
    assert "shutil.disk_usage(" in CODICE, (
        "nessuna misura dello spazio: la riga di archive_indexer.py:105 "
        "prescrive di verificarlo «prima dei giganti», e prescrivere non è fare"
    )
    assert "import shutil" in CODICE, "shutil non importato: la chiamata non girerebbe"


def test_il_controllo_viene_PRIMA_della_scrittura():
    """Ordine non negoziabile: dopo il primo `open(tmp, "wb")` è troppo tardi —
    il file esiste già e il disco ha già cominciato a riempirsi."""
    assert CODICE.index("shutil.disk_usage(") < CODICE.index('open(tmp, "wb")'), (
        "il controllo dello spazio deve precedere l'apertura del file temporaneo"
    )


def test_la_soglia_NON_e_un_numero_nuovo():
    """La soglia è `MAX_UPLOAD_BYTES`, che esiste già.

    Non conosciamo la dimensione dell'upload in anticipo (è uno stream), quindi
    l'unica soglia onesta è «lo spazio che servirebbe nel caso peggiore ammesso».
    Un numero inventato qui sarebbe la classe di difetto che questo repo passa la
    giornata a smontare: una costante plausibile che nessuno ha misurato.
    """
    blocco = CODICE[CODICE.index("shutil.disk_usage("):]
    blocco = blocco[:blocco.index('open(tmp, "wb")')]
    assert "MAX_UPLOAD_BYTES" in blocco, "la soglia deve venire dal tetto già definito"
    import re
    numeri = [n for n in re.findall(r"\b\d{4,}\b", blocco) if n not in ("1024",)]
    assert not numeri, f"soglia con numeri nuovi non misurati: {numeri}"


def test_il_rifiuto_lascia_un_audit():
    """Un rifiuto senza traccia è un rifiuto di cui non sai se è mai scattato —
    ed è l'unico modo per accorgersi che il disco si sta stringendo."""
    assert "admin_archive_upload_rifiutato_spazio" in CODICE


def test_non_misurabile_NON_diventa_un_rifiuto():
    """Se `disk_usage` esplode (filesystem esotico, permessi), NON si blocca l'upload.

    «Non ho potuto guardare» e «ho guardato e non c'è spazio» sono due cose: trattarle
    uguali renderebbe questa guardia un blocco su un errore di misura — cioè
    esattamente il falso positivo che rende gli allarmi inutili.
    """
    blocco = CODICE[CODICE.index("shutil.disk_usage("):]
    blocco = blocco[:blocco.index('open(tmp, "wb")')]
    assert "except OSError" in blocco, "l'errore di misura va catturato"
    assert "is not None" in blocco, (
        "il ramo 'non misurabile' deve essere distinto dal ramo 'spazio insufficiente'"
    )
