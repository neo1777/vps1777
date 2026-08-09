#!/usr/bin/env python3
"""«Chiude la #63» non chiude la #63: GitHub legge solo l'inglese.

PERCHÉ ESISTE, per intero — serve a chi lo vedrà fallire.

Il 09/08 **tre PR su tre** sono state mergiate con la loro cura dentro `main`, e **tre
issue sono rimaste aperte**: #69, #71, #63. Tutte e tre dicevano nel corpo «Chiude la
**#N**». GitHub chiude una issue solo con le keyword inglesi — `close/closes/closed`,
`fix/fixes/fixed`, `resolve/resolves/resolved` — seguite da `#N`.

## Perché è un difetto e non una svista

Il modo in cui fallisce è **silenzioso e assomiglia al successo**: la PR si mergia, il
corpo dice «chiude la #N», chi legge ha ogni ragione di crederlo, e la issue resta lì.
Nessuno se ne accorge finché qualcuno non passa a chiudere a mano — e quel qualcuno
scopre che il registro delle cose aperte contiene lavoro già fatto.

⚠️ La misura al primo caso (12:24) diceva «è l'unica delle ultime 12 PR» e su quella
avevo sconsigliato un gate: *un presidio per un caso solo è come curare un difetto morto.*
**Quella misura era vera alle 12:24 e alle 16:15 aveva tre casi in sei ore.** Questo file
esiste perché il numero è cambiato, non perché il primo giudizio fosse sbagliato.

## Cosa fa, e cosa NON fa

Fallisce **solo** se il testo annuncia una chiusura in italiano per un numero che NON è
coperto da una keyword inglese sullo stesso numero. Una PR che non chiude niente, o che
usa già `Closes #N`, o che nomina `#N` di passaggio, non lo tocca.

Non riscrive niente e non chiude niente da sé: **dice la riga da aggiungere**. Una
correzione automatica qui sarebbe peggio del difetto — il testo di una PR è di chi la
scrive, e un bot che ci mette dentro `Closes #N` deciderebbe al posto suo *quale* issue
si chiude.

Stile: stdlib-only. Il testo si passa da **stdin** o dalla variabile `PR_BODY` — mai come
argomento e mai interpolato in uno script di shell: il corpo di una PR lo scrive chiunque
la apra, e finirebbe eseguito.

Uso:   python3 tools/gate-chiusura-issue.py < corpo.txt
       PR_BODY="$(cat corpo.txt)" python3 tools/gate-chiusura-issue.py
"""
from __future__ import annotations

import os
import re
import sys

# Le keyword che GitHub riconosce davvero (docs: "Linking a pull request to an issue").
EN = r"(?:clos(?:e|es|ed)|fix(?:es|ed)?|resolv(?:e|es|ed))"
# Come lo scriviamo noi quando crediamo di chiudere: verbo italiano + eventuale articolo.
IT = r"(?:chiud(?:e|ono)|risolv(?:e|ono)|chiusa|risolta|fixa)"

RE_EN = re.compile(rf"\b{EN}\s+(?:the\s+)?[*_`]*#(\d+)", re.I)
RE_IT = re.compile(rf"\b{IT}\s+(?:la\s+|il\s+|le\s+|i\s+)?[*_`]*#(\d+)", re.I)


# Ciò che è CITATO non è ciò che si sta facendo: code-span `…`, blocchi ``` … ``` e righe
# di citazione «> …». Vanno tolti PRIMA di cercare l'annuncio.
RE_FENCE = re.compile(r"```.*?```", re.S)
RE_CODE = re.compile(r"`[^`\n]+`")
RE_QUOTE = re.compile(r"^\s*>.*$", re.M)


def senza_citazioni(testo: str) -> str:
    """Toglie il testo che PARLA invece di FARE.

    🔴 Trovato eseguendo il gate sulla PR che lo introduce. Quel corpo cita
    «(chiude #71)» come *esempio del difetto*, e il gate stava per fallire su sé stesso.
    Non è fallito solo perché nella stessa pagina compariva anche `Fixes #71` fra i casi
    di prova, che copriva il numero: **è passato per fortuna, non per correttezza.**

    ⭐ È la trappola H48 — *i commenti che documentano la cura contengono la stringa del
    difetto* — e qui morde più forte che altrove, perché in questo repo **spiegare un
    difetto a parole è la norma**: un gate che scatta su chi lo descrive verrebbe
    disattivato dalla prima PR che prova a raccontarlo.
    """
    t = RE_FENCE.sub(" ", testo)
    t = RE_CODE.sub(" ", t)
    return RE_QUOTE.sub(" ", t)


def issue_non_chiuse(testo: str) -> list[str]:
    """I numeri annunciati come chiusi in italiano e non coperti da una keyword inglese."""
    # Le keyword inglesi si cercano nel testo INTERO: `Closes #63` scritto dentro un
    # code-span resta un'intenzione dichiarata dall'autrice, e vale come copertura.
    # L'annuncio italiano no: quello si cerca solo dove il testo FA, non dove cita.
    it = RE_IT.findall(senza_citazioni(testo))
    en = set(RE_EN.findall(testo))
    # dedup mantenendo l'ordine di apparizione: chi legge cerca il primo caso, non un set
    visti, fuori = set(), []
    for n in it:
        if n not in en and n not in visti:
            visti.add(n)
            fuori.append(n)
    return fuori


def main() -> int:
    testo = os.environ.get("PR_BODY")
    if testo is None:
        testo = sys.stdin.read() if not sys.stdin.isatty() else ""
    # Anche il TITOLO va guardato, e non per completezza: la #132 di oggi annunciava
    # «(chiude #71)» nel titolo *e* nel corpo. GitHub non chiude da titolo — solo corpo
    # e messaggi di commit — quindi un annuncio lì è ancora più muto: sta nel posto più
    # visibile e nel meno efficace.
    testo = (os.environ.get("PR_TITLE", "") + "\n" + testo).strip()
    if not testo.strip():
        # Un corpo vuoto non è un difetto: non annuncia nessuna chiusura. Ma lo si dice,
        # perché «nessun problema trovato» e «non ho avuto niente da guardare» sono due
        # esiti diversi che qui uscirebbero entrambi 0.
        print("⚪ nessun testo da esaminare (corpo vuoto): non ho misurato niente.")
        return 0

    fuori = issue_non_chiuse(testo)
    if not fuori:
        return 0

    plurale = "issue" if len(fuori) == 1 else "issue"
    print(f"✗ {len(fuori)} {plurale} annunciate come chiuse in italiano che GitHub NON chiuderà:")
    for n in fuori:
        print(f"    #{n}")
    print()
    print("  GitHub riconosce solo le keyword inglesi (closes/fixes/resolves + #N).")
    print("  Scritto in italiano, l'annuncio è una DICHIARAZIONE D'INTENTO che nessuno esegue:")
    print("  la PR si mergia, il corpo dice «chiude la #N», e la issue resta aperta.")
    print("  Successo e fallimento hanno lo stesso aspetto — per questo serve un gate.")
    print()
    print("  Aggiungi al corpo della PR una riga per ciascuna (anche in fondo, anche")
    print("  accanto alla frase italiana, che resta più leggibile):")
    for n in fuori:
        print(f"    Closes #{n}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
