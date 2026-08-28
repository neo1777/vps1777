"""Redazione dei dati personali in USCITA dall'archivio.

IL PROBLEMA, misurato prima di scrivere una riga (02/08/2026):
    `users.json` — nome, email, telefono verificato — si indicizza **verbatim**, ed è la
    scelta giusta: filtrare all'INGRESSO è una policy di output applicata dove nessuno la
    può più rivedere. Ma il test che la giustifica prometteva «la protezione è un problema
    di output (mascheramento in ricerca, cifratura at-rest, ACL) e va risolta dove si
    legge» — e **nessuna delle tre esisteva**. Una promessa scritta come se fosse già
    mantenuta: chi legge quella frase smette di cercare.

LA SCELTA FRA LE TRE (decisione di Neo, 02/08 07:09: «la MIGLIORE, non la più economica,
anche perché poi ce lo contestano nell'audit»):
    · cifratura at-rest → protegge il DISCO. Non impedisce che i dati escano dal tool.
    · ACL              → protegge da CHI accede. Il flusso verso il modello di terze
                          parti è AUTORIZZATO: l'ACL lo lascia passare.
    · ✅ mascheramento  → protegge il canale che espone davvero. `search()` è un
      in OUTPUT           `@mcp.tool` instradato dal gateway al connettore: una ricerca
                          qualunque restituiva nome, email e telefono a un modello terzo.
    ⇒ in un audit la terza è l'unica che dà una frase difendibile.

⚠️ E LA FRASE VA DETTA DELLA DIMENSIONE GIUSTA — rilievo di `abdd732a` prima che scrivessi
il codice, e cambia la promessa non il progetto: **un filtro sui dati sensibili si giudica
sui FALSI NEGATIVI, non sui falsi positivi.** «Zero falsi positivi per costruzione» è vero
e non è la proprietà su cui si giudica. Quindi NON si dice «i dati personali non lasciano
il perimetro in chiaro» — è più larga di ciò che il codice fa. Si dice:
    ✅ «gli identificatori in FORMATO RICONOSCIBILE (email, telefono) non escono in chiaro
       da nessun tool, ovunque compaiano — transcript compresi — e i valori dell'anagrafica
       dell'account non escono in chiaro nemmeno quando sono scritti a mano in un messaggio»
    🔴 «un dato personale che NON ha un formato riconoscibile e NON è in anagrafica — il
       nome di un terzo scritto dentro una conversazione — NON viene mascherato»
E l'archivio è fatto di transcript: è la popolazione più grande e quella dove un dato
personale ha più probabilità di essere scritto a mano che registrato. Quanti ce ne siano
**non è misurato**: contiene materiale personale e non si apre per contarli.

DUE MECCANISMI, e la differenza conta:
    · PER PATTERN     email e numeri di telefono, ovunque compaiano. Copre anche i dati
                      personali di TERZI finiti nelle conversazioni, non solo l'anagrafica.
    · PER VALORE NOTO i valori dell'anagrafica (`project = 'account:user'`) letti
                      dall'indice stesso e mascherati verbatim. **Non indovino cosa sia un
                      nome: maschero i nomi che SO essere nomi** — zero falsi positivi per
                      costruzione, che è la ragione per cui non uso un riconoscitore.

COSA NON COPRE, dichiarato invece che taciuto — è precisamente l'errore che questo file
ripara, e ripeterlo qui sarebbe grottesco:
    · nomi di persona di TERZI mai comparsi nell'anagrafica: non c'è modo di saperli senza
      un riconoscitore, e un riconoscitore su testo italiano produce falsi positivi che
      corromperebbero i risultati di ricerca.
    · indirizzi postali, date di nascita, codici fiscali: nessun pattern, oggi.
    · il DB su disco resta in chiaro: questo è mascheramento in uscita, NON cifratura.
      Chi legge il file `.db` vede tutto. È l'altra delle tre, e non è stata scelta.
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

# Attivo per DEFAULT: fail-closed. Si spegne solo con una scelta esplicita e rumorosa,
# perché un interruttore che si spegne da solo (variabile assente, errore di lettura) è
# un presidio che non c'è.
ATTIVA = os.getenv("ARCHIVE_REDACT", "1").strip().lower() not in ("0", "false", "no")

EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]{2,}\b")
# Telefono: prefisso internazionale opzionale, 8-14 cifre con separatori. Richiede o il
# `+` o almeno 9 cifre, così un anno («2026») o un numero di riga non diventano telefoni.
TELEFONO = re.compile(r"(?<![\w.])(?:\+\d{1,3}[\s.-]?)?(?:\d[\s.-]?){8,13}\d(?![\w.])")

# La sagoma YYYYMMDD-HHMMSS (nomi di bundle e DB: `20260811-190343`) ha 14 cifre
# e un separatore: TELEFONO la ingoia e i nomi degli archivi escono «[telefono
# redatto]» nelle risposte (misurato 28/08/2026 sulle description via MCP).
# L'esenzione è STRETTA — solo la forma esatta data-ora con secolo plausibile:
# tutto il resto resta telefono, perché un'esenzione larga qui è un buco nella
# redazione, non una cortesia.
_TS_COMPATTO = re.compile(r"^(?:19|20)\d{6}[-T]\d{6}$")


def _tel_o_timestamp(m: "re.Match[str]") -> str:
    return m.group(0) if _TS_COMPATTO.match(m.group(0)) else SEGNAPOSTO_TEL

SEGNAPOSTO_EMAIL = "[email redatta]"
SEGNAPOSTO_TEL = "[telefono redatto]"
SEGNAPOSTO_VALORE = "[dato personale redatto]"

# Campi dell'anagrafica i cui VALORI vanno mascherati ovunque compaiano. `uuid` no: è un
# identificatore tecnico che serve a `get_context`, e mascherarlo romperebbe la navigazione.
CAMPI_ANAGRAFICI = ("full_name", "display_name", "name", "email_address", "email",
                    "phone_number", "phone", "verified_phone_number")

_MIN_VALORE = 4        # sotto questa lunghezza un valore è troppo generico per essere
                       # mascherato senza falsare i risultati (un nome di 2 lettere
                       # comparirebbe ovunque). Limite dichiarato, non nascosto.


def valori_noti(conn: sqlite3.Connection) -> set[str]:
    """I valori dell'anagrafica presenti in QUESTO indice.

    Torna un insieme vuoto se la tabella non c'è o la query fallisce: qui l'insieme vuoto
    è corretto (nessun valore noto da mascherare) e i pattern restano comunque attivi —
    la redazione non si spegne mai per un errore di lettura.
    """
    out: set[str] = set()
    try:
        righe = conn.execute(
            "SELECT content FROM messages WHERE project = 'account:user'").fetchall()
    except sqlite3.Error as exc:
        log.warning("anagrafica non leggibile (%s): restano i pattern", exc)
        return out
    for (corpo,) in righe:
        for riga in (corpo or "").splitlines():
            chiave, _, valore = riga.partition(":")
            if chiave.strip().lower() in CAMPI_ANAGRAFICI:
                v = valore.strip()
                if len(v) >= _MIN_VALORE:
                    out.add(v)
    return out


def maschera_testo(s: str, noti: set[str] | None = None) -> str:
    """Redige email, telefoni e i valori noti dentro una stringa."""
    if not s:
        return s
    # I valori noti PRIMA dei pattern: così un'email dell'anagrafica esce come
    # «[dato personale redatto]» e non come «[email redatta]» — due segnaposti diversi
    # direbbero a chi legge quale dei due meccanismi l'ha presa, che è un'informazione
    # sull'anagrafica. Uniformare qui costa nulla e non lascia quell'indizio.
    for v in sorted(noti or (), key=len, reverse=True):
        if v in s:
            s = s.replace(v, SEGNAPOSTO_VALORE)
    s = EMAIL.sub(SEGNAPOSTO_EMAIL, s)
    return TELEFONO.sub(_tel_o_timestamp, s)


def maschera(oggetto: Any, noti: set[str] | None = None) -> Any:
    """Applica la redazione ricorsivamente a stringhe dentro dict/list/tuple.

    Ricorsiva e non «sui campi che so»: un campo nuovo in una riga di risultato
    nascerebbe scoperto, ed è la forma di difetto che abbiamo misurato sette volte in
    una notte — il presidio segue la forma del dato invece del rischio.
    """
    if not ATTIVA:
        return oggetto
    if isinstance(oggetto, str):
        return maschera_testo(oggetto, noti)
    if isinstance(oggetto, dict):
        return {k: maschera(v, noti) for k, v in oggetto.items()}
    if isinstance(oggetto, (list, tuple)):
        tipo = type(oggetto)
        return tipo(maschera(v, noti) for v in oggetto)
    return oggetto
