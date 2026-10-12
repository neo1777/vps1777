"""La forma di ciò che restituiscono i tool di nb1777 (P8, 11/10/2026).

Misurato l'11/10: 23 tool su 49 senza schema d'uscita, e 4 liste di oggetti generici. Questi
modelli li dichiarano. Tre regole, ognuna provata con FastMCP 1.30 prima di scriverle:

- **BaseModel con `extra="allow"`, non TypedDict.** FastMCP trasforma un TypedDict in un
  modello e butta le chiavi non dichiarate (anche con `extra="allow"`) e mette null nei
  campi NotRequired assenti. Per i tool che passano il JSON di nlm sarebbe una perdita.
- **Niente null in uscita.** I campi facoltativi valgono None quando mancano; la base li
  toglie dal contenuto strutturato (lo schema resta quello dichiarato).
- **Tipi larghi sui campi che vengono da nlm.** Il server valida l'uscita contro lo schema:
  un `int` dichiarato e una stringa arrivata da una versione nuova di nlm farebbero di una
  risposta buona un errore. Sui campi costruiti qui i tipi sono quelli veri.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SerializerFunctionWrapHandler, model_serializer


class Esito(BaseModel):
    """Base: le chiavi in più restano, i campi assenti non diventano null."""
    model_config = ConfigDict(extra="allow")

    @model_serializer(mode="wrap")
    def _senza_null(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        return {k: v for k, v in handler(self).items() if v is not None}


# ── elementi delle liste ───────────────────────────────────────────────────────────────

class Notebook(Esito):
    id: Any = Field(None, description="id del notebook")
    title: Any = None
    source_count: Any = None
    updated_at: Any = None


class Fonte(Esito):
    id: Any = Field(None, description="id della fonte")
    title: Any = None
    type: Any = None
    url: Any = None
    status: Any = None


class Nota(Esito):
    id: Any = Field(None, description="id della nota")
    title: Any = None
    preview: Any = Field(None, description="i primi 200 caratteri (senza verbose)")
    content: Any = Field(None, description="il testo intero (con verbose)")


class Artefatto(Esito):
    id: Any = Field(None, description="id dell'artefatto dello Studio")
    type: Any = None
    status: Any = None
    label: Any = None


# ── notebook e fonti ───────────────────────────────────────────────────────────────────

class NotebookDettaglio(Esito):
    notebook_id: Any = None
    title: Any = None
    source_count: Any = None
    url: Any = None
    sources: Any = Field(None, description="[{id, title}]")
    emoji: Any = None


class Cancellazione(Esito):
    """Le cancellazioni in due tempi: senza `conferma` l'anteprima e il gettone, con il
    gettone `cancellato: true`."""
    cancellato: bool
    anteprima: Any = Field(None, description="cosa sparirebbe (solo nel primo tempo)")
    conferma: str | None = Field(None, description="il gettone da ripassare, 5 minuti")
    scade_tra_s: int | None = None
    come: str | None = None
    notebook_id: str | None = None
    source_id: str | None = None
    note_id: str | None = None
    artifact_id: str | None = None


class LinkCaricamento(Esito):
    url: str
    scade_il: Any = None
    notebook: Any = Field(None, description="il titolo del notebook")
    come: str | None = None


# ── domande e lavori ───────────────────────────────────────────────────────────────────

class Risposta(Esito):
    """notebook_query e notebook_query_esito: la risposta, o `stato: in_corso` col query_id."""
    stato: str | None = Field(None, description="'in_corso' se NotebookLM non ha finito")
    query_id: str | None = None
    answer: Any = None
    references: Any = Field(None, description="[{citation_number, source_id, anteprima}]")
    sources_used: Any = None
    senza_citazioni: Any = Field(None, description="{paragrafi, su_totale, anteprime}")
    conversation_id: Any = None
    nota: str | None = None
    raw: Any = Field(None, description="la risposta di nlm, se non si è potuta leggere")


class Lavoro(Esito):
    """Un lavoro lungo (P6): `stato: in_corso` col job_id, o il risultato del lavoro."""
    stato: str | None = None
    job_id: str | None = None
    lavoro: str | None = None
    nota: str | None = None
    risultato: Any = Field(None, description="il risultato quando non è un oggetto (raro)")


class FonteAggiunta(Lavoro):
    """source_add_*: l'id della fonte nuova, oppure `stato: in_corso` col job_id."""
    source_id: Any = Field(None, description="l'id della fonte aggiunta")


class Ricerca(Esito):
    """research_start, research_status e research_import (services.research di nlm)."""
    task_id: Any = None
    status: Any = None
    sources_found: Any = None
    sources: Any = None
    report: Any = None
    imported_count: Any = None
    richieste: int | None = None
    nota: str | None = None


class NotaSalvata(Esito):
    note_id: Any = None
    creata: bool | None = None


class Cronologia(Esito):
    notebook_id: Any = None
    notebook_title: Any = None
    sessions: Any = Field(None, description="[{conversation_id, turn_count, preview, is_active}]")
    transcript: Any = Field(None, description="[{turn, query, answer}], con conversation_id")


# ── studio ─────────────────────────────────────────────────────────────────────────────

class StudioTutti(Esito):
    """studio_create_all_9: un esito per tipo di artefatto, o `stato: in_corso`."""
    stato: str | None = None
    job_id: str | None = None


class ArtefattoAttesa(Artefatto):
    in_corso: bool | None = None
    nota: str | None = None


class Scaricato(Esito):
    name: Any = None
    bytes: Any = None
    download_url: Any = None
    link: Any = Field(None, description="link firmato per scaricarlo da fuori (P15)")
    nota: str | None = None
    stato: str | None = None
    job_id: str | None = None


class Censimento(Scaricato):
    """nb_export e censimento (P14): il file JSON sul server e il link per scaricarlo."""
    notebooks: int | None = None
    fonti: int | None = None
    errori: int | None = None


class Descrizione(Esito):
    """source_describe: il riassunto di Gemini e le parole chiave (forma di nlm 0.15)."""
    summary: Any = None
    keywords: Any = None


class Sostituzione(Esito):
    """source_replace (P20): la prima chiamata dà l'anteprima e il gettone, la seconda la
    fonte nuova. L'id cambia sempre: NotebookLM non modifica una fonte, ne aggiunge una."""
    sostituita: str | None = Field(None, description="l'id della fonte tolta")
    source_id: Any = Field(None, description="l'id della fonte nuova")
    id_cambiato: bool | None = None
    vecchia_cancellata: bool | None = None
    avviso: str | None = None
    anteprima: Any = None
    conferma: str | None = None
    scade_tra_s: int | None = None


class FonteDrive(Esito):
    """source_drive_stato (P20): una fonte Drive e se il documento su Drive è più nuovo."""
    source_id: Any = None
    title: Any = None
    tipo: Any = None
    indietro: bool | None = Field(None, description="True = su Drive c'è una versione più nuova")


class SyncDrive(Esito):
    """source_sync_drive (P20): quante fonti si sono riallineate (stesso id)."""
    chieste: int | None = None
    sincronizzate: int | None = None
    source_ids: list[str] | None = None


# ── i tool che rispondevano una stringa (11/10/2026, dopo P20) ─────────────────────────
# Diciassette tool davano «ok», un id nudo o il JSON di nlm COME TESTO (source_get_content):
# chi chiama doveva indovinare la forma. Ora dicono cosa hanno fatto e su cosa.

class NotebookCreato(Esito):
    notebook_id: Any = Field(None, description="l'id del notebook nuovo")
    title: Any = None


class Rinominato(Esito):
    """nb_rename, source_rename, studio_rename: l'id e il titolo nuovo."""
    id: Any = None
    title: Any = None
    rinominato: bool | None = None


class DescrizioneNotebook(Esito):
    """nb_describe: il riassunto di Gemini (forma di nlm); `testo` se nlm non dà JSON."""
    summary: Any = None
    suggested_topics: Any = None
    testo: str | None = None


class Contenuto(Esito):
    """source_get_content: il testo indicizzato della fonte, senza elaborazione AI."""
    content: Any = None
    title: Any = None
    source_type: Any = None
    char_count: Any = None
    url: Any = None


class ArtefattoCreato(Esito):
    """studio_create_*: l'artefatto è partito; lo stato con studio_status o studio_wait."""
    artifact_id: Any = Field(None, description="l'id dell'artefatto")
    notebook_id: Any = None
    tipo: str | None = None


class Esportazione(Esito):
    """studio_export_to_docs / _sheets: il documento creato."""
    url: Any = Field(None, description="l'indirizzo del documento Google")
    artifact_id: Any = None


# ── salute e memoria ───────────────────────────────────────────────────────────────────

class Quota(Esito):
    windows: Any = None
    tier: Any = None


class Doctor(Esito):
    vps1777_version: Any = None
    version: Any = None
    sonda: Any = None
    notebooks_count: Any = None
    quota: Any = None
    canonico: Any = None


class Canonico(Esito):
    available: bool | None = None
    version: Any = None
    date: Any = None
    note: Any = None
    sede: Any = None
    nota: Any = None


class MemoriaCheck(Esito):
    canonico: Any = None
    data: Any = None
    portata: Any = None
    stale: bool | None = None
    delta: Any = None
    nota: Any = None


class MemoriaAck(Esito):
    ok: bool | None = None
    acked: Any = None
    canonico: Any = None
    allineato: bool | None = None
