"""La mappa dei temi (D9, 07/11/2026). Le misure vere stanno fuori dal repo, perché leggono
l'archivio; qui le proprietà che devono restare vere: i temi sopravvivono al ricalcolo, il
personale non esce finché non è stato guardato, e quello che manca si dichiara."""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import temi  # noqa: E402


def _nuvole(n=40, d=384, seme=1):
    """Tre nuvole ben separate di vettori unitari."""
    rng = np.random.default_rng(seme)
    assi = np.eye(d, dtype=np.float32)[:3]
    X = np.vstack([a + rng.normal(0, 0.02, (n, d)) for a in assi]).astype(np.float32)
    return temi._unita(X)


def test_ripartire_dai_centri_tiene_i_temi() -> None:
    X = _nuvole()
    et, C = temi.kmeans(X, 3)
    et2, _ = temi.kmeans(X[:100], 3, centri=C)
    assert (et2 == et[:100]).all()
    assert len(set(et)) == 3


def test_un_tema_vuoto_tiene_il_suo_centro_e_il_suo_posto() -> None:
    X = _nuvole()[:40]                           # tutti della prima nuvola
    C = temi._unita(np.eye(384, dtype=np.float32)[:3])
    et, C2 = temi.kmeans(X, 3, centri=C)
    assert set(et) == {0}
    assert np.allclose(C2[1], C[1])


def test_un_argomento_nuovo_fa_nascere_un_tema_solo_se_e_abbastanza_grande() -> None:
    d = 384
    vecchi = _nuvole(n=30)
    rng = np.random.default_rng(2)
    altrove = temi._unita((np.eye(d)[9] + rng.normal(0, 0.02, (temi.MIN_TEMA_NUOVO, d))).astype(np.float32))
    et, C = temi.kmeans(vecchi, 3)
    X = np.vstack([vecchi, altrove])
    et2, C2 = temi.kmeans(X, 3, centri=C)
    nuovi = np.array([False] * len(vecchi) + [True] * len(altrove))
    assert len(temi.temi_nuovi(X, et2, C2, nuovi, 0.5)) == 1
    pochi = nuovi.copy()
    pochi[-1] = False
    assert len(temi.temi_nuovi(X, et2, C2, pochi, 0.5)) == 0
    assert len(temi.temi_nuovi(X, et2, C2, nuovi, -1.0)) == 0   # vicini abbastanza: niente tema


def test_le_etichette_tolgono_le_parole_di_tutti_e_il_rumore() -> None:
    comune = "gateway " * 5
    gruppi = {g: [comune + f"tema{chr(97 + g)} "] for g in range(6)}
    gruppi[0] = [comune + "sentinella battito sentinella"]
    gruppi[1] = [comune + "sentinella podcast podcast"]
    gruppi[2] = [comune + "podcast"]
    e = temi.etichette(gruppi)
    assert "gateway" not in e[0]                 # sta in tutti: non distingue
    assert "sentinella" in e[0] and "podcast" in e[1]
    assert "battito" not in e[0]                 # sta in uno solo


def test_le_etichette_scartano_percorsi_url_e_numeri() -> None:
    gruppi = {0: ["vedi https://esempio.invalid/x e /home/a/b.py a153 parola"],
              1: ["vedi https://esempio.invalid/x e /home/a/b.py a153 parola"]}
    e = temi.etichette(gruppi)
    assert all("invalid" not in w and "a153" not in w and "home" not in w for w in e[0])


def test_l_intestazione_dei_vocali_non_fa_le_etichette() -> None:
    assert temi._senza_intestazione("# Voce\n[trascrizione automatica]\n\nparlato vero") == "parlato vero"
    assert temi._senza_intestazione("# Solo titolo") == "# Solo titolo"     # non resta un testo vuoto
    assert temi._senza_intestazione("testo\n\naltro") == "testo\n\naltro"


def _mappa():
    return {"generato": "2026-11-07T00:00:00Z", "perimetro": ["a"], "scambi": 9, "temi": [
        {"id": 0, "parole": ["gateway"], "scambi": 5, "mesi": {"2026-08": 2, "2026-09": 3},
         "esempi": [{"db": "a", "uuid": "u"}], "da_guardare": False},
        {"id": 1, "parole": ["linkedin"], "scambi": 3, "mesi": {"2026-09": 3}, "esempi": [], "da_guardare": True},
        {"id": 2, "parole": ["podcast"], "scambi": 1, "mesi": {"2026-07": 1}, "esempi": [], "da_guardare": False},
    ]}


def test_un_tema_da_guardare_non_esce_e_lo_si_dichiara() -> None:
    v = temi.vista(_mappa(), {})
    assert [t["id"] for t in v["temi"]] == [0, 2]
    assert v["nascosti"] == {"riservati": 0, "da_guardare": 1}
    assert "non vuol dire" in v["nota"]


def test_il_marchio_del_proprietario_vince_nei_due_sensi() -> None:
    v = temi.vista(_mappa(), {"1": "libero", "0": "riservato"})
    assert [t["id"] for t in v["temi"]] == [1, 2]
    assert v["nascosti"] == {"riservati": 1, "da_guardare": 0}


def test_tutti_visibili_niente_nota() -> None:
    v = temi.vista(_mappa(), {"1": "libero"})
    assert "nascosti" not in v and "nota" not in v


def test_il_periodo_conta_solo_i_suoi_mesi() -> None:
    v = temi.vista(_mappa(), {"1": "libero"}, dal="2026-09-01", al="2026-09")
    assert {t["id"]: t["scambi"] for t in v["temi"]} == {0: 3, 1: 3}


def test_senza_mappa_lo_dice_e_dice_cosa_fare() -> None:
    v = temi.vista(None, None)
    assert v["disponibile"] is False and "search_ibrida" in v["nota"]


def test_stato_del_tema_e_gemello_nel_gateway() -> None:
    """I servizi hanno build separate: niente import. Il filtro è di sicurezza, e due copie
    divergono in silenzio: le tiene uguali questo test (come i ruoli dei DB)."""
    radice = Path(__file__).resolve().parents[3]
    def corpo(f):
        t = (radice / f).read_text(encoding="utf-8")
        m = re.search(r"def stato_del_tema\(.*?\n(.*?)(?=\n\n\n|\Z)", t, re.S)
        righe = [r.strip() for r in m.group(1).splitlines() if r.strip()]
        i = next(n for n, r in enumerate(righe) if r.startswith("m = marchi.get"))
        return righe[i:]
    assert corpo("services/archive-mcp/app/temi.py") == corpo("services/gateway/app/admin_core.py")


# ── gli scambi, su un DB e un indice minimi: stesso schema, senza vec0 ──────────

def _db(tmp_path: Path, righe: list[tuple], sightings: bool = True) -> tuple[Path, Path]:
    db, vec = tmp_path / "x.db", tmp_path / "x.vec.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE messages(uuid, project, ts, content, speaker, voice)")
    c.execute("CREATE TABLE sightings(uuid, source)")
    v = sqlite3.connect(vec)
    v.execute("CREATE TABLE indice_righe(msg_rowid INTEGER PRIMARY KEY, uuid, impronta, primo_chunk, n_chunk)")
    v.execute("CREATE TABLE vec_chunk_small_rowids(rowid INTEGER PRIMARY KEY, id, chunk_id, chunk_offset)")
    v.execute("CREATE TABLE vec_chunk_small_vector_chunks00(rowid INTEGER PRIMARY KEY, vectors BLOB)")
    blocco = []
    for i, (uuid, ts, content, speaker, voice, asse) in enumerate(righe):
        c.execute("INSERT INTO messages VALUES(?,?,?,?,?,?)", (uuid, "p", ts, content, speaker, voice))
        if sightings:
            c.execute("INSERT INTO sightings VALUES(?,?)", (uuid, "sessions/uno.jsonl"))
        if asse is None:
            continue
        rowid = c.execute("SELECT max(rowid) FROM messages").fetchone()[0]
        v.execute("INSERT INTO indice_righe VALUES(?,?,?,?,?)", (rowid, uuid, "i", i + 1, 1))
        v.execute("INSERT INTO vec_chunk_small_rowids VALUES(?,?,?,?)", (i + 1, i + 1, 1, len(blocco)))
        e = np.zeros(384, dtype=np.float32)
        e[asse] = 1
        blocco.append(e)
    v.execute("INSERT INTO vec_chunk_small_vector_chunks00 VALUES(1,?)", (np.array(blocco).tobytes(),))
    c.commit()
    v.commit()
    c.close()
    v.close()
    return db, vec


LUNGO = "x" * 90
RISPOSTA = "y" * 250


def test_lo_scambio_e_il_messaggio_piu_le_risposte(tmp_path: Path) -> None:
    db, vec = _db(tmp_path, [
        ("a", "2026-09-01T10:00:00Z", LUNGO, "human", "own", 0),
        ("b", "2026-09-01T10:00:01Z", RISPOSTA, "assistant", "own", 1),
        ("c", "2026-09-01T10:00:02Z", "corta", "assistant", "own", 2),
        ("d", "2026-09-01T10:00:03Z", LUNGO, "human", "own", 3),
    ])
    s = temi.scambi_di(db, vec, "x")
    assert [x["uuid"] for x in s] == ["a", "d"]
    assert len(s[0]["righe"]) == 2                   # la risposta corta non entra
    # il messaggio del proprietario pesa il doppio della risposta
    assert s[0]["vec"][0] == pytest.approx(2 * s[0]["vec"][1], rel=1e-5)


def test_un_comando_chiude_lo_scambio_e_non_ne_apre_uno(tmp_path: Path) -> None:
    db, vec = _db(tmp_path, [
        ("a", "2026-09-01T10:00:00Z", LUNGO, "human", "own", 0),
        ("g", "2026-09-01T10:00:01Z", "<command-name>/export</command-name>" + LUNGO, "human", "own", 1),
        ("b", "2026-09-01T10:00:02Z", RISPOSTA, "assistant", "own", 2),
    ])
    s = temi.scambi_di(db, vec, "x")
    assert [x["uuid"] for x in s] == ["a"] and len(s[0]["righe"]) == 1


def test_il_programma_e_gli_incollati_non_aprono_scambi(tmp_path: Path) -> None:
    db, vec = _db(tmp_path, [
        ("n", "2026-09-01T10:00:00Z", LUNGO, "system", "unknown", 0),
        ("p", "2026-09-01T10:00:01Z", LUNGO, "human", "pasted_ai", 1),
        ("a", "2026-09-01T10:00:02Z", LUNGO, "human", "own", 2),
        ("b", "2026-09-01T10:00:03Z", RISPOSTA, "assistant", "own", 3),
    ])
    assert [x["uuid"] for x in temi.scambi_di(db, vec, "x")] == ["a"]


def test_senza_assistente_il_messaggio_e_lo_scambio(tmp_path: Path) -> None:
    db, vec = _db(tmp_path, [("v", "2026-09-07T11:00:00Z", LUNGO, "unknown", "unknown", 0)], sightings=False)
    assert [x["uuid"] for x in temi.scambi_di(db, vec, "x")] == ["v"]


def test_una_riga_senza_registro_non_inventa_un_vettore(tmp_path: Path) -> None:
    db, vec = _db(tmp_path, [("a", "2026-09-01T10:00:00Z", LUNGO, "human", "own", None),
                             ("z", "2026-09-01T10:00:01Z", LUNGO, "human", "own", 1)])
    assert [x["uuid"] for x in temi.scambi_di(db, vec, "x")] == ["z"]


def _scambi_finti(n=60):
    X = _nuvole(n=n // 3)
    return [{"db": "a", "uuid": f"u{i}", "ts": "2026-09-01T00:00:00Z", "vec": v,
             "testo": "gateway tunnel" if i < n // 3 else "podcast puntate"} for i, v in enumerate(X)]


def test_il_ricalcolo_riparte_dallo_stato_e_gli_id_restano() -> None:
    ancore = {"lavoro": np.eye(384, dtype=np.float32)[0]}
    m, st = temi.calcola(_scambi_finti(), None, ancore, k=3)
    m2, st2 = temi.calcola(_scambi_finti(), st, ancore)
    assert {t["id"]: t["scambi"] for t in m["temi"]} == {t["id"]: t["scambi"] for t in m2["temi"]}
    assert st2["media"] == st["media"] and st2["ids"] == [0, 1, 2]


def test_il_tema_vicino_all_ancora_nasce_da_guardare() -> None:
    ancore = {"lavoro": np.eye(384, dtype=np.float32)[0]}
    m, _ = temi.calcola(_scambi_finti(), None, ancore, k=3)
    guardare = [t for t in m["temi"] if t["da_guardare"]]
    assert len(guardare) == 1 and guardare[0]["ancora"] == "lavoro"
    assert guardare[0]["quota_ancora"] >= temi.SOGLIA_ANCORA


def test_ogni_strumento_del_servizio_sta_nell_immagine() -> None:
    """La 0.94.0 è uscita senza tools/costruisci_temi.py: il Dockerfile copiava i file per nome, la
    CLI lo lanciava nel container, e tutti i test giravano dal sorgente. L'ha visto la prima
    prova dal vivo, un giro dopo: python non trovava il file."""
    servizio = Path(__file__).resolve().parents[1]
    dockerfile = (servizio / "Dockerfile").read_text(encoding="utf-8")
    copiati = {w for riga in dockerfile.splitlines() if riga.startswith("COPY") for w in riga.split()}
    assert not [p.name for p in (servizio / "tools").glob("*.py") if f"tools/{p.name}" not in copiati]


def test_la_data_e_quella_del_contenuto() -> None:
    assert temi.data_del_contenuto("voce:20260526-062358", "2026-09-07T11:09:13Z").startswith("2026-05-26")
    assert temi.data_del_contenuto("roo-x", "2025-02-01T00:00:00Z") == "2025-02-01T00:00:00Z"
    assert temi.data_del_contenuto("memory:x", "2026-09-07T00:00:00Z", "data-export") == ""


def test_i_vocali_finiscono_nel_mese_dell_audio(tmp_path: Path) -> None:
    db, vec = _db(tmp_path, [("v", "2026-09-07T11:00:00Z", LUNGO, "unknown", "unknown", 0)], sightings=False)
    c = sqlite3.connect(db)
    c.execute("UPDATE messages SET project='voce:20260526-062358'")
    c.commit()
    c.close()
    assert temi.scambi_di(db, vec, "x")[0]["ts"].startswith("2026-05")
