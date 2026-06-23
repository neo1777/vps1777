"""
nb1777/core.py — wrapper Python su `nlm` CLI per NotebookLM.

Espone tutte le funzioni che servono al bot Telegram e al server MCP:
- notebook CRUD (list/get/create/rename/delete)
- source CRUD (url/text/file/youtube/drive)
- query (chat con NB)
- studio create (i 9 artefatti)
- studio status + wait (polling asincroni)
- studio download (i 9 tipi sui rispettivi formati)
- studio export (Docs per Report, Sheets per Data Table)
- studio_create_all_9 (bulk)

Dipende solo da `nlm` (notebooklm-mcp-cli) raggiungibile sul $PATH e da stdlib.

Convenzioni:
- tutti gli ID sono UUID (8-4-4-4-12)
- nessuna funzione printa: ritornano valori o sollevano NLMError
- `--confirm` passato sempre (no prompt interattivi)
- formato JSON forzato dove supportato (`--json`)

Gotcha noti (dal collaudo empirico 12/06 su GDR1777-lab):
- mind_map: title/language/focus_prompt IGNORATI dal motore; resta sempre inglese
- mind_map status: spesso mislabel come 'flashcards' → filtri laschi
- data_table: parametro `description` REQUIRED (positional, NON --focus)
- video cinematic: --style-prompt mappa a --focus (custom_instructions)
- report 'Create Your Own': --prompt obbligatorio
- audio: rate limit free tier ~2-3/giorno
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional, Union

# === costanti: NB di lavoro noti ===
NB_LAB_GDR1777 = "492a2e7b-1e08-4100-89ed-6a13febf1295"   # GDR1777 — laboratorio artefatti (test 9 strumenti)
NB_VPS_1777 = "489e15bc-ddde-48ef-8c98-ba21bcb0a7da"      # vps-1777 (biblioteca VPS)
NB_BOT_IMITATORE = "15290c4d-a842-4261-99e5-f7824b197c85" # bot-imitatore (da popolare)

# I 9 tipi di artefatto Studio NotebookLM (nome canonico interno)
ARTIFACT_TYPES = (
    "audio", "video", "slides", "mindmap", "infographic",
    "data_table", "report", "quiz", "flashcards",
)

# Mapping: nome canonico interno → comando CLI nlm
_CLI_KIND = {
    "audio": "audio",
    "video": "video",
    "slides": "slides",
    "mindmap": "mindmap",
    "infographic": "infographic",
    "data_table": "data-table",
    "report": "report",
    "quiz": "quiz",
    "flashcards": "flashcards",
}

# Mapping: nome canonico interno → sub-comando di `nlm download`
_CLI_DOWNLOAD = {
    "audio": "audio",
    "video": "video",
    "slides": "slide-deck",
    "mindmap": "mind-map",
    "infographic": "infographic",
    "data_table": "data-table",
    "report": "report",
    "quiz": "quiz",
    "flashcards": "flashcards",
}

# Estensione di default del file scaricato per ogni tipo
DOWNLOAD_EXT = {
    "audio": ".m4a",
    "video": ".mp4",
    "slides": ".pdf",
    "mindmap": ".json",
    "infographic": ".png",
    "data_table": ".csv",
    "report": ".md",
    "quiz": ".json",
    "flashcards": ".json",
}

NLM = shutil.which("nlm") or "nlm"
_UUID_RE = re.compile(r"\b([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})\b")


class NLMError(RuntimeError):
    """Errore nel chiamare il CLI nlm o nel parsare il suo output."""


# ============================================================
# helper interno: subprocess di nlm
# ============================================================

def _run(args: list[str], *, timeout: float = 180.0, check: bool = True) -> subprocess.CompletedProcess:
    cmd = [NLM] + args
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise NLMError(f"timeout {timeout}s su: {' '.join(cmd)}") from e
    if check and p.returncode != 0:
        msg = (p.stderr or "").strip() or (p.stdout or "").strip()
        raise NLMError(f"nlm exit {p.returncode}: {msg[:400]}")
    return p


def _run_json(args: list[str], *, timeout: float = 60.0) -> Union[dict, list]:
    args = list(args)
    if "--json" not in args and "-j" not in args:
        args.append("--json")
    p = _run(args, timeout=timeout, check=True)
    out = (p.stdout or "").strip()
    if not out:
        return []
    try:
        return json.loads(out)
    except json.JSONDecodeError as e:
        raise NLMError(f"JSON parse fallito: {e}\n--- stdout ---\n{out[:500]}") from e


def _norm_type(t: str) -> str:
    return (t or "").lower().strip().replace("-", "_").replace(" ", "_")


def _extract_uuid(text: str) -> Optional[str]:
    m = _UUID_RE.search(text or "")
    return m.group(1) if m else None


# ============================================================
# notebook CRUD
# ============================================================

def nb_list() -> list[dict]:
    """Lista tutti i notebook del profilo attivo. Ogni dict ha almeno 'id' e 'title'."""
    return list(_run_json(["notebook", "list"]))


def nb_get(nb_id: str) -> dict:
    """Dettagli di un singolo notebook."""
    data = _run_json(["notebook", "get", nb_id])
    return data if isinstance(data, dict) else (data[0] if data else {})


def nb_create(title: str) -> str:
    """Crea un nuovo notebook con il titolo dato. Ritorna l'ID (UUID)."""
    p = _run(["notebook", "create", title])
    uid = _extract_uuid(p.stdout + "\n" + p.stderr)
    if uid:
        return uid
    # fallback: cerca per titolo nella lista
    for nb in nb_list():
        if (nb.get("title") or "").strip() == title.strip():
            return nb.get("id") or nb.get("notebook_id") or ""
    raise NLMError(f"notebook create: ID non trovato:\n{p.stdout}\n{p.stderr}")


def nb_rename(nb_id: str, new_title: str) -> None:
    """Rinomina un notebook."""
    _run(["notebook", "rename", nb_id, new_title])


def nb_delete(nb_id: str) -> None:
    """Cancella un notebook in modo permanente (passa --confirm)."""
    _run(["notebook", "delete", nb_id, "--confirm"])


def nb_describe(nb_id: str) -> str:
    """Riassunto AI-generated del notebook. Ritorna il testo."""
    p = _run(["notebook", "describe", nb_id], timeout=120)
    return p.stdout or ""


# ============================================================
# source CRUD
# ============================================================

def source_list(nb_id: str) -> list[dict]:
    """Lista tutte le fonti di un notebook."""
    return list(_run_json(["source", "list", nb_id]))


def _last_source_id(nb_id: str) -> str:
    sources = source_list(nb_id)
    if not sources:
        raise NLMError(f"nessuna fonte trovata in nb={nb_id} dopo add")
    last = sources[-1]
    return last.get("id") or last.get("source_id") or last.get("uuid") or ""


def source_add_url(nb_id: str, url: str, *, title: Optional[str] = None,
                   wait: bool = True, timeout: float = 600.0) -> str:
    """Aggiunge una URL come fonte. Se wait=True attende l'indicizzazione."""
    args = ["source", "add", nb_id, "--url", url]
    if title:
        args += ["--title", title]
    if wait:
        args += ["--wait", "--wait-timeout", str(timeout)]
    _run(args, timeout=timeout + 60)
    return _last_source_id(nb_id)


def source_add_text(nb_id: str, text: str, title: str, *,
                    wait: bool = True, timeout: float = 600.0) -> str:
    """Aggiunge testo libero come fonte (richiede un titolo)."""
    args = ["source", "add", nb_id, "--text", text, "--title", title]
    if wait:
        args += ["--wait", "--wait-timeout", str(timeout)]
    _run(args, timeout=timeout + 60)
    return _last_source_id(nb_id)


def source_add_file(nb_id: str, file_path: Union[str, Path], *,
                    title: Optional[str] = None, wait: bool = True, timeout: float = 900.0) -> str:
    """Carica un file locale (PDF, txt, md, ...) come fonte."""
    args = ["source", "add", nb_id, "--file", str(file_path)]
    if title:
        args += ["--title", title]
    if wait:
        args += ["--wait", "--wait-timeout", str(timeout)]
    _run(args, timeout=timeout + 60)
    return _last_source_id(nb_id)


def source_add_youtube(nb_id: str, url: str, *, wait: bool = True, timeout: float = 900.0) -> str:
    """Aggiunge un video YouTube come fonte (NotebookLM trascrive automaticamente)."""
    args = ["source", "add", nb_id, "--youtube", url]
    if wait:
        args += ["--wait", "--wait-timeout", str(timeout)]
    _run(args, timeout=timeout + 60)
    return _last_source_id(nb_id)


def source_add_drive(nb_id: str, document_id: str, *,
                     doc_type: str = "doc", wait: bool = True, timeout: float = 600.0) -> str:
    """Collega un Google Drive doc come fonte (doc/slides/sheets/pdf)."""
    args = ["source", "add", nb_id, "--drive", document_id, "--type", doc_type]
    if wait:
        args += ["--wait", "--wait-timeout", str(timeout)]
    _run(args, timeout=timeout + 60)
    return _last_source_id(nb_id)


def source_delete(nb_id: str, source_id: str) -> None:
    """Elimina una fonte (irreversibile)."""
    _run(["source", "delete", nb_id, source_id, "--confirm"])


def source_get_content(nb_id: str, source_id: str) -> str:
    """Estrae il contenuto raw di una fonte (no elaborazione AI)."""
    p = _run(["source", "content", nb_id, source_id], timeout=120)
    return p.stdout or ""


def source_rename(nb_id: str, source_id: str, new_title: str) -> None:
    _run(["source", "rename", nb_id, source_id, new_title])


# ============================================================
# chat (notebook_query)
# ============================================================

def notebook_query(nb_id: str, question: str, *,
                   source_ids: Optional[list[str]] = None,
                   conversation_id: Optional[str] = None,
                   timeout: float = 120.0) -> dict:
    """Pone una domanda alla chat del notebook. Ritorna {answer, citations, ...}."""
    args = ["query", "notebook", nb_id, question, "--json", "--timeout", str(timeout)]
    if source_ids:
        args += ["--source-ids", ",".join(source_ids)]
    if conversation_id:
        args += ["--conversation-id", conversation_id]
    data = _run_json(args, timeout=timeout + 30)
    return data if isinstance(data, dict) else {"raw": data}


# ============================================================
# studio — create (i 9 artefatti)
# ============================================================

def _attach_source_ids(args: list[str], source_ids: Optional[list[str]]) -> list[str]:
    if source_ids:
        args += ["--source-ids", ",".join(source_ids)]
    return args


def studio_create_audio(nb_id: str, *,
                        format: str = "deep_dive",
                        length: str = "default",
                        language: str = "it",
                        focus: Optional[str] = None,
                        source_ids: Optional[list[str]] = None) -> str:
    """audio (Audio Overview).
    format: deep_dive | brief | critique | debate
    length: short | default | long
    ATTENZIONE: rate-limit free tier ~2-3 al giorno.
    """
    args = ["audio", "create", nb_id,
            "--format", format, "--length", length, "--language", language, "--confirm"]
    if focus:
        args += ["--focus", focus]
    _attach_source_ids(args, source_ids)
    _run(args, timeout=300)
    return _last_artifact_id(nb_id, "audio")


def studio_create_video(nb_id: str, *,
                        format: str = "explainer",
                        style: str = "auto_select",
                        style_prompt: Optional[str] = None,
                        focus: Optional[str] = None,
                        language: str = "it",
                        source_ids: Optional[list[str]] = None) -> str:
    """video (Video Overview).
    format: explainer | brief | cinematic
    style: auto_select | custom | classic | whiteboard | kawaii | anime | watercolor | retro_print | heritage | paper_craft
    Per cinematic: usa `focus` come full steering prompt (style_prompt mappa lì).
    """
    args = ["video", "create", nb_id,
            "--format", format, "--style", style, "--language", language, "--confirm"]
    if style_prompt:
        args += ["--style-prompt", style_prompt]
    if focus:
        args += ["--focus", focus]
    _attach_source_ids(args, source_ids)
    _run(args, timeout=300)
    return _last_artifact_id(nb_id, "video")


def studio_create_slides(nb_id: str, *,
                         format: str = "detailed_deck",
                         length: str = "default",
                         focus: Optional[str] = None,
                         language: str = "it",
                         source_ids: Optional[list[str]] = None) -> str:
    """slides (Slide Deck).
    format: detailed_deck | presenter_slides
    length: short | default
    """
    args = ["slides", "create", nb_id,
            "--format", format, "--length", length, "--language", language, "--confirm"]
    if focus:
        args += ["--focus", focus]
    _attach_source_ids(args, source_ids)
    _run(args, timeout=300)
    return _last_artifact_id(nb_id, "slides")


def studio_create_mindmap(nb_id: str, *,
                          title: str = "Mind Map",
                          source_ids: Optional[list[str]] = None) -> str:
    """mindmap (Mind Map).
    NOTA: title/language/focus IGNORATI dal motore — il risultato è sempre in inglese.
    """
    args = ["mindmap", "create", nb_id, "--title", title, "--confirm"]
    _attach_source_ids(args, source_ids)
    _run(args, timeout=240)
    return _last_artifact_id(nb_id, "mindmap")


def studio_create_infographic(nb_id: str, *,
                              orientation: str = "landscape",
                              detail: str = "standard",
                              style: str = "auto_select",
                              focus: Optional[str] = None,
                              language: str = "it",
                              source_ids: Optional[list[str]] = None) -> str:
    """infographic (Infographic, immagine PNG).
    orientation: landscape | portrait | square
    detail: concise | standard | detailed
    style: auto_select | sketch_note | professional | bento_grid | editorial | instructional | bricks | clay | anime | kawaii | scientific
    NOTA: testo dentro l'immagine spesso con refusi (limite del modello image-gen).
    """
    args = ["infographic", "create", nb_id,
            "--orientation", orientation, "--detail", detail, "--style", style,
            "--language", language, "--confirm"]
    if focus:
        args += ["--focus", focus]
    _attach_source_ids(args, source_ids)
    _run(args, timeout=300)
    return _last_artifact_id(nb_id, "infographic")


def studio_create_data_table(nb_id: str, description: str, *,
                             language: str = "it",
                             source_ids: Optional[list[str]] = None) -> str:
    """data_table (Data Table).
    `description` è OBBLIGATORIA (descrive le colonne richieste).
    Es: "Tabella con: Nome concetto, Definizione breve, Citazione dalla fonte."
    """
    args = ["data-table", "create", nb_id, description,
            "--language", language, "--confirm"]
    _attach_source_ids(args, source_ids)
    _run(args, timeout=240)
    return _last_artifact_id(nb_id, "data_table")


def studio_create_report(nb_id: str, *,
                         format: str = "Briefing Doc",
                         prompt: Optional[str] = None,
                         language: str = "it",
                         source_ids: Optional[list[str]] = None) -> str:
    """report (Report markdown).
    format: 'Briefing Doc' | 'Study Guide' | 'Blog Post' | 'Create Your Own'
    Per 'Create Your Own' il parametro `prompt` è OBBLIGATORIO.
    """
    if format == "Create Your Own" and not prompt:
        raise NLMError("report format='Create Your Own' richiede `prompt` non vuoto")
    args = ["report", "create", nb_id,
            "--format", format, "--language", language, "--confirm"]
    if prompt:
        args += ["--prompt", prompt]
    _attach_source_ids(args, source_ids)
    _run(args, timeout=240)
    return _last_artifact_id(nb_id, "report")


def studio_create_quiz(nb_id: str, *,
                       count: int = 10,
                       difficulty: int = 2,
                       focus: Optional[str] = None,
                       source_ids: Optional[list[str]] = None) -> str:
    """quiz (Quiz).
    count: numero di domande (CLI default 2, qui pushiamo a 10)
    difficulty: 1=easy ... 5=hard
    """
    args = ["quiz", "create", nb_id,
            "--count", str(count), "--difficulty", str(difficulty), "--confirm"]
    if focus:
        args += ["--focus", focus]
    _attach_source_ids(args, source_ids)
    _run(args, timeout=240)
    return _last_artifact_id(nb_id, "quiz")


def studio_create_flashcards(nb_id: str, *,
                             difficulty: str = "medium",
                             focus: Optional[str] = None,
                             source_ids: Optional[list[str]] = None) -> str:
    """flashcards (Flashcards).
    difficulty: easy | medium | hard
    """
    args = ["flashcards", "create", nb_id,
            "--difficulty", difficulty, "--confirm"]
    if focus:
        args += ["--focus", focus]
    _attach_source_ids(args, source_ids)
    _run(args, timeout=240)
    return _last_artifact_id(nb_id, "flashcards")


# ============================================================
# studio — status / wait
# ============================================================

def studio_list(nb_id: str) -> list[dict]:
    """Lista tutti gli artefatti studio di un notebook con stato corrente."""
    return list(_run_json(["status", "artifacts", nb_id]))


def _last_artifact_id(nb_id: str, kind: str) -> str:
    """Restituisce l'ID dell'ultimo artefatto del tipo dato (assume order=cronologico)."""
    arts = studio_list(nb_id)
    if not arts:
        return ""
    target = _norm_type(kind)
    # mind_map mislabel come 'flashcards' in alcune versioni: se cercavi mindmap e non trovi,
    # accetta anche le flashcards 'recenti' come fallback debole — meglio prendere l'ultima.
    matching = [a for a in arts
                if _norm_type(a.get("type") or a.get("artifact_type") or "") == target]
    chosen = matching[-1] if matching else arts[-1]
    return chosen.get("id") or chosen.get("artifact_id") or ""


def studio_status(nb_id: str, artifact_id: str) -> dict:
    """Stato di un singolo artefatto (cerca per ID nella lista del NB)."""
    for a in studio_list(nb_id):
        aid = a.get("id") or a.get("artifact_id")
        if aid == artifact_id:
            return a
    return {}


def studio_wait(nb_id: str, artifact_id: str, *,
                poll_interval: float = 5.0, timeout: float = 600.0) -> dict:
    """Polling fino a stato terminale (completed/failed/error/done) o timeout."""
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        last = studio_status(nb_id, artifact_id)
        state = _norm_type(last.get("status") or last.get("state") or "")
        if state in ("completed", "failed", "error", "done", "ready"):
            return last
        time.sleep(poll_interval)
    raise NLMError(f"studio_wait timeout {timeout}s su {artifact_id}; ultimo stato: {last}")


def studio_delete(nb_id: str, artifact_id: str) -> None:
    """Cancella un artefatto studio (irreversibile)."""
    _run(["studio", "delete", nb_id, artifact_id, "--confirm"])


def studio_rename(nb_id: str, artifact_id: str, new_title: str) -> None:
    _run(["studio", "rename", nb_id, artifact_id, new_title])


# ============================================================
# studio — download (i 9 tipi)
# ============================================================

def studio_download(kind: str, nb_id: str, output_path: Union[str, Path], *,
                    artifact_id: Optional[str] = None) -> Path:
    """Scarica un artefatto sul filesystem. `kind` è il nome canonico interno (audio/video/...)."""
    cli_kind = _CLI_DOWNLOAD.get(kind)
    if not cli_kind:
        raise NLMError(f"download: tipo non riconosciuto '{kind}'. Validi: {list(_CLI_DOWNLOAD)}")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    args = ["download", cli_kind, nb_id, "--output", str(output_path), "--no-progress"]
    if artifact_id:
        args += ["--id", artifact_id]
    _run(args, timeout=900)
    return output_path


def studio_download_audio(nb_id, out, *, artifact_id=None): return studio_download("audio", nb_id, out, artifact_id=artifact_id)
def studio_download_video(nb_id, out, *, artifact_id=None): return studio_download("video", nb_id, out, artifact_id=artifact_id)
def studio_download_slides(nb_id, out, *, artifact_id=None): return studio_download("slides", nb_id, out, artifact_id=artifact_id)
def studio_download_mindmap(nb_id, out, *, artifact_id=None): return studio_download("mindmap", nb_id, out, artifact_id=artifact_id)
def studio_download_infographic(nb_id, out, *, artifact_id=None): return studio_download("infographic", nb_id, out, artifact_id=artifact_id)
def studio_download_data_table(nb_id, out, *, artifact_id=None): return studio_download("data_table", nb_id, out, artifact_id=artifact_id)
def studio_download_report(nb_id, out, *, artifact_id=None): return studio_download("report", nb_id, out, artifact_id=artifact_id)
def studio_download_quiz(nb_id, out, *, artifact_id=None): return studio_download("quiz", nb_id, out, artifact_id=artifact_id)
def studio_download_flashcards(nb_id, out, *, artifact_id=None): return studio_download("flashcards", nb_id, out, artifact_id=artifact_id)


# ============================================================
# studio — export (Docs / Sheets)
# ============================================================

def studio_export_to_docs(nb_id: str, artifact_id: str, *, title: Optional[str] = None) -> str:
    """Esporta un Report su Google Docs. Ritorna l'URL del doc (o l'output raw)."""
    args = ["export", "to-docs", nb_id, artifact_id]
    if title:
        args += ["--title", title]
    p = _run(args, timeout=120)
    m = re.search(r"https?://[^\s]+", p.stdout or "")
    return m.group(0) if m else (p.stdout or "").strip()


def studio_export_to_sheets(nb_id: str, artifact_id: str, *, title: Optional[str] = None) -> str:
    """Esporta una Data Table su Google Sheets. Ritorna l'URL del foglio."""
    args = ["export", "to-sheets", nb_id, artifact_id]
    if title:
        args += ["--title", title]
    p = _run(args, timeout=120)
    m = re.search(r"https?://[^\s]+", p.stdout or "")
    return m.group(0) if m else (p.stdout or "").strip()


# ============================================================
# bulk — i 9 in colpo solo
# ============================================================

def studio_create_all_9(nb_id: str, *,
                        source_ids: Optional[list[str]] = None,
                        language: str = "it",
                        data_table_description: str = "Tabella con: Concetto, Definizione, Citazione dalla fonte.",
                        report_format: str = "Study Guide",
                        wait: bool = False,
                        skip: tuple[str, ...] = ()) -> dict[str, str]:
    """Crea tutti e 9 gli artefatti in sequenza.

    Ritorna {tipo: artifact_id_o_messaggio_errore}.

    Parametri:
      skip: tipi da saltare (es. ('audio',) per evitare il rate-limit).
      wait: se True attende il completamento di ogni artefatto prima del prossimo.
            False (default) lancia e ritorna subito gli ID (gli asincroni
            continuano in background sul cloud di NotebookLM).
    """
    results: dict[str, str] = {}
    skip_set = set(skip)
    plan = [
        ("audio",       lambda: studio_create_audio(nb_id, language=language, source_ids=source_ids)),
        ("video",       lambda: studio_create_video(nb_id, language=language, source_ids=source_ids)),
        ("slides",      lambda: studio_create_slides(nb_id, language=language, source_ids=source_ids)),
        ("mindmap",     lambda: studio_create_mindmap(nb_id, source_ids=source_ids)),
        ("infographic", lambda: studio_create_infographic(nb_id, language=language, source_ids=source_ids)),
        ("data_table",  lambda: studio_create_data_table(nb_id, data_table_description, language=language, source_ids=source_ids)),
        ("report",      lambda: studio_create_report(nb_id, format=report_format, language=language, source_ids=source_ids)),
        ("quiz",        lambda: studio_create_quiz(nb_id, count=10, source_ids=source_ids)),
        ("flashcards",  lambda: studio_create_flashcards(nb_id, source_ids=source_ids)),
    ]
    for kind, fn in plan:
        if kind in skip_set:
            results[kind] = "SKIPPED"
            continue
        try:
            aid = fn()
            results[kind] = aid or "?"
            if wait and aid:
                studio_wait(nb_id, aid, timeout=900)
        except NLMError as e:
            results[kind] = f"ERROR: {e}"
        except Exception as e:
            results[kind] = f"ERROR: {type(e).__name__}: {e}"
    return results


# ============================================================
# self-check / doctor
# ============================================================

def doctor() -> dict:
    """Diagnostica: verifica nlm + lista NB visibili."""
    info: dict = {"nlm_path": NLM}
    try:
        p = _run(["--version"], check=True)
        info["version"] = (p.stdout or "").strip()
    except Exception as e:
        info["error"] = str(e)
        return info
    try:
        nbs = nb_list()
        info["notebooks_count"] = len(nbs)
        info["first_3"] = [{"id": nb.get("id"), "title": nb.get("title")} for nb in nbs[:3]]
    except Exception as e:
        info["list_error"] = str(e)
    return info


if __name__ == "__main__":
    import sys
    print("=== nb1777/core.py — doctor ===")
    d = doctor()
    for k, v in d.items():
        print(f"  {k}: {v}")
    print("\nNB di lavoro noti:")
    print(f"  GDR1777 lab : {NB_LAB_GDR1777}")
    print(f"  vps-1777    : {NB_VPS_1777}")
    print(f"  bot-imitatore: {NB_BOT_IMITATORE}")
    if "--list" in sys.argv:
        print("\nElenco completo notebook:")
        for nb in nb_list():
            print(f"  {nb.get('id')}  {nb.get('title')}")
