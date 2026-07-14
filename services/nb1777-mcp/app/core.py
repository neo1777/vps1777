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
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

# H41 — contenuti personali fuori da argv/errori.
# Tutto ciò che sta in `argv` è visibile a OGNI utente della VPS via `ps` e
# `/proc/<pid>/cmdline`. Il corpo di una fonte sono contenuti personali di Neo:
# non deve MAI passare da lì. Sopra questa soglia il testo va scritto in un file
# temporaneo 0600 e passato con `--file` (nlm non ha un canale stdin — verificato
# su `nlm source add --help`). Sotto la soglia (etichette/snippet corti) resta in
# argv: è la stessa dimensione dei titoli, già inevitabilmente lì.
TEXT_ARGV_MAX = 256  # caratteri: oltre questo, il testo va su file temporaneo
# Troncamento dei command-line negli errori: un timeout non deve ri-versare nei
# log/nella response gli argomenti (domande, prompt, path) che pure stanno in argv.
_ERR_ARG_MAX = 80
_ERR_CMD_MAX = 300

# === costanti: NB di lavoro noti ===
NB_LAB_GDR1777 = "492a2e7b-1e08-4100-89ed-6a13febf1295"   # GDR1777 — laboratorio artefatti (test 9 strumenti)
NB_VPS_1777 = "489e15bc-ddde-48ef-8c98-ba21bcb0a7da"      # vps-1777 (biblioteca VPS)
NB_BOT_IMITATORE = "15290c4d-a842-4261-99e5-f7824b197c85" # bot-imitatore (da popolare)

# H40 — prefisso dei notebook scratch usa-e-getta creati dall'OCR
# (transcribe_document). È l'UNICO segnale per riconoscere e recuperare gli
# scratch rimasti orfani quando il cleanup fallisce: chi lo cambia deve
# aggiornare anche sweep_ingest_notebooks() e doctor().
INGEST_NB_PREFIX = "_ingest_"

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

log = logging.getLogger("nb1777-mcp.core")


class NLMError(RuntimeError):
    """Errore nel chiamare il CLI nlm o nel parsare il suo output."""


# ============================================================
# helper interno: subprocess di nlm
# ============================================================

def _safe_cmd(cmd: list[str]) -> str:
    """Command line per un messaggio d'errore, SENZA versare contenuti (H41).

    In argv finiscono dati personali (domande, prompt, path, titoli). Un errore —
    che finisce nei log e nella response — non deve ri-esporli: ogni argomento
    lungo è troncato e il totale è capato. Prima il timeout stampava `' '.join(cmd)`
    per intero, cioè anche il `--text <tutta la fonte>`."""
    parts = [a if len(a) <= _ERR_ARG_MAX else a[:_ERR_ARG_MAX] + "…" for a in map(str, cmd)]
    line = " ".join(parts)
    return line if len(line) <= _ERR_CMD_MAX else line[:_ERR_CMD_MAX] + "…"


def _run(args: list[str], *, timeout: float = 180.0, check: bool = True) -> subprocess.CompletedProcess:
    cmd = [NLM] + args
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise NLMError(f"timeout {timeout}s su: {_safe_cmd(cmd)}") from e
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


def _source_id_of(s: dict) -> str:
    return s.get("id") or s.get("source_id") or s.get("uuid") or ""


def _source_ids(nb_id: str) -> set[str]:
    """Insieme degli id delle fonti attualmente nel notebook."""
    return {sid for s in source_list(nb_id) if (sid := _source_id_of(s))}


def _last_source_id(nb_id: str) -> str:
    """Ripiego best-effort: l'ultima fonte in lista. Vedi _add_and_resolve_id
    per perché NON è affidabile come identità della fonte appena creata."""
    sources = source_list(nb_id)
    if not sources:
        raise NLMError(f"nessuna fonte trovata in nb={nb_id} dopo add")
    return _source_id_of(sources[-1])


def _add_and_resolve_id(nb_id: str, args: list[str], *, timeout: float) -> str:
    """Esegue un `source add` e ritorna l'id della fonte APPENA creata.

    `nlm source add` non stampa l'id in modo affidabile, quindi lo si ricava
    per differenza: si fotografano gli id prima e dopo l'add. Questo è robusto
    contro l'ordinamento di `source list` — il vecchio `sources[-1]` assumeva
    che l'ultima in lista fosse la nuova, falso con >=2 fonti (era il bug per
    cui source_add_url tornava l'id della fonte testo precedente).

    Limite dichiarato — concorrenza: se un'ALTRA sessione aggiunge una fonte
    allo stesso notebook nella finestra fra i due snapshot (stesso account
    NotebookLM), la differenza può contenere piu di un id. In quel caso non si
    indovina: si logga e si ripiega sull'ultima (best-effort). Richiede wait=True
    perché la fonte compaia nello snapshot 'dopo'.
    """
    before = _source_ids(nb_id)
    _run(args, timeout=timeout + 60)
    after = _source_ids(nb_id)
    new = after - before
    if len(new) == 1:
        return next(iter(new))
    if not new:
        log.warning("source add: nessun id nuovo rilevato (nb=%s) — ripiego su last", nb_id)
        return _last_source_id(nb_id)
    log.warning(
        "source add: %d id nuovi (nb=%s) — concorrenza sullo stesso account? ripiego su last",
        len(new), nb_id,
    )
    return _last_source_id(nb_id)


def source_add_url(nb_id: str, url: str, *, title: Optional[str] = None,
                   wait: bool = True, timeout: float = 600.0) -> str:
    """Aggiunge una URL come fonte. Se wait=True attende l'indicizzazione."""
    args = ["source", "add", nb_id, "--url", url]
    if title:
        args += ["--title", title]
    if wait:
        args += ["--wait", "--wait-timeout", str(timeout)]
    return _add_and_resolve_id(nb_id, args, timeout=timeout)


def source_add_text(nb_id: str, text: str, title: str, *,
                    wait: bool = True, timeout: float = 600.0) -> str:
    """Aggiunge testo libero come fonte (richiede un titolo).

    H41 — il corpo NON va in argv (process list / /proc/<pid>/cmdline, leggibili
    da ogni utente della VPS: sono contenuti personali). Sopra TEXT_ARGV_MAX lo si
    scrive in un file temporaneo 0600 e lo si passa con `--file`; `nlm` non ha un
    canale stdin (verificato su `nlm source add --help`), quindi il file è la via.
    Il titolo resta in argv: è un'etichetta corta, come per tutte le altre fonti.
    """
    if len(text) <= TEXT_ARGV_MAX:
        args = ["source", "add", nb_id, "--text", text, "--title", title]
        if wait:
            args += ["--wait", "--wait-timeout", str(timeout)]
        return _add_and_resolve_id(nb_id, args, timeout=timeout)

    # mkstemp crea già con permessi 0600 (O_CREAT|O_EXCL): il file col contenuto
    # personale non è leggibile da altri utenti nemmeno per l'istante in cui esiste.
    fd, tmp = tempfile.mkstemp(suffix=".txt", prefix="nb1777-src-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        args = ["source", "add", nb_id, "--file", tmp, "--title", title]
        if wait:
            args += ["--wait", "--wait-timeout", str(timeout)]
        return _add_and_resolve_id(nb_id, args, timeout=timeout)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def source_add_file(nb_id: str, file_path: Union[str, Path], *,
                    title: Optional[str] = None, wait: bool = True, timeout: float = 900.0) -> str:
    """Carica un file locale (PDF, txt, md, ...) come fonte."""
    args = ["source", "add", nb_id, "--file", str(file_path)]
    if title:
        args += ["--title", title]
    if wait:
        args += ["--wait", "--wait-timeout", str(timeout)]
    return _add_and_resolve_id(nb_id, args, timeout=timeout)


def source_add_youtube(nb_id: str, url: str, *, wait: bool = True, timeout: float = 900.0) -> str:
    """Aggiunge un video YouTube come fonte (NotebookLM trascrive automaticamente)."""
    args = ["source", "add", nb_id, "--youtube", url]
    if wait:
        args += ["--wait", "--wait-timeout", str(timeout)]
    return _add_and_resolve_id(nb_id, args, timeout=timeout)


def source_add_drive(nb_id: str, document_id: str, *,
                     doc_type: str = "doc", wait: bool = True, timeout: float = 600.0) -> str:
    """Collega un Google Drive doc come fonte (doc/slides/sheets/pdf)."""
    args = ["source", "add", nb_id, "--drive", document_id, "--type", doc_type]
    if wait:
        args += ["--wait", "--wait-timeout", str(timeout)]
    return _add_and_resolve_id(nb_id, args, timeout=timeout)


def source_delete(nb_id: str, source_id: str) -> None:  # noqa: ARG001 (nb_id tenuto per firma MCP)
    """Elimina una fonte (irreversibile).

    nlm 0.7.7: `source delete SOURCE_IDS... [--confirm]` — la fonte è
    identificata dal solo source_id (globale), NON dal notebook. Passare nb_id
    come primo posizionale lo farebbe interpretare come un source_id da
    cancellare → "Failed to delete sources".
    """
    _run(["source", "delete", source_id, "--confirm"])


def source_get_content(nb_id: str, source_id: str) -> str:  # noqa: ARG001 (nb_id tenuto per firma MCP)
    """Estrae il contenuto raw di una fonte (no elaborazione AI).

    nlm 0.7.7: `source content SOURCE_ID` — un solo posizionale. Il notebook
    non serve (source_id è globale). Passare nb_id → "Got unexpected extra
    argument(s)".
    """
    p = _run(["source", "content", source_id], timeout=120)
    return p.stdout or ""


def source_rename(nb_id: str, source_id: str, new_title: str) -> None:
    """Rinomina una fonte.

    nlm 0.7.7: `source rename -n NOTEBOOK SOURCE_ID TITLE` — il notebook è
    un'opzione OBBLIGATORIA `-n/--notebook`, non un posizionale. Passarlo
    posizionale → "Missing option --notebook".
    """
    _run(["source", "rename", "-n", nb_id, source_id, new_title])


# ============================================================
# chat (notebook_query)
# ============================================================

def notebook_query(nb_id: str, question: str, *,
                   source_ids: Optional[list[str]] = None,
                   conversation_id: Optional[str] = None,
                   timeout: float = 240.0) -> dict:  # RAG su notebook grandi può essere lento
    """Pone una domanda alla chat del notebook. Ritorna {answer, citations, ...}."""
    args = ["query", "notebook", nb_id, question, "--json", "--timeout", str(timeout)]
    if source_ids:
        args += ["--source-ids", ",".join(source_ids)]
    if conversation_id:
        args += ["--conversation-id", conversation_id]
    data = _run_json(args, timeout=timeout + 30)
    return data if isinstance(data, dict) else {"raw": data}


# ============================================================
# transcribe — NotebookLM come motore OCR/estrazione (doer + checker)
# ============================================================

_TRANSCRIBE_PROMPT = (
    "Riporta INTEGRALMENTE e VERBATIM tutto il contenuto testuale di questo "
    "documento/immagine, nell'ordine originale. NON riassumere, NON commentare, "
    "NON aggiungere nulla di tuo: solo il testo così com'è."
)
_VERIFY_PROMPT = (
    "Il testo che hai appena trascritto è completo e fedele all'originale? "
    "Segnala in 2-3 righe eventuali parti mancanti, tabelle, numeri o passaggi "
    "incerti o poco leggibili. Se è tutto fedele, dillo esplicitamente."
)


def _delete_notebook_with_retry(nb_id: str, *, attempts: int = 3, backoff: float = 1.0) -> None:
    """`nb_delete` con qualche tentativo: la cancellazione di un notebook su
    NotebookLM può fallire per un errore transiente (rete, rate-limit, 5xx). Si
    riprova `attempts` volte con backoff lineare; se fallisce ancora, si rilancia
    l'ultima NLMError e decide il chiamante. Usato sia dalla pulizia dell'OCR sia
    dallo sweep di recupero (H40)."""
    last: Optional[NLMError] = None
    for i in range(attempts):
        try:
            nb_delete(nb_id)
            return
        except NLMError as exc:
            last = exc
            if i < attempts - 1:
                time.sleep(backoff * (i + 1))
    raise last if last is not None else NLMError(f"delete fallita: {nb_id}")


def _parse_iso8601(ts: Optional[str]) -> Optional[float]:
    """ISO-8601 (es. '2026-07-14T13:44:58Z') → epoch secondi UTC; None se assente
    o non parsabile. `nlm notebook list --json` espone `updated_at` in questa forma
    (verificato dal vivo); è il segnale d'età usato dallo sweep."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def transcribe_document(file_path: Union[str, Path], *, title: Optional[str] = None,
                        verify: bool = False, timeout: float = 600.0) -> dict:
    """Estrae il testo di un file via NotebookLM (multimodale → legge anche le
    immagini/scansioni che pypdf non sa fare).

    Crea un notebook scratch usa-e-getta, aggiunge il file (NotebookLM lo
    processa), chiede la trascrizione integrale via query, opzionalmente chiede
    una verifica di fedeltà (NotebookLM controlla il proprio lavoro), poi
    cancella lo scratch. Ritorna {text, chars, cleanup_ok, verification?}.

    H40 — `cleanup_ok` dice al chiamante se lo scratch è stato davvero cancellato.
    Il documento OCR-ato vive dentro quel notebook: se la delete fallisce (anche
    dopo i retry) resta su Google. In quel caso `cleanup_ok=False` e il notebook
    (prefisso INGEST_NB_PREFIX) sarà recuperato più tardi da sweep_ingest_notebooks().
    La pulizia gira SEMPRE, anche se la trascrizione stessa solleva.

    NB: la trascrizione è generata da LLM, non è OCR deterministico → su layout
    complessi può omettere/allucinare. La query di verifica (`verify=True`) serve
    a segnalarlo.
    """
    path = Path(file_path)
    out: dict = {"text": "", "chars": 0, "cleanup_ok": False}
    nb = nb_create(f"{INGEST_NB_PREFIX}{os.urandom(4).hex()}")
    try:
        source_add_file(nb, path, title=title or path.name, wait=True, timeout=timeout)
        q = notebook_query(nb, _TRANSCRIBE_PROMPT, timeout=timeout)
        text = (q.get("answer") if isinstance(q, dict) else None) or ""
        out["text"] = text
        out["chars"] = len(text)
        if verify and text:
            v = notebook_query(nb, _VERIFY_PROMPT, timeout=timeout)
            out["verification"] = (v.get("answer") if isinstance(v, dict) else None) or ""
    finally:
        try:
            _delete_notebook_with_retry(nb)
            out["cleanup_ok"] = True
        except NLMError as exc:
            log.warning(
                "transcribe: cleanup scratch nb FALLITO dopo i retry (%s): %s — il "
                "documento resta su NotebookLM; recuperabile con sweep_ingest_notebooks()",
                nb, exc)
    return out


def sweep_ingest_notebooks(*, older_than_s: float = 3600.0, max_deletes: int = 50) -> dict:
    """Recupera i notebook scratch '`_ingest_`*' rimasti orfani (H40).

    Uno scratch dell'OCR (transcribe_document) che non è stato cancellato — perché
    `nb_delete` ha fallito anche coi retry — resta su NotebookLM col documento
    dentro. Questo sweep li elimina: prende i notebook col prefisso INGEST_NB_PREFIX
    la cui ultima attività (`updated_at`) è più vecchia di `older_than_s`, e li
    cancella (con retry). La soglia PROTEGGE una trascrizione ancora in corso
    (updated_at recente): non toccare quella. Uno scratch senza timestamp è un
    orfano non databile → si considera vecchio e si recupera.

    Richiamabile a mano, da `doctor`, o da un timer periodico. Ritorna un
    resoconto: {candidates, deleted:[id], failed:[{id,error}], skipped_recent,
    swept_ok}.
    """
    now = time.time()
    candidates: list[str] = []
    skipped_recent = 0
    for nb in nb_list():
        if not (nb.get("title") or "").startswith(INGEST_NB_PREFIX):
            continue
        nb_id = nb.get("id") or nb.get("notebook_id") or ""
        if not nb_id:
            continue
        age = _parse_iso8601(nb.get("updated_at") or nb.get("created_at"))
        if age is not None and (now - age) < older_than_s:
            skipped_recent += 1
            continue
        candidates.append(nb_id)

    deleted: list[str] = []
    failed: list[dict] = []
    for nb_id in candidates[:max_deletes]:
        try:
            _delete_notebook_with_retry(nb_id)
            deleted.append(nb_id)
        except NLMError as exc:
            failed.append({"id": nb_id, "error": str(exc)})
    return {
        "candidates": len(candidates),
        "deleted": deleted,
        "failed": failed,
        "skipped_recent": skipped_recent,
        "swept_ok": not failed,
    }


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
    return _create_and_resolve_artifact_id(nb_id, args, "audio", timeout=300)


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
    return _create_and_resolve_artifact_id(nb_id, args, "video", timeout=300)


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
    return _create_and_resolve_artifact_id(nb_id, args, "slides", timeout=300)


def studio_create_mindmap(nb_id: str, *,
                          title: str = "Mind Map",
                          source_ids: Optional[list[str]] = None) -> str:
    """mindmap (Mind Map).
    NOTA: title/language/focus IGNORATI dal motore — il risultato è sempre in inglese.
    """
    args = ["mindmap", "create", nb_id, "--title", title, "--confirm"]
    _attach_source_ids(args, source_ids)
    return _create_and_resolve_artifact_id(nb_id, args, "mindmap", timeout=240)


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
    return _create_and_resolve_artifact_id(nb_id, args, "infographic", timeout=300)


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
    return _create_and_resolve_artifact_id(nb_id, args, "data_table", timeout=240)


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
    return _create_and_resolve_artifact_id(nb_id, args, "report", timeout=240)


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
    return _create_and_resolve_artifact_id(nb_id, args, "quiz", timeout=240)


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
    return _create_and_resolve_artifact_id(nb_id, args, "flashcards", timeout=240)


# ============================================================
# studio — status / wait
# ============================================================

def _artifact_id_of(a: dict) -> str:
    return a.get("id") or a.get("artifact_id") or ""


def _artifact_compact(a: dict) -> dict:
    """Proiezione compatta di un artefatto studio: id/type/status + un `label`
    (i primi 80 char del focus). Il focus intero (`custom_instructions`, 4-6 KB
    per un podcast) resta FUORI: è ~85:1 di rumore e il risultato di un tool MCP
    entra inline nel contesto, non paginabile. Il label basta a riconoscerlo —
    ed è indispensabile, perché senza è l'unico modo di distinguere due artefatti
    dello stesso tipo."""
    return {
        "id": _artifact_id_of(a),
        "type": a.get("type") or a.get("artifact_type"),
        "status": a.get("status") or a.get("state"),
        "label": (a.get("custom_instructions") or a.get("focus") or "")[:80],
    }


def studio_list(nb_id: str, verbose: bool = False) -> list[dict]:
    """Lista gli artefatti studio di un notebook.

    Default COMPATTO (id/type/status/label): la proiezione la sceglie chi
    consuma, non chi produce. `verbose=True` restituisce il JSON pieno della CLI
    (focus incluso) — solo quando serve davvero il dettaglio."""
    arts = list(_run_json(["status", "artifacts", nb_id]))
    return arts if verbose else [_artifact_compact(a) for a in arts]


def _artifact_ids(nb_id: str) -> set[str]:
    """Insieme degli id degli artefatti studio attualmente nel notebook."""
    return {aid for a in studio_list(nb_id, verbose=True) if (aid := _artifact_id_of(a))}


def _last_artifact_id(nb_id: str, kind: str) -> str:
    """Ripiego best-effort: l'ultimo artefatto del tipo dato in lista. NON è
    affidabile come identità dell'artefatto appena creato — l'ordine di
    `status artifacts` non è cronologico (verificato il 14/07: sei create
    consecutivi tornavano tutti l'id del primo). La via primaria è
    `_create_and_resolve_artifact_id` (snapshot prima/dopo); questa resta solo
    come fallback quando la differenza è ambigua (0 o >1 id nuovi)."""
    arts = studio_list(nb_id, verbose=True)
    if not arts:
        return ""
    target = _norm_type(kind)
    matching = [a for a in arts
                if _norm_type(a.get("type") or a.get("artifact_type") or "") == target]
    chosen = matching[-1] if matching else arts[-1]
    return _artifact_id_of(chosen)


def _create_and_resolve_artifact_id(nb_id: str, args: list[str], kind: str,
                                    *, timeout: float) -> str:
    """Esegue un `studio create` e ritorna l'id dell'artefatto APPENA creato.

    Stessa cura delle fonti (`_add_and_resolve_id`): l'id NON si ricava
    dall'ordine di `status artifacts` — verificato il 14/07, sei create
    consecutivi tornavano tutti l'id del PRIMO artefatto. Lo si ricava per
    DIFFERENZA: si fotografano gli id prima e dopo il create.

    Limite dichiarato — concorrenza: se un'ALTRA sessione crea un artefatto sullo
    stesso account NotebookLM nella finestra fra i due snapshot, la differenza
    contiene più di un id. Si tenta di disambiguare col `kind` atteso; se resta
    ambiguo si ripiega sul best-effort (`_last_artifact_id`) e si logga — non si
    indovina in silenzio."""
    before = _artifact_ids(nb_id)
    _run(args, timeout=timeout)
    after = _artifact_ids(nb_id)
    new = after - before
    if len(new) == 1:
        return next(iter(new))
    if not new:
        log.warning("studio create (%s): nessun id nuovo (nb=%s) — ripiego best-effort",
                    kind, nb_id)
        return _last_artifact_id(nb_id, kind)
    # >1 id nuovo: concorrenza sullo stesso account. Disambigua col tipo atteso.
    target = _norm_type(kind)
    typed = [aid for a in studio_list(nb_id, verbose=True)
             if (aid := _artifact_id_of(a)) in new
             and _norm_type(a.get("type") or a.get("artifact_type") or "") == target]
    if len(typed) == 1:
        return typed[0]
    log.warning("studio create (%s): %d id nuovi (nb=%s) — concorrenza? ripiego best-effort",
                kind, len(new), nb_id)
    return _last_artifact_id(nb_id, kind)


def studio_status(nb_id: str, artifact_id: str, verbose: bool = False) -> dict:
    """Stato di un singolo artefatto (cerca per ID nella lista del NB).

    Default COMPATTO (id/type/status/label): quasi sempre serve solo lo stato.
    `verbose=True` per l'artefatto pieno col focus."""
    for a in studio_list(nb_id, verbose=True):
        if _artifact_id_of(a) == artifact_id:
            return a if verbose else _artifact_compact(a)
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


def studio_rename(nb_id: str, artifact_id: str, new_title: str) -> None:  # noqa: ARG001 (nb_id tenuto per firma MCP)
    # nlm 0.7.x: `studio rename ARTIFACT_ID NEW_TITLE` — l'artifact id è globale,
    # niente notebook (a differenza di `studio delete`, che invece lo vuole).
    # nb_id resta nella firma MCP per coerenza ma NON si inoltra alla CLI: prima
    # veniva passato come posizionale e slittava gli argomenti (studio_rename era
    # inutilizzabile — "unexpected extra argument").
    _run(["studio", "rename", artifact_id, new_title])


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
    # nlm 0.7.7: `download <kind> NOTEBOOK_ID [-o PATH] [--id ARTIFACT]`. NON
    # esiste `--no-progress` (era il motivo per cui studio_download falliva a
    # valle: nel test MCP originale il blocco-approvazione lo mascherava).
    args = ["download", cli_kind, nb_id, "--output", str(output_path)]
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
    """Diagnostica viva: versione vps1777 + nlm + lista NB visibili.

    `vps1777_version` è iniettata a build-time dalla CI di release (env
    VPS1777_VERSION), quindi si aggiorna DA SOLA a ogni update del gateway: una
    sessione che chiama doctor vede sempre la build corrente. `nlm_pinned` è la
    versione del CLI su cui i tool sono contratti (verificata dal contract-test).

    `contract_note` esiste per rompere la dipendenza dalla memoria: i quirk dei
    sottocomandi cambiano fra versioni di nlm, quindi vanno LETTI qui/dagli schemi
    dei tool, non ricordati. Fidati del vivo, non degli appunti.
    """
    info: dict = {
        "vps1777_version": os.environ.get("VPS1777_VERSION", "0.0.0-dev"),
        "nlm_path": NLM,
        "contract_note": (
            "Tool source/studio contratti su nlm 0.7.x e verificati da un "
            "contract-test in CI. Verifica le firme dal vivo (doctor + schemi "
            "dei tool), non da memoria: i quirk cambiano fra versioni di nlm."
        ),
    }
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
        # H40 — visibilità (NON distruttiva) sugli scratch OCR rimasti orfani.
        # doctor osserva; a cancellarli è sweep_ingest_notebooks() su richiesta.
        info["ingest_orphans"] = sum(
            1 for nb in nbs if (nb.get("title") or "").startswith(INGEST_NB_PREFIX))
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
