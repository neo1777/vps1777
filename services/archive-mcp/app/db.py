"""
Storage layer — astratto su SQLite FTS5.

Mantiene la registry `DBS: dict[name, Path]` filtrata ai DB esistenti (degraded
mode: i mancanti vengono rimossi all'avvio con un warning). Orchestra il
multi-DB (registry + freshness + limit globale) sopra la logica FTS pura di
`fts.py` (stdlib-only, testabile senza il runtime del server).

Per swap futuro a Postgres: implementa `_open` e le funzioni di fts con backend
diverso.
"""
from __future__ import annotations

import datetime
import logging
import os
import json
import time
import urllib.request
import urllib.error
import sqlite3
import threading
from pathlib import Path
from typing import Any

from . import fts
from . import integrita
from .fts import FtsSyntaxError  # noqa: F401 — riesportato per server.py
from .integrita import ArchivioSporco  # noqa: F401 — riesportato per server.py
from .settings import get_settings

log = logging.getLogger(__name__)


def _snapshot(path: Path) -> str:
    """Data di ultima modifica del file DB (ISO, UTC) — la 'freschezza' del DB:
    ogni risposta la porta, così una sessione sa quanto è vecchio ciò che legge."""
    try:
        return datetime.datetime.utcfromtimestamp(
            path.stat().st_mtime).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        return ""


def _db_dir() -> Path | None:
    s = get_settings()
    return Path(s.archive_db_dir) if s.archive_db_dir else None


def _scan_dir(db_dir: Path) -> dict[str, Path]:
    """Tutti i *.db nella dir → {nome-file-senza-estensione: path}."""
    if not db_dir.is_dir():
        return {}
    return {p.stem: p for p in sorted(db_dir.glob("*.db")) if p.is_file()}


def load_registry() -> dict[str, Path]:
    s = get_settings()
    out: dict[str, Path] = {}
    # 1. auto-discovery: ogni *.db nella dir compare SENZA restart.
    db_dir = _db_dir()
    if db_dir:
        out.update(_scan_dir(db_dir))
    # 2. ARCHIVE_DB_PATHS: override/aggiunta di path espliciti (fuori dalla dir).
    missing: list[str] = []
    for name, p in s.archive_db_paths.items():
        if p.exists() and p.is_file():
            out[name] = p
        else:
            missing.append(f"{name}={p}")
    if missing:
        # Un path DICHIARATO ma con file assente è un errore di config.
        log.warning("DB dichiarati ma non trovati sul volume: %s", ", ".join(missing))
    if not out:
        # Archivio vuoto = stato normale di un'installazione nuova, non un errore.
        log.info(
            "Archivio vuoto — aggiungi DB SQLite FTS5 in %s (o via ARCHIVE_DB_PATHS) "
            "per abilitare la ricerca.", db_dir or "(dir non impostata)",
        )
    return out


def _dir_sig() -> tuple:
    """Firma della dir DB (nome+mtime+size di ogni *.db) per rilevare cambi."""
    db_dir = _db_dir()
    if not db_dir or not db_dir.is_dir():
        return ()
    sig = []
    for p in sorted(db_dir.glob("*.db")):
        if p.is_file():
            st = p.stat()
            sig.append((p.name, st.st_mtime_ns, st.st_size))
    return tuple(sig)


_DBS: dict[str, Path] = load_registry()
_SIG: tuple = _dir_sig()


def _maybe_reload() -> None:
    """Ricarica la registry se la dir DB è cambiata (upload/ingest nuovo)."""
    if _dir_sig() != _SIG:
        log.info("dir DB cambiata — ricarico la registry")
        reload_registry()


_ANAGRAFICA: tuple[tuple, set[str]] | None = None      # (firma della dir, valori)


def valori_anagrafici() -> set[str]:
    """I valori dell'anagrafica presenti negli indici — da mascherare in USCITA.

    Sta QUI e non in `redazione.py` perché è l'unico posto che sa aprire i DB; la
    redazione resta pura e collaudabile senza filesystem.

    In CACHE sulla firma della dir (la stessa di `_maybe_reload`): la query girerebbe a
    ogni chiamata di ogni tool, e un presidio che costa a ogni richiesta è un presidio che
    prima o poi qualcuno spegne. La cache si invalida da sola quando un DB cambia — non
    per un timer, che scadrebbe nel momento sbagliato.
    """
    global _ANAGRAFICA
    _maybe_reload()
    sig = _dir_sig()
    if _ANAGRAFICA is not None and _ANAGRAFICA[0] == sig:
        return _ANAGRAFICA[1]
    from . import redazione
    valori: set[str] = set()
    for name in list(_DBS):
        try:
            conn = _open(name)
        except KeyError:
            continue
        try:
            valori |= redazione.valori_noti(conn)
        finally:
            conn.close()
    _ANAGRAFICA = (sig, valori)
    return valori


def available_dbs() -> list[str]:
    _maybe_reload()
    return sorted(_DBS)


def reload_registry() -> list[str]:
    """Ricarica la registry (scan della dir + ARCHIVE_DB_PATHS)."""
    global _DBS, _SIG
    _DBS = load_registry()
    _SIG = _dir_sig()
    return sorted(_DBS)


class _Persistente(sqlite3.Connection):
    """Una connessione che IGNORA `close()`, perché vive nella cache di `_open()`.

    🔴 Sembra magia e per questo sta scritto qui, dove uno la cerca. I nove chiamanti di
    `_open()` fanno tutti `finally: conn.close()`, ed era giusto finché ogni chiamata
    apriva la sua. Con la cache quel close ucciderebbe la connessione degli altri.

    🔑 **La scelta è fra togliere nove `finally` e rendere innocuo il close, e non è una
    questione di stile: è a quale errore ci si vuole esporre.** Togliere i nove funziona
    oggi e si rompe il giorno in cui qualcuna ne riscrive uno e rimette il close che ha
    visto negli altri otto — *un difetto che non dà errore subito, ma alla richiesta
    dopo, in un punto lontano da chi l'ha causato.* Qui invece il close resta scritto
    dove tutti se lo aspettano e semplicemente non fa danno.
    📌 La cache chiude davvero con `_chiudi_davvero()`. Chi vuole una connessione usa e
       getta non passa da `_open()`: apre con `sqlite3.connect` (è ciò che fa
       `integrita.verifica()`, e deve continuare a farlo — vedi `_open`).
    """

    def close(self) -> None:            # noqa: D102 — no-op VOLUTO, vedi docstring
        pass

    def _chiudi_davvero(self) -> None:
        super().close()


# 🔑 PER-THREAD, non globale: `sqlite3` rifiuta una connessione usata da un thread diverso
#   da quello che l'ha creata (`ProgrammingError`, misurato) e i 13 tool di `server.py` sono
#   SINCRONI — FastMCP li esegue sul thread pool, quindi la stessa `search` arriva ogni volta
#   su un thread potenzialmente diverso. Una cache globale esploderebbe alla seconda
#   richiesta. *Il modello di concorrenza del server non è un dettaglio del deploy: qui è la
#   cosa che sceglie la struttura dati.*
_LOCALE = threading.local()


def _cache_conn() -> dict[str, sqlite3.Connection]:
    """Le connessioni di QUESTO thread, svuotate se la dir DB è cambiata.

    Invalidare sulla firma non è prudenza: un DB rigenerato (ingest, restore) è un file
    NUOVO, e una connessione aperta sul vecchio inode continuerebbe a rispondere — con i
    dati di prima, senza errore. *Sarebbe la peggiore delle risposte: fresca all'aspetto
    e vecchia nei fatti.* È la stessa firma su cui si invalida `_ANAGRAFICA` poco sopra.
    """
    sig = _dir_sig()
    conns: dict[str, sqlite3.Connection] | None = getattr(_LOCALE, "conns", None)
    if conns is None or getattr(_LOCALE, "sig", None) != sig:
        for c in (conns or {}).values():
            try:
                c._chiudi_davvero()      # type: ignore[attr-defined]
            except sqlite3.Error:
                pass
        conns = {}
        _LOCALE.conns = conns
        _LOCALE.sig = sig
    return conns


def _open(name: str) -> sqlite3.Connection:
    """La connessione (PERSISTENTE) al DB `name`. Non chiuderla: ci pensa la cache.

    ⚠️ Il guadagno vero non è sul DB in chiaro — lì la riapertura costa 0,265 ms e questa
    cache vale 7,7x, che da sola non giustificherebbe il codice. Vale **3227x** sul DB
    cifrato (229 ms per apertura: PBKDF2 a 256.000 iterazioni), dove le nove aperture per
    richiesta × N DB diventerebbero **oltre un secondo di sola derivazione chiave**.
    ⇒ è il prerequisito dichiarato in `docs/CIFRATURA-ARCHIVIO.md`, non un'ottimizzazione.
    """
    if name not in _DBS:
        raise KeyError(f"DB '{name}' non disponibile. Disponibili: {available_dbs()}")
    percorso = Path(_DBS[name])
    # Costa un `exists()`: la ragione per cui può stare sul percorso caldo — e la
    # ragione per cui `verifica()` NON ci sta — è scritta in `integrita.py`.
    # 🖐️ RESTA A OGNI CHIAMATA, anche col riuso: è un presidio, non un costo di apertura.
    #    Un journal caldo può comparire mentre la connessione è già aperta — cachearlo
    #    insieme alla connessione toglierebbe il controllo proprio nel momento che lo
    #    giustifica.
    sporco = integrita.journal_caldo(percorso)
    if sporco is not None:
        raise ArchivioSporco(integrita.messaggio_sporco(name, sporco))
    conns = _cache_conn()
    conn = conns.get(name)
    if conn is not None:
        try:
            conn.execute("select 1")     # è ancora viva? costa microsecondi
            return conn
        except sqlite3.Error:
            # qualcuno l'ha chiusa davvero, o il file è sparito sotto: si riapre.
            # *Auto-riparante di proposito: il peggio che può fare questa cache è
            # tornare a costare quanto costava prima, mai far fallire una richiesta.*
            conns.pop(name, None)
    conn = sqlite3.connect(f"file:{percorso}?mode=ro", uri=True, factory=_Persistente)
    conn.row_factory = sqlite3.Row
    conns[name] = conn
    return conn


def _targets(db: str) -> list[str]:
    if not db:
        return list(_DBS)
    if db not in _DBS:
        raise KeyError(f"DB '{db}' non disponibile. Disponibili: {available_dbs()}")
    return [db]


# Budget della scansione MULTI-DB di check_integrity. Misurato il 28/08/2026:
# 12 quick_check su ~6 GB = MINUTI, il proxy MCP molla a ~30-60s, e le chiamate
# scadute restavano IN CODA lato server (cpu occupata, tool bloccati per tutti).
# Sotto budget si risponde con ciò che si è misurato + 'non_misurato' dichiarato
# per il resto. La chiamata su UN DB solo non ha budget: è il percorso mirato.
_INTEGRITA_BUDGET_S = 20.0


def integrita_archivi(db: str = "") -> dict[str, Any]:
    """Integrità (`ok`·`sporco`·`corrotto`·`non_misurabile`·`non_misurato`) —
    l'adattatore che risolve i nomi e delega alla logica pura di
    `integrita.verifica`, con un budget di tempo sulla forma multi-DB.

    🪦 Nato MORTO col tool: `server.py` registrava `check_integrity` e chiamava
       `db.integrita_archivi`, ma questa funzione non è mai stata scritta — i
       test guardavano la REGISTRAZIONE e la CHIAMATA, nessuno la DEFINIZIONE.
       In produzione: `AttributeError: module 'app.db' has no attribute
       'integrita_archivi'`, trovato dall'uso il 27/08/2026 (prima chiamata
       vera del tool, fase USO). Il presidio che manca sta ora in
       `test_tool_registrato.py::test_la_funzione_chiamata_ESISTE_in_db`.
    """
    _maybe_reload()
    nomi = _targets(db)
    out: dict[str, Any] = {}
    t0 = time.monotonic()
    for i, n in enumerate(nomi):
        if len(nomi) > 1 and time.monotonic() - t0 > _INTEGRITA_BUDGET_S:
            # Il resto NON si misura in silenzio: ogni DB saltato lo dichiara,
            # e dice come ottenerlo (la chiamata mirata non ha budget).
            for resto in nomi[i:]:
                out[resto] = {"esito": "non_misurato",
                              "dettaglio": (f"budget di {_INTEGRITA_BUDGET_S:.0f}s esaurito: "
                                            f"chiedi questo DB da solo (db_name='{resto}')")}
            break
        out.update(integrita.verifica({n: _DBS[n]}))
    return {"per_db": out}


def search(query: str, db: str = "", limit: int = 20, *, raw: bool = False,
           sort: str = "rank", since: str = "", until: str = "",
           project: str = "", speaker: str = "", voice: str = "",
           snippet_tokens: int = 32) -> list[dict[str, Any]]:
    """Search FTS5 nel DB indicato (o in TUTTI se db == "").

    Su più DB il `limit` è GLOBALE (non più per-DB) e i risultati sono fusi e
    ri-ordinati per `sort` prima del taglio — niente più concatenamento cieco.
    Ogni riga porta `db` e `snapshot` (freschezza del DB). Un errore di sintassi
    FTS5 solleva FtsSyntaxError (non restituisce lista vuota muta)."""
    _maybe_reload()  # pesca eventuali DB caricati/indicizzati dopo l'avvio
    collected: list[dict[str, Any]] = []
    for name in _targets(db):
        try:
            conn = _open(name)
        except KeyError:
            continue
        try:
            snap = _snapshot(_DBS[name])
            rows = fts.search_conn(
                conn, query, limit=limit, raw=raw, sort=sort, since=since,
                until=until, project=project, speaker=speaker, voice=voice,
                snippet_tokens=snippet_tokens)
            for r in rows:
                r["db"] = name
                r["snapshot"] = snap
            collected.extend(rows)
        except sqlite3.OperationalError as exc:
            # schema non conforme (DB estraneo nella dir): salta, non è fatale
            log.warning("DB %s schema error: %s", name, exc)
        finally:
            conn.close()
    # ordinamento GLOBALE + limit globale: bm25 crescente (più rilevante prima),
    # ts per newest/oldest. Fra DB diversi il bm25 non è perfettamente
    # comparabile (documentato), ma è meglio del concatenamento per-DB.
    if sort == "newest":
        collected.sort(key=lambda r: r.get("ts") or "", reverse=True)
    elif sort == "oldest":
        collected.sort(key=lambda r: r.get("ts") or "")
    else:
        collected.sort(key=lambda r: r.get("rank", 0.0))
    return collected[:limit]


def count(query: str, db: str = "", *, raw: bool = False, since: str = "",
          until: str = "", project: str = "", speaker: str = "",
          voice: str = "") -> dict[str, Any]:
    """Numero di match per DB e totale (non limitato) — abilita frequenze e
    prevalenze, impossibili con la sola `search` limitata."""
    _maybe_reload()
    per_db: dict[str, int] = {}
    warnings: list[str] = []
    for name in _targets(db):
        try:
            conn = _open(name)
        except KeyError:
            continue
        try:
            per_db[name] = fts.count_conn(
                conn, query, raw=raw, since=since, until=until, project=project,
                speaker=speaker, voice=voice)
            # canary: se un termine è collassato sul suo prefisso (`C++`→`C`), il
            # numero appena letto è un falso positivo — dillo, non lasciarlo muto.
            if not raw:
                warnings.extend(
                    f"[{name}] {w}" for w in fts.collapse_warnings_conn(conn, query))
        except sqlite3.OperationalError as exc:
            log.warning("DB %s schema error: %s", name, exc)
        finally:
            conn.close()
    out: dict[str, Any] = {"total": sum(per_db.values()), "per_db": per_db}
    if warnings:
        out["warnings"] = warnings
    return out


def check_term(term: str, db: str = "") -> dict[str, Any]:
    """Diagnostica il COLLASSO di un termine con caratteri speciali (`C++`, `C#`,
    `g++`, `.NET`, `F#`) — il canary di setaccio esposto come tool. Per ogni DB
    confronta count(term) con count(prefisso-alfanumerico): se coincidono, per
    quell'indice `term` == `prefix` e i risultati sono falsi positivi (la causa del
    falso ricordo dell'11/07). Chiede all'INDICE, non alla doc; si auto-tara sui DB
    ricostruiti con tokenchars (lì i conteggi divergono → collapsed=False)."""
    _maybe_reload()
    cands = fts.collapse_candidates(term)
    prefix = cands[0][1] if cands else ""
    per_db: dict[str, Any] = {}
    for name in _targets(db):
        try:
            conn = _open(name)
        except KeyError:
            continue
        try:
            n_term = fts.count_conn(conn, term)
            n_pref = fts.count_conn(conn, prefix) if prefix else n_term
            per_db[name] = {
                "count_term": n_term,
                "count_prefix": n_pref if prefix else None,
                "collapsed": bool(prefix and n_pref > 0 and n_term == n_pref),
            }
        except (sqlite3.OperationalError, FtsSyntaxError) as exc:
            log.warning("DB %s check_term error: %s", name, exc)
        finally:
            conn.close()
    return {"term": term, "prefix": prefix or None, "per_db": per_db}


def get_context(uuid: str, db: str = "", *, before: int = 3,
                after: int = 3) -> list[dict[str, Any]]:
    """I messaggi attorno a uno `uuid` col contenuto PIENO — supera il
    troncamento dello snippet di search. Cerca nel DB indicato o in tutti."""
    _maybe_reload()
    for name in _targets(db):
        try:
            conn = _open(name)
        except KeyError:
            continue
        try:
            ctx = fts.context_conn(conn, uuid, before=before, after=after)
            if ctx:
                snap = _snapshot(_DBS[name])
                for r in ctx:
                    r["db"] = name
                    r["snapshot"] = snap
                return ctx
        except sqlite3.OperationalError as exc:
            log.warning("DB %s schema error: %s", name, exc)
        finally:
            conn.close()
    return []


def get_conversation(uuid: str, db: str = "", *, limit: int = 200) -> list[dict[str, Any]]:
    """Il thread INTERO che contiene `uuid` (camminando parent_uuid), col contenuto
    pieno. Cerca il DB che contiene l'uuid, o in tutti."""
    _maybe_reload()
    for name in _targets(db):
        try:
            conn = _open(name)
        except KeyError:
            continue
        try:
            conv = fts.conversation_conn(conn, uuid, limit=limit)
            if conv:
                snap = _snapshot(_DBS[name])
                for r in conv:
                    r["db"] = name
                    r["snapshot"] = snap
                return conv
        except sqlite3.OperationalError as exc:
            log.warning("DB %s schema error: %s", name, exc)
        finally:
            conn.close()
    return []


def list_projects(db: str = "", *, top: int = 1000) -> list[dict[str, Any]]:
    """Le etichette `project` (con conteggi) per DB — per NAVIGARE l'archivio, non
    solo cercarlo. Su più DB i risultati portano `db` e sono ordinati per conteggio."""
    _maybe_reload()
    out: list[dict[str, Any]] = []
    for name in _targets(db):
        try:
            conn = _open(name)
        except KeyError:
            continue
        try:
            for r in fts.projects_conn(conn, top=top):
                r["db"] = name
                out.append(r)
        except sqlite3.OperationalError as exc:
            log.warning("DB %s schema error: %s", name, exc)
        finally:
            conn.close()
    out.sort(key=lambda r: r.get("rows", 0), reverse=True)
    return out


def archive_stats(db: str = "") -> list[dict[str, Any]]:
    """Istogramma temporale per ANNO, per DB — «quando» l'archivio è fitto, prima
    di cercare. Ogni riga porta `db`."""
    _maybe_reload()
    out: list[dict[str, Any]] = []
    for name in _targets(db):
        try:
            conn = _open(name)
        except KeyError:
            continue
        try:
            for r in fts.stats_by_period_conn(conn):
                r["db"] = name
                out.append(r)
        except sqlite3.OperationalError as exc:
            log.warning("DB %s schema error: %s", name, exc)
        finally:
            conn.close()
    return out


# Le statistiche di describe() sono scansioni COMPLETE (count, min/max ts,
# etichette DISTINCT) — misurate il 28/08/2026 sul vivo: 74,6 s a freddo e
# 53,9 s a caldo su 12 DB (5,7 GB), col proxy MCP che molla molto prima →
# ogni describe_databases rispondeva «connection lost». Ma le statistiche
# cambiano SOLO quando cambia il file: la chiave giusta è lo snapshot (mtime),
# che describe già espone. Il memo si invalida da solo a ogni upload o
# set_description — il gateway riscrive il file, l'mtime cambia.
_STATS_MEMO: dict[str, tuple[str, dict[str, Any]]] = {}


def describe() -> list[dict[str, Any]]:
    """Scheda di ogni DB: righe, intervallo temporale, n. etichette, snapshot
    (freschezza). Più ricca di list_databases (che resta list[str] per compat).

    Le statistiche sono memoizzate per snapshot: la scansione si paga una volta
    per versione del file, non a ogni chiamata (vedi _STATS_MEMO qui sopra)."""
    _maybe_reload()
    out: list[dict[str, Any]] = []
    for name in sorted(_DBS):
        snap = _snapshot(_DBS[name])
        ricordo = _STATS_MEMO.get(name)
        if ricordo is not None and ricordo[0] == snap:
            info = dict(ricordo[1])
        else:
            try:
                conn = _open(name)
            except KeyError:
                continue
            try:
                info = fts.db_stats_conn(conn)
                info["description"] = fts.meta_value_conn(conn, "description")
            except sqlite3.OperationalError:
                info = {"rows": 0, "oldest": "", "newest": "", "labels": 0, "description": ""}
            finally:
                conn.close()
            _STATS_MEMO[name] = (snap, dict(info))
        info["name"] = name
        info["snapshot"] = snap
        out.append(info)
    return out


def set_description(db: str, description: str) -> dict[str, Any]:
    """Imposta la descrizione di un archivio — **inoltrandola al gateway** (D9).

    Perché non scrive qui: questo container monta il volume degli archivi in
    SOLA LETTURA, per scelta deliberata (`compose.yaml`: «a scrivere i .db è il
    gateway, non questo servizio»). Fino al 20/07/2026 questa funzione apriva
    comunque il DB in scrittura e la docstring dichiarava «è l'UNICA scrittura
    ammessa da questo layer»: due affermazioni entrambe vere, ognuna nel suo
    file, che insieme mentivano — il tool prometteva una scrittura che il suo
    container non poteva fare, e chi lo chiamava riceveva
    `attempt to write a readonly database`.

    L'inoltro non è un'architettura nuova: la docstring di `set_meta` nel gateway
    dichiarava GIÀ «la usano l'upload (admin) e il tool MCP set_description».
    Era il pezzo che qualcuno aveva dato per esistente e che non era mai stato
    scritto.

    Il canale è quello di casa (`/internal/*` + `x-vps1777-internal`), sulla rete
    interna. Gli errori risalgono parlanti: chi chiama deve sapere *perché* non
    ha scritto, non ricevere un silenzio.
    """
    _maybe_reload()
    if db not in _DBS:
        raise KeyError(f"DB '{db}' non disponibile. Disponibili: {available_dbs()}")

    base = os.environ.get("GATEWAY_INTERNAL_BASE", "http://gateway:8080").rstrip("/")
    secret = _leggi_segreto()
    if not secret:
        # fail-closed e PARLANTE: senza segreto la scrittura non parte, e chi
        # chiama lo scopre subito invece di credere di aver scritto.
        raise RuntimeError(
            "set_description non configurata: manca il segreto interno "
            "(ARCHIVE_DESC_SECRET/_FILE) — la scrittura passa dal gateway."
        )
    req = urllib.request.Request(
        f"{base}/internal/archive/description",
        data=json.dumps({"db": db, "description": str(description)}).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-vps1777-archive-desc": secret},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            esito = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as ex:
        corpo = ex.read().decode("utf-8", "replace")[:200]
        raise RuntimeError(f"il gateway ha rifiutato la scrittura ({ex.code}): {corpo}") from ex
    except urllib.error.URLError as ex:
        raise RuntimeError(f"gateway non raggiungibile per la scrittura: {ex.reason}") from ex
    return {"db": db, "description": str(description), "via": "gateway", "esito": esito}


def _leggi_segreto() -> str:
    """Il segreto interno, da variabile o da file (come fa il gateway)."""
    v = os.environ.get("ARCHIVE_DESC_SECRET", "").strip()
    if v:
        return v
    p = os.environ.get("ARCHIVE_DESC_SECRET_FILE", "").strip()
    if p:
        try:
            return Path(p).read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    return ""

