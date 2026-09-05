"""
FastMCP server — espone tool search MCP via streamable-http.

Stateless mode (FASTMCP_STATELESS_HTTP=true) per scalare.
"""
from __future__ import annotations

import functools
import logging
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from . import db, redazione
from .settings import get_settings

log = logging.getLogger(__name__)

_s = get_settings()
mcp = FastMCP(
    "archive",
    host=_s.archive_http_host,
    port=_s.archive_http_port,
    stateless_http=_s.fastmcp_stateless_http,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,  # dietro gateway, rete interna
    ),
)


# ── REDAZIONE IN USCITA: si avvolge `mcp.tool` STESSO, non i singoli tool ────────────
# I tool che restituiscono testo sono 3 su 9. Avvolgerne 3 significa che **il quarto
# nasce cieco** — la forma di difetto che abbiamo misurato sette volte in una notte: il
# presidio segue la forma del dato invece del rischio. Sostituendo il decoratore, un tool
# nuovo scritto con `@mcp.tool()` eredita la redazione **per costruzione**, e chi lo
# scrive non deve saperlo.
# ⚠️ L'ORDINE È IL PUNTO FRAGILE: un `@mcp.tool()` scritto SOPRA questo blocco userebbe il
#    decoratore originale. Lo verifica `test_redazione_copre_tutti_i_tool` con l'AST, che
#    fallisce se compare un tool prima della sostituzione.
_tool_originale = mcp.tool


def _tool_con_redazione(*args: Any, **kw: Any) -> Any:
    decoratore = _tool_originale(*args, **kw)

    def applica(fn):
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
        return decoratore(avvolta)
    return applica


mcp.tool = _tool_con_redazione                            # type: ignore[method-assign]


@mcp.tool()
def search(query: str, db_name: str = "", limit: int = 20, raw: bool = False,
           sort: str = "rank", since: str = "", until: str = "",
           project: str = "", speaker: str = "", voice: str = "",
           snippet_tokens: int = 32) -> list[dict[str, Any]]:
    """Cerca nell'archivio full-text (SQLite FTS5) delle conversazioni.

    COME SCRIVERE LA QUERY (leggere prima di cercare — evita falsi negativi):
    - Operatori SEMPRE in MAIUSCOLO: `AND`, `OR`, `NOT`, `NEAR(a b, 5)`. In
      minuscolo diventano termini di ricerca, non operatori.
    - Ricerca senza stemming e bilingue: cerca sempre le due lingue,
      `errore OR error`, `memoria OR memory`.
    - Famiglie di nomi col PREFISSO: `palant*` trova palantir1777 (i numeri
      attaccati non si separano: `1777` non trova N1777).
    - Termini con caratteri speciali (`- . / @ : # '`) vanno tra doppi apici:
      `"flutter-elinux"`, `"0.7.9"`, `"github.com"`, `"l'archivio"`. In modalità
      smart (default) il server li quota da sé; con `raw=true` la query passa
      intatta (per NEAR/parentesi complesse).
    - Case- e accent-insensitive: `perché` ≡ `perche`.

    PROTOCOLLO DELLO ZERO: 0 risultati NON prova assenza. Riprova quotando il
    termine e togliendo i caratteri speciali; solo più tentativi coerenti a zero
    valgono "non c'è". Una query malformata NON restituisce lista vuota: solleva
    un errore che spiega come correggerla.

    Args:
        query: espressione FTS5.
        db_name: nome DB ('' = tutti; vedi list_databases / describe_databases).
        limit: massimo risultati, GLOBALE anche su più DB (default 20).
        raw: se True passa la query intatta senza auto-quoting (default False).
        sort: 'rank' (rilevanza, default), 'newest' o 'oldest' (per data).
        since / until: filtro temporale sul ts (ISO, confronto lessicografico).
        project: filtra per etichetta esatta (titolo chat, project:*, design:*).
        speaker: CHI HA SCRITTO la riga — 'human', 'assistant', 'unknown'. È un
            FATTO preso dalla fonte, non una stima.
        voice: DI CHI È LA VOCE nel contenuto — è una STIMA euristica, con la sua
            confidenza. Valori: 'own', 'pasted_transcript', 'pasted_ai',
            'character', 'mixed', 'unknown', più due alias e un terzo stato:
              'direct'  = own con poca citazione (quoted_share < 0.2)
              'quoted'  = prevalentemente citato (quoted_share >= 0.5)
              'none'    = MAI CLASSIFICATA — nessuno l'ha guardata. NON è
                          'unknown', che invece è un giudizio: «guardata e non
                          riconosciuta». Chiederli insieme è chiedere due cose.
        snippet_tokens: lunghezza dello snippet (default 32). Per il testo pieno
            attorno a un risultato usa get_context(uuid).

    ⚠️ `voice:own` NON VUOL DIRE «lo ha scritto Neo». Vuol dire «chi ha scritto
    questo messaggio parlava di suo», e vale anche per l'assistente: misurato il
    02/08 su 61.100 righe, `own` contiene 10.629 messaggi dell'assistente —
    l'80% del totale `own`. **Per le parole di una persona servono DUE filtri:**
    `speaker='human', voice='own'`. Un filtro solo risponde a un'altra domanda.

    🔑 LA REGOLA D'ORO, ora interrogabile: cerchi chi-È-una-cosa (una definizione,
    un'attribuzione, «X è Y»)? Aggiungi `voice='direct'`. Un match identitario
    trovato SENZA quel filtro può venire da materiale incollato: prima di usarlo
    come fatto, `get_context(uuid)` — la citazione non diventa un fatto finché
    non sai chi parla.

    Ritorna righe {db, uuid, project, ts, rank, snippet, snapshot}. `snapshot` è
    la data dell'ultima modifica del DB: quanto è fresco ciò che leggi.
    Sulla ricerca in TUTTI i DB lo stesso uuid presente in più archivi (bundle e
    riscontri v1/v2) arriva UNA volta, col campo `anche_in` che elenca gli altri
    DB: il limit non si spreca più in fotocopie (#272).
    ⚠️ CONCORRENZA: il server serve 2 ricerche alla volta; le altre si mettono
    in coda da sole (#270). Raggruppa le chiamate a coppie, non a quartetti.
    """
    return db.search(query, db_name, limit, raw=raw, sort=sort, since=since,
                     until=until, project=project, speaker=speaker, voice=voice,
                     snippet_tokens=snippet_tokens)


@mcp.tool()
def count(query: str, db_name: str = "", raw: bool = False, since: str = "",
          until: str = "", project: str = "", speaker: str = "",
          voice: str = "") -> dict[str, Any]:
    """Conta quanti messaggi corrispondono alla query (non limitato) — per
    frequenze e prevalenze. Stessa sintassi di search. Ritorna
    {total, per_db:{nome: n}}. Query malformata → errore parlante, non 0.
    Se un termine COLLASSA (`C++`→`C`, vedi check_term) aggiunge `warnings`."""
    return db.count(query, db_name, raw=raw, since=since, until=until, project=project,
                    speaker=speaker, voice=voice)


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
    e `after` sono quanti messaggi prendere prima e dopo. Se il messaggio è in un
    thread (`parent_uuid`), i vicini vengono dallo STESSO thread; sulle fonti senza
    arco (documenti chunked, db storici) è l'adiacenza temporale nello stesso
    archivio. Per la chat INTERA usa `get_conversation`.
    `max_chars` (0 = intero) tronca OGNI riga a quel numero di caratteri, col
    troncamento dichiarato nel testo: sui messaggi-hub giganti (workfile/board
    incollati) il payload pieno uccideva la connessione proprio dove il contesto
    serve di più (#268) — parti con max_chars=2000 e allarga solo se serve.
    Ogni riga: {db, uuid, project, ts, content, is_match, snapshot}."""
    return db.get_context(uuid, db_name, before=before, after=after,
                          max_chars=max_chars)


@mcp.tool()
def get_conversation(uuid: str, db_name: str = "", limit: int = 200,
                     max_chars: int = 0) -> list[dict[str, Any]]:
    """Il thread di conversazione INTERO che contiene `uuid` — camminando l'albero
    `parent_uuid` (antenati + discendenti), col contenuto pieno e in ordine. Per
    LEGGERE una chat dall'inizio alla fine, non solo la finestra ±N di get_context.

    Dove l'albero manca — documenti chunked (pdf/telegram/memory) e db storici —
    ricade sull'ordine lineare dello stesso archivio. Ogni riga:
    {db, uuid, project, ts, content, sender, is_match, snapshot}.
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
    ({name, rows, oldest, newest, description}) invece del solo nome (#274) —
    è la stessa scheda di describe_databases, memoizzata, quindi costa poco.
    Default: lista di soli nomi (compatibilità con chi la usa da prima)."""
    if schede:
        return [{k: d.get(k) for k in ("name", "rows", "oldest", "newest", "description")}
                for d in db.describe()]
    return db.available_dbs()


@mcp.tool()
def describe_databases() -> list[dict[str, Any]]:
    """Scheda di ogni DB caricato: {name, rows, oldest, newest, labels,
    snapshot, description}. `oldest`/`newest` = intervallo temporale coperto;
    `snapshot` = data dell'ultima modifica (freschezza); `description` = a cosa
    serve / cosa contiene l'archivio (scritta all'upload o via set_description).
    Utile per sapere PRIMA di cercare quanto è ampio e aggiornato l'archivio."""
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
    quando la scheda è vuota/stale. È l'unica scrittura ammessa via MCP: tocca
    solo la scheda, mai i messaggi."""
    return db.set_description(db_name, description)


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
