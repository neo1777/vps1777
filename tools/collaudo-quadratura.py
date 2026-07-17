#!/usr/bin/env python3
"""Collaudo della quadratura di un ingest in archive1777.

  Uso:  python3 collaudo-quadratura.py <db> --sorgente N [--ingest-n N]

Risponde a UNA domanda: **il corpus è entrato tutto, o si è perso qualcosa?**
E la risponde in modo che un residuo non possa essere confuso con una perdita.

LA FORMULA, e perché non è quella che credevamo
-----------------------------------------------
Ci siamo passate tutto il giorno: «export = indicizzati + skipped». Sembra ovvio
finché non provi con numeri noti. Misurato il 16/07 su un corpus costruito apposta
(11 righe: 5 buone, 1 doppione esatto, 3 senza uuid, 2 vuote):

    n_ingest        + skipped =  6 + 5 = 11  vs sorgente 11   ✓ CHIUDE
    COUNT(messages) + skipped =  5 + 5 = 10  vs sorgente 11   ✗ NON chiude

**«Indicizzati» NON è `COUNT(messages)`.** `write_rows` conta le righe che *legge*
(`n += 1` prima della scrittura); la tabella poi **deduplica** per uuid con
`INSERT OR REPLACE`. Quindi dal DB, a posteriori, manca una riga per ogni doppione —
e **quel buco non è una perdita: è la deduplica che ha fatto il suo mestiere.**

Un collaudo che guarda solo il DB lo legge come «un messaggio sparito» e ti manda a
cercare un bug nell'ingest per una cosa andata bene. È la figura di tutta la giornata:
`COUNT(messages)` risponde onestamente a *«quanti messaggi distinti ho»* — che non è
la domanda *«quanti ne ho letti»*. Lo strumento non mente: risponde a un'altra domanda.

→ **Il numero da annotare è quello che l'ingest STAMPA** (`n`). Se lo perdi, la
quadratura non è più ricostruibile e il residuo-doppioni resta indistinguibile da una
perdita vera, per sempre. Questo script lo chiede, e se non ce l'hai te lo dice
invece di indovinarlo.

NON TUTTE LE RIGHE SONO EVENTI (scoperto sul carico vero, 17/07)
----------------------------------------------------------------
L'archivio contiene **due specie** di righe, e questo script quadra solo la prima:

- **eventi** — le chat: accadono in un istante, hanno un `ts`, **non cambiano mai più**;
- **stati** — `memory:*` e `account:user`: non accadono, *sono*. **Nessuna data**, e
  **vengono riscritti**.

Lo schema ha una sola colonna `ts` e presuppone che tutto sia un evento. Da lì tre
sintomi che sembrano bug e non lo sono: `describe_databases` dice `oldest: ""` (il
`MIN` su una stringa vuota vince su ogni data); `archive_stats` non colloca quelle
righe in nessun anno; e **confrontando due snapshot gli stati sembrano "perdite"**.

Misurato sui due export di Neo, e chiude a zero in entrambi:

    08/07 : 49 memory + 1 account:user = 50 righe senza data
    16/07 : 57 memory + 1 account:user = 58 righe senza data
    (il DB Telegram quadra perfetto: sono solo messaggi, e un messaggio la data ce l'ha sempre)

→ **Quadra le chat, non gli stati.** Se confronti due date e vedi `memory:conversations`
passare da 6 a 4, **non hai perso 2 messaggi**: hai fotografato due volte un documento
vivo. Contarli come conversazioni produce perdite fantasma — ed è la stessa domanda
della chiave primaria qui sotto, con un'altra faccia: *quando due cose sono la stessa
cosa?* Stessa colonna ≠ stessa specie.

PERCHÉ I BUCKET SI STAMPANO SINGOLARMENTE
-----------------------------------------
Un totale che torna grazie a due errori che si compensano è peggio di un totale che
non torna. E i bucket non sono un enum: `reason` è una stringa libera (i call-site ne
emettono 4 — `empty`, `no-uuid`, `no-uuid-o-ts`, `non-dict` — da 5 punti diversi:
`empty` è emesso da due). Non aspettarti un numero fisso di bucket: **leggi quelli che
trovi**. Il «5 bucket» che ci siamo passate contava i call-site, non i bucket.

Storia: il ledger prima della v0.37.3 **collassava** gli scarti `no-uuid-o-ts` (il
`detail` portava il *tipo*, non la riga → stesso `uid` → `INSERT OR IGNORE`). Contava i
*tipi* di scarto, non gli scarti. Se giri su un DB costruito con una versione
precedente, quel bucket è sotto-riportato: verifica la versione prima di credere al
residuo.

b82df434 · 2026-07-16 · stdlib only.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="Quadratura di un ingest archive1777")
    ap.add_argument("db", type=Path, help="il .db da collaudare")
    ap.add_argument("--sorgente", type=int, required=True,
                    help="righe TOTALI del corpus dato in pasto (contate alla fonte)")
    ap.add_argument("--ingest-n", type=int, default=None,
                    help="il numero che l'ingest ha STAMPATO (righe lette non scartate). "
                         "Senza questo la quadratura non è ricostruibile: vedi il docstring.")
    a = ap.parse_args()

    if not a.db.exists():
        print(f"✗ non trovo {a.db}")
        return 2

    conn = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)  # sola lettura: non tocco i dati
    try:
        msgs = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        try:
            buckets = list(conn.execute(
                "SELECT reason, COUNT(*) FROM skipped GROUP BY reason ORDER BY 2 DESC"))
        except sqlite3.OperationalError:
            print("✗ questo DB non ha la tabella `skipped`: è stato costruito prima del")
            print("  libro-mastro (D3/#56). La quadratura non è calcolabile — gli scarti")
            print("  di quell'ingest non esistono da nessuna parte. Ri-ingerisci.")
            return 2
        skip_tot = sum(c for _, c in buckets)
    finally:
        conn.close()

    # Gli STATI (memory:*, account:user) non sono eventi: niente `ts`, e vengono
    # riscritti. Vanno contati a parte o produrranno "perdite" fantasma.
    conn = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    try:
        stati = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE project LIKE 'memory:%'"
            " OR project LIKE 'account:%'").fetchone()[0]
        senza_ts = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE ts IS NULL OR ts = ''").fetchone()[0]
    except sqlite3.OperationalError:
        stati = senza_ts = None
    finally:
        conn.close()

    print(f"\n  db            : {a.db}")
    print(f"  sorgente      : {a.sorgente} righe (dichiarate)")
    print(f"  messages      : {msgs}  (DISTINTI, post-dedup)")
    print(f"  skipped       : {skip_tot}")
    if stati:
        print(f"\n  ⓘ  STATI (non eventi): {stati} righe  ·  righe senza `ts`: {senza_ts}")
        print("     `memory:*` e `account:*` non sono conversazioni: sono documenti VIVI,")
        print("     senza data, che vengono RISCRITTI. Fra due snapshot CAMBIANO — e non è")
        print("     una perdita. Se stai confrontando due date, quadra le chat, non questi.")
        if senza_ts and senza_ts != stati:
            print(f"     ⚠ {senza_ts - stati} righe senza `ts` NON sono stati: quelle vanno guardate.")
    print("\n  bucket degli scarti (i nomi sono quelli che trovo, non quelli che mi aspetto):")
    if not buckets:
        print("    (nessuno scarto registrato)")
    for reason, c in buckets:
        print(f"    {reason:18s} {c}")

    if a.ingest_n is None:
        print("\n  ⚠ QUADRATURA NON CALCOLABILE: manca --ingest-n (il numero stampato dall'ingest).")
        print("    Dal solo DB non si distingue un DOPPIONE COLLASSATO da un MESSAGGIO PERSO:")
        print(f"    `messages + skipped` = {msgs + skip_tot} vs sorgente {a.sorgente} "
              f"→ scarto {a.sorgente - msgs - skip_tot}, di natura IGNOTA.")
        print("    Non tiro a indovinare. Recupera il numero dall'output dell'ingest,")
        print("    oppure ri-ingerisci annotandolo.")
        return 1

    quadra = a.ingest_n + skip_tot
    doppioni = a.ingest_n - msgs
    residuo = a.sorgente - quadra

    print(f"\n  QUADRATURA:  n_ingest({a.ingest_n}) + skipped({skip_tot}) = {quadra}"
          f"  vs sorgente({a.sorgente})")
    print(f"  doppioni collassati (n − messages): {doppioni}"
          + ("   ← informazione, NON un allarme: la dedup ha lavorato" if doppioni else ""))

    if residuo == 0:
        print("\n  ✓ QUADRA. Residuo inspiegato: ZERO. Ogni riga della sorgente è")
        print("    indicizzata, oppure ha la sua lapide con un motivo.")
        return 0

    print(f"\n  ✗ NON QUADRA. Residuo inspiegato: {residuo} righe.")
    print("    Non sono doppioni (quelli sono già contati sopra) e non sono scarti")
    print("    (quelli hanno la lapide). Sono righe che la sorgente ha e di cui")
    print("    l'archivio non sa NULLA: né indicizzate, né dichiarate perse.")
    print("    È il difetto che il libro-mastro esiste per rendere impossibile.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
