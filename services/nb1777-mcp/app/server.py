"""
FastMCP wrapper su nlm CLI — MVP con tool essenziali.

Il pacchetto `notebooklm-mcp-cli` espone una classe core in Python (sopra
il subprocess CLI o direttamente nel modulo). MVP delega a subprocess CLI
per semplicità — sostituibile con import nativo se la libreria lo permette.
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from typing import Any

from fastmcp import FastMCP

from . import auth

log = logging.getLogger(__name__)

mcp = FastMCP("nb1777")


async def _nlm(*args: str) -> str:
    """Esegue `nlm <args>` come subprocess. Ritorna stdout (str) o solleva."""
    auth.check_or_raise()
    proc = await asyncio.create_subprocess_exec(
        "nlm", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_b, stderr_b = await proc.communicate()
    if proc.returncode != 0:
        msg = stderr_b.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"nlm failed (rc={proc.returncode}): {msg}")
    return stdout_b.decode("utf-8", errors="replace").strip()


# ───── notebook tools ─────

@mcp.tool()
async def nb_list() -> list[dict[str, Any]]:
    """Elenca i notebook NotebookLM dell'account autorizzato."""
    out = await _nlm("notebook", "list", "--json")
    try:
        return json.loads(out) if out else []
    except json.JSONDecodeError:
        return [{"raw": out}]


@mcp.tool()
async def nb_get(notebook_id: str) -> dict[str, Any]:
    """Dettagli completi di un notebook."""
    out = await _nlm("notebook", "get", notebook_id, "--json")
    return json.loads(out) if out else {}


@mcp.tool()
async def nb_create(title: str) -> dict[str, Any]:
    """Crea un nuovo notebook con il titolo dato."""
    out = await _nlm("notebook", "create", title, "--json")
    return json.loads(out) if out else {"title": title}


@mcp.tool()
async def nb_rename(notebook_id: str, new_title: str) -> str:
    """Rinomina notebook."""
    return await _nlm("notebook", "rename", notebook_id, new_title)


@mcp.tool()
async def nb_delete(notebook_id: str) -> str:
    """Cancella notebook (irreversibile!)."""
    return await _nlm("notebook", "delete", notebook_id, "--yes")


# ───── source tools ─────

@mcp.tool()
async def source_list(notebook_id: str) -> list[dict[str, Any]]:
    """Lista delle fonti di un notebook."""
    out = await _nlm("source", "list", notebook_id, "--json")
    return json.loads(out) if out else []


@mcp.tool()
async def source_add_url(notebook_id: str, url: str, title: str = "") -> dict[str, Any]:
    """Aggiunge URL/YouTube come fonte."""
    args = ["source", "add", notebook_id, "--url", url]
    if title:
        args.extend(["--title", title])
    args.append("--json")
    out = await _nlm(*args)
    return json.loads(out) if out else {"url": url}


@mcp.tool()
async def source_add_text(notebook_id: str, title: str, text: str) -> dict[str, Any]:
    """Aggiunge testo libero come fonte."""
    out = await _nlm(
        "source", "add", notebook_id, "--text", text, "--title", title, "--json",
    )
    return json.loads(out) if out else {"title": title}


# ───── chat ─────

@mcp.tool()
async def notebook_query(notebook_id: str, question: str) -> str:
    """Chiede a NotebookLM una domanda RAG sul notebook."""
    out = await _nlm("chat", notebook_id, question)
    return out


# ───── studio (i 9 artefatti) ─────

@mcp.tool()
async def studio_list(notebook_id: str) -> list[dict[str, Any]]:
    """Lista degli artefatti studio di un notebook."""
    out = await _nlm("studio", "list", notebook_id, "--json")
    return json.loads(out) if out else []


@mcp.tool()
async def studio_create_audio(notebook_id: str, topic: str = "") -> dict[str, Any]:
    """Crea audio overview ('Deep Dive')."""
    args = ["studio", "create", "audio", notebook_id]
    if topic:
        args.extend(["--topic", topic])
    args.append("--json")
    out = await _nlm(*args)
    return json.loads(out) if out else {}


@mcp.tool()
async def doctor() -> dict[str, Any]:
    """Stato dell'integrazione nlm (auth, profili, versione)."""
    auth.check_or_raise()
    out = await _nlm("doctor")
    return {"raw": out}
