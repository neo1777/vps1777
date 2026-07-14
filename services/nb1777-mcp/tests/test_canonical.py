# Issue #30 — il canonico del blocco di memoria 1777.
# Il parser è PURO (niente I/O): si testa dando la lista che restituirebbe
# source_list. get_canonical (che chiama nlm) è fail-open, testato a parte col
# monkeypatch di core.source_list.
from __future__ import annotations

from app import canonical


# Titoli reali del notebook claudemd1777 (letti dal vivo il 14/07), più rumore
# non-canonico da ignorare.
REAL_SOURCES = [
    {"title": "canonico v2.2 — 2026-07-11 — blocco pieno + blocco-lite + identità verificata"},
    {"title": "canonico v2.3 — 2026-07-13 — asse FRESCHEZZA (il tempo del giudizio)"},
    {"title": "canonico v2.4 — 2026-07-13 — regola CANONICO (la freschezza applicata al blocco stesso)"},
    {"title": "censimento completo filesystem + innesti round 2 — 2026-07-12 00:30"},
    {"title": "distribuzione completata — 2026-07-12 00:30 — globale innestato"},
]


def test_prende_la_versione_piu_alta_dai_titoli_reali() -> None:
    got = canonical.highest_canonical(REAL_SOURCES)
    assert got is not None
    assert got["version"] == "v2.4"
    assert got["date"] == "2026-07-13"
    assert got["note"].startswith("regola CANONICO")


def test_ignora_le_fonti_non_canoniche() -> None:
    # Solo rumore → nessun canonico.
    noise = [
        {"title": "censimento superfici — 2026-07-11 — 11 file su disco"},
        {"title": "innesto eseguito — 2026-07-12 notte — 6 file su disco"},
    ]
    assert canonical.highest_canonical(noise) is None


def test_confronto_numerico_non_lessicale() -> None:
    # v2.10 deve battere v2.9 (10 > 9), non perdere per confronto tra stringhe.
    srcs = [
        {"title": "canonico v2.9 — 2026-08-01 — nona"},
        {"title": "canonico v2.10 — 2026-08-02 — decima"},
    ]
    assert canonical.highest_canonical(srcs)["version"] == "v2.10"


def test_titolo_senza_data() -> None:
    got = canonical.highest_canonical([{"title": "canonico v3.0 — cambio grosso"}])
    assert got["version"] == "v3.0"
    assert got["date"] is None
    assert got["note"] == "cambio grosso"


def test_lista_vuota_o_none() -> None:
    assert canonical.highest_canonical([]) is None
    assert canonical.highest_canonical(None) is None


def test_titolo_malformato_ignorato() -> None:
    # "canonico" senza versione, o versione non numerica → ignorato.
    srcs = [
        {"title": "canonico senza versione"},
        {"title": "canonico vX.Y — non numerica"},
        {"title": "canonico v1.5 — 2026-01-01 — buona"},
    ]
    assert canonical.highest_canonical(srcs)["version"] == "v1.5"


def test_public_view_disponibile_e_non() -> None:
    view = canonical.public_view({"version": "v2.4", "date": "2026-07-13", "note": "x"})
    assert view["available"] is True and view["version"] == "v2.4"
    assert "major" not in view  # niente dettagli interni verso i tool
    down = canonical.public_view(None)
    assert down["available"] is False and "notebook_query" in down["nota"]


# ── get_canonical: cache + fail-open (monkeypatch di core.source_list) ────────

def test_get_canonical_usa_e_scrive_la_cache(monkeypatch) -> None:
    calls = {"n": 0}

    def fake_source_list(nb_id):
        calls["n"] += 1
        assert nb_id == canonical.CANON_NOTEBOOK_ID
        return REAL_SOURCES

    monkeypatch.setattr(canonical.core, "source_list", fake_source_list)
    # cache pulita
    canonical._cache["data"] = None
    canonical._cache["ts"] = 0.0

    first = canonical.get_canonical(force=True)
    assert first["version"] == "v2.4"
    assert calls["n"] == 1
    # seconda chiamata entro TTL → cache, niente nuovo fetch
    second = canonical.get_canonical()
    assert second["version"] == "v2.4"
    assert calls["n"] == 1


def test_get_canonical_fail_open_tiene_la_cache(monkeypatch) -> None:
    monkeypatch.setattr(canonical.core, "source_list", lambda nb: REAL_SOURCES)
    canonical._cache["data"] = None
    canonical._cache["ts"] = 0.0
    assert canonical.get_canonical(force=True)["version"] == "v2.4"

    # ora il notebook esplode: get_canonical NON deve sollevare, torna la cache
    def boom(nb):
        raise RuntimeError("notebook irraggiungibile")

    monkeypatch.setattr(canonical.core, "source_list", boom)
    assert canonical.get_canonical(force=True)["version"] == "v2.4"
