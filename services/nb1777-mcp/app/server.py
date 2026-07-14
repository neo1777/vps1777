"""
nb1777/mcp_server.py — FastMCP wrapper sopra core.py.

Espone tutte le funzioni di `core.py` come tool MCP, in ascolto su loopback
(default 127.0.0.1:8003). Davanti gli mettiamo il gateway OAuth sulla VPS.

NIENTE chiave/secret qui: l'autenticazione è del gateway. Questo server è
loopback-only e si aspetta di NON essere mai esposto direttamente.

Avvio standalone:
    python3 -m nb1777.mcp_server                  # streamable-http su :8003
    NB1777_TRANSPORT=stdio python3 -m nb1777.mcp_server   # mode stdio (per dev)

Variabili d'ambiente:
    NB1777_HOST       (default 127.0.0.1)
    NB1777_PORT       (default 8003)
    NB1777_TRANSPORT  (default streamable-http; alt: stdio, sse)
"""
from __future__ import annotations

import asyncio
import hmac
import os
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import core, nlm_profile
from .settings import get_settings


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
    transport_security=TransportSecuritySettings(
        # DNS-rebinding protection OFF: il server sta dietro il gateway su rete
        # Docker interna (non esposto ai browser). Il gateway inoltra
        # `Host: nb1777-mcp:8003`, che con la protezione attiva dava 421
        # (Misdirected Request). Coerente con archive-mcp. La sicurezza è al
        # gateway (OAuth + path-secret), non qui.
        enable_dns_rebinding_protection=False,
    ),
)


# Stato auth NotebookLM.
# Se il file AUTH_PENDING.flag esiste, l'auth nlm non è caricata: ogni tool
# ritorna un errore strutturato con istruzioni per l'admin panel /admin/nlm.
NLM_CFG = Path.home() / ".notebooklm-mcp-cli"
AUTH_FLAG = NLM_CFG / "AUTH_PENDING.flag"
# nlm 0.7.x: l'auth è il profilo profiles/default/cookies.json (non auth.json)
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
async def _aio(fn, *args, **kwargs):
    _check_auth_or_raise()
    return await asyncio.to_thread(fn, *args, **kwargs)


# ============================================================
# ENDPOINT INTERNI — il profilo NotebookLM (H6)
# ============================================================
# nb1777-mcp è l'UNICO servizio che monta il volume dei cookie Google. Il
# gateway (l'unico esposto su Internet) e il bot non lo montano più: chiedono
# qui. Così un gateway compromesso non può né leggere né riscrivere la
# sessione Google.
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
    """Stato del profilo, senza esporre i cookie: {ok, has_cookies, pending}."""
    if not _internal_ok(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    return JSONResponse(nlm_profile.profile_status(Path(get_settings().nlm_home)))


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


@mcp.tool()
async def nb_delete(notebook_id: str) -> str:
    """Cancella un notebook in modo permanente."""
    await _aio(core.nb_delete, notebook_id)
    return "deleted"


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
    """Carica un file locale come fonte (PDF/txt/md...)."""
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
async def source_delete(notebook_id: str, source_id: str) -> str:
    """Elimina una fonte (irreversibile)."""
    await _aio(core.source_delete, notebook_id, source_id)
    return "deleted"


@mcp.tool()
async def source_get_content(notebook_id: str, source_id: str) -> str:
    """Estrae il contenuto raw di una fonte (no AI)."""
    return await _aio(core.source_get_content, notebook_id, source_id)


@mcp.tool()
async def source_rename(notebook_id: str, source_id: str, new_title: str) -> str:
    await _aio(core.source_rename, notebook_id, source_id, new_title)
    return "ok"


# ============================================================
# CHAT
# ============================================================

@mcp.tool()
async def notebook_query(notebook_id: str, question: str,
                         source_ids: Optional[list[str]] = None,
                         conversation_id: Optional[str] = None) -> dict:
    """Pone una domanda alla chat del notebook. Ritorna {answer, citations, ...}."""
    return await _aio(core.notebook_query, notebook_id, question,
                      source_ids=source_ids, conversation_id=conversation_id)


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
    """Crea tutti e 9 gli artefatti in sequenza. Ritorna {tipo: id_o_errore}."""
    return await _aio(core.studio_create_all_9, notebook_id, source_ids=source_ids,
                      language=language, data_table_description=data_table_description,
                      report_format=report_format, wait=wait,
                      skip=tuple(skip or ()))


# ============================================================
# STUDIO — status / wait / delete / rename
# ============================================================

@mcp.tool()
async def studio_list(notebook_id: str) -> list[dict]:
    """Lista tutti gli artefatti studio di un notebook con stato."""
    return await _aio(core.studio_list, notebook_id)


@mcp.tool()
async def studio_status(notebook_id: str, artifact_id: str) -> dict:
    """Stato di un singolo artefatto."""
    return await _aio(core.studio_status, notebook_id, artifact_id)


@mcp.tool()
async def studio_wait(notebook_id: str, artifact_id: str,
                      poll_interval: float = 5.0, timeout: float = 600.0) -> dict:
    """Polling fino a stato terminale o timeout."""
    return await _aio(core.studio_wait, notebook_id, artifact_id,
                      poll_interval=poll_interval, timeout=timeout)


@mcp.tool()
async def studio_delete(notebook_id: str, artifact_id: str) -> str:
    """Cancella un artefatto studio (irreversibile)."""
    await _aio(core.studio_delete, notebook_id, artifact_id)
    return "deleted"


@mcp.tool()
async def studio_rename(notebook_id: str, artifact_id: str, new_title: str) -> str:
    await _aio(core.studio_rename, notebook_id, artifact_id, new_title)
    return "ok"


# ============================================================
# STUDIO — download (un solo tool, dispatcha per kind)
# ============================================================

@mcp.tool()
async def studio_download(kind: str, notebook_id: str, output_path: str,
                          artifact_id: Optional[str] = None) -> str:
    """Scarica un artefatto. kind: audio|video|slides|mindmap|infographic|data_table|report|quiz|flashcards.
    Ritorna il path effettivo del file scritto."""
    p = await _aio(core.studio_download, kind, notebook_id, output_path,
                   artifact_id=artifact_id)
    return str(p)


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
    """Diagnostica: nlm reachable + count notebook."""
    return await _aio(core.doctor)


# ============================================================
# main
# ============================================================

if __name__ == "__main__":
    print(f"[nb1777-mcp] {TRANSPORT} on {HOST}:{PORT}")
    mcp.run(transport=TRANSPORT)
