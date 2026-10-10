"""
app/server.py — FastMCP wrapper sopra core.py (servizio nb1777-mcp).

Espone le funzioni di `core.py` come tool MCP (39), più le rotte custom:
gli endpoint `/internal/*` (H6) e `/health`. In compose ascolta su
0.0.0.0:8003 sulla rete interna `backend`, mai pubblicata: da Internet si
arriva solo attraverso il gateway (OAuth + path-secret), che rifiuta i
sotto-path `internal/`. Il bot lo chiama direttamente sulla rete interna.

L'autenticazione dei TOOL è del gateway. Gli endpoint `/internal/*` invece
vogliono il segreto condiviso (`GATEWAY_SECRET_FILE`, header
`x-vps1777-internal`): senza segreto configurato negano tutto (fail-closed).

Avvio (è l'ENTRYPOINT dell'immagine, via app/__main__.py):
    python -m app                           # streamable-http su :8003
    NB1777_TRANSPORT=stdio python -m app    # stdio (per dev)

Variabili d'ambiente:
    NB1777_HOST       (default 127.0.0.1; compose.yaml mette 0.0.0.0)
    NB1777_PORT       (default 8003)
    NB1777_TRANSPORT  (default streamable-http; alt: stdio, sse)
"""
from __future__ import annotations

import asyncio
import hmac
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from . import canonical, core, memoria, nlm_profile, sonda
from . import conferma as _gettoni
from .settings import get_settings

log = logging.getLogger("nb1777-mcp.server")


HOST = os.environ.get("NB1777_HOST", "127.0.0.1")
PORT = int(os.environ.get("NB1777_PORT", "8003"))
TRANSPORT = os.environ.get("NB1777_TRANSPORT", "streamable-http")

# Stateless HTTP: NO session_id required tra initialize/call.
# Permette chiamate dirette tools/call senza initialize preventivo
# (necessario per la Mini App + claude.ai che chiamano tool one-shot).
mcp = FastMCP(
    "nb1777",
    host=HOST,
    port=PORT,
    stateless_http=True,
    # Canale involontario del canonico (issue #30, Veicolo A): le instructions
    # viaggiano nella risposta di initialize. Testo STATICO → non dipende
    # dall'auth nlm al boot; il numero di versione vivo lo dà il tool `canonico`.
    instructions=canonical.declaration_text(),
    transport_security=TransportSecuritySettings(
        # DNS-rebinding protection OFF: il server sta dietro il gateway su rete
        # Docker interna (non esposto ai browser). Il gateway inoltra
        # `Host: nb1777-mcp:8003`, che con la protezione attiva dava 421
        # (Misdirected Request). Coerente con archive-mcp. La sicurezza è al
        # gateway (OAuth + path-secret), non qui.
        enable_dns_rebinding_protection=False,
    ),
)


# ── S10 (05/10/2026): titolo e annotazioni di OGNI tool, in un posto solo ───────────────
# Il client li usa per raggruppare i permessi (claude.ai) e per sapere cosa scrive. Quasi
# tutto parla con Google (openWorld). `destructiveHint` va scritto anche quando è False:
# il default della spec è True. Un tool che manca da questa tabella non si registra
# (KeyError all'import): `test_annotazioni` lo dice prima.
_LEGGE = {"readOnlyHint": True, "openWorldHint": True}
_AGGIUNGE = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True}
_RINOMINA = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True,
             "openWorldHint": True}
_CANCELLA = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True,
             "openWorldHint": True}
ANNOTAZIONI: dict[str, tuple[str, dict[str, bool]]] = {
    "nb_list": ("Elenca i notebook", _LEGGE),
    "nb_get": ("Leggi un notebook", _LEGGE),
    "nb_create": ("Crea un notebook", _AGGIUNGE),
    "nb_rename": ("Rinomina un notebook", _RINOMINA),
    "nb_delete": ("Cancella un notebook", _CANCELLA),
    "nb_describe": ("Descrivi un notebook", _LEGGE),
    "source_list": ("Elenca le fonti", _LEGGE),
    "source_add_url": ("Aggiungi una fonte da URL", _AGGIUNGE),
    "source_add_text": ("Aggiungi una fonte di testo", _AGGIUNGE),
    "source_add_file": ("Aggiungi una fonte da file", _AGGIUNGE),
    "source_add_youtube": ("Aggiungi un video YouTube", _AGGIUNGE),
    "source_add_drive": ("Aggiungi una fonte da Drive", _AGGIUNGE),
    "source_delete": ("Cancella una fonte", _CANCELLA),
    "source_get_content": ("Leggi il testo di una fonte", _LEGGE),
    "source_rename": ("Rinomina una fonte", _RINOMINA),
    "notebook_query": ("Chiedi al notebook", _LEGGE),
    "notebook_query_esito": ("Ritira una risposta in corso", _LEGGE),
    "studio_create_audio": ("Crea un audio", _AGGIUNGE),
    "studio_create_video": ("Crea un video", _AGGIUNGE),
    "studio_create_slides": ("Crea le slide", _AGGIUNGE),
    "studio_create_mindmap": ("Crea una mappa mentale", _AGGIUNGE),
    "studio_create_infographic": ("Crea un'infografica", _AGGIUNGE),
    "studio_create_data_table": ("Crea una tabella", _AGGIUNGE),
    "studio_create_report": ("Crea un report", _AGGIUNGE),
    "studio_create_quiz": ("Crea un quiz", _AGGIUNGE),
    "studio_create_flashcards": ("Crea le flashcard", _AGGIUNGE),
    "studio_create_all_9": ("Crea tutti e nove gli artefatti", _AGGIUNGE),
    "studio_list": ("Elenca gli artefatti", _LEGGE),
    "studio_status": ("Stato di un artefatto", _LEGGE),
    "studio_wait": ("Aspetta un artefatto", _LEGGE),
    "studio_delete": ("Cancella un artefatto", _CANCELLA),
    "studio_rename": ("Rinomina un artefatto", _RINOMINA),
    # scrive un file sul volume degli artefatti: non è sola lettura
    "studio_download": ("Scarica un artefatto", _AGGIUNGE),
    "studio_export_to_docs": ("Esporta in Google Docs", _AGGIUNGE),
    "studio_export_to_sheets": ("Esporta in Google Sheets", _AGGIUNGE),
    "doctor": ("Diagnostica", _LEGGE),
    "canonico": ("Il canonico della memoria", {"readOnlyHint": True, "openWorldHint": False}),
    # manda un ping su Telegram quando trova un disallineamento: non è sola lettura
    "memoria_check": ("Controlla la versione della memoria",
                      {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True}),
    "memoria_ack": ("Registra l'aggiornamento della memoria",
                    {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True,
                     "openWorldHint": False}),
}
_tool_originale = mcp.tool


def _tool_annotato(*args, **kw):
    def applica(fn):
        titolo, hint = ANNOTAZIONI[fn.__name__]
        return _tool_originale(*args, title=titolo,
                               annotations=ToolAnnotations(title=titolo, **hint), **kw)(fn)
    return applica


mcp.tool = _tool_annotato                                # type: ignore[method-assign]


# Stato auth NotebookLM.
# Se il file AUTH_PENDING.flag esiste, l'auth nlm non è caricata: ogni tool
# ritorna un errore strutturato con istruzioni per l'admin panel /admin/nlm.
NLM_CFG = Path.home() / ".notebooklm-mcp-cli"
AUTH_FLAG = NLM_CFG / "AUTH_PENDING.flag"
# nlm (dalla 0.7, verificato fino alla 0.12): l'auth è il profilo profiles/default/cookies.json (non auth.json)
AUTH_COOKIES = NLM_CFG / "profiles" / "default" / "cookies.json"


def _check_auth_or_raise() -> None:
    """Solleva RuntimeError se auth nlm non disponibile."""
    if AUTH_FLAG.exists() or not AUTH_COOKIES.exists():
        raise RuntimeError(
            "Auth NotebookLM mancante. Sul TUO PC: `uv tool install "
            "notebooklm-mcp-cli --python 3.12 && nlm login`, poi "
            "`cd ~/.notebooklm-mcp-cli && tar czf nlm-profile.tgz profiles/default` "
            "e carica il tar.gz su /admin/nlm del gateway."
        )


# Helper: incapsula chiamate sync di core.py in un thread per non bloccare
# l'event loop di FastMCP (nlm può prendere decine di secondi).
# Verifica auth nlm prima di lanciare il thread → fail-fast con messaggio chiaro.
async def _esito(nome: str, coro):
    """Tre esiti, tre righe di log — non due (28/09). `ok`: il tool ha risposto.
    `fallito`: il tool ha sollevato un errore (già senza contenuti, H41; qui troncato).
    `interrotto`: il CLIENT ha chiuso la richiesta prima della risposta. Il terzo è quello
    che ha fatto nascere tutto: da claude.ai `notebook_query` dava «MCP tool call failed» a
    ~30 s e il server non registrava niente, perché la chiusura non è un'eccezione del tool
    (è un CancelledError) e il gateway vede solo il 200 dello streaming."""
    t0 = time.monotonic()
    try:
        r = await coro
    except asyncio.CancelledError:
        log.warning("tool %s interrotto dopo %.1fs: il client ha chiuso la richiesta",
                    nome, time.monotonic() - t0)
        raise
    except Exception as e:
        log.warning("tool %s fallito dopo %.1fs: %s: %s", nome,
                    time.monotonic() - t0, type(e).__name__, str(e)[:300])
        raise
    log.info("tool %s ok in %.1fs", nome, time.monotonic() - t0)
    return r


async def _aio(fn, *args, **kwargs):
    async def _corpo():
        _check_auth_or_raise()
        return await asyncio.to_thread(fn, *args, **kwargs)
    return await _esito(getattr(fn, "__name__", "?"), _corpo())


# ============================================================
# ENDPOINT INTERNI — il profilo NotebookLM (H6)
# ============================================================
# Fra i servizi in esercizio, nb1777-mcp è l'unico che monta il volume dei cookie
# Google — ed è l'unico che ci scrive. Il gateway (l'unico esposto su Internet) e
# il bot non lo montano più: chiedono qui. Così un gateway compromesso non può né
# leggere né riscrivere la sessione Google. (Lo montano in sola lettura anche il
# backup, che li cifra, e il check settimanale delle scadenze: SECURITY.md.)
#
# Questi endpoint NON sono raggiungibili dall'esterno: il proxy del gateway
# rifiuta i sotto-path `internal/` (vedi gateway/app/proxy.py) e la rete
# `backend` è `internal: true`. In più chiedono un segreto condiviso — così
# nemmeno un container vicino compromesso (archive-mcp, bot) può scriverci.
# Fail-closed: senza segreto configurato si nega tutto.

def _internal_ok(request: "Request") -> bool:
    secret = get_settings().effective_gateway_secret
    if not secret:                       # non configurato → nega (fail-closed)
        return False
    got = request.headers.get("x-vps1777-internal", "")
    return hmac.compare_digest(got, secret)


@mcp.custom_route("/internal/nlm/status", methods=["GET"])
async def internal_nlm_status(request: "Request") -> "JSONResponse":
    """Stato del profilo, senza esporre i cookie: {ok, has_cookies, pending, sonda, sessione}.
    `ok` dice solo che il file c'è; `sonda` ({quando, esito} o null) dice se l'ultima
    chiamata vera a Google è riuscita (S8); `sessione` ({nata_il, ultimo_refresh} o null)
    è l'età vera della sessione (S9)."""
    if not _internal_ok(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    home = Path(get_settings().nlm_home)
    stato = nlm_profile.profile_status(home)
    stato["sonda"] = await asyncio.to_thread(sonda.ultimo)
    stato["sessione"] = await asyncio.to_thread(nlm_profile.eta_sessione, home)
    return JSONResponse(stato)


@mcp.custom_route("/internal/nlm/artifacts", methods=["GET"])
async def internal_nlm_artifacts(request: "Request") -> "JSONResponse":
    """Elenco degli artefatti scaricati: [{name, bytes, mtime}]. Nessun contenuto."""
    if not _internal_ok(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    return JSONResponse({"artifacts": await asyncio.to_thread(core.artifact_list)})


@mcp.custom_route("/internal/nlm/artifact", methods=["GET"])
async def internal_nlm_artifact(request: "Request") -> "Response":
    """Serve UN artefatto (`?name=`). È la via che porta il file fuori dal container.

    Sta qui e non nel gateway per la stessa ragione di /internal/nlm/profile (H6): il
    volume lo monta solo questo servizio. Il gateway INOLTRA — non monta niente, e
    resta senza accesso al filesystem che contiene i cookie.

    `core.artifact_path` risolve il nome DENTRO la directory artefatti e alza se esce:
    l'unico input che arriva da fuori è quel nome.
    """
    if not _internal_ok(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    name = request.query_params.get("name", "")
    if not name:
        return JSONResponse({"error": "missing_name"}, status_code=400)
    try:
        p = await asyncio.to_thread(core.artifact_path, name)
    except core.NLMError as exc:
        # 404 e non 400: dall'esterno «nome non ammesso» e «non c'è» non devono
        # distinguersi, o l'errore diventa un oracolo su cosa esiste nel container.
        return JSONResponse({"error": "not_found", "reason": str(exc)}, status_code=404)
    return FileResponse(p, filename=p.name, media_type="application/octet-stream")


@mcp.custom_route("/internal/nlm/profile", methods=["POST"])
async def internal_nlm_profile(request: "Request") -> "JSONResponse":
    """Installa il profilo da un tar.gz (body raw). Un tar invalido non tocca quello buono."""
    if not _internal_ok(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    body = await request.body()
    try:
        n = await asyncio.to_thread(
            nlm_profile.install_profile, body, Path(get_settings().nlm_home)
        )
    except ValueError as exc:            # messaggio pensato per l'utente
        return JSONResponse({"error": "invalid_profile", "reason": str(exc)}, status_code=400)
    except OSError as exc:
        return JSONResponse({"error": "write_failed", "reason": str(exc)}, status_code=500)
    return JSONResponse({"files": n})


# ============================================================
# NOTEBOOK
# ============================================================

@mcp.tool()
async def nb_list() -> list[dict]:
    """Lista tutti i notebook visibili al profilo attivo."""
    return await _aio(core.nb_list)


@mcp.tool()
async def nb_get(notebook_id: str) -> dict:
    """Dettagli di un singolo notebook."""
    return await _aio(core.nb_get, notebook_id)


@mcp.tool()
async def nb_create(title: str) -> str:
    """Crea un nuovo notebook. Ritorna l'ID."""
    return await _aio(core.nb_create, title)


@mcp.tool()
async def nb_rename(notebook_id: str, new_title: str) -> str:
    """Rinomina un notebook."""
    await _aio(core.nb_rename, notebook_id, new_title)
    return "ok"



def _anteprima(azione: str, ids: tuple[str, ...], cosa: dict) -> dict:
    """La prima delle due chiamate di una cancellazione: cosa sparirebbe, e il gettone."""
    return {"cancellato": False, "anteprima": cosa,
            "conferma": _gettoni.gettone(azione, *ids), "scade_tra_s": _gettoni.DURATA_S,
            "come": f"richiama {azione} con gli stessi id e conferma=<il gettone>"}


def _conferma_o_errore(valore: str, azione: str, *ids: str) -> None:
    errore = _gettoni.verifica(valore, azione, *ids)
    if errore:
        raise ValueError(errore)


@mcp.tool()
async def nb_delete(notebook_id: str, conferma: str = "") -> dict:
    """Cancella un notebook in modo permanente, con tutte le sue fonti e gli artefatti.

    Due tempi (05/10/2026): senza `conferma` NON cancella, restituisce `anteprima` (cosa
    sparirebbe) e un gettone `conferma` valido 5 minuti; richiamalo con gli stessi id e
    `conferma=<gettone>` per cancellare. Prima di confermare, mostra l'anteprima a chi te
    l'ha chiesto. Ritorna {cancellato, anteprima?, conferma?, scade_tra_s?}."""
    if not conferma:
        nb = await _aio(core.nb_get, notebook_id)
        sorgenti = nb.get("sources")
        return _anteprima("nb_delete", (notebook_id,), {
            "notebook_id": notebook_id, "title": nb.get("title"),
            "fonti": len(sorgenti) if isinstance(sorgenti, list) else nb.get("source_count")})
    _conferma_o_errore(conferma, "nb_delete", notebook_id)
    await _aio(core.nb_delete, notebook_id)
    return {"cancellato": True, "notebook_id": notebook_id}


@mcp.tool()
async def nb_describe(notebook_id: str) -> str:
    """Riassunto AI-generated del notebook (testo)."""
    return await _aio(core.nb_describe, notebook_id)


# ============================================================
# SOURCE
# ============================================================

@mcp.tool()
async def source_list(notebook_id: str) -> list[dict]:
    """Lista tutte le fonti di un notebook."""
    return await _aio(core.source_list, notebook_id)


@mcp.tool()
async def source_add_url(notebook_id: str, url: str, title: Optional[str] = None,
                         wait: bool = True) -> str:
    """Aggiunge una URL come fonte. Ritorna il source_id."""
    return await _aio(core.source_add_url, notebook_id, url, title=title, wait=wait)


@mcp.tool()
async def source_add_text(notebook_id: str, text: str, title: str, wait: bool = True) -> str:
    """Aggiunge testo libero come fonte (richiede titolo)."""
    return await _aio(core.source_add_text, notebook_id, text, title, wait=wait)


@mcp.tool()
async def source_add_file(notebook_id: str, file_path: str,
                          title: Optional[str] = None, wait: bool = True) -> str:
    """Carica un file come fonte (PDF/txt/md...).

    `file_path` è un path del filesystem del SERVER (il container nb1777-mcp),
    non di chi chiama: un file che sta solo sul tuo disco qui non esiste (è la
    stessa sorpresa di studio_download, al contrario). Per testo che hai già in
    mano usa source_add_text."""
    return await _aio(core.source_add_file, notebook_id, file_path, title=title, wait=wait)


@mcp.tool()
async def source_add_youtube(notebook_id: str, url: str, wait: bool = True) -> str:
    """Aggiunge un video YouTube come fonte."""
    return await _aio(core.source_add_youtube, notebook_id, url, wait=wait)


@mcp.tool()
async def source_add_drive(notebook_id: str, document_id: str,
                           doc_type: str = "doc", wait: bool = True) -> str:
    """Collega un Google Drive document_id come fonte. doc_type: doc|slides|sheets|pdf"""
    return await _aio(core.source_add_drive, notebook_id, document_id,
                      doc_type=doc_type, wait=wait)


@mcp.tool()
async def source_delete(notebook_id: str, source_id: str, conferma: str = "") -> dict:
    """Elimina una fonte (irreversibile).

    Due tempi (05/10/2026): senza `conferma` NON cancella, restituisce `anteprima` (cosa
    sparirebbe) e un gettone `conferma` valido 5 minuti; richiamalo con gli stessi id e
    `conferma=<gettone>` per cancellare. Prima di confermare, mostra l'anteprima a chi te
    l'ha chiesto. Ritorna {cancellato, anteprima?, conferma?, scade_tra_s?}."""
    if not conferma:
        fonti = await _aio(core.source_list, notebook_id)
        voce = next((f for f in fonti if core._source_id_of(f) == source_id), None)
        if voce is None:
            raise ValueError(f"la fonte {source_id} non è nel notebook {notebook_id}")
        return _anteprima("source_delete", (notebook_id, source_id), voce)
    _conferma_o_errore(conferma, "source_delete", notebook_id, source_id)
    await _aio(core.source_delete, notebook_id, source_id)
    return {"cancellato": True, "source_id": source_id}


@mcp.tool()
async def source_get_content(notebook_id: str, source_id: str) -> str:
    """Estrae il contenuto raw di una fonte (no AI)."""
    return await _aio(core.source_get_content, notebook_id, source_id)


@mcp.tool()
async def source_rename(notebook_id: str, source_id: str, new_title: str) -> str:
    """Rinomina una fonte. Qui il notebook_id serve davvero (la CLI lo vuole
    come opzione obbligatoria). Ritorna "ok"."""
    await _aio(core.source_rename, notebook_id, source_id, new_title)
    return "ok"


# ============================================================
# CHAT
# ============================================================

# Le query lasciate indietro dal client: query_id → (task, nascita). Vivono nel processo
# (stateless_http tiene un solo event loop); un riavvio le perde, e l'esito lo dice.
_QUERY_IN_CORSO: dict[str, tuple["asyncio.Task", float]] = {}
# La stessa domanda sullo stesso notebook → la stessa query (28/09). Un client con lo schema
# vecchio dei tool non vede notebook_query_esito: rilanciare la domanda è il suo modo di
# ritirarla, e senza questo indice ne farebbe partire un'altra (e ripartirebbe da zero).
_QUERY_PER_DOMANDA: dict[tuple, str] = {}
_QUERY_TTL = 1800.0           # una risposta non ritirata in 30 minuti si butta
ATTESA_MAX_TETTO = 270.0      # come il timeout del subprocess di core.notebook_query


def _attesa(attesa_max: float) -> float:
    return min(max(float(attesa_max), 1.0), ATTESA_MAX_TETTO)


def _pulisci_query() -> None:
    ora = time.monotonic()
    for qid, (task, nata) in list(_QUERY_IN_CORSO.items()):
        if task.done() and ora - nata > _QUERY_TTL:
            _QUERY_IN_CORSO.pop(qid, None)
    for chiave, qid in list(_QUERY_PER_DOMANDA.items()):
        if qid not in _QUERY_IN_CORSO:
            _QUERY_PER_DOMANDA.pop(chiave, None)


async def _aspetta_query(qid: str, task: "asyncio.Task", attesa_max: float) -> dict:
    try:
        r = await asyncio.wait_for(asyncio.shield(task), _attesa(attesa_max))
    except asyncio.TimeoutError:
        _QUERY_IN_CORSO[qid] = (task, _QUERY_IN_CORSO.get(qid, (task, time.monotonic()))[1])
        return {"stato": "in_corso", "query_id": qid,
                "nota": (f"NotebookLM non ha ancora risposto dopo {_attesa(attesa_max):.0f} s: "
                         "la query continua sul server. Chiama notebook_query_esito(query_id) "
                         "per ritirarla, oppure rilancia notebook_query con la STESSA domanda "
                         "sullo stesso notebook: si aggancia a questa invece di ripartire (è la "
                         "via per i client che non vedono ancora notebook_query_esito). Può "
                         "servire più di un giro: su un notebook grande NotebookLM arriva a "
                         "qualche minuto.")}
    _QUERY_IN_CORSO.pop(qid, None)
    _pulisci_query()
    return r


@mcp.tool()
async def notebook_query(notebook_id: str, question: str,
                         source_ids: Optional[list[str]] = None,
                         conversation_id: Optional[str] = None,
                         verbose: bool = False,
                         attesa_max: float = 25.0) -> dict:
    """Pone una domanda alla chat del notebook. Ritorna {answer, references,
    sources_used} in PROIEZIONE COMPATTA (#275): le references portano
    un'anteprima, il testo citato integrale arriva con verbose=True.
    Se l'answer contiene paragrafi SENZA marcatori [n], la risposta porta
    `senza_citazioni` (conteggio + anteprime) e una `nota`: quei paragrafi
    sono generati dal modello, non letti dalle fonti — ipotesi, non fatti.

    ⏱️ NotebookLM risponde in 20 s come in 2 minuti, e alcuni client chiudono la
    chiamata verso i 30 s («MCP tool call failed»). Perciò si aspetta al massimo
    `attesa_max` secondi (default 25, tetto 270): se la risposta non c'è ancora, torna
    {stato: "in_corso", query_id, nota} e la query CONTINUA sul server. Ritirala con
    notebook_query_esito(query_id), oppure RILANCIA la stessa domanda sullo stesso notebook,
    con gli stessi source_ids, conversation_id e verbose: si aggancia alla query in corso (o
    finita e non ritirata) invece di farne partire un'altra. Un client che sa aspettare
    passa attesa_max=270."""
    async def _corpo():
        _check_auth_or_raise()
        _pulisci_query()
        chiave = (notebook_id, question, tuple(source_ids or ()), conversation_id or "",
                  bool(verbose))
        qid = _QUERY_PER_DOMANDA.get(chiave)
        if qid is None or qid not in _QUERY_IN_CORSO:
            task = asyncio.create_task(asyncio.to_thread(
                core.notebook_query, notebook_id, question, source_ids=source_ids,
                conversation_id=conversation_id, verbose=verbose))
            qid = uuid.uuid4().hex[:12]
            _QUERY_IN_CORSO[qid] = (task, time.monotonic())
            _QUERY_PER_DOMANDA[chiave] = qid
        try:
            return await _aspetta_query(qid, _QUERY_IN_CORSO[qid][0], attesa_max)
        except Exception:
            _QUERY_IN_CORSO.pop(qid, None)
            _pulisci_query()
            raise
    return await _esito("notebook_query", _corpo())


@mcp.tool()
async def notebook_query_esito(query_id: str, attesa_max: float = 25.0) -> dict:
    """Ritira una notebook_query che era tornata `in_corso`. Aspetta al massimo
    `attesa_max` secondi (default 25, minimo 1, tetto 270): ritorna la risposta (stessa forma di
    notebook_query), di nuovo {stato: "in_corso", …} se NotebookLM non ha ancora finito,
    o l'errore della query. Un query_id sconosciuto è un errore: già ritirato, scaduto
    (30 minuti) o perso a un riavvio del servizio — rilancia la domanda."""
    async def _corpo():
        voce = _QUERY_IN_CORSO.get(query_id)
        if voce is None:
            raise ValueError(f"query_id {query_id!r} sconosciuto: già ritirato, scaduto "
                             "(30 minuti) o perso a un riavvio del servizio. Rilancia notebook_query.")
        try:
            return await _aspetta_query(query_id, voce[0], attesa_max)
        except Exception:
            _QUERY_IN_CORSO.pop(query_id, None)
            raise
    return await _esito("notebook_query_esito", _corpo())


# ============================================================
# STUDIO — create (9 tipi)
# ============================================================

@mcp.tool()
async def studio_create_audio(notebook_id: str,
                              format: str = "deep_dive",
                              length: str = "default",
                              language: str = "it",
                              focus: Optional[str] = None,
                              source_ids: Optional[list[str]] = None) -> str:
    """Crea Audio Overview (podcast). format: deep_dive|brief|critique|debate. RATE-LIMIT free tier."""
    return await _aio(core.studio_create_audio, notebook_id, format=format, length=length,
                      language=language, focus=focus, source_ids=source_ids)


@mcp.tool()
async def studio_create_video(notebook_id: str,
                              format: str = "explainer",
                              style: str = "auto_select",
                              style_prompt: Optional[str] = None,
                              focus: Optional[str] = None,
                              language: str = "it",
                              source_ids: Optional[list[str]] = None) -> str:
    """Crea Video Overview. format: explainer|brief|cinematic."""
    return await _aio(core.studio_create_video, notebook_id, format=format, style=style,
                      style_prompt=style_prompt, focus=focus, language=language,
                      source_ids=source_ids)


@mcp.tool()
async def studio_create_slides(notebook_id: str,
                               format: str = "detailed_deck",
                               length: str = "default",
                               focus: Optional[str] = None,
                               language: str = "it",
                               source_ids: Optional[list[str]] = None) -> str:
    """Crea Slide Deck. format: detailed_deck|presenter_slides. length: short|default."""
    return await _aio(core.studio_create_slides, notebook_id, format=format, length=length,
                      focus=focus, language=language, source_ids=source_ids)


@mcp.tool()
async def studio_create_mindmap(notebook_id: str,
                                title: str = "Mind Map",
                                source_ids: Optional[list[str]] = None) -> str:
    """Crea Mind Map. NOTA: titolo/lingua/focus ignorati dal motore."""
    return await _aio(core.studio_create_mindmap, notebook_id, title=title, source_ids=source_ids)


@mcp.tool()
async def studio_create_infographic(notebook_id: str,
                                    orientation: str = "landscape",
                                    detail: str = "standard",
                                    style: str = "auto_select",
                                    focus: Optional[str] = None,
                                    language: str = "it",
                                    source_ids: Optional[list[str]] = None) -> str:
    """Crea Infographic (PNG). orientation: landscape|portrait|square."""
    return await _aio(core.studio_create_infographic, notebook_id,
                      orientation=orientation, detail=detail, style=style,
                      focus=focus, language=language, source_ids=source_ids)


@mcp.tool()
async def studio_create_data_table(notebook_id: str, description: str,
                                   language: str = "it",
                                   source_ids: Optional[list[str]] = None) -> str:
    """Crea Data Table. `description` OBBLIGATORIA (descrive le colonne)."""
    return await _aio(core.studio_create_data_table, notebook_id, description,
                      language=language, source_ids=source_ids)


@mcp.tool()
async def studio_create_report(notebook_id: str,
                               format: str = "Briefing Doc",
                               prompt: Optional[str] = None,
                               language: str = "it",
                               source_ids: Optional[list[str]] = None) -> str:
    """Crea Report. format: 'Briefing Doc'|'Study Guide'|'Blog Post'|'Create Your Own'."""
    return await _aio(core.studio_create_report, notebook_id, format=format, prompt=prompt,
                      language=language, source_ids=source_ids)


@mcp.tool()
async def studio_create_quiz(notebook_id: str,
                             count: int = 10,
                             difficulty: int = 2,
                             focus: Optional[str] = None,
                             source_ids: Optional[list[str]] = None) -> str:
    """Crea Quiz. difficulty 1=easy ... 5=hard."""
    return await _aio(core.studio_create_quiz, notebook_id, count=count, difficulty=difficulty,
                      focus=focus, source_ids=source_ids)


@mcp.tool()
async def studio_create_flashcards(notebook_id: str,
                                   difficulty: str = "medium",
                                   focus: Optional[str] = None,
                                   source_ids: Optional[list[str]] = None) -> str:
    """Crea Flashcards. difficulty: easy|medium|hard."""
    return await _aio(core.studio_create_flashcards, notebook_id, difficulty=difficulty,
                      focus=focus, source_ids=source_ids)


@mcp.tool()
async def studio_create_all_9(notebook_id: str,
                              source_ids: Optional[list[str]] = None,
                              language: str = "it",
                              data_table_description: str = "Tabella con: Concetto, Definizione, Citazione dalla fonte.",
                              report_format: str = "Study Guide",
                              wait: bool = False,
                              skip: Optional[list[str]] = None) -> dict:
    """Crea tutti e 9 gli artefatti in sequenza. Ritorna {tipo: esito}, dove
    esito è l'artifact_id, "ERROR: <motivo>" se quel tipo è fallito (gli altri
    proseguono) o "SKIPPED" se era in `skip`.

    skip: tipi da saltare, es. ["audio"] per evitare il rate-limit.
    wait: False (default) lancia e ritorna subito gli id, la generazione
          continua su NotebookLM; True attende ogni artefatto (fino a 900s)
          prima di lanciare il successivo."""
    return await _aio(core.studio_create_all_9, notebook_id, source_ids=source_ids,
                      language=language, data_table_description=data_table_description,
                      report_format=report_format, wait=wait,
                      skip=tuple(skip or ()))


# ============================================================
# STUDIO — status / wait / delete / rename
# ============================================================

@mcp.tool()
async def studio_list(notebook_id: str, verbose: bool = False) -> list[dict]:
    """Lista gli artefatti studio di un notebook.

    Default COMPATTO: per ognuno solo id/type/status/label (i primi 80 char del
    focus). verbose=True restituisce il JSON pieno col focus intero (4-6 KB per
    artefatto) — usalo solo se ti serve davvero il dettaglio."""
    return await _aio(core.studio_list, notebook_id, verbose=verbose)


@mcp.tool()
async def studio_status(notebook_id: str, artifact_id: str, verbose: bool = False) -> dict:
    """Stato di un singolo artefatto (id/type/status/label). verbose=True per
    l'artefatto pieno col focus."""
    return await _aio(core.studio_status, notebook_id, artifact_id, verbose=verbose)


@mcp.tool()
async def studio_wait(notebook_id: str, artifact_id: str,
                      poll_interval: float = 5.0, timeout: float = 25.0) -> dict:
    """Aspetta che un artefatto studio sia pronto, al massimo `timeout` secondi (tetto 25).
    Se non è pronto restituisce l'ultimo stato con `in_corso: true`: richiamalo. Il tetto
    esiste perché da claude.ai una chiamata oltre ~30 s cade."""
    return await _aio(core.studio_wait, notebook_id, artifact_id,
                      poll_interval=poll_interval, timeout=min(float(timeout), 25.0),
                      restituisci_al_tetto=True)


@mcp.tool()
async def studio_delete(notebook_id: str, artifact_id: str, conferma: str = "") -> dict:
    """Cancella un artefatto studio (irreversibile).

    Due tempi (05/10/2026): senza `conferma` NON cancella, restituisce `anteprima` (cosa
    sparirebbe) e un gettone `conferma` valido 5 minuti; richiamalo con gli stessi id e
    `conferma=<gettone>` per cancellare. Prima di confermare, mostra l'anteprima a chi te
    l'ha chiesto. Ritorna {cancellato, anteprima?, conferma?, scade_tra_s?}."""
    if not conferma:
        arts = await _aio(core.studio_list, notebook_id)
        voce = next((a for a in arts if a.get("id") == artifact_id), None)
        if voce is None:
            raise ValueError(f"l'artefatto {artifact_id} non è nel notebook {notebook_id}")
        return _anteprima("studio_delete", (notebook_id, artifact_id), voce)
    _conferma_o_errore(conferma, "studio_delete", notebook_id, artifact_id)
    await _aio(core.studio_delete, notebook_id, artifact_id)
    return {"cancellato": True, "artifact_id": artifact_id}


@mcp.tool()
async def studio_rename(notebook_id: str, artifact_id: str, new_title: str) -> str:
    """Rinomina un artefatto studio. L'artifact_id è globale: notebook_id resta
    nella firma per coerenza con gli altri tool ma viene IGNORATO (non arriva
    alla CLI). Ritorna "ok"."""
    await _aio(core.studio_rename, notebook_id, artifact_id, new_title)
    return "ok"


# ============================================================
# STUDIO — download (un solo tool, dispatcha per kind)
# ============================================================

@mcp.tool()
async def studio_download(kind: str, notebook_id: str, output_path: str,
                          artifact_id: Optional[str] = None) -> dict:
    """Scarica un artefatto. kind: audio|video|slides|mindmap|infographic|data_table|report|quiz|flashcards.

    `output_path` vale come NOME del file, non come destinazione: il file nasce sul
    filesystem del SERVER, nella directory degli artefatti. Ritorna dove prenderlo
    (`download_url`, dal pannello admin del gateway), non un path da aprire in locale.
    """
    p = await _aio(core.studio_download, kind, notebook_id, output_path,
                   artifact_id=artifact_id)
    # Prima qui c'era `return str(p)`: un percorso che sul disco di chi chiama NON
    # ESISTE, restituito come se fosse un risultato utilizzabile. Chi lo riceveva
    # provava ad aprirlo e trovava il nulla — il valore era vero sul server e falso
    # per il lettore. Ora il ritorno dice DOVE prenderlo davvero.
    return {
        "name": p.name,
        "bytes": p.stat().st_size,
        "download_url": f"/admin/nlm/artifact/{p.name}",
        "nota": "Il file è sul server. Scaricalo dal pannello: /admin/nlm (sezione "
                "artefatti). Il path del container non è raggiungibile da qui.",
    }


# ============================================================
# STUDIO — export
# ============================================================

@mcp.tool()
async def studio_export_to_docs(notebook_id: str, artifact_id: str,
                                title: Optional[str] = None) -> str:
    """Esporta un Report su Google Docs. Ritorna l'URL."""
    return await _aio(core.studio_export_to_docs, notebook_id, artifact_id, title=title)


@mcp.tool()
async def studio_export_to_sheets(notebook_id: str, artifact_id: str,
                                  title: Optional[str] = None) -> str:
    """Esporta una Data Table su Google Sheets. Ritorna l'URL."""
    return await _aio(core.studio_export_to_sheets, notebook_id, artifact_id, title=title)


# ============================================================
# DOCTOR
# ============================================================

@mcp.tool()
async def doctor() -> dict:
    """Diagnostica: nlm reachable + count notebook + canonico del blocco memoria."""
    d = await _aio(core.doctor)
    # Canonico anche qui: doctor è la chiamata tipica d'avvio sessione, così il
    # canonico atterra senza un tool dedicato. Fail-open (get_canonical non alza).
    d["canonico"] = canonical.public_view(await asyncio.to_thread(canonical.get_canonical))
    return d


@mcp.tool()
async def canonico(full: bool = False, taglio: str = "pieno") -> dict:
    """MEMORIA 1777 (canale B) — DICHIARA il canonico del blocco di memoria: la
    versione «buona» con cui una sessione dovrebbe allinearsi. Da 0.44.0 è un FILE
    del prodotto (neutro, versionato con vps1777), non più un notebook.
    Chiamalo all'avvio se la versione in testa al blocco che porti potrebbe essere
    vecchia, e confrontala: se sei più vecchio sei disallineato.
    `full=true` è la CURA: restituisce il testo della disciplina nel `taglio`
    chiesto (`pieno` | `lite` | `micro`) più i due strati LOCALI dell'installazione
    — `fatti` (chi è l'utente) ed `errata` (falsi corretti) — ognuno con la sua
    origine, così ti allinei in contesto senza aspettare che le superfici vengano
    aggiornate a mano. Fail-open: `available: false` se il file non è leggibile."""
    # NON via _aio: non serve l'auth nlm (è un file locale) ed è fail-open per
    # contratto (deve poter dire "available: false" invece di sollevare).
    data = await asyncio.to_thread(canonical.get_canonical)
    if full:
        return await asyncio.to_thread(canonical.full_view, data, taglio=taglio)
    return canonical.public_view(data)


@mcp.tool()
async def memoria_check(versione_portata: str) -> dict:
    """MEMORIA 1777 — il VERDETTO: confronta la versione del blocco di memoria che
    porti (es. 'v2.2') col canonico attuale. Ritorna `{canonico, data, stale,
    delta}`, più `portata` (la tua versione normalizzata) e, se sei vecchio, le
    `note` del canonico. Fail-open: se il canonico non è leggibile, o la versione
    passata non si riconosce, `stale: null` con una `nota` che lo dice.
    Effetto collaterale che è IL PUNTO: se sei vecchio (`stale:true`), manda a
    Neo UN ping Telegram (max 1 al giorno per coppia portata→canonico) — così
    anche se la sessione ignora il verdetto, Neo lo sa. Chiamalo all'avvio se la
    versione in testa al tuo blocco potrebbe essere superata."""
    verdict = await asyncio.to_thread(memoria.compare, versione_portata)
    if verdict.get("stale") and verdict.get("canonico"):
        await asyncio.to_thread(memoria.note_drift, versione_portata, verdict["canonico"])
    return verdict


@mcp.tool()
async def memoria_ack(versione: str) -> dict:
    """MEMORIA 1777 — l'ACK: registra che le superfici cloud (claude.ai: preferenze
    e istruzioni dei Project) sono state aggiornate a `versione`, e spegne il
    promemoria Telegram fino al prossimo bump del canonico. È la stessa cosa del
    bottone «✓ Fatto» sul bot. ⚠️ Chiamalo SOLO su dichiarazione esplicita di chi
    ti parla («ho incollato»): un ack scritto senza il fatto dietro è la
    dichiarazione senza verifica che la disciplina stessa vieta."""
    acked = await asyncio.to_thread(memoria.set_ack, versione)
    canon = await asyncio.to_thread(canonical.get_canonical)
    return {
        "ok": True,
        "acked": acked,
        "canonico": canon["version"] if canon else None,
        "allineato": bool(canon and memoria.parse_version(acked) == (canon["major"], canon["minor"])),
    }


@mcp.custom_route("/internal/notifications", methods=["GET"])
async def internal_notifications(request: "Request") -> "JSONResponse":
    """Il bot preleva qui le notifiche da mandare a Neo (drift + promemoria cloud).
    Interno (secret condiviso): non è un tool pubblico, così una sessione non può
    svuotare la coda al posto del bot."""
    if not _internal_ok(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    items = await asyncio.to_thread(memoria.drain)
    return JSONResponse({"items": items})


@mcp.custom_route("/internal/canonico/ack", methods=["POST"])
async def internal_canonico_ack(request: "Request") -> "JSONResponse":
    """Il bot registra qui l'ack del bottone «✓ Fatto»: superfici cloud aggiornate
    a `version`. Spegne il promemoria fino al prossimo bump del canonico."""
    if not _internal_ok(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    try:
        body = await request.json()
    except (ValueError, TypeError):
        return JSONResponse({"error": "bad_json"}, status_code=400)
    version = str((body or {}).get("version") or "").strip()
    if not version:
        return JSONResponse({"error": "missing_version"}, status_code=400)
    acked = await asyncio.to_thread(memoria.set_ack, version)
    return JSONResponse({"ok": True, "acked": acked})


# ============================================================
# main
# ============================================================

if __name__ == "__main__":
    print(f"[nb1777-mcp] {TRANSPORT} on {HOST}:{PORT}")
    mcp.run(transport=TRANSPORT)


# ── /health — la sonda che il compose interroga (vaglio corso1777, 03/09) ────────
# Come per archive-mcp: il check TCP-only faceva passare per sano un processo
# con la porta aperta e l'app rotta, e su quel verde si appoggia il HEALTH-GATE
# dell'updater. Qui la sonda prova settings + volume dati (nlm_home leggibile) —
# MAI una chiamata a NotebookLM: un health che dipende da un servizio esterno
# riavvia il container per i guasti degli altri. Espone anche la revisione MCP
# massima dell'SDK spedito nell'immagine (osservabile, non dedotta dal lock).
@mcp.custom_route("/health", methods=["GET"])
async def health(_request: "Request") -> "JSONResponse":
    import importlib.metadata
    from pathlib import Path

    try:
        home = Path(get_settings().nlm_home)
        home_ok = home.is_dir()
    except Exception as exc:  # noqa: BLE001 — QUALUNQUE guasto = non healthy
        return JSONResponse({"status": "error", "reason": str(exc)[:200]}, status_code=503)
    if not home_ok:
        return JSONResponse({"status": "error", "reason": "nlm_home assente"}, status_code=503)
    try:
        from mcp.types import LATEST_PROTOCOL_VERSION
        sdk = importlib.metadata.version("mcp")
    except Exception:  # noqa: BLE001 — la versione è informativa, non gate
        sdk, LATEST_PROTOCOL_VERSION = None, None
    return JSONResponse({
        "status": "ok",
        "mcp_sdk": sdk,
        "mcp_protocol_max": LATEST_PROTOCOL_VERSION,
    })
