"""La mappa dei temi: di cosa si è parlato, senza sapere cosa cercare (D9, 07/11/2026).

La ricerca risponde a «trova X»; questa a «di cosa ho parlato a settembre?». Non calcola
vettori nuovi: raggruppa quelli che l'indice per senso ha già.

Le scelte, ognuna misurata (kit interno, 303 + 47 prove):
- l'unità è lo SCAMBIO, un messaggio del proprietario più le risposte che lo seguono. I
  messaggi da soli si raggruppano per modo di scrivere; le sessioni di Claude Code durano
  settimane e mescolano tutto;
- i vettori si CENTRANO: senza, il giudice alla cieca trova l'intruso nel 78% dei temi, con
  la media tolta nel 92%;
- ogni ricalcolo riparte dai centri e dalla media congelati: da zero, due semi diversi danno
  temi diversi (ARI 0,42), dai centri il 97,8% degli scambi resta nel suo tema. Un marchio
  messo su un tema deve poter durare;
- i temi che somigliano alle ANCORE (vita privata, salute, lavoro cercato…) nascono
  «da guardare» e non escono finché il proprietario non li ha visti. Niente LLM in cloud e
  nessuna lettura dei DB riservati: è lo stesso modello dell'indice.
"""
from __future__ import annotations

import collections
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable

import numpy as np

CARTELLA = "temi"                # dentro al volume dell'archivio, accanto a db/
FILE_TEMI = "temi.json"          # quello che legge il tool (niente vettori)
FILE_STATO = "stato.json"        # centri, media, ancore: quello da cui riparte il ricalcolo
FILE_MARCHI = "marchi.json"      # {id_tema: "libero"|"riservato"}: lo scrive la pagina admin

K_INIZIALE = 30
MIN_CARATTERI = 80               # sotto, un «sì procedi» non ha argomento
MAX_RISPOSTE = 6
MIN_RISPOSTA = 200
MIN_TEMA_NUOVO = 15              # quanti scambi nuovi e lontani fanno nascere un tema
MAX_TEMI_NUOVI = 3               # per ricalcolo
SOGLIA_ANCORA = 0.10             # quota di scambi vicini all'ancora che fa dire «da guardare»
PERCENTILE_ANCORA = 97           # «vicino» = il 3% più vicino di tutta la mappa

ANCORE = {
    "lavoro": "ricerca di lavoro, candidature, curriculum, colloqui con aziende, stipendio, LinkedIn",
    "salute": "salute, medico, terapia, psicologo, ansia, malattia, farmaci",
    "relazioni": "famiglia, figli, separazione, relazione di coppia, amore, amicizia, litigi",
    "soldi": "soldi personali, debiti, mutuo, tasse, conto in banca, spese di casa",
    "vita": "la mia vita privata, come mi sento, ricordi personali, momenti difficili",
}

# Un comando slash è un gesto, non un argomento: non apre uno scambio, e chiude quello aperto.
_GESTI = ("<command-name>", "<command-message>")

_VUOTE = frozenset("""a ad al alla alle allo agli ai anche ancora che chi ci cio come con cosa così cui
da dal dalla dalle dei del della delle dello degli di dove e ed era fa fai fare già gli ha hai ho i il in io
la le lei li lo loro lui ma mi mia mio ne nei nel nella nelle no noi non o per perché più poi può quale quando
quella quelle quello questa queste questo qui se sei si sia sì solo sono su sua sue suo sul sulla tra tu tua
tuo un una uno vi voi è the and to of in is it that for on with this be you are not or as at by from have can
will an all if do so we what just me my your but yes ok fatto tutto tutti bene ora devi deve dobbiamo puoi
vedi fammi dimmi però quindi allora quanto magari tipo cioè ecc bo cose abbiamo perche piu cosi gia siamo siete
avete voglio vorrei devo facciamo diciamo sembra vedo vediamo forse pure procedi prima dopo ogni altre altri
altro altra sempre mai molto poco male bisogna serve serva possiamo potrebbe dovrebbe essere stato stata stati
avere aver hanno questi quelli qualche qualcosa nulla niente volta volte modo parte punto caso fatta faccio
invece anzi infatti comunque proprio davvero almeno meglio peggio grazie ciao scusa okay https http www com
due tre senza vuoi oggi dentro procederò eseguirò inizierò nuovamente""".split())
_PAROLA = re.compile(r"\b[a-zà-ù]{3,}\b")
_SPORCO = re.compile(r"https?://\S+|\S*[/\\]\S*|`[^`]*`|\b\w*\d\w*\b")
_DATA_VOCE = re.compile(r"voce:(\d{4})(\d{2})(\d{2})")
_LOTTO = 500                     # variabili SQL per query (il limite di SQLite è più alto)


def _a_lotti(valori: list, n: int = _LOTTO) -> Iterable[list]:
    for i in range(0, len(valori), n):
        yield valori[i:i + n]


def data_del_contenuto(project: str, ts: str, ts_source: str = "") -> str:
    """La data di cui parla la riga. Nei vocali `ts` è l'ora del caricamento (tutti settembre
    2026, ma gli audio sono da maggio) e quella vera sta nell'etichetta `voce:AAAAMMGG-…`. Un
    `ts` messo dall'export non è una data del contenuto: meglio nessuna che una falsa."""
    m = _DATA_VOCE.match(project or "")
    if m:
        return f"{m[1]}-{m[2]}-{m[3]}T00:00:00Z"
    return "" if ts_source == "data-export" else (ts or "")


def _unita(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v, axis=-1, keepdims=True).clip(min=1e-9))


# ── gli scambi ─────────────────────────────────────────────────────────────────

def scambi_di(db: Path, indice: Path, nome: str) -> list[dict[str, Any]]:
    """Gli scambi di un DB. Legge dal disco solo i blocchi di vettori che servono: il primario
    ha 452 mila vettori (690 MB) e ne servono poche migliaia, in un job da 1300 MB.

    Un DB senza assistente (i vocali) non ha scambi: l'unità è il messaggio da solo."""
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    v = sqlite3.connect(f"file:{indice}?mode=ro", uri=True)
    try:
        con_assistente = c.execute(
            "SELECT 1 FROM messages WHERE speaker='assistant' LIMIT 1").fetchone() is not None
        filtro = ("speaker IN ('human','assistant')" if con_assistente
                  else "speaker IN ('human','unknown') AND voice NOT LIKE 'pasted%'")
        file_di: dict[str, str] = {}
        if c.execute("SELECT 1 FROM sqlite_master WHERE name='sightings'").fetchone():
            file_di = dict(c.execute("SELECT uuid, MIN(source) FROM sightings GROUP BY uuid"))
        per_file: dict[str, list] = collections.defaultdict(list)
        colonne = {r[1] for r in c.execute("PRAGMA table_info(messages)")}
        fonte_ts = "ts_source" if "ts_source" in colonne else "''"
        for riga in c.execute(
                f"SELECT rowid, uuid, project, ts, speaker, voice, length(content), "
                f"substr(content, 1, 40), {fonte_ts} FROM messages WHERE {filtro}"):
            rowid, uuid, project, ts, speaker, voice, lung, testa, fonte = riga
            per_file[file_di.get(uuid) or project or ""].append(
                (ts or "", rowid, uuid, project or "", speaker, voice, lung or 0, testa or "", fonte or ""))
        out: list[dict[str, Any]] = []
        for righe in per_file.values():
            righe.sort()
            corrente = None
            for ts, rowid, uuid, project, speaker, voice, lung, testa, fonte in righe:
                proprio = speaker != "assistant" and (voice == "own" or not con_assistente)
                if speaker == "human" and testa.lstrip().startswith(_GESTI):
                    corrente = None
                elif proprio and lung >= MIN_CARATTERI:
                    corrente = {"db": nome, "uuid": uuid, "project": project,
                                "ts": data_del_contenuto(project, ts, fonte),
                                "righe": [rowid], "neo": rowid}
                    out.append(corrente)
                elif (speaker == "assistant" and corrente is not None and lung >= MIN_RISPOSTA
                      and len(corrente["righe"]) <= MAX_RISPOSTE):
                    corrente["righe"].append(rowid)
        _riempi_vettori(out, v)
        return [s for s in out if s.get("vec") is not None]
    finally:
        c.close()
        v.close()


def _riempi_vettori(scambi: list[dict[str, Any]], v: sqlite3.Connection) -> None:
    """Il vettore di ogni scambio: media delle righe, col messaggio del proprietario che pesa 2.
    Si fidano solo del registro dell'indice: una riga senza registro non ha vettore."""
    servono = sorted({r for s in scambi for r in s["righe"]})
    registro: dict[int, tuple[int, int]] = {}
    for lotto in _a_lotti(servono):
        segni = ",".join("?" * len(lotto))
        for rowid, primo, n in v.execute(
                f"SELECT msg_rowid, primo_chunk, n_chunk FROM indice_righe WHERE msg_rowid IN ({segni})",
                lotto):
            registro[rowid] = (primo, n)
    pezzi = sorted({p for r in registro for p in range(registro[r][0], registro[r][0] + registro[r][1])})
    dove: dict[int, tuple[int, int]] = {}
    for lotto in _a_lotti(pezzi):
        segni = ",".join("?" * len(lotto))
        for p, blocco, pos in v.execute(
                f"SELECT rowid, chunk_id, chunk_offset FROM vec_chunk_small_rowids WHERE rowid IN ({segni})",
                lotto):
            dove[p] = (blocco, pos)
    per_blocco: dict[int, list[tuple[int, int]]] = collections.defaultdict(list)
    for p, (blocco, pos) in dove.items():
        per_blocco[blocco].append((p, pos))
    vettori: dict[int, np.ndarray] = {}
    for blocco, voci in per_blocco.items():
        riga = v.execute("SELECT vectors FROM vec_chunk_small_vector_chunks00 WHERE rowid=?",
                         (blocco,)).fetchone()
        if not riga:
            continue
        m = np.frombuffer(riga[0], dtype=np.float32).reshape(-1, 384)
        for p, pos in voci:
            vettori[p] = m[pos].copy()
    for s in scambi:
        somma, peso = None, 0
        for r in s["righe"]:
            if r not in registro:
                continue
            primo, n = registro[r]
            emb = [vettori[p] for p in range(primo, primo + n) if p in vettori]
            if not emb:
                continue
            m = _unita(np.mean(emb, axis=0))
            w = 2 if r == s["neo"] else 1
            somma = m * w if somma is None else somma + m * w
            peso += w
        s["vec"] = None if somma is None else _unita(somma / peso)


def _senza_intestazione(testo: str) -> str:
    """Una riga che comincia con un blocco «# …» di provenienza (i vocali) lo perde: altrimenti
    le parole tipiche di quei temi sono «trascrizione automatica, audio nome»."""
    if testo.startswith("# "):
        _, sep, resto = testo.partition("\n\n")
        if sep and resto.strip():
            return resto
    return testo


def testi_degli_scambi(scambi: list[dict[str, Any]], db: Path) -> None:
    """Il testo per le etichette: le parole del proprietario e l'inizio delle risposte."""
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        for s in scambi:
            testi = []
            for lotto in _a_lotti(s["righe"]):
                segni = ",".join("?" * len(lotto))
                testi += [_senza_intestazione(t or "") for (t,) in c.execute(
                    f"SELECT substr(content, 1, 3000) FROM messages WHERE rowid IN ({segni})", lotto)]
            s["testo"] = " ".join(testi)
    finally:
        c.close()


# ── il raggruppamento ──────────────────────────────────────────────────────────

def kmeans(X: np.ndarray, k: int, *, seme: int = 1777, centri: np.ndarray | None = None,
           giri: int = 25) -> tuple[np.ndarray, np.ndarray]:
    """K-means sferico in numpy (niente scikit-learn sulla VPS: su 2.250 scambi costa 0,3 s).
    Con `centri` riparte da quelli, e i temi restano gli stessi."""
    if centri is None:
        rng = np.random.default_rng(seme)
        scelti = [X[rng.integers(len(X))]]
        for _ in range(k - 1):                      # k-means++
            d = (1 - (X @ np.array(scelti).T).max(axis=1)).clip(min=0) ** 2
            somma = d.sum()
            scelti.append(X[rng.choice(len(X), p=d / somma)] if somma > 0 else X[rng.integers(len(X))])
        C = np.array(scelti, dtype=np.float32)
    else:
        C = centri.astype(np.float32).copy()
    et = None
    for _ in range(giri):
        nuove = (X @ C.T).argmax(axis=1)
        if et is not None and (nuove == et).all():
            break
        et = nuove
        for g in range(len(C)):
            membri = X[et == g]
            if len(membri):              # un tema vuoto tiene il suo centro: può tornare
                C[g] = _unita(membri.mean(axis=0))
    return et, C


def temi_nuovi(X: np.ndarray, et: np.ndarray, C: np.ndarray, nuovi: np.ndarray,
               soglia: float) -> np.ndarray:
    """I centri da aggiungere. Con k fisso un argomento davvero nuovo finirebbe nel tema più
    vicino: se almeno MIN_TEMA_NUOVO scambi nuovi stanno lontani da ogni centro, ne nasce uno."""
    vicinanza = (X * C[et]).sum(axis=1)
    lontani = X[nuovi & (vicinanza < soglia)]
    if len(lontani) < MIN_TEMA_NUOVO:
        return np.empty((0, X.shape[1]), dtype=np.float32)
    k = min(MAX_TEMI_NUOVI, len(lontani) // MIN_TEMA_NUOVO)
    et2, C2 = kmeans(lontani, k)
    return np.array([C2[g] for g in range(k) if (et2 == g).sum() >= MIN_TEMA_NUOVO], dtype=np.float32
                    ).reshape(-1, X.shape[1])


def etichette(gruppi: dict[int, list[str]], quante: int = 10) -> dict[int, list[str]]:
    """Le parole tipiche di ogni tema (c-TF-IDF), parole singole e coppie. Una parola che sta
    in più di un terzo dei temi non distingue nessuno; una che sta in un tema solo è rumore
    (il nome di un file, un refuso)."""
    conti: dict[int, collections.Counter] = {}
    for g, testi in gruppi.items():
        cnt: collections.Counter = collections.Counter()
        for t in testi:
            parole = [p for p in _PAROLA.findall(_SPORCO.sub(" ", t.lower())) if p not in _VUOTE]
            cnt.update(parole)
            cnt.update(f"{a} {b}" for a, b in zip(parole, parole[1:]))
        conti[g] = cnt
    presenze: collections.Counter = collections.Counter()
    totali: collections.Counter = collections.Counter()
    for cnt in conti.values():
        presenze.update(cnt.keys())
        totali.update(cnt)
    n = len(conti) or 1
    media = sum(sum(c.values()) for c in conti.values()) / n
    out = {}
    for g, cnt in conti.items():
        tot = sum(cnt.values()) or 1
        punti = {w: (f / tot) * float(np.log(1 + media / totali[w])) for w, f in cnt.items()
                 if 2 <= presenze[w] <= max(2, n // 3)}
        out[g] = sorted(punti, key=lambda w: (-punti[w], w))[:quante]
    return out


def segnali_ancore(G: np.ndarray, et: np.ndarray, ancore: dict[str, np.ndarray]) -> dict[int, dict[str, Any]]:
    """Per ogni tema l'ancora che gli somiglia di più: la quota di scambi nel 3% più vicino
    di tutta la mappa. Sui vettori grezzi: l'ancora è una query, non è centrata."""
    out: dict[int, dict[str, Any]] = {}
    for nome, q in ancore.items():
        sim = G @ q
        soglia = np.percentile(sim, PERCENTILE_ANCORA)
        for g in np.unique(et):
            quota = float((sim[et == g] >= soglia).mean())
            if int(g) not in out or quota > out[int(g)]["quota"]:
                out[int(g)] = {"ancora": nome, "quota": round(quota, 3)}
    return out


def calcola(scambi: list[dict[str, Any]], stato: dict[str, Any] | None,
            ancore: dict[str, np.ndarray], *, k: int = K_INIZIALE) -> tuple[dict[str, Any], dict[str, Any]]:
    """Dagli scambi (con `vec` e `testo`) e dallo stato precedente: (mappa, stato nuovo)."""
    G = np.array([s["vec"] for s in scambi], dtype=np.float32)
    ts = [s["ts"] for s in scambi]
    if stato:
        media = np.array(stato["media"], dtype=np.float32)
        X = _unita(G - media)
        C = np.array(stato["centri"], dtype=np.float32)
        ids = list(stato["ids"])
        soglia = float(stato["soglia_lontano"])
        fino_a = stato.get("fino_a", "")
        et, C = kmeans(X, len(C), centri=C)
        nuovi_centri = temi_nuovi(X, et, C, np.array([t > fino_a for t in ts]), soglia)
        if len(nuovi_centri):
            prossimo = max(ids) + 1
            ids += list(range(prossimo, prossimo + len(nuovi_centri)))
            et, C = kmeans(X, len(C) + len(nuovi_centri), centri=np.vstack([C, nuovi_centri]))
    else:
        media = G.mean(axis=0)
        X = _unita(G - media)
        k = min(k, len(X))
        et, C = kmeans(X, k)
        ids = list(range(len(C)))
        # il decimo percentile della vicinanza al proprio centro: sotto, uno scambio è «lontano»
        soglia = float(np.percentile((X * C[et]).sum(axis=1), 10))
    gruppi: dict[int, list[int]] = collections.defaultdict(list)
    for i, g in enumerate(et):
        gruppi[int(g)].append(i)
    parole = etichette({g: [scambi[i].get("testo", "") for i in idx] for g, idx in gruppi.items()})
    segnali = segnali_ancore(G, et, ancore)
    temi = []
    for g, idx in sorted(gruppi.items(), key=lambda x: -len(x[1])):
        vicini = sorted(idx, key=lambda i: -float(X[i] @ C[g]))[:5]
        sig = segnali.get(g, {"ancora": "", "quota": 0.0})
        temi.append({
            "id": ids[g],
            "parole": parole.get(g, []),
            "scambi": len(idx),
            "mesi": dict(sorted(collections.Counter(scambi[i]["ts"][:7] for i in idx if scambi[i]["ts"]).items())),
            "fonti": dict(collections.Counter(scambi[i]["db"] for i in idx)),
            "esempi": [{"db": scambi[i]["db"], "uuid": scambi[i]["uuid"]} for i in vicini],
            "ancora": sig["ancora"],
            "quota_ancora": sig["quota"],
            "da_guardare": sig["quota"] >= SOGLIA_ANCORA,
        })
    mappa = {"scambi": len(scambi), "perimetro": sorted({s["db"] for s in scambi}), "temi": temi}
    nuovo_stato = {"media": media.tolist(), "centri": C.tolist(), "ids": ids, "soglia_lontano": soglia,
                   "fino_a": max(ts) if ts else "",
                   "ancore": {k_: v.tolist() for k_, v in ancore.items()}}
    return mappa, nuovo_stato


# ── i file ─────────────────────────────────────────────────────────────────────

def cartella(db_dir: Path) -> Path:
    """Accanto a db/: il volume è /var/lib/archive, i DB stanno in /var/lib/archive/db."""
    return db_dir.parent / CARTELLA


def scrivi_json(percorso: Path, dati: Any) -> None:
    percorso.parent.mkdir(parents=True, exist_ok=True)
    tmp = percorso.with_suffix(".tmp")
    tmp.write_text(json.dumps(dati, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, percorso)


def leggi_json(percorso: Path) -> Any:
    try:
        return json.loads(percorso.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def stato_del_tema(tema: dict[str, Any], marchi: dict[str, str]) -> str:
    """libero | riservato | da_guardare. Il marchio del proprietario vince sempre; senza, un
    tema che somiglia alle ancore resta nascosto finché qualcuno non lo guarda."""
    m = marchi.get(str(tema.get("id")))
    if m in ("libero", "riservato"):
        return m
    return "da_guardare" if tema.get("da_guardare") else "libero"


def vista(mappa: dict[str, Any] | None, marchi: dict[str, str] | None, *, dal: str = "", al: str = "",
          limit: int = 40) -> dict[str, Any]:
    """Quello che vede chi chiede: i temi liberi, e quanti ne sono stati tolti. Mai in silenzio:
    «non c'è in mappa» e «c'è, ma è nascosto» sono risposte diverse."""
    if not mappa:
        return {"disponibile": False,
                "nota": "la mappa non è ancora stata calcolata: la costruisce il job notturno sui DB di "
                        "ARCHIVE_TEMI_DB (vps1777 indice-notturno --temi). Intanto usa search_ibrida."}
    marchi = marchi or {}
    temi, riservati, da_guardare = [], 0, 0
    for t in mappa.get("temi", []):
        st = stato_del_tema(t, marchi)
        if st == "riservato":
            riservati += 1
            continue
        if st == "da_guardare":
            da_guardare += 1
            continue
        mesi = {m: n for m, n in t.get("mesi", {}).items()
                if (not dal or m >= dal[:7]) and (not al or m <= al[:7])}
        if (dal or al) and not mesi:
            continue
        temi.append({"id": t["id"], "parole": t["parole"], "scambi": sum(mesi.values()) if (dal or al) else t["scambi"],
                     "mesi": mesi, "fonti": t.get("fonti", {}), "esempi": t.get("esempi", [])})
    temi.sort(key=lambda x: -x["scambi"])
    out: dict[str, Any] = {"disponibile": True, "generato": mappa.get("generato", ""),
                           "perimetro": mappa.get("perimetro", []), "scambi": mappa.get("scambi", 0),
                           "temi": temi[:max(1, min(limit, 200))]}
    if riservati or da_guardare:
        out["nascosti"] = {"riservati": riservati, "da_guardare": da_guardare}
        out["nota"] = ("alcuni temi non sono in questa vista, perché il proprietario li ha marcati riservati "
                       "o deve ancora guardarli: «non è in mappa» non vuol dire «non se n'è parlato»")
    return out
