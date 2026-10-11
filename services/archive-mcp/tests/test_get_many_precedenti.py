"""P5 (11/10/2026): leggere più messaggi in una chiamata, sapere chi parla, trovare i precedenti.

Tre cose, dal dossier dell'evoluzione degli MCP (§3.5, P5):
  · `get_many(uuids)`: dopo una ricerca, i testi pieni di N risultati costavano N chiamate
    a `get_context` (1+N giri). Ora è una chiamata sola, e dice quali uuid mancano.
  · `speaker` (e `voice`) sulle righe di `search`, `search_ibrida` e `get_context`: la
    regola 3 del server dice «una citazione non è un fatto finché non sai chi parla», ma
    né le righe della ricerca né `get_context` lo dicevano. Si doveva rifare la ricerca
    con `speaker='human'` per saperlo.
  · `precedenti(tema)`: «l'hai già detto?» prima di aprire un filone (#281). Un involucro
    su `search_ibrida` con `speaker='human'`, fino a N giorni fa, raggruppato per
    `project`. Il personale resta fuori perché il perimetro di default (P1) non lo tocca.

Stdlib, tranne l'ultimo test (sqlite-vec, step «deps del lock» della CI).
"""
from __future__ import annotations

import datetime as dt
import sqlite3
import sys
import types
from pathlib import Path

import pytest

_SERVIZIO = Path(__file__).resolve().parents[1]

_SCHEMA = """
CREATE TABLE messages(uuid TEXT PRIMARY KEY, project, ts, content,
                      tools TEXT DEFAULT '', speaker TEXT DEFAULT '', voice TEXT DEFAULT '',
                      sender TEXT DEFAULT '', parent_uuid TEXT DEFAULT '');
CREATE VIRTUAL TABLE messages_fts USING fts5(
    uuid, project, ts, content, content='messages', content_rowid='rowid');
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
"""

# (uuid, project, ts, content, tools, speaker, voice)
_RIGHE = {
    "prim": ("primario", [
        ("h1", "chat-a", "2026-05-01T10:00:00Z", "il piano della memoria a tre livelli", "",
         "human", "own"),
        ("a1", "chat-a", "2026-05-01T10:01:00Z", "ecco il piano della memoria", "",
         "assistant", "own"),
        ("t1", "chat-a", "2026-05-01T10:02:00Z", "", '[{"name": "Bash"}]', "tool", ""),
        ("comune", "chat-b", "2026-05-02T10:00:00Z", "riga che vive in due DB", "",
         "human", "pasted_ai"),
    ]),
    "foto": ("fotografia", [
        ("comune", "chat-b", "2026-05-02T10:00:00Z", "riga che vive in due DB", "",
         "human", "pasted_ai"),
        ("f1", "chat-c", "2026-04-01T10:00:00Z", "solo nella fotografia", "", "human", "own"),
    ]),
    "pers": ("riservato", [
        ("p1", "diario", "2026-04-02T10:00:00Z", "materiale personale sul piano", "",
         "human", "own"),
    ]),
}


def _crea(percorso: Path, ruolo: str, righe: list[tuple]) -> None:
    c = sqlite3.connect(percorso)
    c.executescript(_SCHEMA)
    c.executemany("INSERT INTO messages(uuid, project, ts, content, tools, speaker, voice) "
                  "VALUES (?,?,?,?,?,?,?)", righe)
    c.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
    c.execute("INSERT INTO meta(key, value) VALUES ('ruolo', ?)", (ruolo,))
    c.commit()
    c.close()


def _vecchio(percorso: Path) -> None:
    """Un DB v1: niente colonne speaker/voice/tools."""
    c = sqlite3.connect(percorso)
    c.executescript("""
        CREATE TABLE messages(uuid TEXT PRIMARY KEY, project, ts, content);
        CREATE VIRTUAL TABLE messages_fts USING fts5(
            uuid, project, ts, content, content='messages', content_rowid='rowid');""")
    c.execute("INSERT INTO messages VALUES ('v1', 'storico', '2025-01-01', 'il piano antico')")
    c.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
    c.commit()
    c.close()


class _SettingsFinte:
    def __init__(self, d: Path) -> None:
        self.archive_db_dir = str(d)
        self.archive_db_paths: dict[str, Path] = {}
        self.archive_model_dir = str(d / "modello")


def _importa_db(tmp_path: Path, monkeypatch):
    sys.path.insert(0, str(_SERVIZIO))
    for mod in [m for m in list(sys.modules) if m == "app" or m.startswith("app.")]:
        del sys.modules[mod]
    finte = types.ModuleType("app.settings")
    finte.get_settings = lambda: _SettingsFinte(tmp_path)   # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.settings", finte)
    from app import db as modulo
    modulo.reload_registry()
    return modulo


@pytest.fixture()
def db(tmp_path, monkeypatch):
    for nome, (ruolo, righe) in _RIGHE.items():
        _crea(tmp_path / f"{nome}.db", ruolo, righe)
    _vecchio(tmp_path / "storico.db")
    yield _importa_db(tmp_path, monkeypatch)


# ── get_many ────────────────────────────────────────────────────────────────────

def test_get_many_una_chiamata_per_n_messaggi_nell_ordine_chiesto(db):
    r = db.get_many(["a1", "h1"])
    assert [x["uuid"] for x in r["righe"]] == ["a1", "h1"]
    assert r["righe"][1]["content"] == "il piano della memoria a tre livelli"
    assert r["righe"][1]["speaker"] == "human" and r["righe"][1]["voice"] == "own"
    assert r["righe"][0]["speaker"] == "assistant"
    assert {x["db"] for x in r["righe"]} == {"prim"}
    assert all(x.get("snapshot") for x in r["righe"])
    assert r["mancanti"] == []


def test_get_many_dice_quali_uuid_mancano(db):
    r = db.get_many(["h1", "non-esiste"])
    assert [x["uuid"] for x in r["righe"]] == ["h1"]
    assert r["mancanti"] == ["non-esiste"]


def test_get_many_riga_senza_testo_porta_le_azioni(db):
    (riga,) = db.get_many(["t1"])["righe"]
    assert riga["content"] == "" and "Bash" in riga["tools"]
    assert riga["speaker"] == "tool"


def test_get_many_stesso_uuid_in_due_db_una_riga_sola_col_primario_prima(db):
    r = db.get_many(["comune"])
    assert len(r["righe"]) == 1
    assert r["righe"][0]["db"] == "prim" and r["righe"][0]["anche_in"] == ["foto"]


def test_get_many_trova_anche_fuori_dal_perimetro_di_ricerca(db):
    """Un uuid si chiede perché lo si è già trovato: come get_context, guarda in ogni DB."""
    r = db.get_many(["f1", "p1"])
    assert {x["uuid"]: x["db"] for x in r["righe"]} == {"f1": "foto", "p1": "pers"}


def test_get_many_con_db_name_guarda_solo_li(db):
    r = db.get_many(["comune", "h1"], "foto")
    assert [x["uuid"] for x in r["righe"]] == ["comune"]
    assert r["righe"][0]["db"] == "foto" and "anche_in" not in r["righe"][0]
    assert r["mancanti"] == ["h1"]


def test_get_many_tronca_dichiarandolo(db):
    (riga,) = db.get_many(["h1"], max_chars=8)["righe"]
    assert riga["content"].startswith("il piano") and "troncato" in riga["content"]


def test_get_many_doppioni_e_limiti(db):
    assert [x["uuid"] for x in db.get_many(["h1", "h1", "a1"])["righe"]] == ["h1", "a1"]
    with pytest.raises(ValueError, match="almeno un uuid"):
        db.get_many([])
    with pytest.raises(ValueError, match="al massimo"):
        db.get_many([f"u{i}" for i in range(db.GET_MANY_MASSIMO + 1)])


def test_get_many_su_un_db_vecchio_senza_colonne_speaker(db):
    (riga,) = db.get_many(["v1"])["righe"]
    assert riga["content"] == "il piano antico" and "speaker" not in riga


# ── speaker e voice sulle righe ────────────────────────────────────────────────

def test_search_dice_chi_parla_su_ogni_riga(db):
    righe = db.search("piano", "prim")
    per_uuid = {r["uuid"]: r for r in righe}
    assert per_uuid["h1"]["speaker"] == "human" and per_uuid["h1"]["voice"] == "own"
    assert per_uuid["a1"]["speaker"] == "assistant"


def test_search_su_db_vecchio_non_inventa_lo_speaker(db):
    (riga,) = db.search("antico", "storico")
    assert "speaker" not in riga


def test_get_context_dice_chi_parla(db):
    ctx = db.get_context("h1", "prim", before=0, after=1)
    assert [(r["uuid"], r["speaker"]) for r in ctx] == [("h1", "human"), ("a1", "assistant")]


def test_get_conversation_dice_chi_parla_accanto_a_sender(db):
    conv = db.get_conversation("h1", "prim")
    assert {r["uuid"]: r.get("speaker") for r in conv}["a1"] == "assistant"


# ── precedenti ─────────────────────────────────────────────────────────────────

def _ibrida_finta(chiamate: list[dict]):
    def finta(query, db="", limit=20, **k):
        chiamate.append({"query": query, "db": db, "limit": limit, **k})
        return {
            "righe": [
                {"db": "prim", "uuid": "h1", "project": "chat-a", "ts": "2026-05-01T10:00:00Z",
                 "snippet": "il piano", "origine": "entrambi", "speaker": "human",
                 "voice": "own"},
                {"db": "prim", "uuid": "comune", "project": "chat-b",
                 "ts": "2026-05-02T10:00:00Z", "snippet": "riga", "origine": "vettori",
                 "speaker": "human", "voice": "pasted_ai"},
                {"db": "prim", "uuid": "h0", "project": "chat-a", "ts": "2026-03-01T10:00:00Z",
                 "snippet": "prima ancora", "origine": "fts", "speaker": "human",
                 "voice": "own"},
            ],
            "indici": [{"db": "prim"}],
            "parametri": {"k_rrf": 30},
            "fuori_perimetro": {"riservato": ["pers"]},
        }
    return finta


def test_precedenti_chiede_le_parole_del_proprietario_fino_a_n_giorni_fa(db, monkeypatch):
    chiamate: list[dict] = []
    monkeypatch.setattr(db, "search_ibrida", _ibrida_finta(chiamate))
    db.precedenti("il piano della memoria", giorni=7, limit=15)
    (c,) = chiamate
    assert c["query"] == "il piano della memoria" and c["limit"] == 15
    assert c["speaker"] == "human"
    attesa = (dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=7)).isoformat()
    assert c["until"].startswith(attesa) and c["until"] > attesa + "T23:59"
    assert c.get("ruoli", "") == ""      # il perimetro di default: il riservato resta fuori


def test_precedenti_zero_giorni_non_mette_la_finestra(db, monkeypatch):
    chiamate: list[dict] = []
    monkeypatch.setattr(db, "search_ibrida", _ibrida_finta(chiamate))
    r = db.precedenti("x", giorni=0)
    assert chiamate[0]["until"] == "" and r["fino_a"] == ""


def test_precedenti_raggruppa_per_project_nell_ordine_del_migliore(db, monkeypatch):
    monkeypatch.setattr(db, "search_ibrida", _ibrida_finta([]))
    r = db.precedenti("il piano")
    assert [g["project"] for g in r["gruppi"]] == ["chat-a", "chat-b"]
    a = r["gruppi"][0]
    assert a["n"] == 2 and [x["uuid"] for x in a["righe"]] == ["h1", "h0"]
    assert a["primo_ts"] == "2026-03-01T10:00:00Z" and a["ultimo_ts"] == "2026-05-01T10:00:00Z"
    assert a["db"] == ["prim"]
    # la voce resta sulla riga: un «human» incollato non è una sua parola
    assert r["gruppi"][1]["righe"][0]["voice"] == "pasted_ai"
    assert r["righe_totali"] == 3
    # quello che search_ibrida dice sul perimetro non si perde
    assert r["indici"] == [{"db": "prim"}] and r["fuori_perimetro"] == {"riservato": ["pers"]}


def test_precedenti_valida_i_giorni(db):
    with pytest.raises(ValueError, match="giorni"):
        db.precedenti("x", giorni=-1)


# ── search_ibrida con l'indice vero (sqlite-vec) ──────────────────────────────

def _ha_vec() -> bool:
    try:
        import sqlite_vec
        c = sqlite3.connect(":memory:")
        c.enable_load_extension(True)
        sqlite_vec.load(c)
        c.close()
        return True
    except Exception:                                   # noqa: BLE001
        return False


@pytest.mark.skipif(not _ha_vec(), reason="sqlite-vec assente (step stdlib-only)")
def test_search_ibrida_dice_chi_parla(tmp_path, monkeypatch):
    sys.path.insert(0, str(_SERVIZIO / "tools"))
    sys.path.insert(0, str(_SERVIZIO / "tests"))
    import test_costruisci_indice as tci
    frase = "Un messaggio sintetico abbastanza lungo da entrare nell'indice vettoriale"
    percorso = tci.nuovo_db(tmp_path / "arch.db", [
        (f"u{i}", "claude-code", f"2026-05-{10 + i:02d}", f"{frase} numero {i}")
        for i in range(1, 4)])
    c = sqlite3.connect(percorso)
    c.execute("ALTER TABLE messages ADD COLUMN speaker TEXT DEFAULT ''")
    c.execute("ALTER TABLE messages ADD COLUMN voice TEXT DEFAULT ''")
    c.execute("UPDATE messages SET speaker='human', voice='own' WHERE uuid='u2'")
    c.execute("UPDATE messages SET speaker='assistant', voice='own' WHERE uuid<>'u2'")
    c.commit()
    c.close()
    import costruisci_indice as ci
    ci.costruisci(percorso, tci.Finto(), ci.Perimetro(tutto=True))
    modulo = _importa_db(tmp_path, monkeypatch)
    blob = tci.vettore(modulo.semantica.PREFISSO_PASSAGGIO + f"{frase} numero 2")
    monkeypatch.setattr(modulo.semantica, "embed_query", lambda q, d: blob)
    righe = modulo.search_ibrida("x", db="arch", limit=3)["righe"]
    assert righe[0]["uuid"] == "u2" and righe[0]["speaker"] == "human"
    assert {r["speaker"] for r in righe[1:]} == {"assistant"}


# ── i DB del perimetro senza indice si dicono ──────────────────────────────────

def test_search_ibrida_dice_quali_db_del_perimetro_non_hanno_l_indice(db, monkeypatch):
    """Dal vivo, 11/10: `precedenti` sui casi della #281 cercava in 5 DB su 8 del perimetro.
    Il primario di claude.ai non ha l'indice per senso, e la risposta non lo diceva: zero
    risultati da lì sembravano un'assenza."""
    monkeypatch.setattr(db, "_indici_disponibili", lambda: {"prim": Path("/x/prim.vec.db")})
    monkeypatch.setattr(db.semantica, "embed_query", lambda t, d: b"\x00" * 4)

    class _Finta:
        def execute(self, *a, **k):
            raise sqlite3.OperationalError("niente vec in questo test")
        def close(self):
            pass

        def set_progress_handler(self, *a):
            pass
    monkeypatch.setattr(db, "_open_con_indice", lambda name, idx: _Finta())
    out = db.search_ibrida("piano", limit=5)
    # nel perimetro di default: prim (primario) e storico (non dichiarato); solo prim ha l'indice
    assert out["senza_indice"] == ["storico"]


def test_precedenti_porta_senza_indice(db, monkeypatch):
    def finta(query, db="", limit=20, **k):
        return {"righe": [], "indici": [], "parametri": {}, "senza_indice": ["claude-ai"]}
    monkeypatch.setattr(db, "search_ibrida", finta)
    r = db.precedenti("x")
    assert r["senza_indice"] == ["claude-ai"]
    assert "senza indice" in r["nota"]
