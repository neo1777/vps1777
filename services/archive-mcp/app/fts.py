"""
Logica FTS5 pura — stdlib-only (sqlite3, re), zero dipendenze da settings/MCP.

Estratta da db.py così che la CI possa testarla con `uvx pytest` senza installare
il runtime del server (stesso pattern di gateway/archive_indexer, miniapp_core).

Contiene: sanitizzazione difensiva della query (auto-quoting dei termini con
caratteri speciali), la ricerca su una connessione con distinzione ESPLICITA fra
"nessun risultato" e "sintassi FTS5 non valida" (il bug capitale), il conteggio,
il contesto attorno a un messaggio e la scheda di un DB.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any

# ── errore parlante ──────────────────────────────────────────────────────────


class FtsSyntaxError(ValueError):
    """Query FTS5 malformata. Sollevata al posto di restituire lista vuota:
    un `[]` da errore di sintassi è indistinguibile da 'nessun match' e produce
    falsi negativi silenziosi — l'esatto contrario dello scopo dell'archivio."""


_SYNTAX_HINT = (
    "sintassi FTS5 non valida. Regole: operatori in MAIUSCOLO (AND OR NOT NEAR); "
    "i termini con - . / @ : # ' o punti vanno tra virgolette (es. \"flutter-elinux\", "
    "\"0.7.9\", \"github.com\"); le famiglie di nomi col prefisso (palant*). "
    "Se cercavi un termine letterale con caratteri speciali, mettilo tra doppi apici."
)

# ── sanitizzazione difensiva ─────────────────────────────────────────────────

# Un token è "già sicuro" per FTS5 se è fatto solo di word-char unicode
# (lettere accentate incluse) più un eventuale `*` di prefisso: `nb_list`,
# `palant*`, `perché`. Tutto il resto (trattini, punti, slash, apostrofi…) è
# sintassi per il parser e va quotato per essere cercato come letterale.
_SAFE_TOKEN = re.compile(r"^\w+\*?$", re.UNICODE)
_FTS_OPERATORS = {"AND", "OR", "NOT", "NEAR"}
# spezza preservando: stringhe già quotate e sequenze non-spazio
_SPLIT = re.compile(r'"[^"]*"|\S+')
# costrutti FTS "strutturali": se la query li usa, NON la si tocca (quotare
# spezzerebbe la semantica). NEAR, parentesi di gruppo, column filter `col:term`.
_ADVANCED = re.compile(r"\bNEAR\b|[()]|\w+\s*:", re.UNICODE)


def sanitize_query(query: str) -> str:
    """Quota i termini con caratteri speciali (`flutter-elinux` → `"flutter-elinux"`),
    lasciando intatti operatori, frasi già quotate e prefissi. Pensata per il
    caso comune 'lista di termini'.

    Conservativa: se la query usa sintassi FTS avanzata (NEAR, parentesi,
    `col:term`) la restituisce INVARIATA — sanitizzarla ne cambierebbe la
    semantica. `search` prova comunque la versione sanitizzata e, se il parser
    la rifiuta, ricade sull'originale prima di dichiarare l'errore.
    """
    q = query or ""
    if _ADVANCED.search(q):
        return q
    out: list[str] = []
    for tok in _SPLIT.findall(q):
        if tok.startswith('"') and tok.endswith('"'):
            out.append(tok)              # frase già quotata: intatta
        elif tok in _FTS_OPERATORS:
            out.append(tok)              # operatore FTS: intatto
        elif _SAFE_TOKEN.match(tok):
            out.append(tok)              # già sicuro (parola, prefisso)
        else:
            out.append('"' + tok.replace('"', '""') + '"')  # letterale → quota
    return " ".join(out)


# ── ricerca ──────────────────────────────────────────────────────────────────

# `ts` è qualificato `f.`: con la JOIN su `messages` (filtri dell'asse-voce) il
# nome è ambiguo — entrambe le tabelle ce l'hanno — e SQLite alza
# «ambiguous column name». Senza JOIN `f` esiste comunque (l'alias è sempre nel
# FROM), quindi la qualifica è sempre valida e non ha un ramo scoperto.
_SORTS = {
    "rank": "bm25(messages_fts)",
    "oldest": "f.ts ASC",
    "newest": "f.ts DESC",
}


# ─────────────────────────── voice-tagging: i filtri sull'asse-voce (Fase 3) ──
# 🔑 PERCHÉ UNA JOIN E NON COLONNE NELL'INDICE. `speaker`, `voice`, `quoted_share`
# vivono in `messages` e NON in `messages_fts` — scelta della Fase 1, che rimandava
# il costo «finché non esistono i filtri che le interrogano (Fase 3)», cioè adesso.
# ⭐ MISURATO PRIMA DI SCEGLIERE (02/08, su copia del DB reale da 61.100 righe): il
# rebuild NON serve. `messages_fts` è una tabella FTS5 **external content**
# (`content='messages'`, `content_rowid='rowid'`), quindi una JOIN su `rowid` dà
# accesso a ogni colonna di `messages` senza toccare l'indice: 5 conteggi filtrati
# in 0,14s, e la somma per `voice` torna esatta al totale non filtrato (4790=4790).
# ⇒ un DROP+rebuild dell'FTS su ogni archivio vivo — che è ciò che la Fase 1 dava
# per necessario — sarebbe stato un costo pagato per niente.
_JOIN_MSG = " JOIN messages m ON m.rowid = f.rowid"


def _filtri_voce(speaker: str = "", voice: str = "") -> tuple[str, list]:
    """Traduce i filtri dell'asse-voce in `WHERE` + parametri. Alias inclusi.

    Gli ALIAS vivono qui e non nello schema (spec §3): sono comodità di
    interrogazione, e metterli in una colonna li congelerebbe.
        voice:direct  → own con poca citazione   (quoted_share < 0.2)
        voice:quoted  → prevalentemente citato   (quoted_share >= 0.5)

    🔴 QUANTO MORDONO DAVVERO, misurato il 02/08 su 61.100 righe reali — perché un
    alias che non taglia niente è peggio di nessun alias, dà l'impressione di aver
    filtrato:
        quoted_share > 0     343 righe  (0,56%)   massimo osservato: 0,667
        >= 0.2                87 righe  (0,14%)
        >= 0.5                 7 righe  (0,01%)   ← tutto ciò che `quoted` prende
    ⇒ `quoted` è quasi inerte e `direct` taglia pochissimo (su una query campione:
    643 righe su 656 `own`, cioè 13 escluse).
    ⭐ LA CAUSA NON È LA SOGLIA, è cosa misura la metrica: `_quota_citata` conta le
    righe con marcatore di citazione (`>` o fence). **L'incollato SENZA formattazione
    — che è il caso per cui il voice-tagging esiste — non produce nessun marcatore
    e non entra in `quoted_share`.** Le soglie sono marcate PROVVISORIE e si tarano
    col campione cieco previsto dalla spec §5, ma spostarle non recupererebbe
    l'incollato piatto: quello chiede un segnale diverso, non un numero diverso.
    🔴 `voice:none` è un terzo valore e NON è `unknown`: sono le righe che nessuno
    ha classificato (`voice=''`). Tenerle separate è la condizione posta da
    `71d540e6`: chi cerca `unknown` deve avere «le righe guardate e non
    riconosciute», non «le righe mai lette».
    """
    where, extra = "", []
    if speaker:
        where += " AND m.speaker = ?"
        extra.append(speaker)
    if voice == "direct":
        where += " AND m.voice = 'own' AND m.quoted_share < 0.2"
    elif voice == "quoted":
        where += " AND m.quoted_share >= 0.5"
    elif voice == "none":
        where += " AND m.voice = ''"
    elif voice:
        where += " AND m.voice = ?"
        extra.append(voice)
    return where, extra


def _run_match(conn: sqlite3.Connection, match: str, *, where_extra: str,
               params_extra: list, order: str, limit: int,
               snippet_tokens: int, join: str = "") -> list[dict[str, Any]]:
    sql = (
        f"SELECT f.uuid, f.project, f.ts, bm25(messages_fts) AS rank, "
        f"snippet(messages_fts, -1, '«', '»', '…', {int(snippet_tokens)}) AS snip "
        f"FROM messages_fts f{join} WHERE messages_fts MATCH ?{where_extra} "
        f"ORDER BY {order} LIMIT ?"
    )
    cur = conn.execute(sql, [match, *params_extra, int(limit)])
    return [dict(r) for r in cur]


def search_conn(conn: sqlite3.Connection, query: str, *, limit: int = 20,
                raw: bool = False, sort: str = "rank",
                since: str = "", until: str = "", project: str = "",
                speaker: str = "", voice: str = "",
                snippet_tokens: int = 32) -> list[dict[str, Any]]:
    """Cerca su UNA connessione. Distingue 0-risultati da errore di sintassi
    (solleva FtsSyntaxError). In modalità smart (default) prova la query
    sanitizzata e, se il parser la rifiuta, ricade sulla query originale così da
    non rompere mai ciò che 'raw' avrebbe accettato."""
    order = _SORTS.get(sort, _SORTS["rank"])
    where = ""
    extra: list = []
    if since:
        where += " AND f.ts >= ?"
        extra.append(since)
    if until:
        where += " AND f.ts <= ?"
        extra.append(until)
    if project:
        where += " AND f.project = ?"
        extra.append(project)
    w_voce, e_voce = _filtri_voce(speaker, voice)
    where += w_voce
    extra += e_voce
    join = _JOIN_MSG if w_voce else ""

    candidates = [query] if raw else [sanitize_query(query), query]
    last_exc: sqlite3.OperationalError | None = None
    for match in candidates:
        try:
            rows = _run_match(conn, match, where_extra=where, params_extra=extra,
                              order=order, limit=limit, snippet_tokens=snippet_tokens,
                              join=join)
        except sqlite3.OperationalError as exc:
            last_exc = exc
            continue
        for r in rows:
            r["snippet"] = r.pop("snip")
        return rows
    raise FtsSyntaxError(f"{_SYNTAX_HINT} (dettaglio: {last_exc})")


def count_conn(conn: sqlite3.Connection, query: str, *, raw: bool = False,
               since: str = "", until: str = "", project: str = "",
               speaker: str = "", voice: str = "") -> int:
    """Numero di match (non limitato). Stessa disciplina d'errore di search.

    Gli stessi filtri di `search_conn`, e non è un dettaglio: se `count` e `search`
    accettassero filtri diversi, un conteggio e la lista che dovrebbe spiegarlo
    parlerebbero di due popolazioni — che è il difetto che questo archivio ci ha
    già fatto fare più volte, con due numeri veri e nessuno confrontabile.
    """
    where = ""
    extra: list = []
    if since:
        where += " AND f.ts >= ?"
        extra.append(since)
    if until:
        where += " AND f.ts <= ?"
        extra.append(until)
    if project:
        where += " AND f.project = ?"
        extra.append(project)
    w_voce, e_voce = _filtri_voce(speaker, voice)
    where += w_voce
    extra += e_voce
    join = _JOIN_MSG if w_voce else ""
    sql = (f"SELECT count(*) FROM messages_fts f{join} "
           f"WHERE messages_fts MATCH ?{where}")
    candidates = [query] if raw else [sanitize_query(query), query]
    last_exc: sqlite3.OperationalError | None = None
    for match in candidates:
        try:
            return int(conn.execute(sql, [match, *extra]).fetchone()[0])
        except sqlite3.OperationalError as exc:
            last_exc = exc
    raise FtsSyntaxError(f"{_SYNTAX_HINT} (dettaglio: {last_exc})")


# ── canary dei termini collassati ─────────────────────────────────────────────
# Il tokenizer FTS5 di default (unicode61) tratta `+ #` da SEPARATORI: un termine
# come `C++` perde il suffisso e collassa sul token `C`, che compare ovunque
# (coordinate SVG, copyright, gradi). La ricerca non si SVUOTA — restituisce
# migliaia di risultati sbagliati (falso POSITIVO silenzioso). È la causa del falso
# ricordo dell'11/07 e il gemello a verso opposto dell'FTS5 muto (PR #20): lì lista
# vuota, qui lista piena della cosa sbagliata. La medicina è la stessa — un errore
# PARLANTE — ma non basta la doc (descrive l'intenzione): si CHIEDE ALL'INDICE.
#
# `collapse_candidates` è statica (dal solo testo): trova i termini che si riducono
# a UN token più corto (`C++`→`C`, `.NET`→`NET`, `g++`→`g`). Il separatore IN MEZZO
# (`node.js`→node,js) dà DUE token veri: il quoting li tiene come frase, NON
# collassano — esclusi. Il `*` di prefisso è sintassi voluta — escluso.
#
# `collapse_warnings_conn` conferma DINAMICAMENTE sul singolo DB: se
# count(term)==count(prefix)>0 il termine non esiste per quell'indice. Si auto-tara:
# su un DB ricostruito con `tokenchars` i due conteggi divergono e l'avviso NON
# scatta. Costo: un count(prefix) in più per candidato (rari — solo termini con + #).

# un token della query, spezzato sulle sequenze di word-char (come farebbe unicode61)
_WORDS = re.compile(r"\w+", re.UNICODE)


def collapse_candidates(query: str) -> list[tuple[str, str]]:
    """Termini della query che il tokenizer ridurrebbe a un prefisso più corto.
    Ritorna [(termine, prefisso)]. Statica: nessuna connessione, nessun I/O.
    Le query strutturate (NEAR, parentesi, col:term) le lascia stare."""
    if _ADVANCED.search(query or ""):
        return []
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for tok in _SPLIT.findall(query or ""):
        term = tok[1:-1] if len(tok) >= 2 and tok[0] == '"' and tok[-1] == '"' else tok
        if term.endswith("*"):
            term = term[:-1]              # prefisso FTS: sintassi voluta, non collasso
        if not term or term in seen or term in _FTS_OPERATORS:
            continue
        parts = _WORDS.findall(term)
        # UN solo token dopo lo strip, e diverso dal termine → il resto (+ #) è
        # sparito su un token più corto. Due o più token = frase (la regge il quoting).
        if len(parts) == 1 and parts[0] != term:
            seen.add(term)
            out.append((term, parts[0]))
    return out


def collapse_warnings_conn(conn: sqlite3.Connection, query: str) -> list[str]:
    """Per i candidati, conferma sul DB reale che il termine è COLLASSATO sul suo
    prefisso (stesso conteggio) e ritorna avvisi parlanti. Lista vuota = sano
    (o DB già ricostruito con tokenchars)."""
    warns: list[str] = []
    for term, prefix in collapse_candidates(query):
        try:
            n_term = count_conn(conn, term)
            n_pref = count_conn(conn, prefix)
        except (sqlite3.OperationalError, FtsSyntaxError):
            continue
        if n_pref > 0 and n_term == n_pref:
            # 🔴 17/08 (b82df434) — I CARATTERI SI DERIVANO DAL TERMINE, NON SI
            #   ELENCANO. Il messaggio diceva «il tokenizer non indicizza i caratteri
            #   +/#» e il caso che me l'ha fatto leggere era `.NET`, dove a sparire è
            #   **il punto**: l'avviso era giusto nel verdetto e sbagliato nella causa,
            #   e mandava a cercare il difetto fra due caratteri che non c'entravano.
            # ⭐ La logica qui sopra è già generale — `collapse_candidates` spezza su
            #   `\w+` e prende QUALUNQUE carattere non-word — quindi l'elenco a mano non
            #   era nemmeno una semplificazione: era la sola parte del meccanismo che
            #   sapeva meno del meccanismo. *Un messaggio che enumera ciò che il codice
            #   deriva invecchia da solo, e lo fa nel punto in cui qualcuno si fida.*
            # ⚠️ NIENTE dedup: la prima stesura faceva `dict.fromkeys(...)` e su `C++`
            #   stampava «+» invece di «++». Il test l'ha preso subito — *chi legge
            #   l'avviso cerca nel proprio termine ciò che il messaggio nomina, e «+»
            #   non si trova in `C++` allo stesso modo in cui ci si trova «++»*.
            persi = "".join(c for c in term if c not in prefix)
            warns.append(
                f'"{term}" è collassato su "{prefix}" in questo indice: i {n_term} '
                f'risultati riguardano "{prefix}", non "{term}" — il tokenizer non '
                f'indicizza «{persi}», e il termine perde quella parte. Questo DB '
                f'va ricostruito con tokenchars per distinguerli (usa check_term).'
            )
    return warns


def _thread_ids(conn: sqlite3.Connection, uuid: str) -> set[str]:
    """Gli uuid del thread connesso a `uuid` via `parent_uuid` (antenati +
    discendenti), camminando l'albero con due CTE ricorsive. Insieme = 1 solo
    (il messaggio stesso) quando l'arco manca — fonti chunked (pdf/telegram/memory)
    e db storici del prototipo, che `parent_uuid` non ce l'hanno. Su un DB v1 (4
    colonne, senza `parent_uuid`) ritorna il solo `uuid` → i chiamanti ripiegano
    sul comportamento storico invece di rompersi."""
    try:
        rows = conn.execute(
            "WITH RECURSIVE "
            " up(u) AS (SELECT ? UNION "
            "   SELECT m.parent_uuid FROM messages m JOIN up ON m.uuid = up.u "
            "   WHERE m.parent_uuid <> ''), "
            " down(u) AS (SELECT ? UNION "
            "   SELECT m.uuid FROM messages m JOIN down ON m.parent_uuid = down.u) "
            "SELECT u FROM up UNION SELECT u FROM down",
            (uuid, uuid),
        ).fetchall()
    except sqlite3.OperationalError:
        return {uuid}  # DB v1 senza colonna parent_uuid
    return {r[0] for r in rows if r[0]}


def _fonte_sessione(conn: sqlite3.Connection, uuid: str) -> str:
    """Il file di sessione Claude Code (`sessions/…` o `subagents/…`) in cui l'ingest ha
    visto `uuid`, dalla tabella `sightings`; '' se non c'è (fonti claude.ai, documenti,
    DB senza la tabella). Per una scheda di sessione R1, il file della sessione che
    descrive. Più copie dello stesso uuid: vince la prima in ordine di nome,
    cioè il file principale prima dei filoni `__fN` («.» < «_»)."""
    try:
        r = conn.execute(
            "SELECT source FROM sightings WHERE uuid = ? AND (substr(source, 1, 9) = "
            "'sessions/' OR substr(source, 1, 10) = 'subagents/') ORDER BY source LIMIT 1",
            (uuid,)).fetchone()
        if r is None:
            # una SCHEDA R1 (`recupero/sessioni/<sid>.md`, o il ponte) porta al file
            # della sua sessione: dalla scheda si legge la chat intera
            m = conn.execute(
                "SELECT source FROM sightings WHERE uuid = ? AND (source LIKE "
                "'recupero/sessioni/%.md' OR source LIKE 'workfiles/_recupero-1777/sessioni/%.md') "
                "LIMIT 1", (uuid,)).fetchone()
            if m:
                sid = m[0].rsplit("/", 1)[1][: -len(".md")]
                r = conn.execute("SELECT source FROM sightings WHERE source = ? LIMIT 1",
                                 (f"sessions/{sid}.jsonl",)).fetchone()
    except sqlite3.OperationalError:
        return ""  # DB senza `sightings`
    return r[0] if r else ""


def _righe_sessione(conn: sqlite3.Connection, fonte: str) -> list[dict[str, Any]]:
    """Le righe viste nel file di sessione `fonte`, in ordine (ts, uuid)."""
    return [dict(r) for r in conn.execute(
        "SELECT m.uuid, m.project, m.ts, m.content, m.sender FROM sightings s "
        "CROSS JOIN messages m ON m.uuid = s.uuid WHERE s.source = ? "
        "ORDER BY m.ts ASC, m.uuid ASC", (fonte,)).fetchall()]


def context_conn(conn: sqlite3.Connection, uuid: str, *, before: int = 3,
                 after: int = 3) -> list[dict[str, Any]]:
    """I messaggi attorno a `uuid`, col CONTENUTO PIENO (non lo snippet troncato).

    Se il messaggio fa parte di un thread (`parent_uuid`), i vicini vengono dallo
    STESSO thread — non più dalla sola vicinanza temporale nello stesso project, che
    poteva mischiare conversazioni diverse (era l'over-claim di «stesso thread»).
    Sulle fonti senza arco (chunked / db storici) ricade sull'adiacenza per
    (ts, uuid) dello stesso project — il comportamento storico. Vuoto se l'uuid non c'è.

    Sulle righe di Claude Code la finestra si prende PRIMA nel file di sessione in
    cui l'ingest le ha viste (`sightings`): la catena `parent_uuid` di Claude Code
    passa per record che l'indexer non tiene (durate dei turni, allegati vuoti,
    messaggi di soli metadati), e sul primario del 24/09 il genitore mancava in
    82.876 righe su 260.072 — il 32%. Lì il thread si riduceva al messaggio stesso e
    `get_context` restituiva solo lui (misurato il 26/09 su un messaggio di Neo). Il
    file di sessione è la conversazione vera, senza buchi e senza le sessioni
    parallele dello stesso project. La riga cercata porta `vicini_da`."""
    row = conn.execute(
        "SELECT project, ts FROM messages WHERE uuid = ?", (uuid,)).fetchone()
    if row is None:
        return []
    project, ts = row["project"], row["ts"]
    fonte = _fonte_sessione(conn, uuid)
    if fonte:
        seq = _righe_sessione(conn, fonte)
        pos = next((i for i, r in enumerate(seq) if r["uuid"] == uuid), None)
        if pos is not None and len(seq) > 1:
            out = seq[max(0, pos - int(before)): pos + int(after) + 1]
            for r in out:
                r.pop("sender", None)
                r["is_match"] = (r["uuid"] == uuid)
                if r["is_match"]:
                    r["vicini_da"] = f"file di sessione {fonte}"
            return out
    ids = _thread_ids(conn, uuid)
    if len(ids) > 1:
        # threaded: la finestra ±N si prende DENTRO il thread, ordinato (ts, uuid).
        qmarks = ",".join("?" * len(ids))
        seq = [dict(r) for r in conn.execute(
            f"SELECT uuid, project, ts, content FROM messages WHERE uuid IN ({qmarks}) "
            "ORDER BY ts ASC, uuid ASC", tuple(ids)).fetchall()]
        pos = next((i for i, r in enumerate(seq) if r["uuid"] == uuid), None)
        if pos is not None:
            out = seq[max(0, pos - int(before)): pos + int(after) + 1]
            for r in out:
                r["is_match"] = (r["uuid"] == uuid)
            return out
    # ancora per (ts, uuid): stabile anche con ts uguali (dedup deterministico)
    prev = conn.execute(
        "SELECT uuid, project, ts, content FROM messages "
        "WHERE project = ? AND (ts, uuid) < (?, ?) "
        "ORDER BY ts DESC, uuid DESC LIMIT ?",
        (project, ts, uuid, int(before)),
    ).fetchall()
    center_after = conn.execute(
        "SELECT uuid, project, ts, content FROM messages "
        "WHERE project = ? AND (ts, uuid) >= (?, ?) "
        "ORDER BY ts ASC, uuid ASC LIMIT ?",
        (project, ts, uuid, int(after) + 1),
    ).fetchall()
    out = [dict(r) for r in reversed(prev)] + [dict(r) for r in center_after]
    for r in out:
        r["is_match"] = (r["uuid"] == uuid)
    return out


def conversation_conn(conn: sqlite3.Connection, uuid: str, *,
                      limit: int = 200) -> list[dict[str, Any]]:
    """Il thread di conversazione che CONTIENE `uuid` — camminando l'albero
    `parent_uuid` (antenati + discendenti), col contenuto pieno e in ordine (ts, uuid).
    Per LEGGERE una chat intera, non solo la finestra ±N di `context_conn`.

    Dove l'arco manca — fonti chunked (pdf/telegram/memory) e db storici — ricade
    sull'ordine lineare dello stesso archivio (`project`). La ricostruzione FEDELE
    dell'ordine sulla coda-documenti (colonna `seq`) è un passo evolutivo DICHIARATO
    fuori scope oggi. Vuoto se l'uuid non c'è.

    Sulle righe di Claude Code la conversazione è il FILE DI SESSIONE in cui l'ingest
    le ha viste (`sightings`), non l'albero `parent_uuid`: quello passa per record che
    l'indexer non tiene e sul primario del 24/09 era spezzato nel 32% delle righe
    (vedi `context_conn`), quindi restituiva frammenti. In coda vengono le schede
    `recupero:sessioni` appese all'ultimo messaggio (il loro `parent_uuid`)."""
    anchor = conn.execute(
        "SELECT project FROM messages WHERE uuid = ?", (uuid,)).fetchone()
    if anchor is None:
        return []
    fonte = _fonte_sessione(conn, uuid)
    if fonte:
        seq = _righe_sessione(conn, fonte)
        if len(seq) > 1:
            # le schede del contratto R1 della STESSA sessione, per nome del membro (non
            # risalendo `parent_uuid`: i cloni condividono gli uuid, e la scheda di un
            # clone appesa a un messaggio comune finiva in coda alla conversazione
            # sbagliata — misurato il 26/09). Solo per i file `sessions/`.
            coda: list[dict[str, Any]] = []
            if fonte.startswith("sessions/"):
                sid = fonte[len("sessions/"):].rsplit(".jsonl", 1)[0].split("__f", 1)[0]
                membri = (f"recupero/sessioni/{sid}.md",
                          f"workfiles/_recupero-1777/sessioni/{sid}.md")
                coda = [dict(r) for r in conn.execute(
                    "SELECT m.uuid, m.project, m.ts, m.content, m.sender FROM sightings s "
                    "CROSS JOIN messages m ON m.uuid = s.uuid WHERE s.source IN (?, ?) "
                    "ORDER BY m.rowid", membri).fetchall()]  # CROSS: prima i pochi sightings
                # (senza, il planner scorreva `messages` in ordine di rowid: 1,2 s misurati)
            out = (seq + coda)[: int(limit)]
            for r in out:
                r["is_match"] = (r["uuid"] == uuid)
                if r["is_match"]:
                    r["conversazione_da"] = f"file di sessione {fonte}"
            return out
    ids = _thread_ids(conn, uuid)
    if len(ids) > 1:
        qmarks = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT uuid, project, ts, content, sender FROM messages "
            f"WHERE uuid IN ({qmarks}) ORDER BY ts ASC, uuid ASC LIMIT ?",
            (*ids, int(limit))).fetchall()
    else:
        # fallback lineare (coda-documenti / db storici senza arco)
        rows = conn.execute(
            "SELECT uuid, project, ts, content, sender FROM messages "
            "WHERE project = ? ORDER BY ts ASC, uuid ASC LIMIT ?",
            (anchor["project"], int(limit))).fetchall()
    out = [dict(r) for r in rows]
    for r in out:
        r["is_match"] = (r["uuid"] == uuid)
    return out


def projects_conn(conn: sqlite3.Connection, *, top: int = 1000) -> list[dict[str, Any]]:
    """Le etichette `project` di un DB con quanti messaggi ciascuna — per NAVIGARE
    l'archivio invece di solo cercarlo (era uno dei tool di browse persi, B4)."""
    return [{"project": p or "", "rows": int(n)} for p, n in conn.execute(
        "SELECT project, count(*) FROM messages "
        "GROUP BY project ORDER BY count(*) DESC, project LIMIT ?",
        (max(0, int(top)),)).fetchall()]


def stats_by_period_conn(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Istogramma temporale per ANNO (`substr(ts,1,4)`) — «quando» l'archivio è
    fitto, prima di cercare. I ts vuoti (fonti senza data) sono esclusi."""
    return [{"period": per, "rows": int(n)} for per, n in conn.execute(
        "SELECT substr(ts, 1, 4) AS period, count(*) FROM messages "
        "WHERE ts <> '' GROUP BY period ORDER BY period").fetchall()]


def meta_value_conn(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    """Una voce dalla scheda `meta` del DB (es. `description`, D5). `default` se la
    tabella manca (DB precedenti alla feature) o la chiave non c'è."""
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (str(key),)).fetchone()
    except sqlite3.OperationalError:
        return default
    return row[0] if row and row[0] is not None else default


def db_stats_conn(conn: sqlite3.Connection) -> dict[str, Any]:
    """Righe, intervallo temporale e n. di etichette di un DB (per describe)."""
    rows = int(conn.execute("SELECT count(*) FROM messages").fetchone()[0])
    oldest = newest = ""
    labels = 0
    if rows:
        # min(NULLIF(ts,'')): le righe-STATO (memory:*, account:user) hanno ts vuoto —
        # non sono EVENTI, non hanno una data di nascita. Senza NULLIF la stringa vuota
        # vince su min() e `oldest` diventa "" — il tool direbbe «non so da quando»
        # sapendolo. NULLIF le esclude dal minimo; max() le ignora già (vuoto ordina prima).
        lo, hi = conn.execute(
            "SELECT min(NULLIF(ts,'')), max(ts) FROM messages").fetchone()
        oldest, newest = lo or "", hi or ""
        labels = int(conn.execute(
            "SELECT count(DISTINCT project) FROM messages").fetchone()[0])
    return {"rows": rows, "oldest": oldest, "newest": newest, "labels": labels,
            "voci": distribuzione_voce_conn(conn)}


def distribuzione_voce_conn(conn: sqlite3.Connection) -> dict[str, int]:
    """Quante righe per `voice` — «quanto è contaminato» un DB a colpo d'occhio.

    🔑 `''` NON viene rinominato in `unknown` qui, e non è pedanteria: un DB con
    tutte le righe a `''` è un DB **mai classificato**, e va potuto distinguere da
    uno in cui il classificatore ha guardato e non ha saputo dire. Sono due schede
    diverse dello stesso archivio.
    📌 Torna `{}` — non uno zero — se le colonne non ci sono: su un DB v2 la
    domanda non ha risposta, e «non ho potuto guardare» non è «non c'è niente».
    """
    try:
        return {(v or "(non classificate)"): int(n) for v, n in conn.execute(
            "SELECT voice, count(*) FROM messages GROUP BY voice ORDER BY 2 DESC")}
    except sqlite3.OperationalError:
        return {}


# ══════════════════════════════════════════════════════════════════════════════
# SESSIONI E STIRPI — il Livello 2 del contratto `recupero/` R1 (24/09/2026)
# ══════════════════════════════════════════════════════════════════════════════
# Dal contratto R1 l'indexer scrive, oltre ai messaggi, le tabelle `sessioni`
# (una riga per sessione consegnata in un bundle), `archi` (le relazioni fra
# sessioni: continua, clone, …) e le schede `recupero:sessioni`/`recupero:stirpi`
# come righe di `messages`, ognuna con l'avvistamento del suo membro. Fino a qui
# l'archivio non aveva un'entità «sessione»: il sessionId non era una colonna.
# Queste funzioni leggono quelle tabelle su UNA connessione; il multi-DB, la
# scelta del DB e gli errori sui DB vecchi stanno in db.py. Sola lettura.


class SessioneNonRisolta(ValueError):
    """Il sessionId chiesto non porta a UNA sessione: troppo corto, ambiguo, assente,
    o l'archivio non ha le tabelle del contratto R1. Sollevata con il perché e la
    cura invece di restituire una scheda vuota: un `{}` qui direbbe «la sessione non
    ha niente» quando la verità è «non l'ho trovata» — o «non potevo cercarla»."""


def tabelle_conn(conn: sqlite3.Connection) -> set[str]:
    """I nomi delle tabelle del DB (per sapere se è nato prima del contratto R1)."""
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _righe_dict(cur: sqlite3.Cursor) -> list[dict[str, Any]]:
    """Righe come dict, con qualunque row_factory (i test aprono senza sqlite3.Row)."""
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, tuple(r))) for r in cur.fetchall()]


def _tronca_testo(testo: str | None, max_chars: int) -> str | None:
    """Stesso patto di `_tronca_righe` in db.py (#268): il troncamento si DICHIARA."""
    if testo is None or not max_chars or max_chars <= 0 or len(testo) <= max_chars:
        return testo
    return (testo[:max_chars] + f" …‹troncato: {max_chars} di {len(testo)} char — "
            f"testo pieno con max_chars=0›")


def candidati_sessione_conn(conn: sqlite3.Connection, chiave: str) -> list[str]:
    """I sessionId di questo DB che cominciano con `chiave`, presi da `sessioni` E
    dagli estremi degli `archi` (una sessione può essere nota solo come estremo di un
    arco: la madre non consegnata di un clone). Se `chiave` è un id presente per
    intero, torna solo quello. `substr` e non `LIKE`: `%` e `_` nell'input restano
    caratteri, non diventano jolly."""
    tab = tabelle_conn(conn)
    n = len(chiave)
    trovati: set[str] = set()
    if "sessioni" in tab:
        trovati |= {r[0] for r in conn.execute(
            "SELECT sessionId FROM sessioni WHERE substr(sessionId, 1, ?) = ?", (n, chiave))}
    if "archi" in tab:
        trovati |= {r[0] for r in conn.execute(
            "SELECT da FROM archi WHERE substr(da, 1, ?) = ? "
            "UNION SELECT a FROM archi WHERE substr(a, 1, ?) = ?", (n, chiave, n, chiave))}
    if chiave in trovati:
        return [chiave]
    return sorted(trovati)


def ultimo_ts_sessione_conn(conn: sqlite3.Connection, sid: str) -> str:
    """`last_ts` della sessione in questo DB ('' se non ha una riga in `sessioni`):
    serve a scegliere, fra più archivi che la conoscono, quello più aggiornato. Con
    più filoni vale il più recente fra i loro."""
    try:
        r = conn.execute("SELECT max(last_ts) FROM sessioni WHERE sessionId=?",
                         (sid,)).fetchone()
    except sqlite3.OperationalError:
        return ""
    return (r[0] or "") if r else ""


# Un FILONE è un file consegnato con lo stesso sessionId di un altro: la sessione in
# collisione esce dal bundle come `sessions/<sid>.jsonl` più `sessions/<sid>__fN.jsonl`,
# e dal 25/09/2026 la tabella `sessioni` ne tiene una riga ciascuno (chiave
# `(sessionId, file)`). Il PRINCIPALE è il file senza `__fN`; se manca, il primo per N.
_FILONE_RE = re.compile(r"__f(\d+)\.jsonl$")


def _ordine_filone(riga: dict[str, Any]) -> tuple[int, int, str]:
    """Chiave d'ordine dei filoni: prima il file senza `__fN`, poi per N, poi per nome."""
    f = str(riga.get("file") or "")
    m = _FILONE_RE.search(f)
    return (1, int(m.group(1)), f) if m else (0, 0, f)


def _filoni(righe: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Le righe di UNA sessione in ordine di filone: la prima è il principale."""
    return sorted(righe, key=_ordine_filone)


def _membro_scheda(sid: str, riga: dict[str, Any] | None) -> str:
    """Il membro della scheda di un filone: stesso nome del file della conversazione
    (`sessions/<sid>__f2.jsonl` → `recupero/sessioni/<sid>__f2.md`, contratto R1).
    Senza riga, o con un `file` che non ha quella forma, la scheda è `<sid>.md`."""
    f = str((riga or {}).get("file") or "")
    if f.startswith("sessions/") and f.endswith(".jsonl") and "/" not in f[len("sessions/"):]:
        return "recupero/sessioni/" + f[len("sessions/"):-len(".jsonl")] + ".md"
    return f"recupero/sessioni/{sid}.md"


def avvistamenti_sessione_conn(conn: sqlite3.Connection, chiave: str) -> int:
    """Quante righe dell'archivio vengono da `sessions/<chiave>…` (anche un prefisso).
    Sui DB nati prima del contratto R1 dice se la CONVERSAZIONE c'è anche se la
    scheda no. -1 se il DB non ha nemmeno gli avvistamenti (non misurabile ≠ zero)."""
    pref = f"sessions/{chiave}"
    try:
        return int(conn.execute(
            "SELECT count(DISTINCT uuid) FROM sightings WHERE substr(source, 1, ?) = ?",
            (len(pref), pref)).fetchone()[0])
    except sqlite3.OperationalError:
        return -1


def _scheda_da_avvistamenti(conn: sqlite3.Connection, membro: str) -> str | None:
    """Il testo di una scheda `recupero/…` ricomposto dai suoi pezzi, in ordine.
    Si trovano dall'avvistamento del membro (è il registro di ciò che il membro ha
    scritto), non ricostruendo gli uuid dell'indexer: il modo in cui l'indexer li
    calcola è affar suo."""
    try:
        pezzi = conn.execute(
            "SELECT m.content FROM sightings s JOIN messages m ON m.uuid = s.uuid "
            "WHERE s.source = ? ORDER BY m.ts, m.uuid", (membro,)).fetchall()
    except sqlite3.OperationalError:
        return None
    return "\n".join((p[0] or "") for p in pezzi) if pezzi else None


def sessione_conn(conn: sqlite3.Connection, sid: str, *, limit: int = 200,
                  max_chars: int = 0) -> dict[str, Any]:
    """Tutto ciò che QUESTO DB sa della sessione `sid` (id intero, già risolto).

    - `sessione`: la riga di `sessioni` del filone PRINCIPALE (il file senza
      `__fN`, o il primo) — None se la sessione è nota solo dagli archi;
    - `filoni`: TUTTE le righe di `sessioni` per quel sessionId, il principale per
      primo (una sola per una sessione senza collisioni, [] senza riga);
    - `scheda`: il testo della scheda `recupero:sessioni` del principale (stato,
      ultime parole, fili aperti, commit…), ricomposto dai pezzi;
    - `conversazione`: le righe avvistate in `sessions/<sid>…` (tutti i filoni),
      per mittente, con primo e ultimo ts e i file d'origine;
    - `archi`: gli archi che la toccano (da o a), fino a `limit`;
    - `stirpe`: id e posizione dichiarati nella riga, più la scheda della stirpe;
    - `note`: ciò che manca, detto — mai un campo vuoto che finge di essere un dato.
    """
    note: list[str] = []
    riga = None
    filoni = []
    for r in _filoni(_righe_dict(conn.execute("SELECT * FROM sessioni WHERE sessionId=?",
                                              (sid,)))):
        f = {k: v for k, v in r.items() if k != "ingest_date"}
        f["ingest_date"] = r.get("ingest_date")
        filoni.append(f)
    if filoni:
        riga = filoni[0]
        if len(filoni) > 1:
            note.append(f"{len(filoni)} filoni (file distinti con lo stesso sessionId): "
                        f"`sessione` è il principale ({riga.get('file')}), tutti in `filoni`")
    else:
        note.append("nessuna riga in `sessioni`: la sessione è nota solo come estremo "
                    "di un arco (non è stata consegnata in un bundle di questo DB)")
    scheda = _scheda_da_avvistamenti(conn, _membro_scheda(sid, riga))
    if scheda is None:
        note.append("nessuna scheda `recupero:sessioni` per questa sessione in questo DB")
    pref = f"sessions/{sid}"
    conversazione: dict[str, Any]
    try:
        per_sender = {(s or "(vuoto)"): int(n) for s, n in conn.execute(
            "SELECT m.sender, count(DISTINCT m.uuid) FROM sightings s "
            "JOIN messages m ON m.uuid = s.uuid WHERE substr(s.source, 1, ?) = ? "
            "GROUP BY m.sender ORDER BY 2 DESC", (len(pref), pref))}
        tot, primo, ultimo = conn.execute(
            "SELECT count(DISTINCT m.uuid), min(NULLIF(m.ts,'')), max(NULLIF(m.ts,'')) "
            "FROM sightings s JOIN messages m ON m.uuid = s.uuid "
            "WHERE substr(s.source, 1, ?) = ?", (len(pref), pref)).fetchone()
        fonti = [f for (f,) in conn.execute(
            "SELECT DISTINCT source FROM sightings WHERE substr(source, 1, ?) = ? "
            "ORDER BY source", (len(pref), pref))]
        conversazione = {"messaggi": int(tot or 0), "per_sender": per_sender,
                         "primo_ts": primo or "", "ultimo_ts": ultimo or "", "fonti": fonti}
        if not tot:
            note.append(f"nessuna riga avvistata in {pref}…: la conversazione non è in "
                        f"questo DB (o ci è entrata da un'altra strada)")
    except sqlite3.OperationalError:
        conversazione = {"messaggi": None, "per_sender": {}, "primo_ts": "",
                         "ultimo_ts": "", "fonti": []}
        note.append("questo DB non ha la tabella `sightings`: i messaggi della "
                    "conversazione non si possono contare da qui")
    archi_tot = int(conn.execute("SELECT count(*) FROM archi WHERE da=? OR a=?",
                                 (sid, sid)).fetchone()[0])
    archi = _righe_dict(conn.execute(
        "SELECT da, a, relazione, via, livello, prova, voce, peso, chiusura, bundle_scan "
        "FROM archi WHERE da=? OR a=? ORDER BY da, a, relazione, via LIMIT ?",
        (sid, sid, max(0, int(limit)))))
    if archi_tot > len(archi):
        note.append(f"archi troncati: {len(archi)} di {archi_tot} (alza `limit`)")
    stirpe = None
    if riga and riga.get("stirpe"):
        sid_stirpe = str(riga["stirpe"])
        scheda_stirpe = _scheda_da_avvistamenti(conn, f"recupero/stirpi/{sid_stirpe}.md")
        stirpe = {"id": sid_stirpe, "posizione": riga.get("stirpe_pos"),
                  "scheda": _tronca_testo(scheda_stirpe, max_chars)}
        if scheda_stirpe is None:
            note.append(f"la stirpe {sid_stirpe} è dichiarata ma la sua scheda non è in "
                        f"questo DB (la chiusura sugli archi la dà get_stirpe)")
    return {"sessionId": sid, "sessione": riga, "filoni": filoni,
            "scheda": _tronca_testo(scheda, max_chars),
            "conversazione": conversazione, "archi": archi, "archi_totali": archi_tot,
            "stirpe": stirpe, "note": note}


_CHIUSURA = "(chiusura = 1 OR chiusura = '1')"


def stirpe_conn(conn: sqlite3.Connection, sid: str, *, limit: int = 200,
                max_chars: int = 0) -> dict[str, Any]:
    """La STIRPE di `sid`: la chiusura sugli archi con `chiusura=1`, presi senza
    verso (da↔a), a partire da `sid`. Ogni membro porta i suoi dati da `sessioni`;
    un membro SENZA riga in `sessioni` resta nella stirpe e lo dice (`in_sessioni:
    false`, e l'elenco `senza_riga`) — sparire sarebbe peggio che essere incompleto.
    Un membro con più filoni porta i dati del principale e tutte le righe in
    `filoni` ([] per chi non ha riga).
    Oltre `limit` membri la visita si ferma e lo dichiara."""
    note: list[str] = []
    visti: list[str] = [sid]
    insieme = {sid}
    fronte = [sid]
    archi: dict[tuple, dict[str, Any]] = {}
    troncata = False
    while fronte and not troncata:
        seg = ",".join("?" * len(fronte))
        righe = _righe_dict(conn.execute(
            "SELECT da, a, relazione, via, livello, prova, voce, peso, chiusura, bundle_scan "
            f"FROM archi WHERE {_CHIUSURA} AND (da IN ({seg}) OR a IN ({seg}))",
            (*fronte, *fronte)))
        nuovo: list[str] = []
        for arco in righe:
            archi[(arco["da"], arco["a"], arco["relazione"], arco["via"])] = arco
            for estremo in (arco["da"], arco["a"]):
                if estremo not in insieme:
                    if len(insieme) >= max(1, int(limit)):
                        troncata = True
                        break
                    insieme.add(estremo)
                    visti.append(estremo)
                    nuovo.append(estremo)
        fronte = nuovo
    if troncata:
        # gli archi verso i nodi rimasti fuori non si danno: nominerebbero membri
        # che l'elenco non contiene
        archi = {k: v for k, v in archi.items() if v["da"] in insieme and v["a"] in insieme}
        note.append(f"stirpe troncata a {len(insieme)} membri (alza `limit`)")
    seg = ",".join("?" * len(visti))
    per_sid: dict[str, list[dict[str, Any]]] = {}
    for r in _righe_dict(conn.execute(
            "SELECT sessionId, titolo, cwd, first_ts, last_ts, last_uuid, file, stato, "
            f"stato_fonte, stirpe, stirpe_pos, n_commit, n_fili FROM sessioni "
            f"WHERE sessionId IN ({seg})", tuple(visti))):
        per_sid.setdefault(r["sessionId"], []).append(r)
    # un membro con più filoni: i suoi dati sono quelli del PRINCIPALE, e `filoni`
    # li porta tutti (come in get_session) — prima ne restava uno a caso
    filoni_di = {k: _filoni(v) for k, v in per_sid.items()}
    dati = {k: v[0] for k, v in filoni_di.items()}
    membri = []
    for m in visti:
        if m in dati:
            membri.append({**dati[m], "in_sessioni": True, "filoni": filoni_di[m]})
        else:
            membri.append({"sessionId": m, "in_sessioni": False, "filoni": []})
    membri.sort(key=lambda d: (not d["in_sessioni"], d.get("first_ts") or "", d["sessionId"]))
    senza_riga = [m["sessionId"] for m in membri if not m["in_sessioni"]]
    if senza_riga:
        note.append(f"{len(senza_riga)} membri senza riga in `sessioni`: noti solo come "
                    f"estremi di un arco (non consegnati in un bundle di questo DB)")
    if len(visti) == 1:
        altri = int(conn.execute("SELECT count(*) FROM archi WHERE da=? OR a=?",
                                 (sid, sid)).fetchone()[0])
        note.append("nessun arco con chiusura=1: la sessione è sola nella sua stirpe"
                    + (f" ({altri} archi senza chiusura: vedi get_session)" if altri else ""))
    dichiarate = sorted({str(d["stirpe"]) for righe in filoni_di.values() for d in righe
                         if d.get("stirpe")})
    schede = {s: _tronca_testo(_scheda_da_avvistamenti(conn, f"recupero/stirpi/{s}.md"),
                               max_chars) for s in dichiarate}
    if len(dichiarate) > 1:
        note.append(f"i membri dichiarano {len(dichiarate)} stirpi diverse: la chiusura "
                    f"sugli archi le unisce, le righe di `sessioni` no")
    return {"sessionId": sid, "membri": membri, "senza_riga": senza_riga,
            "archi": sorted(archi.values(), key=lambda a: (a["da"], a["a"], a["relazione"],
                                                           a["via"])),
            "stirpi_dichiarate": dichiarate, "schede_stirpe": schede, "note": note}
