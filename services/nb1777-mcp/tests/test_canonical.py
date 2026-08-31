# Issue #30 → 0.44.0: il canonico del blocco di memoria 1777 vive nel PRODOTTO
# (app/memoria_1777/disciplina.md), non più nel notebook. Il parser è PURO
# (testo → dict); la lettura dal file e dagli strati locali si testa con
# monkeypatch dei path. I parser dei titoli del notebook restano (storico).
from __future__ import annotations

from pathlib import Path

from app import canonical


DISCIPLINA_MINIMA = """# Disciplina di memoria 1777 — canonico v2.5 · 2026-08-30

<!-- commento per chi legge il file: NON deve uscire dal tool -->

## Storia
- v2.5 · 2026-08-30 — SEDE nel prodotto; CURA con full=true,
  su più righe come nel file vero.
- v2.4 · 2026-07-13 — regola CANONICO.

## PIENO
<!-- superfici con MCP -->
## Memoria 1777 (v2.5 · 2026-08-30 · canonico: vps1777, tool `canonico`)
riga uno del pieno
riga due del pieno

## LITE
## Disciplina di memoria 1777 (lite · v2.5 · 2026-08-30)
- riga del lite

## MICRO
- riga del micro
"""


# ── il parser del file ───────────────────────────────────────────────────────

def test_parse_titolo_versione_data_e_nota() -> None:
    d = canonical.parse_disciplina(DISCIPLINA_MINIMA)
    assert d and d["version"] == "v2.5" and (d["major"], d["minor"]) == (2, 5)
    assert d["date"] == "2026-08-30"
    assert d["note"] == "SEDE nel prodotto; CURA con full=true, su più righe come nel file vero.", (
        "la nota è la voce di Storia INTERA: la prima riga da sola esce troncata "
        "a metà frase nel verdetto di ogni memoria_check")


def test_parse_tre_tagli_senza_commenti_html() -> None:
    d = canonical.parse_disciplina(DISCIPLINA_MINIMA)
    assert d["tagli"]["pieno"].startswith("## Memoria 1777 (v2.5")
    assert "riga due del pieno" in d["tagli"]["pieno"]
    assert "<!--" not in d["tagli"]["pieno"], "i commenti del file non sono per la sessione"
    assert d["tagli"]["lite"].startswith("## Disciplina di memoria 1777 (lite")
    assert d["tagli"]["micro"] == "- riga del micro"
    assert "riga del lite" not in d["tagli"]["pieno"], "un taglio non deve inglobare il successivo"


def test_parse_senza_titolo_o_senza_data_e_none() -> None:
    assert canonical.parse_disciplina("") is None
    assert canonical.parse_disciplina("# Disciplina — canonico v2.5\n## PIENO\nx") is None, (
        "un canonico senza data è ciò che FRESCHEZZA vieta: non si accetta")


def test_il_file_del_prodotto_esiste_e_si_legge() -> None:
    """Il canonico VERO, quello spedito nell'immagine: deve stare nel package
    (COPY app → /app/app) e avere titolo con versione e data, e i tre tagli
    non vuoti — un taglio vuoto sarebbe una sessione che si allinea al nulla."""
    assert canonical.DISCIPLINA_PATH.is_file(), canonical.DISCIPLINA_PATH
    assert canonical.DISCIPLINA_PATH.parent.name == "memoria_1777"
    assert canonical.DISCIPLINA_PATH.parent.parent == Path(canonical.__file__).resolve().parent
    d = canonical.get_canonical()
    assert d and d["date"] and d["version"].startswith("v")
    for t in canonical.TAGLI:
        assert len(d["tagli"][t]) > 200, f"taglio {t} vuoto o troncato"
        assert d["version"] in d["tagli"][t], (
            f"il taglio {t} non porta in testa la versione {d['version']}: "
            "una superficie che lo incolla non saprebbe cosa porta")


def test_il_canonico_del_prodotto_e_neutro() -> None:
    """NEUTRALITÀ: vps1777 è un prodotto per chiunque. Il file non nomina il suo
    primo utente né riferimenti locali; i fatti e l'errata stanno negli strati."""
    d = canonical.get_canonical()
    # Si giudica ciò che una sessione RICEVE (i tre tagli), non la «Storia», che
    # può legittimamente dire «la parola X è stata tolta».
    for t in canonical.TAGLI:
        for vietato in ("di Neo", "a Neo", "Cowork", "cookbook_query", "marzio", "81/81"):
            assert vietato not in d["tagli"][t], f"riferimento non neutro nel taglio {t}: {vietato!r}"


# ── fail-open e strati locali (path monkeypatchati) ─────────────────────────

def test_get_canonical_fail_open_su_file_mancante(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(canonical, "DISCIPLINA_PATH", tmp_path / "non-c-e.md")
    assert canonical.get_canonical() is None
    v = canonical.public_view(None)
    assert v["available"] is False and "disciplina.md" in v["nota"]


def test_public_view_non_espone_i_tagli() -> None:
    d = canonical.parse_disciplina(DISCIPLINA_MINIMA)
    v = canonical.public_view(d)
    assert v == {"available": True, "version": "v2.5", "date": "2026-08-30",
                 "note": d["note"], "sede": v["sede"]}
    assert "tagli" not in v and "disciplina" not in v


def test_full_view_porta_disciplina_e_strati_con_origine(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(canonical, "dir_strati_locali", lambda: tmp_path / "memoria-1777")
    (tmp_path / "memoria-1777").mkdir()
    (tmp_path / "memoria-1777" / "fatti.md").write_text("# fatti\n- dominio: Dart\n")
    d = canonical.parse_disciplina(DISCIPLINA_MINIMA)
    v = canonical.full_view(d, taglio="lite")
    assert v["available"] and v["taglio"] == "lite"
    assert v["disciplina"] == d["tagli"]["lite"]
    assert "prodotto" in v["origine_disciplina"]
    strati = {s["strato"]: s for s in v["strati"]}
    assert strati["fatti"]["presente"] and "Dart" in strati["fatti"]["testo"]
    assert strati["errata"]["presente"] is False and strati["errata"]["testo"] is None
    assert "locale" in strati["fatti"]["origine"] and "non nel prodotto" in strati["fatti"]["origine"]


def test_full_view_taglio_sconosciuto_e_un_errore_parlante() -> None:
    d = canonical.parse_disciplina(DISCIPLINA_MINIMA)
    v = canonical.full_view(d, taglio="gigante")
    assert v["available"] and "taglio sconosciuto" in v["errore"]


def test_full_view_fail_open() -> None:
    assert canonical.full_view(None)["available"] is False


def test_read_strato_nome_invalido() -> None:
    import pytest
    with pytest.raises(ValueError):
        canonical.read_strato("segreti")


# ── i parser dello STORICO (titoli del notebook claudemd1777) ────────────────

STORICO = [
    {"title": "canonico v2.2 — 2026-07-11 — blocco pieno + blocco-lite + identità verificata"},
    {"title": "canonico v2.4 — 2026-07-13 — regola CANONICO (la freschezza applicata al blocco stesso)"},
    {"title": "canonico v2.3 — 2026-07-13 — asse FRESCHEZZA (il tempo del giudizio)"},
    {"title": "cloud-ack v2.4 — 2026-08-30 — superfici cloud allineate"},
    {"title": "censimento completo filesystem + innesti round 2 — 2026-07-12 00:30"},
]


def test_storico_versione_piu_alta_numerica() -> None:
    best = canonical.highest_canonical(STORICO)
    assert best["version"] == "v2.4" and best["date"] == "2026-07-13"
    assert canonical.highest_canonical([{"title": "canonico v2.9 — x"},
                                        {"title": "canonico v2.10 — y"}])["version"] == "v2.10"
    assert canonical.highest_canonical([]) is None and canonical.highest_canonical(None) is None


def test_storico_cloud_ack() -> None:
    assert canonical.highest_cloud_ack(STORICO) == (2, 4)
    assert canonical.highest_cloud_ack(STORICO[:3]) is None


def test_il_prodotto_non_e_indietro_rispetto_allo_storico() -> None:
    """Il file del prodotto deve essere ≥ dell'ultima versione del notebook
    storico: se qualcuno riportasse il file a v2.3, il notebook «vincerebbe»
    e nessuno se ne accorgerebbe."""
    d = canonical.get_canonical()
    st = canonical.highest_canonical(STORICO)
    assert (d["major"], d["minor"]) > (st["major"], st["minor"])


def test_declaration_text_non_nomina_il_notebook() -> None:
    t = canonical.declaration_text()
    assert "canonico" in t and "full=true" in t
    assert "notebook_query" not in t and "claudemd1777" not in t
