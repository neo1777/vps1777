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

TERZO MECCANISMO (27/09/2026): le CREDENZIALI in formato riconoscibile (prefissi dei
fornitori: GitHub, Anthropic/OpenAI, AWS, Google, Slack, Telegram, Tailscale, age, JWT,
blocchi di chiave privata) e il percorso degli URL trycloudflare. Stesso limite dei
pattern: un segreto senza formato (una password scritta a mano) resta scoperto.

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

import functools
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

# Due sagome che TELEFONO ingoiava e che un telefono non può avere (misurato il 24/09/2026 dal
# vivo, via MCP, sulle schede di Recupero Sessioni: «quota tornata il [telefono redatto]:10 UTC»
# al posto di «2026-09-05 13:10», e gli uuid coi gruppi di sole cifre che uscivano spezzati):
# · una DATA ISO valida (secolo plausibile, mese 01-12, giorno 01-31) con l'ora 00-23 separata
#   da uno spazio o da `T` — TELEFONO si ferma ai due punti, quindi il match è «AAAA-MM-GG HH».
#   STRETTA come `_TS_COMPATTO`: un mese 13 o un giorno 32 restano telefono.
# · un UUID canonico (8-4-4-4-12 esadecimali): non si cerca un telefono DENTRO un uuid. Un
#   uuid è un identificatore tecnico — `CAMPI_ANAGRAFICI` già lo esclude di proposito, perché
#   serve a `get_context` — e la sua forma esatta non è quella di un numero di telefono.
# · (26/09/2026) la stessa data con l'ora scritta coi TRATTINI o coi punti, come nei nomi degli
#   screenshot: «Schermata del 2026-09-24 18-41-38.png» usciva «[telefono redatto]-38.png»
#   (TELEFONO prende «2026-09-24 18-41» e si ferma prima di «-38.png»). Minuti e secondi 00-59,
#   stessa strettezza dell'ora.
_DATA_ORA = re.compile(r"^(?:19|20)\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])"
                       r"(?:[ T](?:[01]\d|2[0-3])(?:[-.][0-5]\d(?:[-.][0-5]\d)?)?)?$")
_UUID = re.compile(r"(?<![0-9A-Za-z])[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?![0-9A-Za-z])")


def _tel_o_timestamp(m: "re.Match[str]") -> str:
    t = m.group(0)
    return t if _TS_COMPATTO.match(t) or _DATA_ORA.match(t) else SEGNAPOSTO_TEL


def _telefoni(s: str) -> str:
    """TELEFONO applicato FUORI dagli uuid canonici: il testo si spezza agli uuid, ogni pezzo
    passa dal pattern, gli uuid tornano al loro posto intatti. Un telefono attaccato a un uuid
    senza separatore non esiste (il pattern vuole un confine prima e dopo)."""
    if "-" not in s:
        return _senza_evidenziatori(TELEFONO, s, _tel_o_timestamp)
    parti, i = [], 0
    for u in _UUID.finditer(s):
        parti.append(_senza_evidenziatori(TELEFONO, s[i:u.start()], _tel_o_timestamp))
        parti.append(u.group(0))
        i = u.end()
    parti.append(_senza_evidenziatori(TELEFONO, s[i:], _tel_o_timestamp))
    return "".join(parti)

SEGNAPOSTO_EMAIL = "[email redatta]"
SEGNAPOSTO_TEL = "[telefono redatto]"
SEGNAPOSTO_VALORE = "[dato personale redatto]"
SEGNAPOSTO_CREDENZIALE = "[credenziale redatta]"

# CREDENZIALI IN FORMATO RICONOSCIBILE (27/09/2026). Rilievo della curatrice dei rimandi:
# su un DB claude.ai una ricerca restituiva in chiaro un token GitHub e un URL
# trycloudflare col suo percorso segreto. Stessa filosofia di email e telefoni: si
# maschera ciò che ha un FORMATO; un segreto senza formato (una password scritta a mano)
# resta scoperto, e questo va detto invece di promettere di più.
# I prefissi sono quelli dei fornitori; le lunghezze minime tengono fuori «sk-learn»,
# «AIza.txt» e simili. Si applicano PRIMA dei telefoni: un token Telegram comincia con
# nove cifre, e il pattern del telefono ne mangerebbe metà lasciando in chiaro il resto.
CREDENZIALI = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----"
    r"|\bgh[pousr]_[A-Za-z0-9]{36,}\b"
    r"|\bgithub_pat_[A-Za-z0-9_]{40,}"
    r"|\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{32,}"
    r"|\bAKIA[0-9A-Z]{16}\b"
    r"|\bAIza[0-9A-Za-z_-]{35}\b"
    r"|\bxox[abprs]-[A-Za-z0-9-]{10,}"
    r"|\b\d{8,10}:[A-Za-z0-9_-]{35}\b"
    r"|\btskey-[a-z]+-[A-Za-z0-9-]{8,}"
    r"|AGE-SECRET-KEY-1[A-Z0-9]{50,}"
    r"|\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}",
    re.S)
# Un tunnel rapido di Cloudflare è segreto per URL: chi conosce il percorso entra.
# L'host resta (dice DOVE era il servizio), il percorso no.
TRYCLOUDFLARE = re.compile(r"(\bhttps?://[a-z0-9-]+\.trycloudflare\.com)(/[^\s\"'<>)\]]+)")
SEGNAPOSTO_PERCORSO = "/[percorso redatto]"

# SEGRETI SENZA FORMATO, MA ASSEGNATI A UN NOME DA SEGRETO (30/09/2026). Rilievo della
# curatrice: righe «RESULT_SECRET=<32 caratteri>» — l'output dell'installer incollato in
# chat — uscivano in chiaro, e il valore era il gateway_secret IN USO. Il valore non ha
# un prefisso di fornitore, ma l'assegnazione ha una forma: un nome che contiene
# SECRET/TOKEN/PASSWORD/…KEY, un `=` o `:`, un valore lungo con lettere E cifre. È il
# criterio di gitleaks (generic-api-key). Il valore deve avere 16 caratteri e almeno una
# cifra e una lettera: così `OAUTH_ACCESS_TOKEN_LIFETIME: "900"` (una durata) e
# `password = request.form.get(…)` (codice) restano. Il nome resta: dice cosa era.
ASSEGNAZIONE = re.compile(
    r"(?i)(?<![A-Za-z0-9])([A-Za-z0-9_]*(?:secret|token|passw(?:or)?d|pwd|auth_?key"
    r"|api_?key|private_?key|access_?key)[A-Za-z0-9_]*[`\"']?\s*[=:]\s*[`\"']?)"
    r"(?=[A-Za-z0-9_+/=.-]*[0-9])(?=[A-Za-z0-9_+/=.-]*[A-Za-z])[A-Za-z0-9_+/=.-]{16,}")
# Il segreto del gateway sta per costruzione nell'URL del connettore
# (`https://<host>/<SECRET>/<servizio>/mcp`): chi installa deve riceverlo, e incollato in
# chat finiva nell'archivio. Resta l'host e il servizio, va via il segmento.
# Senza chiedere lo schema: il 21/06 l'URL era scritto `host/<segreto>/archive/mcp`
# (rilievo MAPPA-17, 30/09). In cambio il segmento deve avere maiuscole, minuscole e
# cifre, come un `token_urlsafe`: un percorso lungo ma leggibile
# («claude-code-sessions/archive/mcp») resta.
URL_CONNETTORE = re.compile(
    r"(/)(?=[A-Za-z0-9_-]*[A-Z])(?=[A-Za-z0-9_-]*[a-z])(?=[A-Za-z0-9_-]*[0-9])"
    r"[A-Za-z0-9_-]{20,}(/[a-z0-9-]+/mcp\b)")


# Campi dell'anagrafica i cui VALORI vanno mascherati ovunque compaiano. `uuid` no: è un
# identificatore tecnico che serve a `get_context`, e mascherarlo romperebbe la navigazione.
CAMPI_ANAGRAFICI = ("full_name", "display_name", "name", "email_address", "email",
                    "phone_number", "phone", "verified_phone_number")

# Valori dell'anagrafica che l'operatore ha dichiarato PUBBLICI e che quindi non si mascherano
# (26/09/2026). Il caso che l'ha fatto nascere: il `full_name` dell'account claude.ai era
# l'handle pubblico dell'autore — lo stesso nome del repository — e la redazione per valore
# noto lo toglieva da ogni percorso e da ogni etichetta («_chat/corpus-<handle>/…»,
# «-home-<handle>-Scrivania»), rendendo illeggibili i riferimenti che le sessioni si
# scambiano. Vuoto per default: la politica del prodotto non cambia finché l'operatore non
# scrive `ARCHIVE_REDACT_ESENTI` (valori separati da virgola, confronto senza maiuscole).
# Vale SOLO per i valori noti: email e telefoni in formato riconoscibile restano redatti
# comunque, anche se l'operatore ne esentasse uno (non si esenta un pattern per nome).
ESENTI = {v.strip().lower() for v in os.getenv("ARCHIVE_REDACT_ESENTI", "").split(",") if v.strip()}

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
                if len(v) >= _MIN_VALORE and v.lower() not in ESENTI:
                    out.add(v)
    return out


# Lo snippet di FTS5 evidenzia la parola cercata con «»: su una ricerca `ghp*` il token
# usciva «ghp»_<resto> e il pattern, spezzato dai marcatori, non lo riconosceva (misurato
# dal vivo sulla 0.62.1, 27/09). Si cerca sul testo SENZA marcatori e si sostituisce il
# tratto corrispondente del testo originale, marcatori compresi.
_EVIDENZIATORI = "«»"


def _senza_evidenziatori(pattern: "re.Pattern[str]", s: str, sostituto) -> str:
    if not any(c in s for c in _EVIDENZIATORI):
        return pattern.sub(sostituto, s)
    indici = [i for i, c in enumerate(s) if c not in _EVIDENZIATORI]
    pulito = "".join(s[i] for i in indici)
    pezzi, fine_prec = [], 0
    for m in pattern.finditer(pulito):
        inizio, fine = indici[m.start()], indici[m.end() - 1] + 1
        # un marcatore che apre subito prima o chiude subito dopo fa parte del tratto
        if inizio > 0 and s[inizio - 1] in _EVIDENZIATORI:
            inizio -= 1
        if fine < len(s) and s[fine] in _EVIDENZIATORI:
            fine += 1
        pezzi.append(s[fine_prec:inizio])
        pezzi.append(sostituto(m))
        fine_prec = fine
    pezzi.append(s[fine_prec:])
    return "".join(pezzi)


# I BORDI DELLA FINESTRA (audit della doc, 27/09/2026). Lo snippet di FTS5 è una finestra
# di token che comincia e finisce dove capita, anche a metà di una credenziale, e lo segna
# con «…»; il ramo vettoriale di search_ibrida taglia il contenuto a 400 caratteri senza
# segno. Il pattern completo non c'è più e il pezzo restava in chiaro. Tre regole:
# - CODA: un prefisso noto seguito da almeno 8 caratteri e poi dalla fine del testo;
# - TESTA: dopo il «…» iniziale, una corsa di almeno 20 caratteri base62 con maiuscole,
#   minuscole e cifre insieme (un hash esadecimale, un identificatore o un percorso no);
# - CHIAVE PRIVATA a metà: dal BEGIN senza END alla fine, dall'inizio all'END senza BEGIN.
_CODA = re.compile(
    r"(?<![A-Za-z0-9])(?:gh[pousr]_|github_pat_|sk-(?:ant-|proj-)?|xox[abprs]-|AIza|AKIA"
    r"|tskey-|AGE-SECRET-KEY-1|eyJ|(?<![-:])\d{8,10}:)[A-Za-z0-9_.-]{8,}…?\Z")
# ⚠️ Le cifre del token Telegram NON valgono attaccate a un trattino o a due punti: in
# «memory:legacy-20260926:<nome Project>» la coda `20260926:Nome` ha la forma di un token
# tagliato, e le etichette dei Project uscivano «[credenziale redatta]» (MAPPA-17, 30/09).
# La finestra di FTS5 comincia sempre a un confine di token (unicode61: una corsa
# alfanumerica), quindi basta guardare la PRIMA corsa: deve avere 20 caratteri o più e
# maiuscole, minuscole e cifre insieme. Un percorso con i trattini («-home-…-Scrivania-»)
# comincia con una corsa corta e resta. Presa la corsa, si prende anche la coda del
# token (`_`/`-` e altro alfanumerico), che è ancora segreto.
_TESTA = re.compile(r"\A…(?=[A-Za-z0-9]*[A-Z])(?=[A-Za-z0-9]*[a-z])(?=[A-Za-z0-9]*[0-9])"
                    r"[A-Za-z0-9]{20,}(?![A-Za-z0-9])[A-Za-z0-9_-]*")
_CHIAVE_SENZA_FINE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*\Z", re.S)
_CHIAVE_SENZA_INIZIO = re.compile(r"\A.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)


@functools.lru_cache(maxsize=32)
def _pattern_noti(noti: frozenset[str]) -> "re.Pattern[str]":
    """Un pattern solo per i valori noti: senza maiuscole (un nome si scrive come capita)
    e passato da `_senza_evidenziatori` come gli altri — «Mario» Rossi usciva in chiaro."""
    return re.compile("|".join(re.escape(v) for v in sorted(noti, key=len, reverse=True)),
                      re.I)


def maschera_testo(s: str, noti: set[str] | None = None) -> str:
    """Redige credenziali, email, telefoni e i valori noti dentro una stringa."""
    if not s:
        return s
    # I valori noti PRIMA dei pattern: così un'email dell'anagrafica esce come
    # «[dato personale redatto]» e non come «[email redatta]» — due segnaposti diversi
    # direbbero a chi legge quale dei due meccanismi l'ha presa, che è un'informazione
    # sull'anagrafica. Uniformare qui costa nulla e non lascia quell'indizio.
    if noti:
        s = _senza_evidenziatori(_pattern_noti(frozenset(noti)), s,
                                 lambda m: SEGNAPOSTO_VALORE)
    s = _senza_evidenziatori(CREDENZIALI, s, lambda m: SEGNAPOSTO_CREDENZIALE)
    s = _senza_evidenziatori(ASSEGNAZIONE, s, lambda m: m.group(1) + SEGNAPOSTO_CREDENZIALE)
    s = _senza_evidenziatori(URL_CONNETTORE, s,
                             lambda m: m.group(1) + SEGNAPOSTO_CREDENZIALE + m.group(2))
    for bordo in (_CHIAVE_SENZA_FINE, _CHIAVE_SENZA_INIZIO, _CODA):
        s = _senza_evidenziatori(bordo, s, lambda m: SEGNAPOSTO_CREDENZIALE)
    s = _senza_evidenziatori(_TESTA, s, lambda m: "…" + SEGNAPOSTO_CREDENZIALE)
    s = _senza_evidenziatori(TRYCLOUDFLARE, s,
                             lambda m: m.group(1) + SEGNAPOSTO_PERCORSO)
    s = _senza_evidenziatori(EMAIL, s, lambda m: SEGNAPOSTO_EMAIL)
    return _telefoni(s)


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
