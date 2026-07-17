"""
FastMCP server — espone tool search MCP via streamable-http.

Stateless mode (FASTMCP_STATELESS_HTTP=true) per scalare.
"""
from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from . import db
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


@mcp.tool()
def search(query: str, db_name: str = "", limit: int = 20, raw: bool = False,
           sort: str = "rank", since: str = "", until: str = "",
           project: str = "", snippet_tokens: int = 32) -> list[dict[str, Any]]:
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
        snippet_tokens: lunghezza dello snippet (default 32). Per il testo pieno
            attorno a un risultato usa get_context(uuid).

    Ritorna righe {db, uuid, project, ts, rank, snippet, snapshot}. `snapshot` è
    la data dell'ultima modifica del DB: quanto è fresco ciò che leggi.
    """
    return db.search(query, db_name, limit, raw=raw, sort=sort, since=since,
                     until=until, project=project, snippet_tokens=snippet_tokens)


@mcp.tool()
def count(query: str, db_name: str = "", raw: bool = False, since: str = "",
          until: str = "", project: str = "") -> dict[str, Any]:
    """Conta quanti messaggi corrispondono alla query (non limitato) — per
    frequenze e prevalenze. Stessa sintassi di search. Ritorna
    {total, per_db:{nome: n}}. Query malformata → errore parlante, non 0.
    Se un termine COLLASSA (`C++`→`C`, vedi check_term) aggiunge `warnings`."""
    return db.count(query, db_name, raw=raw, since=since, until=until, project=project)


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
                after: int = 3) -> list[dict[str, Any]]:
    """Restituisce i messaggi ATTORNO a un risultato (col contenuto pieno, non
    lo snippet troncato). Dai a `uuid` uno dei valori tornati da search; `before`
    e `after` sono quanti messaggi prendere prima e dopo. Se il messaggio è in un
    thread (`parent_uuid`), i vicini vengono dallo STESSO thread; sulle fonti senza
    arco (documenti chunked, db storici) è l'adiacenza temporale nello stesso
    archivio. Per la chat INTERA usa `get_conversation`.
    Ogni riga: {db, uuid, project, ts, content, is_match, snapshot}."""
    return db.get_context(uuid, db_name, before=before, after=after)


@mcp.tool()
def get_conversation(uuid: str, db_name: str = "", limit: int = 200) -> list[dict[str, Any]]:
    """Il thread di conversazione INTERO che contiene `uuid` — camminando l'albero
    `parent_uuid` (antenati + discendenti), col contenuto pieno e in ordine. Per
    LEGGERE una chat dall'inizio alla fine, non solo la finestra ±N di get_context.

    Dove l'albero manca — documenti chunked (pdf/telegram/memory) e db storici —
    ricade sull'ordine lineare dello stesso archivio. Ogni riga:
    {db, uuid, project, ts, content, sender, is_match, snapshot}."""
    return db.get_conversation(uuid, db_name, limit=limit)


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
    {period, rows, db}."""
    return db.archive_stats(db_name)


@mcp.tool()
def list_databases() -> list[str]:
    """Elenca i nomi dei DB caricati. Per la scheda (righe, date, freschezza)
    usa describe_databases()."""
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
def set_description(db_name: str, description: str) -> dict[str, Any]:
    """Imposta/aggiorna la DESCRIZIONE di un archivio: a cosa serve, cosa
    contiene, come va usato. Compare in describe_databases (campo `description`)
    e nella pagina admin. Usala quando carichi o riorganizzi un archivio, o
    quando la scheda è vuota/stale. È l'unica scrittura ammessa via MCP: tocca
    solo la scheda, mai i messaggi."""
    return db.set_description(db_name, description)
