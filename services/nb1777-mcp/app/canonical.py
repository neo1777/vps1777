"""Il canonico del blocco di memoria 1777 (issue #30 → 0.44.0: nel prodotto).

nb1777 CONOSCE e DICHIARA la versione corrente del blocco di memoria, così una
sessione può accorgersi che la copia che porta è vecchia (la regola FRESCHEZZA,
finalmente applicata al blocco stesso) — e da 0.44.0 può anche CURARSI: con
`full=true` riceve il testo e si allinea in contesto.

DOVE STA LA VERITÀ (0.44.0, 30/08/2026):
- la DISCIPLINA è un file del prodotto, `app/memoria_1777/disciplina.md`, spedito
  dentro l'immagine (COPY app → /app/app). È NEUTRA: vale per qualunque utente.
  La riga di titolo porta versione e data (`canonico vX.Y · YYYY-MM-DD`); il corpo
  ha tre tagli, `## PIENO`, `## LITE`, `## MICRO`.
- i due strati LOCALI dell'installazione — `fatti.md` (chi è l'utente) ed
  `errata.md` (falsi corretti) — vivono nel volume dati, `<nlm_home>/memoria-1777/`,
  fuori dal repo per costruzione (non in .gitignore: in un altro posto), dentro il
  backup notturno cifrato. Si caricano con `vps1777 memoria importa`.
- lo storico v2.2 → v2.4 (11-13/07/2026) resta nel notebook NotebookLM
  `claudemd1777`, in sola lettura: non lo si legge più da qui.

PERCHÉ NON PIÙ IL NOTEBOOK (la scelta di luglio era ragionata: il canonico su
Google sopravviveva al format della VPS del 19/07, un file SULLA VPS no). La
terza via — un file NEL REPO servito dalla VPS — non era sul tavolo e vince su
ogni colonna: sopravvive al format (GitHub + backup), ha storico e diff con
`git log`, non passa da Google, è testabile in CI, non dipende da `nlm`. E il
guadagno più forte non è la privacy: prima una sessione stale sapeva il NUMERO e
non il TESTO — il verdetto senza la cura.

Due proprietà restano non negoziabili:
- **Fail-open**: se il file è illeggibile (impossibile in un'immagine sana, ma
  il contratto vale), nb1777 funziona lo stesso e dichiara `available: false`.
- **Puro dove si può**: il parser del titolo e degli strati non fa I/O — si
  testa con testo.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from .settings import get_settings

log = logging.getLogger("nb1777.canonical")

# Il canonico spedito col prodotto: accanto a questo modulo, dentro il package.
DISCIPLINA_PATH = Path(__file__).resolve().parent / "memoria_1777" / "disciplina.md"

# Gli strati locali, nel volume dati (non nel repo). Sottocartella propria, così
# un `ls` del volume dice cosa c'è e il backup li porta con tutto il resto.
STRATI_LOCALI = ("fatti", "errata")
TAGLI = ("pieno", "lite", "micro")

# `# Disciplina di memoria 1777 — canonico v2.5 · 2026-08-30`. Separatori
# tolleranti (·, —, –, -); la data ISO è obbligatoria: un canonico senza data è
# esattamente ciò che la regola FRESCHEZZA vieta.
_TITOLO_RE = re.compile(
    r"canonico\s+v(\d+)\.(\d+)\s*[·—–-]+\s*(\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)
_SEZIONE_RE = re.compile(r"^##\s+(PIENO|LITE|MICRO|Storia)\s*$", re.MULTILINE)

# Titoli delle fonti del notebook storico: `canonico vX.Y — <data> — <nota>` e
# `cloud-ack vX.Y`. Restano come parser PURI (servono a chi legge lo storico e
# ai test), ma NON sono più la sorgente del canonico né dell'ack.
_CANON_RE = re.compile(
    r"^\s*canonico\s+v(\d+)\.(\d+)\s*[—–-]+\s*"
    r"(\d{4}-\d{2}-\d{2})?\s*[—–-]*\s*(.*)$",
    re.IGNORECASE,
)
_CLOUD_ACK_RE = re.compile(r"^\s*cloud-ack\s+v(\d+)\.(\d+)\b", re.IGNORECASE)


# ── parser PURI ──────────────────────────────────────────────────────────────

def parse_disciplina(testo: str) -> Optional[dict]:
    """Dal testo di disciplina.md → `{version, major, minor, date, note, tagli}`.

    `note` è la prima voce di «## Storia» (cosa cambia nell'ultima versione),
    `tagli` la mappa {pieno, lite, micro} → testo del blocco (senza i commenti
    HTML, che sono per chi legge il file, non per chi lo riceve). None se manca
    il titolo con versione+data."""
    m = _TITOLO_RE.search(testo.splitlines()[0] if testo else "")
    if not m:
        return None
    major, minor = int(m.group(1)), int(m.group(2))
    sezioni = _spezza_sezioni(testo)
    storia = sezioni.get("Storia", "")
    prima_voce = next((r.strip()[2:] for r in storia.splitlines() if r.strip().startswith("- ")), "")
    note = prima_voce.split(" — ", 1)[1] if " — " in prima_voce else (prima_voce or None)
    tagli = {t: _senza_commenti(sezioni.get(t.upper(), "")).strip() for t in TAGLI}
    return {
        "version": f"v{major}.{minor}",
        "major": major,
        "minor": minor,
        "date": m.group(3),
        "note": note,
        "tagli": tagli,
    }


def _spezza_sezioni(testo: str) -> dict[str, str]:
    out: dict[str, str] = {}
    matches = list(_SEZIONE_RE.finditer(testo))
    for i, mm in enumerate(matches):
        fine = matches[i + 1].start() if i + 1 < len(matches) else len(testo)
        out[mm.group(1)] = testo[mm.end():fine]
    return out


def _senza_commenti(testo: str) -> str:
    return re.sub(r"<!--.*?-->\s*", "", testo, flags=re.DOTALL)


def highest_canonical(sources: list[dict]) -> Optional[dict]:
    """Versione canonica più alta fra i titoli delle fonti del notebook STORICO
    (PURA). Confronto NUMERICO (v2.10 > v2.9). Non è più la sorgente del
    canonico: serve a leggere lo storico e a confrontarlo col file."""
    best: Optional[dict] = None
    for s in sources or []:
        m = _CANON_RE.match((s.get("title") or "").strip())
        if not m:
            continue
        major, minor = int(m.group(1)), int(m.group(2))
        if best is None or (major, minor) > (best["major"], best["minor"]):
            best = {
                "version": f"v{major}.{minor}",
                "major": major,
                "minor": minor,
                "date": (m.group(3) or "").strip() or None,
                "note": (m.group(4) or "").strip() or None,
            }
    return best


def highest_cloud_ack(sources: list[dict]) -> Optional[tuple[int, int]]:
    """Versione più alta fra le fonti `cloud-ack vX.Y` (PURA, storico)."""
    best: Optional[tuple[int, int]] = None
    for s in sources or []:
        m = _CLOUD_ACK_RE.match((s.get("title") or "").strip())
        if not m:
            continue
        cand = (int(m.group(1)), int(m.group(2)))
        if best is None or cand > best:
            best = cand
    return best


# ── lettura dal prodotto e dal volume ────────────────────────────────────────

def get_canonical(*, force: bool = False) -> Optional[dict]:
    """Versione canonica corrente, letta dal file del prodotto.

    Fail-open: su qualsiasi errore ritorna None senza sollevare — il canonico
    non deve poter rompere il server. Niente cache: è un file locale, e leggerlo
    a ogni chiamata costa meno di una cache che può mentire dopo un deploy.
    `force` resta nella firma per compatibilità coi chiamanti."""
    try:
        data = parse_disciplina(DISCIPLINA_PATH.read_text(encoding="utf-8"))
    except OSError as exc:
        log.warning("canonico: disciplina.md illeggibile (%s) — fail-open", exc)
        return None
    if data is None:
        log.warning("canonico: disciplina.md senza titolo `canonico vX.Y · data` — fail-open")
    return data


def dir_strati_locali() -> Path:
    return Path(get_settings().nlm_home) / "memoria-1777"


def read_strato(nome: str) -> Optional[str]:
    """Il testo di uno strato locale (`fatti` | `errata`), o None se non c'è.
    Un file assente NON è un errore: è un'installazione che non l'ha ancora
    riempito, e la risposta lo dice."""
    if nome not in STRATI_LOCALI:
        raise ValueError(f"strato sconosciuto: {nome!r} (validi: {', '.join(STRATI_LOCALI)})")
    p = dir_strati_locali() / f"{nome}.md"
    try:
        return p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        log.warning("strato %s illeggibile (%s)", nome, exc)
        return None


def public_view(data: Optional[dict]) -> dict:
    """Proiezione per i tool MCP: niente major/minor interni né tagli. Se `data`
    è None (fail-open), dichiara `available: false` e dove sta la verità."""
    if not data:
        return {
            "available": False,
            "nota": ("canonico non leggibile ora — la disciplina è il file "
                     "app/memoria_1777/disciplina.md dell'immagine nb1777-mcp: "
                     "un'immagine sana lo porta sempre. Segnalalo."),
        }
    return {
        "available": True,
        "version": data["version"],
        "date": data.get("date"),
        "note": data.get("note"),
        "sede": "vps1777 · app/memoria_1777/disciplina.md (servito da questo tool)",
    }


def full_view(data: Optional[dict], *, taglio: str = "pieno") -> dict:
    """`canonico(full=true)`: la cura, non solo il verdetto. Disciplina nel
    taglio chiesto + gli strati locali, ognuno marcato con la sua provenienza —
    così la sessione sa cosa è prodotto (neutro) e cosa è dell'installazione."""
    base = public_view(data)
    if not data:
        return base
    if taglio not in TAGLI:
        return {**base, "errore": f"taglio sconosciuto: {taglio!r} (validi: {', '.join(TAGLI)})"}
    strati = []
    for nome in STRATI_LOCALI:
        testo = read_strato(nome)
        strati.append({
            "strato": nome,
            "presente": testo is not None,
            "origine": f"locale · {dir_strati_locali() / (nome + '.md')} (non nel prodotto)",
            "testo": testo,
        })
    return {
        **base,
        "taglio": taglio,
        "disciplina": data["tagli"].get(taglio, ""),
        "origine_disciplina": "prodotto · neutra · versionata con vps1777",
        "strati": strati,
        "come_usarlo": ("Incolla `disciplina` al posto del blocco che porti (stesso taglio). "
                        "`fatti`/`errata` valgono per questa installazione: leggili, non "
                        "copiarli nel blocco. Se uno strato è assente, chi amministra lo "
                        "carica con `vps1777 memoria importa <fatti|errata> <file>`."),
    }


def declaration_text() -> str:
    """Testo per `FastMCP(instructions=...)` — Veicolo A del canale involontario.

    STATICO di proposito: non porta il numero di versione (che è dinamico) ma
    dice alla sessione che nb1777 lo conosce e come confrontarsi — il numero vivo
    lo dà il tool `canonico`, il testo `canonico(full=true)`."""
    return (
        "MEMORIA 1777 — nb1777 conosce il canonico del blocco di memoria 1777 "
        "(un file del prodotto, non un notebook). Se la versione in testa al blocco "
        "che porti potrebbe essere vecchia, chiama il tool `canonico`: ti dà la "
        "versione canonica attuale e la data. Confrontala con la tua — se sei più "
        "vecchio sei disallineato: dillo a chi ti parla prima di procedere e chiama "
        "`canonico(full=true)` per ricevere il testo e allinearti in contesto. "
        "(nb1777 · canale A/instructions)"
    )
