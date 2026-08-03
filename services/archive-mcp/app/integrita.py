"""Integrità dell'archivio — logica PURA, stdlib-only, testabile senza il runtime.

🔓 PERCHÉ È UN MODULO A SÉ e non sta dentro `db.py`. La CI esegue questa suite
   con `uvx pytest` (`ci.yml:156`, e il nome dello step lo dice: «stdlib-only»).
   `db.py` importa `settings` → pydantic, che in quel job non c'è: un test che
   importasse `db.py` **non darebbe rosso sul merito, romperebbe la RACCOLTA**,
   portandosi dietro gli altri 46 test del job. *Misurato, non temuto:*
   `ModuleNotFoundError: No module named 'app'`, run 30806066015, exit 2.
   ⇒ È la separazione che `fts.py` già dichiara nel proprio docstring («logica
     FTS pura, stdlib-only, testabile senza il runtime del server»).
     **Non è una struttura nuova: è quella, applicata dove mancava.**

📌 E la ragione per cui l'ho scoperto invece di dedurlo: avevo scritto il test
   importando `app.db` con `settings` stubbato. In locale passava; in CI il job
   è uscito 2. **La forma giusta era nel file accanto** — `test_fts.py:13` mette
   `app/` in `sys.path` e importa il MODULO, non il pacchetto.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class ArchivioSporco(RuntimeError):
    """Il DB ha un journal caldo: uno scrittore è morto a metà transazione.

    Non è un errore di questo servizio ed è **irreparabile da qui**: il volume è
    montato in sola lettura di proposito (a scrivere è il gateway), e SQLite non
    può fare il rollback di un journal senza permesso di scrittura.
    """


def journal_caldo(percorso: Path) -> Path | None:
    """Il journal di rollback esiste e non è vuoto? Allora la scrittura è morta a metà.

    🔓 Round-16, rilievo `bd02ca6f` (audio B, «cosa non è coperto da niente»). Il
       gateway monta `archive-data` in `:rw` (compose.yaml:105), archive-mcp in
       `:ro` (compose.yaml:167). Se il gateway muore a metà scrittura — OOM
       killer, SIGKILL, container fermato — resta un `-journal` caldo, **e qui
       nessuno ripulisce**. `H46` traccia la convivenza `:ro`/`:rw` e dichiara
       che il `:rw` è funzionale: non copre il caso CRASH.

    ⚠️ COSA FA SQLITE SENZA QUESTO CONTROLLO, misurato nel test di polarità:
       aprendo in `mode=ro` un DB con journal caldo l'errore è «attempt to write
       a readonly database». **Parla del PERMESSO, non del DANNO**: chi lo legge
       va a controllare i mount, li trova giusti, e non pensa mai a un archivio
       interrotto. *Un errore vero che manda a cercare nel posto sbagliato costa
       più di un errore assente.*

    🔑 Costa un `exists()`, quindi può stare sul percorso caldo. La verifica vera
       (`PRAGMA quick_check`) costa una scansione e sta in `verifica()`, a
       richiesta — **le due non si mettono nello stesso posto**: una verifica
       costosa sul percorso caldo la si disattiva al primo rallentamento, e una
       disattivata è peggio di una assente perché risulta presente.
    """
    for suffisso in ("-journal", "-wal"):
        j = percorso.with_name(percorso.name + suffisso)
        try:
            if j.is_file() and j.stat().st_size > 0:
                return j
        except OSError:
            # non poter guardare non è «non c'è»: si tace e si lascia provare a
            # SQLite, che almeno fallirà sul dato invece che su una nostra ipotesi.
            return None
    return None


def messaggio_sporco(nome: str, journal: Path) -> str:
    """Il testo dell'errore. Deve mandare nel posto GIUSTO, non sui permessi."""
    return (
        f"L'archivio '{nome}' ha un journal caldo ({journal.name}): una scrittura "
        "è morta a metà e il DB è in uno stato intermedio.\n"
        "  · NON è un problema di permessi: i mount sono giusti (`:rw` al gateway, "
        "`:ro` qui) ed è la ragione per cui da qui NON si può riparare.\n"
        "  · Il rimedio è dal lato che SCRIVE: aprire il DB in scrittura una volta "
        "(il gateway lo fa da solo al primo indicizzamento) fa applicare il "
        "rollback a SQLite.\n"
        "  · Finché resta, ciò che leggeresti sarebbe uno stato NON committato."
    )


def verifica(dbs: dict[str, Any]) -> dict[str, dict[str, str]]:
    """`PRAGMA quick_check` sui DB dati. **Costa una scansione** — a richiesta.

    `quick_check(1)` si ferma al PRIMO problema: dice **se** è rotto, non quanto.
    Per «quanto» serve `PRAGMA integrity_check` completo, e non lo facciamo qui.

    Esiti: `ok` · `sporco` (journal caldo) · `corrotto` · `non_misurabile`.
    """
    out: dict[str, dict[str, str]] = {}
    for nome in sorted(dbs):
        percorso = Path(dbs[nome])
        sporco = journal_caldo(percorso)
        if sporco is not None:
            out[nome] = {"esito": "sporco", "dettaglio": f"journal caldo: {sporco.name}"}
            continue
        try:
            conn = sqlite3.connect(f"file:{percorso}?mode=ro", uri=True)
            try:
                righe = conn.execute("PRAGMA quick_check(1)").fetchall()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            out[nome] = {"esito": "non_misurabile", "dettaglio": str(exc)}
            continue
        esiti = [r[0] for r in righe]          # SQLite dice ["ok"] quando è sano
        out[nome] = ({"esito": "ok", "dettaglio": ""} if esiti == ["ok"]
                     else {"esito": "corrotto", "dettaglio": "; ".join(esiti)[:400]})
    return out
