"""
FastMCP server — espone tool search MCP via streamable-http.

Stateless mode (FASTMCP_STATELESS_HTTP=true) per scalare.
"""
from __future__ import annotations

import asyncio
import functools
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field

from . import db, redazione
from .settings import get_settings

log = logging.getLogger(__name__)

_s = get_settings()
# S4 (05/10/2026): le regole che contano stanno qui, in testa, e non solo in fondo alla
# descrizione di un tool. Claude Code tronca descrizioni e istruzioni a 2048 caratteri:
# fino alla 0.72 la guida di `search` arrivava tagliata a metà.
ISTRUZIONI = """\
archive1777: l'archivio delle conversazioni passate del proprietario (claude.ai, Claude Code,
Telegram, vocali). Cinque regole:
1. Per LESSICO usa `search` (sai come si chiama ciò che cerchi); per SENSO `search_ibrida`.
2. Zero risultati non prova un'assenza: riprova con altre parole, o con l'altro tool.
3. Una citazione non è un fatto finché non sai chi parla: `get_context(uuid)`. Le parole del
   proprietario sono speaker='human'; voice='own' da solo vale anche per l'assistente.
4. Prima di dire «non c'è» leggi `saltati` e, in search_ibrida, il perimetro degli `indici`.
5. Il server serve due ricerche alla volta: raggruppa le chiamate a coppie.
`list_databases(schede=True)` dice cosa c'è in ogni DB e il suo ruolo."""

mcp = FastMCP(
    "archive",
    instructions=ISTRUZIONI,
    host=_s.archive_http_host,
    port=_s.archive_http_port,
    stateless_http=_s.fastmcp_stateless_http,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,  # dietro gateway, rete interna
    ),
)


# ── REDAZIONE IN USCITA: si avvolge `mcp.tool` STESSO, non i singoli tool ────────────
# I tool che restituivano testo erano 3 su 9 (oggi i tool sono 15). Avvolgerne 3
# significa che **il quarto nasce cieco** — la forma di difetto che abbiamo misurato sette volte in una notte: il
# presidio segue la forma del dato invece del rischio. Sostituendo il decoratore, un tool
# nuovo scritto con `@mcp.tool()` eredita la redazione **per costruzione**, e chi lo
# scrive non deve saperlo.
# ⚠️ L'ORDINE È IL PUNTO FRAGILE: un `@mcp.tool()` scritto SOPRA questo blocco userebbe il
#    decoratore originale. Lo verifica `test_redazione_copre_tutti_i_tool` con l'AST, che
#    fallisce se compare un tool prima della sostituzione.
_tool_originale = mcp.tool

# ── FUORI DALL'EVENT LOOP (S1, 05/10/2026) ───────────────────────────────────────────
# FastMCP chiama un tool `def` DENTRO l'event loop: una ricerca lenta fermava tutto il
# server, `/health` compreso (il 04/10 muta per 311, 536 e 656 s; 92 errori dei client
# dal 07/09). Ogni tool diventa una coroutine che fa il lavoro, redazione compresa, su
# questo executor. Thread PERSISTENTI e non `anyio.to_thread`: la cache delle connessioni
# di `db` è per thread, e un thread che muore dopo 10 s di ozio ripaga l'apertura di ogni
# DB. Tre thread: le ricerche restano due alla volta (`db._RICERCHE`), il terzo tiene
# libero il passo agli altri tool (get_context, list_databases…).
_THREAD_TOOL = 3
_ESECUTORE = ThreadPoolExecutor(max_workers=_THREAD_TOOL, thread_name_prefix="archive-tool")


def _fuori_dal_loop(lavoro):
    """La coroutine che esegue `lavoro` sull'executor dei tool, con la sua firma."""
    @functools.wraps(lavoro)
    async def coroutine(*a: Any, **k: Any) -> Any:
        return await asyncio.get_running_loop().run_in_executor(
            _ESECUTORE, functools.partial(lavoro, *a, **k))
    return coroutine


# ── S10 (05/10/2026): titolo e annotazioni di OGNI tool, in un posto solo ───────────────
# Il client li usa per raggruppare i permessi (claude.ai) e per sapere cosa scrive. Tutti
# leggono un archivio locale (openWorld no), tranne i due che sovrascrivono i metadati di un
# DB senza storia: distruttivi e idempotenti. Un tool che manca da questa tabella non
# si registra (KeyError all'import): `test_annotazioni` lo dice prima.
_LETTURA = {"readOnlyHint": True, "openWorldHint": False}
_SCRIVE_METADATI = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True,
                    "openWorldHint": False}
ANNOTAZIONI: dict[str, tuple[str, dict[str, bool]]] = {
    "search": ("Cerca per parole", _LETTURA),
    "search_ibrida": ("Cerca per senso", _LETTURA),
    "count": ("Conta le occorrenze", _LETTURA),
    "check_term": ("Controlla un termine", _LETTURA),
    "get_context": ("Contesto di un messaggio", _LETTURA),
    "get_conversation": ("Leggi una conversazione", _LETTURA),
    "list_projects": ("Elenca le etichette", _LETTURA),
    "archive_stats": ("Messaggi per anno", _LETTURA),
    "list_databases": ("Elenca i DB", _LETTURA),
    "describe_databases": ("Descrivi i DB", _LETTURA),
    "check_integrity": ("Integrità dei DB", _LETTURA),
    "set_description": ("Scrivi la descrizione di un DB", _SCRIVE_METADATI),
    "set_ruolo": ("Scrivi il ruolo di un DB", _SCRIVE_METADATI),
    "get_session": ("Scheda di una sessione", _LETTURA),
    "get_stirpe": ("Catena di una sessione", _LETTURA),
}


def _tool_con_redazione(*args: Any, **kw: Any) -> Any:
    def applica(fn):
        titolo, hint = ANNOTAZIONI[fn.__name__]
        decoratore = _tool_originale(*args, title=titolo,
                                     annotations=ToolAnnotations(title=titolo, **hint), **kw)

        @functools.wraps(fn)
        def avvolta(*a: Any, **k: Any) -> Any:
            risultato = fn(*a, **k)
            if not redazione.ATTIVA:
                return risultato
            try:
                noti = db.valori_anagrafici()
            except Exception as exc:                      # noqa: BLE001
                # Fail-CLOSED sui pattern: se l'anagrafica non è leggibile perdo i valori
                # noti ma NON la redazione. Il contrario — restituire il risultato grezzo
                # perché una query è fallita — sarebbe un presidio che si spegne da solo
                # nell'unico momento in cui qualcosa non va.
                log.warning("valori anagrafici non disponibili (%s): restano i pattern", exc)
                noti = set()
            return redazione.maschera(risultato, noti)
        return decoratore(_fuori_dal_loop(avvolta))
    return applica


mcp.tool = _tool_con_redazione                            # type: ignore[method-assign]


@mcp.tool()
def search(
    query: Annotated[str, Field(description=(
        "Espressione FTS5. Operatori in MAIUSCOLO (AND OR NOT NEAR(a b, 5)); termini con "
        "- . / @ : # ' tra doppi apici; famiglie di nomi col prefisso (palant*)."))],
    db_name: Annotated[str, Field(description=(
        "Nome del DB; '' = tutti (vedi list_databases)."))] = "",
    limit: Annotated[int, Field(description=(
        "Massimo risultati, GLOBALE anche su più DB (default 20, massimo 200)."))] = 20,
    raw: Annotated[bool, Field(description=(
        "True = la query passa intatta, senza quotare da sé i caratteri speciali "
        "(per NEAR e parentesi complesse)."))] = False,
    sort: Annotated[str, Field(description=(
        "'rank' (rilevanza, default), 'newest' o 'oldest'."))] = "rank",
    since: Annotated[str, Field(description=(
        "Inizio della finestra (ISO, confronto lessicografico sul ts: ts >= since)."))] = "",
    until: Annotated[str, Field(description=(
        "Fine della finestra (ts <= until; un giorno senza ora esclude quel giorno: "
        "usa '2026-09-30T23:59')."))] = "",
    project: Annotated[str, Field(description=(
        "Etichetta esatta (titolo chat, project:*, design:*)."))] = "",
    speaker: Annotated[str, Field(description=(
        "CHI HA SCRITTO la riga, un fatto preso dalla fonte: 'human', 'assistant', "
        "'tool' (output di un comando), 'system' (turni iniettati dal programma), "
        "'other' (un altro membro di un gruppo Telegram), 'unknown' (allegati, titoli, "
        "memorie, documenti, log MCP). Un valore che non esiste è un errore."))] = "",
    voice: Annotated[str, Field(description=(
        "DI CHI È LA VOCE nel contenuto, una STIMA: 'own', 'pasted_transcript', "
        "'pasted_ai', 'character', 'mixed', 'unknown'; alias 'direct' (own con poca "
        "citazione) e 'quoted' (soprattutto citato); 'none' = mai classificata, che non "
        "è 'unknown'."))] = "",
    campi: Annotated[str, Field(description=(
        "'tutto' (default: testo, azioni e allegati) o 'testo' (solo le parole, senza "
        "comandi e file letti o scritti). Usa 'testo' con sort='newest' e per «chi ha "
        "detto cosa» (#273)."))] = "tutto",
    snippet_tokens: Annotated[int, Field(description=(
        "Lunghezza dello snippet (default 32). Per il testo attorno: get_context(uuid)."))] = 32,
) -> list[dict[str, Any]]:
    """Cerca nell'archivio full-text (SQLite FTS5) delle conversazioni, per LESSICO: quando
    sai come si chiama ciò che cerchi. Per il SENSO usa search_ibrida.

    QUERY: senza stemming e bilingue (cerca `errore OR error`); case- e accent-insensitive;
    `1777` non trova N1777 (usa il prefisso). I dettagli dei parametri stanno nello schema.

    PROTOCOLLO DELLO ZERO: 0 risultati NON prova assenza. Riprova quotando il termine e
    togliendo i caratteri speciali; solo più tentativi coerenti a zero valgono «non c'è».
    Una query malformata solleva un errore che spiega come correggerla, non una lista vuota.

    ⚠️ `voice='own'` NON vuol dire «lo ha scritto Neo»: vale anche per l'assistente (l'80%
    degli `own`, misurato il 02/08). Per le parole di una persona servono DUE filtri:
    `speaker='human', voice='own'`.

    🔑 REGOLA D'ORO: cerchi chi-È-una-cosa («X è Y»)? Aggiungi `voice='direct'`. Un match
    trovato senza quel filtro può venire da materiale incollato: prima di usarlo come fatto,
    `get_context(uuid)`.

    Ritorna righe {db, uuid, project, ts, rank, snippet, snapshot}; `snapshot` = quanto è
    fresco il DB. Su tutti i DB lo stesso uuid arriva UNA volta, con `anche_in` per gli altri
    DB (#272). ⚠️ Il server serve 2 ricerche alla volta, le altre aspettano in coda (#270):
    raggruppa le chiamate a coppie.
    """
    return db.search(query, db_name, limit, raw=raw, sort=sort, since=since,
                     until=until, project=project, speaker=speaker, voice=voice,
                     campi=campi, snippet_tokens=snippet_tokens)


@mcp.tool()
def search_ibrida(
    query: Annotated[str, Field(description=(
        "La domanda in linguaggio naturale, come la diresti a voce: niente AND/OR/asterischi."))],
    db_name: Annotated[str, Field(description=(
        "Nome del DB; '' = tutti quelli che hanno un indice vettoriale."))] = "",
    limit: Annotated[int, Field(description=(
        "Righe restituite (default 20, massimo 200)."))] = 20,
    query_fts: Annotated[str, Field(description=(
        "Facoltativa: un'espressione FTS5 col lessico giusto per il ramo full-text, se lo "
        "conosci (vale solo per la domanda, non per le riformulazioni)."))] = "",
    since: Annotated[str, Field(description=(
        "Inizio della finestra (ts >= since), su tutte e due le liste."))] = "",
    until: Annotated[str, Field(description=(
        "Fine della finestra (ts <= until); le righe senza ts restano fuori."))] = "",
    campi: Annotated[str, Field(description=(
        "'tutto' (default) o 'testo': con 'testo' il ramo vettoriale tiene solo le righe "
        "che hanno parole."))] = "tutto",
    k_rrf: Annotated[int, Field(description=(
        "Parametro di fusione RRF: il default (30) è quello misurato; cambiarlo è un "
        "esperimento."))] = 30,
    peso_fts: Annotated[float, Field(description=(
        "Peso del ramo full-text nella fusione: il default (1.5) è quello misurato."))] = 1.5,
    snippet_tokens: Annotated[int, Field(description=(
        "Lunghezza dello snippet FTS (default 64, che è anche il tetto di FTS5)."))] = 64,
    speaker: Annotated[str, Field(description=(
        "CHI HA SCRITTO, come in search ('human', 'assistant', 'tool', 'system', 'other', "
        "'unknown'). Per «cosa ha detto Neo» usa 'human': senza, su 20 risultati le sue "
        "parole erano da 0 a 8 (27/09)."))] = "",
    riformulazioni: Annotated[list[str] | None, Field(description=(
        "Fino a 3 altri modi di dire la domanda. La fusione resta una, con lo stesso "
        "limit: serve quando leggi pochi risultati."))] = None,
    passaggio: Annotated[int, Field(description=(
        "0 (default) o un numero di parole fino a 400: al posto dello snippet, la finestra "
        "del testo intero dove i termini sono più fitti. Per vocali, verbali e chat lunghe; "
        "200 parole su 10 righe sono circa 2.700 token."))] = 0,
) -> dict[str, Any]:
    """Cerca per SENSO, non per lessico: FTS5 + vettori fusi in una sola RRF su tutti i DB
    (#281). Usala quando ricordi il senso e non le parole («l'articolo dove raccontavo quanto
    avevo speso»). Quando sai il termine esatto usa `search`: qui la fusione è tarata per non
    peggiorare le query esatte, non per vincerle. Misurato: FTS5 5/9, vettori 4/9, ibrido 6/9.

    Ritorna {righe, indici, parametri} e, solo se qualcosa si è perso, `saltati`:
    - `righe`: come search, più `origine` ('fts' | 'vettori' | 'entrambi'): dice quale
      motore ha trovato la riga;
    - `indici`: per ogni DB quanti messaggi sono indicizzati e CON CHE PERIMETRO. ⚠️ Leggilo
      prima di dire «non c'è»: fuori dal perimetro gli zeri sembrano assenze, e la risposta
      giusta è `search`. `indici[].verifica` con `scartati` > 0 = indice disallineato, quei
      risultati sono stati tolti e non restituiti sbagliati;
    - `saltati`: [{db, ramo, motivo}] per un DB sparito, un ramo full-text inutilizzabile o
      un indice che non risponde (in quel caso resta la metà full-text);
    - `parametri`: k_rrf, peso_fts, modello, quante formulazioni.

    ⚠️ Senza modello di embedding o senza alcun indice `.vec.db` NON ricade in silenzio su
    FTS5: solleva un errore che dice cosa manca (docs/RICERCA-IBRIDA.md).
    """
    return db.search_ibrida(query, db_name, limit, query_fts=query_fts,
                            since=since, until=until, campi=campi, k_rrf=k_rrf,
                            peso_fts=peso_fts, snippet_tokens=snippet_tokens,
                            speaker=speaker, riformulazioni=riformulazioni,
                            passaggio=passaggio)


@mcp.tool()
def count(query: str, db_name: str = "", raw: bool = False, since: str = "",
          until: str = "", project: str = "", speaker: str = "",
          voice: str = "", campi: str = "tutto") -> dict[str, Any]:
    """Conta quanti messaggi corrispondono alla query (non limitato) — per
    frequenze e prevalenze. Stessa sintassi e stessi filtri di search, `campi`
    compreso ('testo' = solo le parole, senza le azioni). Ritorna
    {total, per_db:{nome: n}}. Query malformata → errore parlante, non 0.
    Se un termine COLLASSA (`C++`→`C`, vedi check_term) aggiunge `warnings`."""
    return db.count(query, db_name, raw=raw, since=since, until=until, project=project,
                    speaker=speaker, voice=voice, campi=campi)


@mcp.tool()
def check_term(term: str, db_name: str = "") -> dict[str, Any]:
    """Diagnostica se un TERMINE con caratteri speciali (`C++`, `C#`, `g++`, `.NET`,
    `F#`) è davvero ricercabile o se l'indice lo fa COLLASSARE su una parola più
    corta e comune. È una sottrazione: confronta count(term) con count(prefisso
    alfanumerico). Se coincidono, per quell'indice `C++` == `C` e i risultati sono
    falsi positivi silenziosi (la causa del falso ricordo dell'11/07: «Neo
    programmatore C++» erano coordinate SVG, copyright, gradi centigradi). Non
    chiede alla documentazione — chiede all'indice, e si auto-tara: su un DB
    ricostruito con `tokenchars` i due conteggi divergono e collapsed=False.

    Args:
        term: il termine da verificare (es. 'C++').
        db_name: nome DB ('' = tutti).
    Ritorna {term, prefix, per_db:{nome:{count_term, count_prefix, collapsed}}}.
    `collapsed=true` su un DB = quel DB va ricostruito con tokenchars per
    distinguere il termine dal suo prefisso."""
    return db.check_term(term, db_name)


@mcp.tool()
def get_context(uuid: str, db_name: str = "", before: int = 3,
                after: int = 3, max_chars: int = 0) -> list[dict[str, Any]]:
    """Restituisce i messaggi ATTORNO a un risultato (col contenuto pieno, non
    lo snippet troncato). Dai a `uuid` uno dei valori tornati da search; `before`
    e `after` sono quanti messaggi prendere prima e dopo. Sulle sessioni Claude Code
    i vicini vengono dal FILE DI SESSIONE (la riga cercata lo dice in `vicini_da`):
    la catena `parent_uuid` lì è spezzata in un terzo delle righe. Altrove, se il
    messaggio è in un thread (`parent_uuid`), dallo STESSO thread; sulle fonti senza
    arco (documenti chunked, db storici) è l'adiacenza temporale nello stesso
    archivio. Per la chat INTERA usa `get_conversation`.
    `max_chars` (0 = intero) tronca OGNI riga a quel numero di caratteri, col
    troncamento dichiarato nel testo: sui messaggi-hub giganti (workfile/board
    incollati) il payload pieno uccideva la connessione proprio dove il contesto
    serve di più (#268) — parti con max_chars=2000 e allarga solo se serve.
    Ogni riga: {db, uuid, project, ts, content, is_match, snapshot}; una riga SENZA
    testo (un tool_use, l'output di un comando) porta anche `tools`, le sue azioni."""
    return db.get_context(uuid, db_name, before=before, after=after,
                          max_chars=max_chars)


@mcp.tool()
def get_conversation(uuid: str, db_name: str = "", limit: int = 200,
                     max_chars: int = 0) -> list[dict[str, Any]]:
    """Il thread di conversazione INTERO che contiene `uuid` — camminando l'albero
    `parent_uuid` (antenati + discendenti), col contenuto pieno e in ordine. Per
    LEGGERE una chat dall'inizio alla fine, non solo la finestra ±N di get_context.

    Sulle sessioni Claude Code è il FILE DI SESSIONE intero (`conversazione_da` sulla
    riga cercata), con la scheda R1 della sessione in coda; dall'uuid della scheda
    si arriva alla stessa chat.

    Dove l'albero manca — documenti chunked (pdf/telegram/memory) e db storici —
    ricade sull'ordine lineare dello stesso `project` (di solito dalla prima riga).
    Ogni riga: {db, uuid, project, ts, content, sender, is_match, snapshot}, più
    `tools` sulle righe senza testo, come in get_context.

    📏 `limit` (default 200) è quante righe tornano. Se la chat è più lunga non torna
    l'inizio: torna una FINESTRA che contiene sempre `uuid` (più la scheda, se c'è), e
    la riga del match porta `finestra` = {righe, da, a, nota} — quante righe ha la chat
    e quali sono queste. Senza `finestra` la chat è intera. Per averla tutta alza
    `limit` (e usa `max_chars`).
    `max_chars` come in get_context (#268): su 200 righe piene è la differenza
    fra una risposta e una connessione morta."""
    return db.get_conversation(uuid, db_name, limit=limit, max_chars=max_chars)


@mcp.tool()
def list_projects(db_name: str = "", top: int = 1000) -> list[dict[str, Any]]:
    """Le etichette `project` dell'archivio con quanti messaggi ciascuna — per
    NAVIGARE i contenuti (quali progetti/chat ci sono) invece di solo cercarli.
    Ogni riga: {project, rows, db}. Ordinate per numero di messaggi."""
    return db.list_projects(db_name, top=top)


@mcp.tool()
def archive_stats(db_name: str = "") -> list[dict[str, Any]]:
    """Istogramma temporale per ANNO: quanti messaggi per anno in ogni archivio —
    «quando» l'archivio è fitto, da sapere PRIMA di cercare. Ogni riga:
    {period, rows, db}.
    COSTO: la prima chiamata su un DB scandisce tutto il DB (su installazioni
    grandi può richiedere decine di secondi); le successive sono memoizzate per
    snapshot e costano zero finché il file non cambia (#269)."""
    return db.archive_stats(db_name)


@mcp.tool()
def list_databases(schede: bool = False) -> list[Any]:
    """Elenca i nomi dei DB caricati. La scelta del DB è il PRIMO bivio di ogni
    ricerca: con `schede=True` ogni voce arriva con la sua carta d'identità
    ({name, ruolo, rows, oldest, newest, description}) invece del solo nome
    (#274) — è la stessa scheda di describe_databases, memoizzata, quindi costa
    poco. Default: lista di soli nomi (compatibilità con chi la usa da prima).

    `ruolo` (#278) è il campo su cui INSTRADARE senza leggere prosa: `primario`
    = la fonte corrente di quel versante, `fotografia` = versione più vecchia
    tenuta per la storia, `riscontro` = si interroga per verificare non per
    trovare, `riservato` = materiale personale, fuori dai compiti tecnici senza
    richiesta esplicita. `non dichiarato` = nessuno si è pronunciato su quel DB:
    NON vuol dire «poco importante», e non va indovinato dal nome."""
    if schede:
        return [{k: d.get(k) for k in
                 ("name", "ruolo", "rows", "oldest", "newest", "description")}
                for d in db.describe()]
    return db.available_dbs()


@mcp.tool()
def describe_databases() -> list[dict[str, Any]]:
    """Scheda di ogni DB caricato: {name, ruolo, rows, oldest, newest, labels,
    snapshot, description}. `oldest`/`newest` = intervallo temporale coperto;
    `snapshot` = data dell'ultima modifica (freschezza); `description` = a cosa
    serve / cosa contiene l'archivio (scritta all'upload o via set_description);
    `ruolo` = a cosa serve QUESTO archivio rispetto agli altri (#278: `primario`
    · `fotografia` · `riscontro` · `riservato` · `non dichiarato`).
    Utile per sapere PRIMA di cercare quanto è ampio e aggiornato l'archivio.

    ⚠️ Il `ruolo` è INFORMAZIONE, non ancora comportamento: `search`/`count`
    senza `db_name` toccano tutti i DB come prima, `riservato` compreso. Chi
    vuole restringere ai primari lo deve fare LEGGENDO questo campo e passando
    `db_name` — il default sui primari è la cura B della #278, non è in vigore."""
    return db.describe()


@mcp.tool()
def check_integrity(db_name: str = "") -> dict[str, Any]:
    """Integrità degli archivi: `ok` · `sporco` · `corrotto` · `non_misurabile`.

    Serve a rispondere a UNA domanda che nessun altro tool risponde: **questo
    archivio è in uno stato leggibile, o sto servendo dati di una transazione mai
    committata?** Un archivio `sporco` ha un journal caldo — lo scrittore (il
    gateway) è morto a metà — e da qui **non è riparabile**: il volume è montato
    in sola lettura di proposito. Il rimedio è dal lato che scrive.

    Costa una scansione per DB (`PRAGMA quick_check`): chiamalo quando un
    risultato sembra strano o dopo un riavvio brusco, non a ogni ricerca.
    """
    return db.integrita_archivi(db_name)


@mcp.tool()
def set_description(db_name: str, description: str) -> dict[str, Any]:
    """Imposta/aggiorna la DESCRIZIONE di un archivio: a cosa serve, cosa
    contiene, come va usato. Compare in describe_databases (campo `description`)
    e nella pagina admin. Usala quando carichi o riorganizzi un archivio, o
    quando la scheda è vuota/stale. Come `set_ruolo`, tocca solo la scheda del
    DB: i messaggi non si scrivono da qui, mai."""
    return db.set_description(db_name, description)


@mcp.tool()
def set_ruolo(db_name: str, ruolo: str) -> dict[str, Any]:
    """Dichiara il RUOLO di un archivio (#278) — il campo che dice a una MACCHINA
    quale DB serve, senza farle leggere la prosa della `description`.

    Valori ammessi (vocabolario chiuso):
      · `primario`   la fonte CORRENTE di quel versante — se non scegli, è lei
                     che deve rispondere;
      · `fotografia` versione più vecchia dello stesso versante, tenuta per la
                     storia: si cerca qui quando interessa com'ERA;
      · `riscontro`  non si interroga per trovare ma per VERIFICARE (ridondanza
                     voluta, gemelli re-ingeriti, DB-sonda con un caso-noto);
      · `riservato`  materiale personale: fuori dai compiti tecnici senza
                     richiesta esplicita. È una dichiarazione, non un lucchetto —
                     nessun tool lo esclude da solo.
      · `""` (vuoto) ritira la dichiarazione: il DB torna `non dichiarato`.

    Quando usarla: ogni volta che cambia il primario di un versante (arriva un
    export nuovo, il vecchio retrocede). Prima della #278 quel passaggio era la
    riscrittura a mano di due `description` in italiano, e chi non le leggeva
    tutte instradava sul DB sbagliato senza accorgersene.

    Compare in `describe_databases` e in `list_databases(schede=True)`."""
    return db.set_ruolo(db_name, ruolo)


@mcp.tool()
def get_session(sessionId: str, db_name: str = "", limit: int = 200,
                max_chars: int = 0) -> dict[str, Any]:
    """Tutto ciò che l'archivio sa di UNA sessione Claude Code, dato il suo id.

    Legge le tabelle del contratto `recupero/` R1 (bundle di Recupero Sessioni,
    dal 24/09/2026). `sessionId`: l'uuid intero o un PREFISSO di almeno 8
    caratteri, se univoco — se è ambiguo l'errore elenca i candidati coi loro DB.

    Ritorna {sessionId, db, snapshot, sessione, filoni, scheda, conversazione,
    archi, archi_totali, stirpe, note, anche_in?}:
    - `sessione`: la riga di `sessioni` (titolo, cwd, first_ts/last_ts,
      last_uuid, file, stato, stirpe, n_commit, n_fili…); null se la sessione è
      nota solo come estremo di un arco. Se la sessione ha più FILONI (file
      distinti con lo stesso id: `sessions/<sid>.jsonl`, `…__f2.jsonl`), è la
      riga del principale — il file senza `__fN`, o il primo;
    - `filoni`: tutte le righe di `sessioni` per quel sessionId, il principale
      per primo ([] se non c'è riga);
    - `scheda`: il testo della scheda del principale (stato, ultime parole
      [verbatim], fili aperti, commit, memorie scritte, stirpe). ⚠️ Le «ultime
      parole» sono CITAZIONI: chi parla lo dice la scheda, non il fatto che
      siano qui;
    - `conversazione`: {messaggi, per_sender, primo_ts, ultimo_ts, fonti} —
      le righe avvistate in `sessions/<sid>…` (tutti i filoni). Per LEGGERLA:
      `get_conversation` con `sessione.last_uuid`;
    - `archi`: le relazioni che la toccano (fino a `limit`), `stirpe`: id,
      posizione e scheda della stirpe dichiarata (la chiusura: `get_stirpe`);
    - `note`: ciò che manca, detto. `anche_in`: altri DB che la conoscono (qui
      risponde quello col last_ts più recente).
    `max_chars` tronca le schede dichiarandolo (#268).

    Un DB indicizzato PRIMA del contratto R1 non ha la tabella `sessioni`: lì la
    risposta è un errore che lo dice (e se la conversazione c'è comunque, dove),
    mai una scheda vuota. ⚠️ CONCORRENZA: conta come una ricerca (#270)."""
    return db.get_session(sessionId, db_name, limit=limit, max_chars=max_chars)


@mcp.tool()
def get_stirpe(sessionId: str, db_name: str = "", limit: int = 200,
               max_chars: int = 0) -> dict[str, Any]:
    """La STIRPE di una sessione: le sessioni che si continuano l'una nell'altra
    (clone, /clear, compact…), cioè la chiusura sugli archi con `chiusura=1`
    presi senza verso, a partire da `sessionId` (uuid intero o prefisso ≥ 8
    univoco, come in get_session).

    Ritorna {sessionId, db, snapshot, membri, senza_riga, archi,
    stirpi_dichiarate, schede_stirpe, note, anche_in?}:
    - `membri`: ogni sessione della stirpe coi suoi dati da `sessioni`, in
      ordine di first_ts; chi NON ha una riga in `sessioni` (nota solo come
      estremo di un arco) resta nell'elenco con `in_sessioni: false` ed è
      elencato in `senza_riga` — incompleto, non sparito; ognuno porta
      `filoni` (tutte le sue righe di `sessioni`, il principale per primo: i
      dati del membro sono i suoi);
    - `archi`: gli archi con chiusura=1 fra i membri;
    - `stirpi_dichiarate` / `schede_stirpe`: gli id di stirpe scritti nelle
      righe dei membri e le loro schede.
    Oltre `limit` membri la visita si ferma e lo dichiara in `note`. Stessi
    errori parlanti di get_session sui DB nati prima del contratto R1."""
    return db.get_stirpe(sessionId, db_name, limit=limit, max_chars=max_chars)


# ── /health — la sonda che il compose interroga (vaglio corso1777, 03/09) ────────
# Prima il healthcheck apriva un socket TCP e lo richiudeva: un processo con la
# porta aperta e l'app rotta risultava «healthy», e su quel verde si appoggia il
# HEALTH-GATE dell'updater. La sonda giusta prova il MESTIERE del servizio
# (settings + volume + registry dei DB), senza costare una ricerca vera.
# Espone anche quale revisione MCP sa parlare l'SDK spedito nell'immagine:
# «quale revisione parla il tuo gateway?» deve avere una risposta osservabile,
# non una deduzione dal lockfile.
@mcp.custom_route("/health", methods=["GET"])
async def health(_request):  # noqa: ANN001, ANN202 — firma imposta da custom_route
    import importlib.metadata

    from starlette.responses import JSONResponse

    try:
        n_dbs = len(db.available_dbs())
    except Exception as exc:  # noqa: BLE001 — QUALUNQUE guasto = non healthy
        return JSONResponse({"status": "error", "reason": str(exc)[:200]}, status_code=503)
    try:
        from mcp.types import LATEST_PROTOCOL_VERSION
        sdk = importlib.metadata.version("mcp")
    except Exception:  # noqa: BLE001 — la versione è informativa, non gate
        sdk, LATEST_PROTOCOL_VERSION = None, None
    return JSONResponse({
        "status": "ok",
        "dbs": n_dbs,
        "mcp_sdk": sdk,
        "mcp_protocol_max": LATEST_PROTOCOL_VERSION,
    })
