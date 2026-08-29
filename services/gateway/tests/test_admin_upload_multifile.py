"""L'upload d'archivio accetta PIÙ file in un gesto, tutti sullo stesso nome DB.

Perché esiste (29/08/2026): claude.ai ha smesso di consegnare l'export come un
file unico — dà un manifest coi link one-shot e 5 zip per categoria. Con il form
a un file solo erano 5 upload a mano con il nome DB ribattuto uguale 5 volte
(vuoto = «dal nome file» → cinque DB `conversations-000`, `projects-000`, …).

Stile della suite del gateway: stdlib-only, si ispeziona il sorgente — la
proprietà è strutturale (il form dichiara `multiple`, il handler legge la LISTA,
ogni file ha la sua pulizia e le sue guardie, e un errore a metà dice cosa è
già entrato).
"""
from __future__ import annotations

from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
SRC = (APP / "admin.py").read_text(encoding="utf-8")


def _solo_codice(testo: str) -> str:
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


def test_il_form_dichiara_multiple_sul_campo_fonte():
    """Senza `multiple` il browser manda un file solo, qualunque cosa faccia il handler."""
    riga = next(r for r in SRC.splitlines() if 'name="jsonl_file"' in r and "<input" in r)
    assert " multiple" in riga, riga


def test_il_handler_legge_la_lista_non_il_primo():
    """`form.get` restituisce UN file anche quando ne arrivano cinque: gli altri
    quattro sparirebbero in silenzio — nessun errore, nessun record."""
    assert 'form.getlist("jsonl_file")' in CODICE
    assert 'form.get("jsonl_file")' not in CODICE


def test_ogni_file_passa_dalle_guardie_e_pulisce_il_suo_temporaneo():
    """Le guardie (spazio disco, tetto) e la pulizia del `.upload-*` stanno DENTRO
    il ciclo: un check fatto una volta per cinque file misura lo spazio prima
    del primo, non prima del quinto."""
    i_for = CODICE.index("for upload in uploads:")
    i_disk = CODICE.index("shutil.disk_usage(")
    i_open = CODICE.index('open(tmp, "wb")')
    i_index = CODICE.index("archive_indexer.index_file(")
    assert i_for < i_disk < i_open < i_index
    # il finally per-file: il primo `tmp.unlink` dopo il for sta più dentro del for
    blocco = CODICE[i_for:]
    riga_for = next(r for r in CODICE.splitlines() if "for upload in uploads:" in r)
    riga_unlink = next(r for r in blocco.splitlines() if "tmp.unlink(missing_ok=True)" in r)
    indent = lambda r: len(r) - len(r.lstrip())  # noqa: E731
    assert indent(riga_unlink) > indent(riga_for), "la pulizia del temporaneo non è per-file"


def test_un_errore_a_meta_dice_cosa_e_gia_entrato():
    """Ogni file è la sua transazione: se il terzo fallisce, i primi due sono nel DB.
    Un «Errore» secco farebbe ricaricare anche quelli — innocuo (dedup), ma è
    tempo perso e, peggio, l'utente non sa cosa ha in archivio."""
    assert "già indicizzati" in SRC
    assert '"file": nome_file' in CODICE, "l'audit deve dire QUALE file, non solo il DB"


def test_il_messaggio_di_esito_e_per_file():
    assert "esiti.append(" in CODICE
    assert "len(esiti)" in CODICE
