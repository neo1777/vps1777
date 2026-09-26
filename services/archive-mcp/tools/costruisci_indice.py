#!/usr/bin/env python3
"""Costruttore dell'indice vettoriale della ricerca ibrida: `<db>.vec.db`.

PERCHÉ ESISTE (issue #281, «livello 2, parte b»)
────────────────────────────────────────────────
Il server (`app/semantica.py`, `app/db.py`) LEGGE l'indice; fino a qui nessun
codice del repo lo SCRIVEVA. Viveva fuori, come prototipo del POC, con quattro
difetti che questo file esiste per chiudere:

1. **DB sorgente scritto nel codice.** Qui è un argomento, e il DB si apre in
   SOLA LETTURA (`mode=ro`): il costruttore non può toccare l'archivio.
2. **Perimetro per sola finestra di ts, e le righe senza ts non entravano MAI**
   — in silenzio. Qui il perimetro è dichiarato e parametrico (finestra di ts,
   etichette `project` anche per prefisso come `recupero:*`, oppure tutto), e se
   la finestra lascia fuori righe senza ts il costruttore si FERMA e chiede di
   scegliere (`--senza-ts includi|escludi`), dicendo quante sono.
3. **Nessuno script scriveva `indice_meta`** (fu aggiunta a mano). Qui la scrive
   il costruttore a ogni passaggio: perimetro, modello e sua impronta, conteggi,
   data, versione del costruttore, esito dell'ultimo passaggio.
4. **L'indice è legato al rowid**, e l'indexer fa `INSERT OR REPLACE` sull'uuid:
   un re-ingest dà rowid NUOVI alle righe rimpiazzate. Il vecchio vettore resta
   appeso a un rowid che non esiste più (il server lo scarta: risultato che
   sparisce in silenzio) o — peggio — a un rowid RIUSATO da un altro messaggio
   (il server serve il messaggio sbagliato per il senso di un altro). Qui ogni
   messaggio indicizzato ha una riga nel registro `indice_righe` (rowid, uuid,
   impronta del testo, intervallo dei suoi vettori): l'incrementale confronta il
   registro col DB e rimuove/ricalcola ciò che non combacia più, e lo DICE coi
   numeri.

IL CONTRATTO COL SERVER (il punto critico)
──────────────────────────────────────────
Un indice costruito con un metro diverso da quello della query produce vicini
insensati SENZA errori. Per questo tutto ciò che definisce il metro si importa
da `app/semantica.py`, non si ricopia: il modello si apre con
`semantica.apri_modello` e si interroga con `semantica.codifica` — le STESSE
funzioni di `embed_query` —, il prefisso è `semantica.PREFISSO_PASSAGGIO`
(gemello di `PREFISSO_QUERY`), la tabella è `semantica.TABELLA`, la dimensione
`semantica.DIM`. Lo schema scritto è quello che il server legge:
`vec0(embedding float[384], +msg_rowid integer)` e `indice_meta(chiave, valore)`.
Il registro `indice_righe` è una tabella IN PIÙ: il server non la legge, e un
indice che la porta resta identico per lui.

DOVE GIRA
─────────
Sul PC, non sulla VPS: indicizzare il corpus costa decine di ore di CPU. Gira
nell'ambiente DEL LOCK di archive-mcp — stesse versioni di onnxruntime,
tokenizers e sqlite-vec che il server usa per leggere — e per questo sta in
questo servizio e non in `tools/` alla radice (stdlib-only). Non entra
nell'immagine: il Dockerfile copia solo `app/`.

    cd services/archive-mcp
    uv sync --frozen
    uv run python tools/costruisci_indice.py --db /percorso/archivio.db \\
        --modello /percorso/e5-small --dal 2026-05 --al 2026-07 --senza-ts escludi

ESITO  0 = indice scritto (o, con --controlla, in pari col DB)
       1 = solo con --controlla: l'indice NON è in pari (i numeri dicono perché)
       2 = rifiutato o non misurabile (il messaggio dice cosa manca e come rimediare)
     130 = interrotto: il lavoro fatto resta nel `.parziale`, si riprende rilanciando
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import struct
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Protocol

_SERVIZIO = Path(__file__).resolve().parents[1]
if str(_SERVIZIO) not in sys.path:
    sys.path.insert(0, str(_SERVIZIO))

from app import semantica  # noqa: E402 — dopo il sys.path, di proposito

VERSIONE = "1.0"

# Il chunking del POC, misurato: 1400 caratteri ≈ 400-460 token e5 (dentro i
# 512), overlap 200, al più 12 pezzi per messaggio. È ciò che ha raddoppiato il
# recall sui messaggi lunghi: il succo oltre gli 800 caratteri torna raggiungibile.
CHUNK_CAR = 1400
CHUNK_OVERLAP = 200
CHUNK_MAX = 12
TESTO_MIN = 40               # sotto, un messaggio non porta senso da cercare
CHUNK_DICHIARATO = f"{CHUNK_CAR}/overlap {CHUNK_OVERLAP}/cap {CHUNK_MAX}"

LOTTO = 96                   # pezzi per chiamata al modello (e per transazione)
_PAGINA_SQL = 500            # rowid per `IN (...)`: sotto il limite di SQLite

_SCHEMA_REGISTRO = """
CREATE TABLE IF NOT EXISTS indice_righe(
    msg_rowid   INTEGER PRIMARY KEY,   -- il rowid di `messages` quando è stato indicizzato
    uuid        TEXT NOT NULL,         -- chi era, in quel momento, a quel rowid
    impronta    TEXT NOT NULL,         -- sha256 (32 hex) del testo indicizzato
    primo_chunk INTEGER NOT NULL,      -- rowid del primo vettore nella tabella vec0
    n_chunk     INTEGER NOT NULL       -- vettori contigui da primo_chunk
);
CREATE TABLE IF NOT EXISTS indice_meta(chiave TEXT PRIMARY KEY, valore TEXT);
"""


class ErroreCostruttore(RuntimeError):
    """Rifiuto parlante: cosa non va, e come si rimedia. Esce con 2."""


class Embedder(Protocol):
    """Ciò che serve al costruttore da un modello. Il vero è `EmbedderOnnx`; i
    test ne iniettano uno finto e deterministico, così CI non scarica 449 MB."""

    nome: str                # il modello dichiarato in `indice_meta.modello`
    impronta: str            # cambia se cambia il file del modello

    def __call__(self, testi: list[str]) -> list[bytes]: ...


# ── il testo di un messaggio ─────────────────────────────────────────────────

def spoglia(raw: str | None) -> str:
    """Da un campo JSON (tools, attachments) le sole STRINGHE, senza i payload
    binari (data-URI, PNG in base64). Il testo utile vive anche nei tool-call:
    un indice sul solo `content` è cieco proprio dove la scoperta serve (POC).
    Se il campo non è JSON, è già testo: passa com'è."""
    if not raw:
        return ""
    try:
        obj = json.loads(raw)
    except (ValueError, TypeError):
        return raw
    out: list[str] = []

    def cammina(o: Any) -> None:
        if isinstance(o, str):
            if len(o) > 3 and not o.startswith(("data:", "iVBOR")):
                out.append(o)
        elif isinstance(o, dict):
            for v in o.values():
                cammina(v)
        elif isinstance(o, list):
            for v in o:
                cammina(v)

    cammina(obj)
    return "\n".join(out)


def testo_indicizzabile(content: str | None, attachments: str | None,
                        tools: str | None) -> str:
    """content + attachments + tools spogliati: lo stesso testo del POC, così
    un indice nuovo e uno del POC sono confrontabili vettore per vettore."""
    parti = (content or "", spoglia(attachments), spoglia(tools))
    return "\n".join(x for x in parti if x).strip()


def pezzi(testo: str) -> list[str]:
    """Finestre di CHUNK_CAR caratteri con CHUNK_OVERLAP di sovrapposizione, al
    più CHUNK_MAX. Un testo lungo almeno TESTO_MIN dà sempre almeno un pezzo."""
    passo = CHUNK_CAR - CHUNK_OVERLAP
    out: list[str] = []
    for k in range(CHUNK_MAX):
        pezzo = testo[k * passo: k * passo + CHUNK_CAR]
        if len(pezzo) < TESTO_MIN:
            break
        out.append(pezzo)
        if k * passo + CHUNK_CAR >= len(testo):
            break
    return out


def impronta_testo(testo: str) -> str:
    return hashlib.sha256(testo.encode("utf-8", "surrogatepass")).hexdigest()[:32]


# ── il perimetro ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Perimetro:
    """Quali righe di `messages` entrano nell'indice. Si dichiara SEMPRE: un
    indice parziale che non dice il proprio perimetro produce zeri che sembrano
    assenze (e il server restituisce `perimetro` a ogni ricerca apposta)."""

    tutto: bool = False
    dal: str = ""                       # ts >= dal
    al: str = ""                        # ts <  al
    progetti: tuple[str, ...] = ()      # esatti, o prefissi se finiscono in `*`
    senza_ts: str = ""                  # "", "includi", "escludi" — solo con una finestra

    @property
    def ha_finestra(self) -> bool:
        return bool(self.dal or self.al)

    def valida(self) -> None:
        if not (self.tutto or self.ha_finestra or self.progetti):
            raise ErroreCostruttore(
                "Perimetro non dichiarato. Scegli cosa indicizzare:\n"
                "  --tutto                         tutto il DB\n"
                "  --dal 2026-05 --al 2026-07      una finestra di ts (al escluso)\n"
                "  --project recupero:*            etichette project (ripetibile; `*` = prefisso)\n"
                "Un indice senza perimetro dichiarato è il difetto che questo strumento chiude.")
        if self.tutto and (self.ha_finestra or self.progetti):
            raise ErroreCostruttore(
                "--tutto non si combina con --dal/--al/--project: o tutto, o un filtro.")
        if self.dal and self.al and self.dal >= self.al:
            raise ErroreCostruttore(
                f"Finestra vuota: --dal {self.dal!r} non è prima di --al {self.al!r} "
                "(il confronto è sulla stringa ISO, e `al` è escluso).")
        if self.senza_ts not in ("", "includi", "escludi"):
            raise ErroreCostruttore(f"--senza-ts vuole includi|escludi, non {self.senza_ts!r}")
        if self.senza_ts and not self.ha_finestra:
            raise ErroreCostruttore(
                "--senza-ts ha senso solo con --dal/--al: senza una finestra di ts "
                "le righe senza ts entrano già (nessun filtro le esclude).")
        for p in self.progetti:
            if not p or p == "*":
                raise ErroreCostruttore(
                    f"--project {p!r} non seleziona un'etichetta: per tutto usa --tutto.")

    def _filtro_progetti(self) -> tuple[str, list[str]]:
        if not self.progetti:
            return "", []
        pezzi_sql, par = [], []
        for p in self.progetti:
            if p.endswith("*"):
                base = p[:-1].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                pezzi_sql.append("project LIKE ? ESCAPE '\\'")
                par.append(base + "%")
            else:
                pezzi_sql.append("project = ?")
                par.append(p)
        return "(" + " OR ".join(pezzi_sql) + ")", par

    def _filtro_finestra(self) -> tuple[str, list[str]]:
        cond, par = [], []
        if self.dal:
            cond.append("ts >= ?")
            par.append(self.dal)
        if self.al:
            cond.append("ts < ?")
            par.append(self.al)
        return " AND ".join(cond), par

    def where(self, *, senza_ts: str | None = None) -> tuple[str, list[str]]:
        """La clausola WHERE (senza la parola) e i suoi parametri."""
        scelta = self.senza_ts if senza_ts is None else senza_ts
        clausole, par = [], []
        fp, pp = self._filtro_progetti()
        if fp:
            clausole.append(fp)
            par += pp
        if self.ha_finestra:
            ff, pf = self._filtro_finestra()
            if scelta == "includi":
                clausole.append(f"(({ff}) OR ts IS NULL OR ts = '')")
            else:
                clausole.append(f"({ff})")
            par += pf
        return (" AND ".join(clausole) or "1"), par

    def where_senza_ts(self) -> tuple[str, list[str]]:
        """Le righe che la finestra lascerebbe fuori perché non hanno ts."""
        fp, pp = self._filtro_progetti()
        cond = "(ts IS NULL OR ts = '')"
        return ((f"{fp} AND " if fp else "") + cond), pp

    def descrizione(self, n_senza_ts: int) -> str:
        """La stringa che il server restituisce in `indici[].perimetro`."""
        if self.tutto:
            return "tutto il DB"
        parti = []
        if self.progetti:
            parti.append("project: " + " | ".join(self.progetti))
        if self.ha_finestra:
            ff, pf = self._filtro_finestra()
            for v in pf:
                ff = ff.replace("?", v, 1)
            parti.append(ff)
            if n_senza_ts:
                stato = "incluse" if self.senza_ts == "includi" else "escluse"
                parti.append(f"righe senza ts: {stato} ({n_senza_ts})")
        return " · ".join(parti)

    def come_json(self) -> str:
        return json.dumps({"tutto": self.tutto, "dal": self.dal, "al": self.al,
                           "progetti": list(self.progetti), "senza_ts": self.senza_ts},
                          ensure_ascii=False, sort_keys=True)

    @classmethod
    def da_json(cls, testo: str) -> "Perimetro":
        d = json.loads(testo)
        return cls(tutto=bool(d.get("tutto")), dal=d.get("dal", ""), al=d.get("al", ""),
                   progetti=tuple(d.get("progetti", ())), senza_ts=d.get("senza_ts", ""))


@dataclass
class Bersaglio:
    """Ciò che il perimetro chiede OGGI al DB: rowid → (uuid, impronta del testo)."""

    righe: dict[int, tuple[str, str]]
    nel_perimetro: int
    corti: int
    senza_ts: int                       # righe senza ts nel resto del filtro (0 se non c'è finestra)
    db_righe: int
    db_max_rowid: int


def apri_sorgente(db: Path) -> sqlite3.Connection:
    """Il DB dell'archivio in SOLA LETTURA: il costruttore non può scriverci."""
    if not db.is_file():
        raise ErroreCostruttore(f"DB sorgente assente: {db}")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        colonne = {r[1] for r in conn.execute("PRAGMA table_info(messages)")}
    except sqlite3.DatabaseError as exc:
        conn.close()
        raise ErroreCostruttore(f"{db} non è un DB SQLite leggibile: {exc}") from exc
    attese = {"uuid", "project", "ts", "content", "tools", "attachments"}
    if not attese <= colonne:
        conn.close()
        raise ErroreCostruttore(
            f"{db} non ha la tabella `messages` di un archivio (mancano: "
            f"{', '.join(sorted(attese - colonne)) or 'la tabella'}).")
    return conn


def analizza(src: sqlite3.Connection, perim: Perimetro) -> Bersaglio:
    """Legge il perimetro e ne calcola le impronte. Non tiene i testi in memoria
    (276k messaggi sarebbero centinaia di MB): li rilegge chi li indicizza."""
    perim.valida()
    n_senza_ts = 0
    if perim.ha_finestra:
        w, p = perim.where_senza_ts()
        n_senza_ts = src.execute(f"SELECT count(*) FROM messages WHERE {w}", p).fetchone()[0]
        if n_senza_ts and not perim.senza_ts:
            raise ErroreCostruttore(
                f"La finestra di ts lascerebbe fuori {n_senza_ts} righe SENZA ts "
                "(nel resto del filtro): col prototipo non entravano mai, e nessuno lo diceva.\n"
                "Decidi tu, e la scelta finisce nel perimetro dichiarato:\n"
                "  --senza-ts includi    entrano anche loro\n"
                "  --senza-ts escludi    restano fuori, contate in `indice_meta.perimetro`")
    w, p = perim.where()
    righe: dict[int, tuple[str, str]] = {}
    nel = corti = 0
    for rid, uuid, c, a, t in src.execute(
            f"SELECT rowid, uuid, content, attachments, tools FROM messages WHERE {w}", p):
        nel += 1
        testo = testo_indicizzabile(c, a, t)
        if len(testo) < TESTO_MIN:
            corti += 1
            continue
        righe[rid] = (uuid, impronta_testo(testo))
    db_righe, db_max = src.execute("SELECT count(*), coalesce(max(rowid), 0) FROM messages").fetchone()
    return Bersaglio(righe, nel, corti, n_senza_ts, db_righe, db_max)


def testi_per_rowid(src: sqlite3.Connection, rowids: list[int]) -> Iterator[tuple[int, str, str]]:
    """(rowid, uuid, testo) per i rowid dati, a pagine, nell'ordine dato."""
    for i in range(0, len(rowids), _PAGINA_SQL):
        pagina = rowids[i:i + _PAGINA_SQL]
        seg = ",".join("?" * len(pagina))
        per = {r[0]: r for r in src.execute(
            f"SELECT rowid, uuid, content, attachments, tools FROM messages "
            f"WHERE rowid IN ({seg})", pagina)}
        for rid in pagina:
            r = per.get(rid)
            if r is not None:
                yield rid, r[1], testo_indicizzabile(r[2], r[3], r[4])


# ── l'indice ─────────────────────────────────────────────────────────────────

def _carica_vec(conn: sqlite3.Connection) -> None:
    try:
        import sqlite_vec
    except ImportError as exc:
        raise ErroreCostruttore(
            f"sqlite-vec non installato ({exc}). Il costruttore gira nell'ambiente del "
            "lock di archive-mcp: `cd services/archive-mcp && uv sync --frozen && "
            "uv run python tools/costruisci_indice.py …`") from exc
    conn.enable_load_extension(True)
    try:
        sqlite_vec.load(conn)
    finally:
        conn.enable_load_extension(False)


def leggi_meta(conn: sqlite3.Connection) -> dict[str, str]:
    try:
        return {k: v for k, v in conn.execute("SELECT chiave, valore FROM indice_meta")}
    except sqlite3.OperationalError:
        return {}


def ha_registro(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND "
                        "name='indice_righe'").fetchone() is not None


def _parametri_metro(embedder_nome: str, embedder_impronta: str) -> dict[str, str]:
    """Ciò che, se cambia, rende i vettori vecchi e nuovi INCONFRONTABILI."""
    return {"modello": embedder_nome, "modello_impronta": embedder_impronta,
            "dim": str(semantica.DIM), "tabella": semantica.TABELLA,
            "chunk": CHUNK_DICHIARATO, "prefisso": semantica.PREFISSO_PASSAGGIO}


def _controlla_metro(meta: dict[str, str], atteso: dict[str, str], dove: Path) -> None:
    diversi = [f"{k}: indice {meta.get(k, '(assente)')!r} ≠ ora {v!r}"
               for k, v in atteso.items() if meta.get(k) != v]
    if diversi:
        raise ErroreCostruttore(
            f"{dove.name} è stato costruito con un metro diverso:\n  "
            + "\n  ".join(diversi)
            + "\nMescolare vettori di due metri dà vicini insensati senza errori. "
            "Serve una ricostruzione completa: --ricostruisci.")


def _crea_indice(conn: sqlite3.Connection, metro: dict[str, str], perim: Perimetro) -> None:
    conn.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS {semantica.TABELLA} USING "
                 f"vec0(embedding float[{semantica.DIM}], +msg_rowid integer)")
    conn.executescript(_SCHEMA_REGISTRO)
    conn.executemany("INSERT OR REPLACE INTO indice_meta(chiave, valore) VALUES (?, ?)",
                     [*metro.items(), ("stato", "in costruzione"),
                      # già qui: una costruzione interrotta si riprende senza ridirlo
                      ("perimetro_json", perim.come_json()),
                      ("costruttore", f"costruisci_indice {VERSIONE}")])
    conn.commit()


@dataclass
class Differenza:
    """Registro dell'indice contro il DB di oggi, per categoria (rowid)."""

    invariati: list[int] = field(default_factory=list)
    nuovi: list[int] = field(default_factory=list)
    cambiati: list[int] = field(default_factory=list)      # stesso uuid, testo diverso
    riassegnati: list[int] = field(default_factory=list)   # stesso rowid, uuid diverso
    orfani: list[int] = field(default_factory=list)        # rowid sparito dal DB
    usciti: list[int] = field(default_factory=list)        # stesso uuid, fuori perimetro o ora corto

    @property
    def da_togliere(self) -> list[int]:
        return self.cambiati + self.riassegnati + self.orfani + self.usciti

    def da_indicizzare(self, bersaglio: Bersaglio) -> list[int]:
        return sorted(self.nuovi + self.cambiati
                      + [r for r in self.riassegnati if r in bersaglio.righe])

    def numeri(self) -> dict[str, int]:
        return {k: len(getattr(self, k)) for k in
                ("invariati", "nuovi", "cambiati", "riassegnati", "orfani", "usciti")}


def differenza(registro: dict[int, tuple[str, str]], bersaglio: Bersaglio,
               src: sqlite3.Connection) -> Differenza:
    d = Differenza()
    fuori = [r for r in registro if r not in bersaglio.righe]
    uuid_oggi: dict[int, str] = {}
    for i in range(0, len(fuori), _PAGINA_SQL):
        pagina = fuori[i:i + _PAGINA_SQL]
        seg = ",".join("?" * len(pagina))
        uuid_oggi.update(src.execute(
            f"SELECT rowid, uuid FROM messages WHERE rowid IN ({seg})", pagina).fetchall())
    for rid, (uuid, imp) in registro.items():
        if rid in bersaglio.righe:
            u2, imp2 = bersaglio.righe[rid]
            if u2 != uuid:
                d.riassegnati.append(rid)
            elif imp2 != imp:
                d.cambiati.append(rid)
            else:
                d.invariati.append(rid)
        elif rid not in uuid_oggi:
            d.orfani.append(rid)
        elif uuid_oggi[rid] != uuid:
            d.riassegnati.append(rid)
        else:
            d.usciti.append(rid)
    d.nuovi = sorted(r for r in bersaglio.righe if r not in registro)
    return d


@dataclass
class Esito:
    indice: str
    modo: str                       # ricostruzione | incrementale | ripresa | controllo
    perimetro: str
    nel_perimetro: int
    indicizzabili: int
    corti: int
    senza_ts: int
    registro_prima: int
    differenza: dict[str, int]
    vettori_tolti: int = 0
    vettori_aggiunti: int = 0
    messaggi: int = 0
    vettori: int = 0
    in_pari: bool = True
    verificabile: bool = True       # False: indice senza registro, il controllo è a metà
    note: list[str] = field(default_factory=list)


def _registro(conn: sqlite3.Connection) -> dict[int, tuple[str, str]]:
    return {r: (u, i) for r, u, i in conn.execute(
        "SELECT msg_rowid, uuid, impronta FROM indice_righe")}


def _togli(conn: sqlite3.Connection, rowids: Iterable[int]) -> int:
    tolti = 0
    for rid in rowids:
        r = conn.execute("SELECT primo_chunk, n_chunk FROM indice_righe WHERE msg_rowid = ?",
                         (rid,)).fetchone()
        if r is None:
            continue
        primo, n = r
        conn.executemany(f"DELETE FROM {semantica.TABELLA} WHERE rowid = ?",
                         [(primo + k,) for k in range(n)])
        conn.execute("DELETE FROM indice_righe WHERE msg_rowid = ?", (rid,))
        tolti += n
    return tolti


def _norma(blob: bytes) -> float:
    return math.sqrt(sum(x * x for x in struct.unpack(f"{semantica.DIM}f", blob)))


def _aggiungi(conn: sqlite3.Connection, src: sqlite3.Connection, rowids: list[int],
              embed: Embedder, *, lotto: int, progresso: Callable[[int, int, int], None] | None) -> int:
    """Indicizza i rowid dati, un lotto per transazione: il registro e i vettori
    di un messaggio entrano INSIEME, quindi un'interruzione lascia un indice
    coerente e il rilancio riprende da dove si era fermato."""
    prossimo = (conn.execute(f"SELECT coalesce(max(rowid), 0) FROM {semantica.TABELLA}")
                .fetchone()[0]) + 1
    aggiunti = fatti = 0
    buf: list[tuple[int, str, str, list[str]]] = []
    n_buf = 0

    def svuota() -> None:
        nonlocal prossimo, aggiunti, buf, n_buf
        if not buf:
            return
        testi = [semantica.PREFISSO_PASSAGGIO + p for _, _, _, ps in buf for p in ps]
        blobs = embed(testi)
        if len(blobs) != len(testi):
            raise ErroreCostruttore(
                f"il modello ha restituito {len(blobs)} vettori per {len(testi)} testi")
        attesa = semantica.DIM * 4
        if any(len(b) != attesa for b in blobs):
            raise ErroreCostruttore(
                f"vettori di {len(blobs[0]) // 4} dimensioni, attese {semantica.DIM}: "
                f"non è il modello {semantica.MODELLO_ATTESO} (o l'export è sbagliato)")
        n = _norma(blobs[0])
        if abs(n - 1.0) > 1e-3:
            raise ErroreCostruttore(
                f"vettore di norma {n:.4f}, atteso 1: il grafo ONNX non normalizza. "
                "L'export deve avere pooling e L2 DENTRO il grafo (docs/RICERCA-IBRIDA.md), "
                "come quello che il server usa per le query.")
        i = 0
        righe_vec, righe_reg = [], []
        for rid, uuid, imp, ps in buf:
            righe_reg.append((rid, uuid, imp, prossimo, len(ps)))
            for _ in ps:
                righe_vec.append((prossimo, blobs[i], rid))
                prossimo += 1
                i += 1
        with conn:
            conn.executemany(f"INSERT INTO {semantica.TABELLA}(rowid, embedding, msg_rowid) "
                             "VALUES (?, ?, ?)", righe_vec)
            conn.executemany("INSERT INTO indice_righe(msg_rowid, uuid, impronta, "
                             "primo_chunk, n_chunk) VALUES (?, ?, ?, ?, ?)", righe_reg)
        aggiunti += len(righe_vec)
        buf, n_buf = [], 0

    for rid, uuid, testo in testi_per_rowid(src, rowids):
        ps = pezzi(testo)
        if not ps:
            continue
        buf.append((rid, uuid, impronta_testo(testo), ps))
        n_buf += len(ps)
        fatti += 1
        if n_buf >= lotto:
            svuota()
            if progresso:
                progresso(fatti, len(rowids), aggiunti)
    svuota()
    if progresso:
        progresso(fatti, len(rowids), aggiunti)
    return aggiunti


def _quadra(conn: sqlite3.Connection) -> tuple[int, int]:
    """(messaggi, vettori) — e il registro DEVE spiegare ogni vettore della tabella.
    Un vettore che il registro non conosce è un orfano che il server servirebbe."""
    messaggi, dichiarati = conn.execute(
        "SELECT count(*), coalesce(sum(n_chunk), 0) FROM indice_righe").fetchone()
    presenti = conn.execute(f"SELECT count(*) FROM {semantica.TABELLA}").fetchone()[0]
    if presenti != dichiarati:
        raise ErroreCostruttore(
            f"l'indice non quadra: {presenti} vettori nella tabella, {dichiarati} nel "
            "registro. Non lo pubblico: rilancia con --ricostruisci.")
    return messaggi, presenti


def controlla(db: Path, out: Path | None = None, perimetro: Perimetro | None = None) -> Esito:
    """Confronta un indice esistente col DB SENZA scrivere niente. Serve anche
    dopo un re-ingest, prima di caricare un indice sulla VPS: dice se è in pari."""
    out = out or semantica.percorso_indice(db)
    if not out.is_file():
        raise ErroreCostruttore(f"indice assente: {out}")
    src = apri_sorgente(db)
    conn = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    try:
        _carica_vec(conn)
        meta = leggi_meta(conn)
        if not ha_registro(conn):
            # Indice del POC: senza registro si può dire solo chi è SPARITO dal DB.
            vec_rowids = [r for (r,) in conn.execute(
                f"SELECT DISTINCT msg_rowid FROM {semantica.TABELLA}")]
            esistenti: set[int] = set()
            for i in range(0, len(vec_rowids), _PAGINA_SQL):
                pagina = vec_rowids[i:i + _PAGINA_SQL]
                seg = ",".join("?" * len(pagina))
                esistenti.update(r for (r,) in src.execute(
                    f"SELECT rowid FROM messages WHERE rowid IN ({seg})", pagina))
            orfani = len(vec_rowids) - len(esistenti)
            return Esito(indice=out.name, modo="controllo", perimetro=meta.get("perimetro", "?"),
                         nel_perimetro=0, indicizzabili=0, corti=0, senza_ts=0,
                         registro_prima=0, differenza={"orfani": orfani},
                         messaggi=len(vec_rowids), in_pari=False, verificabile=False,
                         note=["indice senza registro (costruito dal POC): riassegnazioni "
                               "di rowid e contenuti cambiati NON sono verificabili",
                               "per un indice verificabile: --ricostruisci"])
        perim = _perimetro_effettivo(perimetro, meta, out)
        bers = analizza(src, perim)
        d = differenza(_registro(conn), bers, src)
        messaggi, vettori = _quadra(conn)
        num = d.numeri()
        return Esito(indice=out.name, modo="controllo", perimetro=perim.descrizione(bers.senza_ts),
                     nel_perimetro=bers.nel_perimetro, indicizzabili=len(bers.righe),
                     corti=bers.corti, senza_ts=bers.senza_ts, registro_prima=messaggi,
                     differenza=num, messaggi=messaggi, vettori=vettori,
                     in_pari=not (d.da_togliere or d.nuovi))
    finally:
        conn.close()
        src.close()


def _perimetro_effettivo(perimetro: Perimetro | None, meta: dict[str, str], dove: Path) -> Perimetro:
    """Il perimetro passato, o quello che l'indice stesso dichiara."""
    if perimetro is not None:
        return perimetro
    if meta.get("perimetro_json"):
        return Perimetro.da_json(meta["perimetro_json"])
    if not meta:
        Perimetro().valida()                # indice nuovo: l'elenco delle scelte
    raise ErroreCostruttore(
        f"{dove.name} non dichiara un perimetro leggibile (`perimetro_json`): "
        "passalo tu (--tutto | --dal/--al | --project).")


def costruisci(db: Path, embed: Embedder, perimetro: Perimetro | None = None, *,
               out: Path | None = None, ricostruisci: bool = False, lotto: int = LOTTO,
               progresso: Callable[[int, int, int], None] | None = None) -> Esito:
    """Costruisce o aggiorna `<db>.vec.db`. Lavora SEMPRE su `<indice>.parziale`
    e lo rinomina sull'indice solo a lavoro finito e quadrato: l'indice servito
    non è mai un file a metà."""
    db = Path(db)
    out = Path(out) if out else semantica.percorso_indice(db)
    if out.resolve() == db.resolve():
        raise ErroreCostruttore("l'indice non può essere il DB stesso")
    if not out.name.endswith(".vec.db"):
        raise ErroreCostruttore(
            f"{out.name}: l'indice deve chiamarsi `<nome-db>.vec.db`. È così che il server "
            "lo trova accanto al suo DB, e che lo scan non lo scambia per un archivio.")
    parz = out.with_name(out.name + ".parziale")
    metro = _parametri_metro(embed.nome, embed.impronta)
    src = apri_sorgente(db)
    try:
        # ① Prima si decide e si misura, POI si scrive: un rifiuto (metro
        #    diverso, perimetro vuoto) non deve lasciare dietro un `.parziale`.
        if ricostruisci and parz.exists():
            parz.unlink()
        if parz.exists():
            modo, base = "ripresa", parz
        elif out.exists() and not ricostruisci:
            modo, base = "incrementale", out
        else:
            modo, base = "ricostruzione", None
        meta: dict[str, str] = {}
        if base is not None:
            vecchio = sqlite3.connect(f"file:{base}?mode=ro", uri=True)
            try:
                meta = leggi_meta(vecchio)
                if not ha_registro(vecchio):
                    raise ErroreCostruttore(
                        f"{base.name} non ha il registro `indice_righe` (è un indice del POC, "
                        "o non è di questo strumento): l'incrementale non può sapere quali "
                        "rowid sono stati riassegnati o quali testi sono cambiati. Serve "
                        "--ricostruisci (una volta: dopo, gli aggiornamenti sono incrementali).")
                if modo == "ripresa" and meta.get("stato") != "in costruzione":
                    raise ErroreCostruttore(
                        f"{parz.name} esiste ma non è una costruzione interrotta: "
                        "cancellalo, o usa --ricostruisci.")
                _controlla_metro(meta, metro, base)
            finally:
                vecchio.close()
        elif perimetro is None and out.exists():
            # --ricostruisci senza perimetro: si ricostruisce QUELLO dichiarato.
            vecchio = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
            try:
                meta = leggi_meta(vecchio)
            finally:
                vecchio.close()
        perim = _perimetro_effettivo(perimetro, meta, out)
        bers = analizza(src, perim)
        if not bers.nel_perimetro:
            raise ErroreCostruttore(
                f"Perimetro vuoto: 0 messaggi con «{perim.descrizione(0)}». Un indice "
                "vuoto sembrerebbe un indice: non lo scrivo.")
        if not bers.righe:
            raise ErroreCostruttore(
                f"{bers.nel_perimetro} messaggi nel perimetro ma nessuno con almeno "
                f"{TESTO_MIN} caratteri di testo: niente da indicizzare.")

        # ② Il file di lavoro: la copia dell'indice (incrementale), quello
        #    interrotto (ripresa) o uno nuovo. L'indice servito non si tocca.
        if modo == "incrementale":
            # La copia passa da un nome suo: interrotta a metà, non deve sembrare
            # un `.parziale` da riprendere.
            copia = parz.with_name(parz.name + ".copia")
            vecchio = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
            dest = sqlite3.connect(copia)
            try:
                vecchio.backup(dest)
            finally:
                dest.close()
                vecchio.close()
            os.replace(copia, parz)
            conn = sqlite3.connect(parz)
            _carica_vec(conn)
            with conn:
                conn.executemany("INSERT OR REPLACE INTO indice_meta VALUES (?, ?)",
                                 [("stato", "in costruzione"),
                                  ("perimetro_json", perim.come_json())])
        else:
            conn = sqlite3.connect(parz)
            _carica_vec(conn)
            if modo == "ricostruzione":
                _crea_indice(conn, metro, perim)
        try:
            registro = _registro(conn)
            d = differenza(registro, bers, src)
            with conn:
                tolti = _togli(conn, d.da_togliere)
            aggiunti = _aggiungi(conn, src, d.da_indicizzare(bers), embed, lotto=lotto,
                                 progresso=progresso)
            messaggi, vettori = _quadra(conn)
            esito = Esito(indice=out.name, modo=modo, perimetro=perim.descrizione(bers.senza_ts),
                          nel_perimetro=bers.nel_perimetro, indicizzabili=len(bers.righe),
                          corti=bers.corti, senza_ts=bers.senza_ts, registro_prima=len(registro),
                          differenza=d.numeri(), vettori_tolti=tolti, vettori_aggiunti=aggiunti,
                          messaggi=messaggi, vettori=vettori)
            if messaggi != len(bers.righe):
                esito.note.append(
                    f"{len(bers.righe) - messaggi} messaggi indicizzabili senza vettori "
                    "(spariti dal DB durante la costruzione?)")
            meta_nuova = {
                **metro,
                "perimetro": esito.perimetro,
                "perimetro_json": perim.come_json(),
                "db_sorgente": db.stem,
                "db_righe": str(bers.db_righe),
                "db_max_rowid": str(bers.db_max_rowid),
                "messaggi": str(messaggi),
                "vettori": str(vettori),
                "messaggi_perimetro": str(bers.nel_perimetro),
                "messaggi_corti": str(bers.corti),
                "righe_senza_ts": str(bers.senza_ts),
                "generato": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "costruttore": f"costruisci_indice {VERSIONE}",
                "ultimo_passaggio": json.dumps(
                    {"modo": modo, **esito.differenza, "vettori_tolti": tolti,
                     "vettori_aggiunti": aggiunti}, sort_keys=True),
                "stato": "completo",
            }
            with conn:
                conn.executemany("INSERT OR REPLACE INTO indice_meta(chiave, valore) "
                                 "VALUES (?, ?)", list(meta_nuova.items()))
        finally:
            conn.close()
        # ③ Solo ora, a lavoro quadrato, l'indice nuovo prende il posto del vecchio.
        os.replace(parz, out)
        return esito
    finally:
        src.close()


# ── il modello vero ──────────────────────────────────────────────────────────

def impronta_modello(model_dir: Path) -> str:
    """sha256 di model.onnx + tokenizer.json: due export diversi dello «stesso»
    modello (l'int8 scartato dal POC, per esempio) danno vettori diversi. Il nome
    non basta a dirlo; il contenuto sì."""
    h = hashlib.sha256()
    for nome in ("model.onnx", "tokenizer.json"):
        with open(model_dir / nome, "rb") as f:
            while blocco := f.read(1 << 20):
                h.update(blocco)
    return h.hexdigest()[:32]


class EmbedderOnnx:
    """Lo stesso modello, lo stesso tokenizer e la stessa codifica del server.

    I testi di un lotto si passano al grafo ORDINATI PER LUNGHEZZA e a gruppi di
    `sotto_lotto`, poi si rimettono in ordine. Misurato sul PC il 24/09/2026: un
    lotto di 96 pezzi misti in una sola chiamata viene riempito di padding fino
    al più lungo e l'arena di onnxruntime è salita a ~12 GB di RAM. Il risultato
    non cambia: il pooling nel grafo pesa con `attention_mask`, quindi il padding
    non entra nel vettore.
    """

    def __init__(self, model_dir: Path, *, thread: int | None = None,
                 sotto_lotto: int = 16) -> None:
        # Il modello si apre alla PRIMA chiamata, non qui (26/09/2026): nome e impronta
        # bastano al controllo del metro, e un giro incrementale senza niente da calcolare
        # (le notti senza ingest del job sulla VPS) non deve pagare i ~0,5 GB del modello.
        # Misurato sulla VPS sul primario: picco 1.007 MiB con il modello caricato per
        # niente, contro un tetto di 1.300 MB.
        self.model_dir, self.thread = model_dir, thread or os.cpu_count() or 2
        self.sess: Any = None
        self.tk: Any = None
        if not (model_dir / "model.onnx").is_file() or not (model_dir / "tokenizer.json").is_file():
            # l'errore parlante del modello mancante resta all'avvio, non a metà lavoro
            # (e prima dell'impronta, che su un file assente cadrebbe muta)
            semantica.apri_modello(model_dir, thread=1)
        self.nome = semantica.MODELLO_ATTESO
        self.impronta = impronta_modello(model_dir)
        self.sotto_lotto = max(1, sotto_lotto)

    def __call__(self, testi: list[str]) -> list[bytes]:
        if self.sess is None:
            self.sess, self.tk = semantica.apri_modello(self.model_dir, thread=self.thread)
        ordine = sorted(range(len(testi)), key=lambda i: len(testi[i]))
        out: list[bytes] = [b""] * len(testi)
        for k in range(0, len(ordine), self.sotto_lotto):
            gruppo = ordine[k:k + self.sotto_lotto]
            for i, blob in zip(gruppo, semantica.codifica(self.sess, self.tk,
                                                          [testi[i] for i in gruppo])):
                out[i] = blob
        return out


# ── riga di comando ──────────────────────────────────────────────────────────

def _stampa(esito: Esito, out: Any = None) -> None:
    d = esito.differenza
    righe = [
        f"indice: {esito.indice}  ({esito.modo})",
        f"perimetro: {esito.perimetro}",
    ]
    if esito.nel_perimetro:
        righe.append(f"messaggi nel perimetro: {esito.nel_perimetro} · con testo indicizzabile: "
                     f"{esito.indicizzabili} · troppo corti: {esito.corti}")
    if esito.senza_ts:
        righe.append(f"righe senza ts nel resto del filtro: {esito.senza_ts}")
    righe.append(f"registro prima: {esito.registro_prima} messaggi" if esito.verificabile
                 else "registro: ASSENTE (indice del POC)")
    etichette = [("invariati", "invariati"), ("nuovi", "nuovi"),
                 ("cambiati", "testo cambiato (stesso uuid)"),
                 ("riassegnati", "rowid riassegnato a un altro uuid"),
                 ("orfani", "orfani (rowid sparito dal DB)"),
                 ("usciti", "usciti dal perimetro")]
    for k, et in etichette:
        if k in d:
            righe.append(f"  {et}: {d[k]}")
    if esito.modo != "controllo":
        righe.append(f"vettori tolti: {esito.vettori_tolti} · aggiunti: {esito.vettori_aggiunti}")
        righe.append(f"dopo: {esito.messaggi} messaggi · {esito.vettori} vettori "
                     "(registro e tabella vec0 quadrano)")
    else:
        righe.append("in pari col DB" if esito.in_pari
                     else "NON in pari col DB" if esito.verificabile
                     else "NON verificabile per intero")
    for n in esito.note:
        righe.append(f"⚠️  {n}")
    print("\n".join(righe), file=out or sys.stdout)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="costruisci_indice.py",
        description="Costruisce o aggiorna l'indice vettoriale `<db>.vec.db` della "
                    "ricerca ibrida di archive-mcp (vedi docs/RICERCA-IBRIDA.md).")
    p.add_argument("--db", required=True, type=Path, help="DB dell'archivio (aperto in sola lettura)")
    p.add_argument("--modello", type=Path,
                   help="cartella con model.onnx + tokenizer.json (lo stesso export del server)")
    p.add_argument("--out", type=Path, help="indice da scrivere (default: <db>.vec.db accanto al DB)")
    g = p.add_argument_group("perimetro (se manca, vale quello dichiarato dall'indice esistente)")
    g.add_argument("--tutto", action="store_true", help="tutto il DB")
    g.add_argument("--dal", default="", help="ts >= DAL (stringa ISO, es. 2026-05)")
    g.add_argument("--al", default="", help="ts < AL (escluso)")
    g.add_argument("--project", action="append", default=[], metavar="ETICHETTA",
                   help="etichetta project, ripetibile; `recupero:*` = prefisso")
    g.add_argument("--senza-ts", choices=("includi", "escludi"), default="",
                   help="con --dal/--al: le righe senza ts entrano o restano fuori (dichiarato)")
    p.add_argument("--ricostruisci", action="store_true",
                   help="riparte da zero invece di aggiornare (obbligatorio se cambia il metro)")
    p.add_argument("--controlla", action="store_true",
                   help="confronta indice e DB senza scrivere: esce 1 se non sono in pari")
    p.add_argument("--lotto", type=int, default=LOTTO, help=f"pezzi per lotto (default {LOTTO})")
    p.add_argument("--thread", type=int, default=0, help="thread di onnxruntime (default: tutti)")
    p.add_argument("--sotto-lotto", type=int, default=16,
                   help="pezzi per chiamata al modello (default 16). Più piccolo = meno RAM: "
                        "misurato il 26/09, ~0,9 GB di picco a 1-4 pezzi contro ~1,2 GB a 16 "
                        "(il job notturno sulla VPS usa 4)")
    p.add_argument("--json", action="store_true", help="esito in JSON su stdout")
    return p


def _perimetro_da_arg(a: argparse.Namespace) -> Perimetro | None:
    if not (a.tutto or a.dal or a.al or a.project or a.senza_ts):
        return None
    return Perimetro(tutto=a.tutto, dal=a.dal, al=a.al, progetti=tuple(a.project),
                     senza_ts=a.senza_ts)


def main(argv: list[str] | None = None,
         fabbrica: Callable[[Path, int], Embedder] | None = None) -> int:
    a = _parser().parse_args(argv)
    perim = _perimetro_da_arg(a)
    t0 = time.time()

    def progresso(fatti: int, totale: int, vettori: int) -> None:
        v = vettori / max(time.time() - t0, 1e-9)
        print(f"  {fatti}/{totale} messaggi · {vettori} vettori · {v:.1f} vett/s",
              file=sys.stderr, flush=True)

    try:
        if a.controlla:
            esito = controlla(a.db, a.out, perim)
        else:
            if a.modello is None and fabbrica is None:
                raise ErroreCostruttore("--modello è obbligatorio per costruire (non per --controlla)")
            try:
                embed = (fabbrica or (lambda m, t: EmbedderOnnx(
                    m, thread=t or None, sotto_lotto=a.sotto_lotto)))(a.modello, a.thread)
            except semantica.SemanticaNonPronta as exc:
                raise ErroreCostruttore(str(exc)) from exc
            esito = costruisci(a.db, embed, perim, out=a.out, ricostruisci=a.ricostruisci,
                               lotto=a.lotto, progresso=progresso)
    except ErroreCostruttore as exc:
        print(f"🔴 {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("⏸  interrotto: il lavoro fatto è nel `.parziale` accanto all'indice; "
              "rilancia lo stesso comando per riprendere.", file=sys.stderr)
        return 130
    if a.json:
        print(json.dumps(asdict(esito), ensure_ascii=False, indent=2))
    else:
        _stampa(esito)
    if esito.modo == "controllo" and not esito.in_pari:
        # Un controllo a metà che non trova orfani NON è un «in pari»: è non misurabile.
        if not esito.verificabile and not esito.differenza.get("orfani"):
            return 2
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
