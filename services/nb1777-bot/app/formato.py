"""Le parti pure del bot (stdlib): leggere la risposta MCP, i notebook, la tastiera, la risposta.

P12 (11/10/2026). Il parsing è lo stesso del client MCP del gateway
(`services/gateway/app/miniapp_core.py`: parse_mcp_payload, extract_tool_texts): il bot è
un'immagine a sé e non può importarlo, quindi lo ripete qui, con una differenza voluta.
Ogni guasto diventa `ErroreMCP` con un messaggio da mostrare a Neo: fino alla 0.80 un
errore del tool arrivava come «Risposta vuota.».
"""
from __future__ import annotations

import html
import json
import re
from typing import Any

PER_PAGINA = 8
TITOLO_MAX = 48
TETTO_MESSAGGIO = 4000          # Telegram ne accetta 4096: un margine per le entità
_ID_NOTEBOOK = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                          re.IGNORECASE)
_GRASSETTO = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_TAG = re.compile(r"</?(?:b|i)>")


class ErroreMCP(Exception):
    """Un guasto della chiamata o del tool, col messaggio da mostrare così com'è."""


# ── la risposta MCP ─────────────────────────────────────────────────────────────

def payload_rpc(content_type: str, testo: str) -> dict:
    """Il JSON-RPC di una risposta streamable-http (SSE con la riga `data:`, o JSON)."""
    if "text/event-stream" in (content_type or ""):
        for riga in testo.splitlines():
            if riga.startswith("data:") and riga[5:].strip():
                testo = riga[5:].strip()
                break
        else:
            raise ErroreMCP("risposta di nb1777 senza payload (SSE senza 'data:')")
    try:
        rpc = json.loads(testo)
    except ValueError as exc:
        raise ErroreMCP(f"la risposta di nb1777 non è JSON: {testo[:120]!r}") from exc
    if not isinstance(rpc, dict):
        raise ErroreMCP("la risposta di nb1777 non è un oggetto JSON-RPC")
    return rpc


def testi(rpc: dict) -> list[str]:
    """I blocchi di testo del risultato. Un errore JSON-RPC o un tool fallito (`isError`)
    sollevano ErroreMCP col loro messaggio."""
    if "error" in rpc:
        errore = rpc["error"]
        messaggio = errore.get("message", errore) if isinstance(errore, dict) else errore
        raise ErroreMCP(str(messaggio)[:500])
    risultato = rpc.get("result") or {}
    blocchi = [b.get("text", "") for b in risultato.get("content") or []
               if isinstance(b, dict) and b.get("type", "text") == "text"]
    if risultato.get("isError"):
        raise ErroreMCP((blocchi[0] if blocchi else "il tool ha dato errore")[:500])
    return blocchi


def blocchi_json(blocchi: list[str]) -> list[dict]:
    """I blocchi come oggetti JSON: un oggetto per blocco o un blocco con un array."""
    out: list[dict] = []
    for b in blocchi:
        try:
            obj = json.loads(b)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, list):
            out.extend(x for x in obj if isinstance(x, dict))
        elif isinstance(obj, dict):
            out.append(obj)
    return out


# ── i notebook e la tastiera ───────────────────────────────────────────────────

def notebook(blocchi: list[str]) -> list[dict]:
    """[{id, title}] dalla risposta di nb_list."""
    return [{"id": str(n["id"]), "title": str(n.get("title") or "")}
            for n in blocchi_json(blocchi) if n.get("id")]


def e_id_notebook(testo: str) -> bool:
    return bool(_ID_NOTEBOOK.match(testo or ""))


def _etichetta(titolo: str) -> str:
    titolo = " ".join(titolo.split()) or "(senza titolo)"
    return titolo if len(titolo) <= TITOLO_MAX else titolo[:TITOLO_MAX - 1] + "…"


def tastiera(nbs: list[dict], pagina: int = 0) -> list[list[tuple[str, str]]]:
    """Righe di bottoni (testo, callback_data): un notebook per riga, PER_PAGINA a
    pagina, poi «‹ indietro» / «altri ›». `nb:<id>` sceglie, `nbp:<n>` cambia pagina
    (un id di 36 caratteri sta nei 64 byte di callback_data)."""
    pagine = max(1, -(-len(nbs) // PER_PAGINA))
    pagina = min(max(0, pagina), pagine - 1)
    righe = [[(_etichetta(n["title"]), f"nb:{n['id']}")]
             for n in nbs[pagina * PER_PAGINA:(pagina + 1) * PER_PAGINA]]
    navigazione = []
    if pagina > 0:
        navigazione.append(("‹ indietro", f"nbp:{pagina - 1}"))
    if pagina < pagine - 1:
        navigazione.append(("altri ›", f"nbp:{pagina + 1}"))
    if navigazione:
        righe.append(navigazione)
    return righe


# ── la risposta di notebook_query ──────────────────────────────────────────────

def _testo_della_risposta(answer: Any) -> str:
    """notebook_query può incapsulare il testo in JSON ({"answer": …})."""
    if not isinstance(answer, str):
        return ""
    try:
        obj = json.loads(answer)
    except (ValueError, TypeError):
        return answer
    if isinstance(obj, dict) and isinstance(obj.get("answer"), str):
        return obj["answer"]
    return answer


def risposta_html(payload: dict, titoli: dict[str, str]) -> str:
    """La risposta per Telegram (parse_mode HTML): il testo con l'HTML neutralizzato e il
    **grassetto** di NotebookLM reso, poi le fonti, una per riga coi loro numeri di
    citazione, poi la nota sui paragrafi senza citazioni. `titoli` = source_id → titolo
    (vuoto se la lista delle fonti non si è letta: resta l'id)."""
    testo = _testo_della_risposta(payload.get("answer")).strip()
    if not testo:
        corpo = "<i>NotebookLM non ha restituito nessun testo.</i>"
    else:
        corpo = _GRASSETTO.sub(r"<b>\1</b>", html.escape(testo, quote=False))
    numeri: dict[str, list[int]] = {}
    for r in payload.get("references") or []:
        if isinstance(r, dict) and r.get("source_id"):
            n = r.get("citation_number")
            lista = numeri.setdefault(str(r["source_id"]), [])
            if isinstance(n, int) and n not in lista:
                lista.append(n)
    parti = [corpo]
    if numeri:
        righe = []
        for sid, ns in numeri.items():
            titolo = titoli.get(sid) or f"fonte {sid}"
            righe.append(f"[{', '.join(str(n) for n in sorted(ns))}] "
                         f"{html.escape(titolo, quote=False)}")
        parti.append("<b>Fonti</b>\n" + "\n".join(righe))
    if isinstance(payload.get("senza_citazioni"), dict) and payload.get("nota"):
        parti.append(f"<i>{html.escape(str(payload['nota']), quote=False)}</i>")
    return "\n\n".join(parti)


def spezza(testo: str, tetto: int = TETTO_MESSAGGIO) -> list[str]:
    """Il testo in messaggi da al massimo `tetto` caratteri, tagliando fra i paragrafi.
    Un paragrafo più lungo del tetto si taglia a pezzi senza tag: un <b> aperto in un
    messaggio e chiuso nel successivo farebbe rifiutare a Telegram tutti e due."""
    pezzi: list[str] = []
    corrente = ""
    for paragrafo in testo.split("\n\n"):
        if len(paragrafo) > tetto:
            if corrente:
                pezzi.append(corrente)
                corrente = ""
            nudo = _TAG.sub("", paragrafo)
            pezzi.extend(nudo[i:i + tetto] for i in range(0, len(nudo), tetto))
            continue
        candidato = f"{corrente}\n\n{paragrafo}" if corrente else paragrafo
        if len(candidato) > tetto:
            pezzi.append(corrente)
            corrente = paragrafo
        else:
            corrente = candidato
    if corrente:
        pezzi.append(corrente)
    return pezzi
