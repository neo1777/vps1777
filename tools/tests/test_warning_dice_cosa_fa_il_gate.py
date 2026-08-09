#!/usr/bin/env python3
"""Il warning all'avvio deve descrivere il gate CHE C'È, non un altro.

PERCHÉ ESISTE, per intero — serve a chi lo vedrà fallire.

`nb1777-bot`, senza `TELEGRAM_OWNER_ID`, loggava:

    «TELEGRAM_OWNER_ID=0 — bot accetterà chiunque! Configura in .env»

Ed era **l'opposto** di quello che il codice fa. Il gate è fail-closed:

    if not s.telegram_owner_id or user_id != s.telegram_owner_id:   # bot.py

con `owner_id == 0` la prima condizione è vera per chiunque ⇒ **nega a tutti**. È la
garanzia H1 di `SECURITY.md` («Owner-gating fail-closed», critico), e regge: il difetto
era solo nella frase (issue #71).

## Perché un test, e non solo una riga corretta

Un messaggio di log che descrive il rischio sbagliato **non è prosa**: è ciò che una
persona legge in produzione alle tre di notte. Chi vede «accetterà chiunque» crede di
avere un bot aperto e agisce di corsa — o, peggio, impara a non fidarsi di un gate che
invece funziona. *Il codice era giusto e il difetto stava nella cosa che l'operatore
legge: la sola parte del sistema che nessun test guardava.*

E il rischio è di **divergenza**, non di battitura: il gate e il messaggio stanno in due
file diversi (`bot.py` e `__main__.py`). Chi domani cambia il gate — per esempio
tornando a `if s.telegram_owner_id and …`, che è fail-OPEN — non ha nulla che gli
ricordi il messaggio. Questo test lega le due cose: se il gate diventa fail-open, la
frase «NEGA A TUTTI» diventa falsa **e il test lo dice**.

Stile: stdlib-only, legge i sorgenti (nessun bot da avviare).
Uso:  python3 tools/tests/test_warning_dice_cosa_fa_il_gate.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "services/nb1777-bot/app/__main__.py"
BOT = ROOT / "services/nb1777-bot/app/bot.py"


def main() -> int:
    if not (MAIN.is_file() and BOT.is_file()):
        print("✗ sorgenti del bot non trovati: la sonda non sta guardando il repo giusto")
        return 1
    main_src, bot_src = MAIN.read_text(encoding="utf-8"), BOT.read_text(encoding="utf-8")
    errori = 0

    # ① il gate: fail-CLOSED significa che l'assenza di owner NEGA. La forma è
    #    `not <owner> or <diverso>`; la forma fail-OPEN sarebbe `<owner> and <diverso>`.
    chiuso = re.search(r"if\s+not\s+s\.telegram_owner_id\s+or\s+user_id\s*!=", bot_src)
    aperto = re.search(r"if\s+s\.telegram_owner_id\s+and\s+user_id\s*!=", bot_src)
    if aperto and not chiuso:
        errori += 1
        print("  ✗ IL GATE È DIVENTATO FAIL-OPEN (bot.py): `owner and ...` corto-circuita\n"
              "      su owner==0 e il bot risponde a CHIUNQUE. È la regressione di H1,\n"
              "      non un dettaglio di stile — e il warning all'avvio ora mente.")
    elif not chiuso:
        errori += 1
        print("  ✗ non riconosco più la forma del gate in bot.py: rileggilo a mano.\n"
              "      (Questo test non sa dire se sei protetto: NON è un verde.)")
    else:
        print("  ✓ gate fail-closed in bot.py: senza owner configurato nega a tutti")

    # ② il messaggio deve dire QUELLO. Le righe sono le sole `log.warning` — non i
    #    commenti, che qui NOMINANO la frase vecchia per spiegare perché era sbagliata
    #    (ed è la trappola in cui un grep sul testo grezzo cadrebbe: H48).
    warn = " ".join(re.findall(r"log\.warning\((.*?)\)\n", main_src, re.S))
    if "accetterà chiunque" in warn:
        errori += 1
        print("  ✗ il warning dice «accetterà chiunque» mentre il gate NEGA a tutti.\n"
              "      Chi legge il log in produzione crede di avere un bot aperto.")
    elif "NEGA A TUTTI" not in warn:
        errori += 1
        print("  ✗ il warning su owner mancante non dice più che il bot NEGA a tutti.\n"
              "      Se l'hai riscritto, dillo con parole che descrivano il gate vero.")
    else:
        print("  ✓ il warning descrive il gate che c'è: «NEGA A TUTTI»")

    return 1 if errori else 0


def test_presidio_gira_anche_in_ci() -> None:
    """Il gancio che rende questo file un test PER PYTEST, non solo per la mano.

    Senza, `uvx pytest tools/tests/` — la riga che lo esegue in CI — RACCOGLIE il file
    (il nome combacia) e **non esegue niente**: nessuna funzione `test_*`, nessun errore,
    verde. Misurato il 09/08 sabotando questo file su `main`: eseguito a mano usciva 1,
    la suite restava «250 passed».
    ⭐ Tre presidi mergiati lo stesso giorno avevano tutti e tre questo buco, e li avevamo
    revisionati PROVANDOLI — con `python3 <file>`, cioè **nel modo in cui non verranno mai
    eseguiti**. *La prova a mano e la prova in CI rispondono a due domande diverse.*
    """
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
