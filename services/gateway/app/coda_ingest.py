"""coda_ingest — l'indicizzazione di /admin/archive come lavoro a parte (P16, 11/10/2026).

PERCHÉ. Fino alla 0.83 il gateway indicizzava da sé, in un thread (S13): l'event loop
restava libero, ma la MEMORIA no. Un `conversations.json` si carica tutto (json.load):
3,4 volte il file su uno sintetico (221 MB → 745 MB, misurato l'11/10), 4 volte sull'export
vero del 29/08 (297 MB → 1,2 GB, docs/ARCHIVE.md). Dentro il gateway quel picco non aveva
un tetto, e un OOM avrebbe portato via OAuth, il proxy MCP e le pagine.

COME, sul modello del pulsante «Aggiorna» (il gateway scrive un intent, non agisce):
  1. il gateway sposta il file caricato in `/var/lib/archive/coda/<id><ext>` e scrive
     l'intent `onboarding/ingest_coda/<id>.json`;
  2. `vps1777-ingest.path` vede la cartella non vuota e lancia `vps1777 ingest-coda`
     sull'host, che CONSUMA l'intent (lo toglie dalla coda prima di agire, niente giri
     a vuoto) e scrive lo stato in `onboarding/ingest_esiti/<id>.json`;
  3. la CLI fa girare il servizio compose `ingest` (profilo `ingest`, stessa immagine
     del gateway, `mem_limit` suo): se sfora muore lui, non il gateway.
Il gateway legge `ingest_coda/` e `ingest_esiti/` per mostrare lo stato.

Solo stdlib: lo usano la pagina admin e i test, senza servizi.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import time
from pathlib import Path

CODA = "ingest_coda"          # in onboarding/: gli intent in attesa (li guarda la path unit)
ESITI = "ingest_esiti"        # in onboarding/: in corso, fatti, falliti (li scrive la CLI)
CARTELLA_FILE = "coda"        # nel volume dell'archivio, accanto a db/: i file in attesa

ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
DB_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
# le estensioni che l'indexer sa leggere; il .db (drop-in) non passa di qui
SUFFISSI = (".jsonl", ".json", ".zip", ".md", ".txt", ".pdf")
TESTO_MAX = 500               # progetto e descrizione: nell'intent non serve di più
# oltre questa attesa senza che la CLI l'abbia preso, la pagina dice di guardare l'unit
FERMO_DOPO_S = 180
# in ESITI/: lo scrive la CLI finché un lavoro aspetta il lucchetto dell'archivio (l'indice
# notturno sta lavorando sullo stesso volume). Non è un id: lavori() non lo elenca.
ATTESA = "attesa.json"
# un segno d'attesa più vecchio di così non vale (la unit della coda ha un tetto di 12 ore):
# la CLI lo toglie sempre, ma un riavvio a metà lo lascerebbe lì per sempre
ATTESA_VALIDA_S = 13 * 3600


def cartella_file(archive_db_dir: str | Path) -> Path:
    """`/var/lib/archive/coda`, accanto a `db/`: archive-mcp guarda solo `db/`."""
    return Path(archive_db_dir).parent / CARTELLA_FILE


def nuovo_id(adesso: float | None = None) -> str:
    t = time.gmtime(time.time() if adesso is None else adesso)
    return time.strftime("%Y%m%dT%H%M%SZ", t) + "-" + secrets.token_hex(4)


def _scrivi_json(p: Path, dati: dict) -> None:
    # il temporaneo sta FUORI dalla cartella: la path unit scatta su «non vuota», e un
    # .tmp lì dentro la farebbe partire prima del rename (e, orfano, a ripetizione)
    tmp = p.parent.parent / f".{p.parent.name}-{p.name}.tmp"
    tmp.write_text(json.dumps(dati, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # 0640 come l'intent dell'update (H36): niente nonce qui, ma nomi di file e di DB
    # dell'owner non devono essere leggibili da ogni utente dell'host.
    tmp.chmod(0o640)
    tmp.replace(p)


def accoda(onboarding_dir: str | Path, archive_db_dir: str | Path, tmp: Path, *,
           db: str, suffisso: str, nome_file: str, project: str = "",
           description: str = "", by: str = "", adesso: float | None = None) -> str:
    """Sposta `tmp` nella coda e scrive l'intent. Restituisce l'id del lavoro.

    L'ordine conta: prima il file, poi l'intent. Al contrario la CLI potrebbe
    prendere un intent il cui file non c'è ancora."""
    if not DB_RE.match(db):
        raise ValueError(f"nome DB non valido: {db!r}")
    if suffisso not in SUFFISSI:
        raise ValueError(f"formato non accodabile: {suffisso}")
    jid = nuovo_id(adesso)
    dest_dir = cartella_file(archive_db_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{jid}{suffisso}"
    os.replace(tmp, dest)       # stesso volume: un rename, non una copia
    coda = Path(onboarding_dir) / CODA
    coda.mkdir(parents=True, exist_ok=True)
    try:
        _scrivi_json(coda / f"{jid}.json", {
            "id": jid, "db": db, "suffisso": suffisso,
            "file": Path(nome_file).name[:200],
            "project": project[:TESTO_MAX], "description": description[:TESTO_MAX],
            "by": by, "accodato": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() if adesso is None else adesso)),
        })
    except OSError:
        dest.unlink(missing_ok=True)   # un file senza intent non lo prende nessuno
        raise
    return jid


def _leggi(p: Path) -> dict | None:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def in_attesa(onboarding_dir: str | Path, *, adesso: float | None = None) -> str:
    """Chi tiene l'archivio mentre la coda aspetta il suo turno, o '' se non aspetta."""
    p = Path(onboarding_dir) / ESITI / ATTESA
    ora = time.time() if adesso is None else adesso
    try:
        if ora - p.stat().st_mtime > ATTESA_VALIDA_S:
            return ""
    except OSError:
        return ""
    d = _leggi(p)
    return str((d or {}).get("chi") or "un altro lavoro")[:80]


def lavori(onboarding_dir: str | Path, *, limite: int = 12,
           adesso: float | None = None) -> list[dict]:
    """I lavori più recenti, dal più nuovo: quelli in coda e quelli con un esito.

    Ogni voce ha `stato` fra in-coda, in-corso, fatto, errore. Un lavoro in coda da
    più di FERMO_DOPO_S secondi ha `fermo=True`: la CLI non l'ha preso. Se invece la CLI
    l'ha visto e aspetta il lucchetto dell'archivio, `fermo` resta False e `attesa` dice
    chi lo tiene (l'aggiornamento notturno dell'indice, di solito)."""
    ob = Path(onboarding_dir)
    ora = time.time() if adesso is None else adesso
    aspetta = in_attesa(ob, adesso=ora)
    visti: dict[str, dict] = {}
    for cartella, stato_default in ((ob / ESITI, None), (ob / CODA, "in-coda")):
        if not cartella.is_dir():
            continue
        for p in cartella.glob("*.json"):
            if not ID_RE.match(p.stem) or p.stem in visti:
                continue
            d = _leggi(p)
            if d is None:
                continue
            d["id"] = p.stem
            if stato_default:
                d["stato"] = stato_default
                try:
                    d["fermo"] = not aspetta and ora - p.stat().st_mtime > FERMO_DOPO_S
                except OSError:
                    d["fermo"] = False
                if aspetta:
                    d["attesa"] = aspetta
            visti[p.stem] = d
    return [visti[k] for k in sorted(visti, reverse=True)[:limite]]


def qualcuno_aperto(elenco: list[dict]) -> bool:
    return any(d.get("stato") in ("in-coda", "in-corso") for d in elenco)
