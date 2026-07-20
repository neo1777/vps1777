"""Guardie sull'endpoint D9 — `set_description` inoltrata al gateway.

Stile dei test del gateway: stdlib-only, niente app in piedi. Per le proprietà
di SICUREZZA si ispeziona il sorgente, come fa già `test_oauth_consent` con la
guardia H32 sul `compare_digest`. Non è un ripiego: queste proprietà sono
*strutturali* (l'ordine dei controlli, il codice di risposta scelto), e un test
che le legge nel sorgente resiste anche a un refactoring che le riscriverebbe
in buona fede.
"""
from __future__ import annotations

import re
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / "app" / "routes.py").read_text(encoding="utf-8")
FUNC = SRC[SRC.index("async def internal_archive_description"):SRC.index("\nroutes = [")]

def _solo_codice(testo: str) -> str:
    """Le righe eseguibili, senza commenti né docstring.

    Serve perché una guardia che cerca una stringa nel sorgente non deve
    inciampare nella PROSA che spiega la scelta: il commento di questa funzione
    dice «risponde 404, non 403», e un test ingenuo lo leggerebbe come la
    presenza di un 403 nel codice. Un test-guardia deve distinguere ciò che il
    programma FA da ciò che il programma RACCONTA — che è, in piccolo, la stessa
    distinzione su cui abbiamo passato la giornata.
    """
    fuori, dentro = [], False
    for riga in testo.splitlines():
        spoglia = riga.strip()
        if spoglia.count('"""') == 1:
            dentro = not dentro
            continue
        if dentro or spoglia.startswith("#") or spoglia.startswith('"""'):
            continue
        fuori.append(riga.split("  #")[0])
    return "\n".join(fuori)

CODICE = _solo_codice(FUNC)


def test_risponde_404_e_mai_403():
    """Un 403 confermerebbe che la rotta esiste a chi la sta cercando.

    La rotta è raggiungibile dall'esterno per costruzione (Caddy fa reverse_proxy
    catch-all sul gateway), quindi il codice di risposta è esso stesso
    un'informazione: si nega l'esistenza, non il permesso.
    """
    assert "403" not in CODICE, "un 403 rivela che la rotta esiste"
    assert CODICE.count("404") >= 2, "sia il controllo di rete sia quello del segreto negano con 404"


def test_il_controllo_di_rete_viene_prima_del_segreto():
    """Ordine non negoziabile: chi arriva da fuori non deve nemmeno arrivare al
    confronto del segreto. Se l'ordine si invertisse, un attaccante esterno
    potrebbe misurare i tempi di risposta del confronto."""
    assert CODICE.index("ip_is_internal") < CODICE.index("compare_digest")


def test_il_segreto_e_constant_time_e_fail_closed():
    assert "hmac.compare_digest" in CODICE, "confronto non constant-time"
    assert "not atteso or" in CODICE, "segreto non configurato deve NEGARE (fail-closed)"


def test_il_path_lo_costruisce_il_gateway_non_il_chiamante():
    """Path traversal impossibile per costruzione: il chiamante manda un NOME,
    il percorso lo compone il gateway a partire dalla sua directory."""
    assert 'Path(s.archive_db_dir)' in CODICE
    assert re.search(r'fullmatch\(r"\[A-Za-z0-9\._-\]', CODICE), "nome del db non validato"


def test_d17_la_description_e_trattata_come_dato_non_fidato():
    """D17, che Neo ha voluto DENTRO la D9: quel campo finisce nel contesto di
    un LLM con l'autorevolezza di un metadato di sistema."""
    assert "_MAX_DESCRIZIONE" in CODICE, "manca il cap di lunghezza"
    assert "control_chars" in CODICE, "i caratteri di controllo vanno rifiutati"


def test_ogni_scrittura_lascia_un_audit():
    """Un canale di scrittura senza log è un canale di cui non sai se è stato usato."""
    assert CODICE.count("audit(") >= 3, "servono audit sui due rifiuti e sulla scrittura"
    assert "archive_desc_set" in CODICE


def test_scrive_solo_la_description_e_nulla_altro():
    """L'unica scrittura ammessa resta quella: nessun altro campo raggiungibile."""
    assert 'set_meta(db_path, "description", desc)' in CODICE
    assert CODICE.count("set_meta") == 1


def test_la_rotta_e_registrata():
    assert '"/internal/archive/description"' in SRC
    assert 'methods=["POST"]' in SRC[SRC.index("/internal/archive/description"):][:120]
