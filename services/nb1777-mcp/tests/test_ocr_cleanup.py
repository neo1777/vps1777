"""H40 — cleanup dell'OCR propagato + sweep di recupero.

Lo scratch usa-e-getta creato da `transcribe_document` contiene il documento
OCR-ato: se la sua cancellazione fallisce, il documento resta su NotebookLM.
Qui si verifica, mockando il confine `nb_delete`/`nb_list`/`source_add_file`/
`notebook_query` (nessun nlm, nessuna auth), che:
  - `transcribe_document` riporti `cleanup_ok` (True se la delete riesce, False se
    fallisce anche dopo i retry) e pulisca SEMPRE, anche se la trascrizione solleva;
  - `_delete_notebook_with_retry` riprovi e poi rilanci;
  - `sweep_ingest_notebooks` prenda solo gli scratch `_ingest_*` vecchi, protegga
    quelli con attività recente, e riporti i fallimenti senza sollevare.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app import core


def _iso(epoch: float) -> str:
    """epoch → '2026-07-14T13:44:58Z' (stessa forma di `nlm notebook list`)."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── transcribe_document: cleanup_ok ──────────────────────────────────────────

def test_transcribe_cleanup_ok_true_quando_delete_riesce(monkeypatch) -> None:
    deleted: list[str] = []
    monkeypatch.setattr(core, "nb_create", lambda title: "nb-xyz")
    monkeypatch.setattr(core, "source_add_file", lambda *a, **k: "sid")
    monkeypatch.setattr(core, "notebook_query", lambda nb, q, **k: {"answer": "CIAO"})
    monkeypatch.setattr(core, "nb_delete", lambda nb_id: deleted.append(nb_id))

    out = core.transcribe_document("/tmp/x.pdf")

    assert out["text"] == "CIAO"
    assert out["chars"] == 4
    assert out["cleanup_ok"] is True
    assert deleted == ["nb-xyz"]


def test_transcribe_usa_il_prefisso_reale(monkeypatch) -> None:
    seen: dict = {}
    monkeypatch.setattr(core, "nb_create", lambda title: seen.setdefault("title", title) or "nb")
    monkeypatch.setattr(core, "source_add_file", lambda *a, **k: "sid")
    monkeypatch.setattr(core, "notebook_query", lambda nb, q, **k: {"answer": "t"})
    monkeypatch.setattr(core, "nb_delete", lambda nb_id: None)

    core.transcribe_document("/tmp/x.pdf")
    assert seen["title"].startswith(core.INGEST_NB_PREFIX)


def test_transcribe_cleanup_ok_false_quando_delete_fallisce_sempre(monkeypatch) -> None:
    monkeypatch.setattr(core, "nb_create", lambda title: "nb-xyz")
    monkeypatch.setattr(core, "source_add_file", lambda *a, **k: "sid")
    monkeypatch.setattr(core, "notebook_query", lambda nb, q, **k: {"answer": "T"})

    def boom(nb_id):
        raise core.NLMError("delete ko")

    monkeypatch.setattr(core, "nb_delete", boom)
    monkeypatch.setattr(core.time, "sleep", lambda s: None)  # niente attese nei retry

    out = core.transcribe_document("/tmp/x.pdf")
    assert out["cleanup_ok"] is False
    assert out["text"] == "T"


def test_transcribe_pulisce_anche_se_la_trascrizione_esplode(monkeypatch) -> None:
    deleted: list[str] = []
    monkeypatch.setattr(core, "nb_create", lambda title: "nb-boom")
    monkeypatch.setattr(core, "nb_delete", lambda nb_id: deleted.append(nb_id))

    def add_boom(*a, **k):
        raise core.NLMError("add fallita")

    monkeypatch.setattr(core, "source_add_file", add_boom)

    with pytest.raises(core.NLMError):
        core.transcribe_document("/tmp/x.pdf")
    assert deleted == ["nb-boom"]  # il finally ha comunque cancellato lo scratch


# ── _delete_notebook_with_retry ──────────────────────────────────────────────

def test_delete_retry_riprova_e_poi_riesce(monkeypatch) -> None:
    n = {"c": 0}

    def flaky(nb_id):
        n["c"] += 1
        if n["c"] < 3:
            raise core.NLMError("transiente")

    monkeypatch.setattr(core, "nb_delete", flaky)
    monkeypatch.setattr(core.time, "sleep", lambda s: None)

    core._delete_notebook_with_retry("nb-1", attempts=3)
    assert n["c"] == 3


def test_delete_retry_rilancia_dopo_esaurimento(monkeypatch) -> None:
    def always(nb_id):
        raise core.NLMError("giù")

    monkeypatch.setattr(core, "nb_delete", always)
    monkeypatch.setattr(core.time, "sleep", lambda s: None)

    with pytest.raises(core.NLMError):
        core._delete_notebook_with_retry("nb-1", attempts=2)


# ── sweep_ingest_notebooks ───────────────────────────────────────────────────

def test_sweep_prende_solo_ingest_vecchi(monkeypatch) -> None:
    now = 1_000_000.0
    monkeypatch.setattr(core.time, "time", lambda: now)
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    nbs = [
        {"id": "keep-1", "title": "vps-1777", "updated_at": _iso(now - 99999)},
        {"id": "old-ing", "title": "_ingest_abcd", "updated_at": _iso(now - 7200)},
        {"id": "fresh-ing", "title": "_ingest_ef01", "updated_at": _iso(now - 60)},
        {"id": "no-ts-ing", "title": "_ingest_9999"},  # nessun updated_at → non databile
    ]
    monkeypatch.setattr(core, "nb_list", lambda: nbs)
    deleted: list[str] = []
    monkeypatch.setattr(core, "nb_delete", lambda nb_id: deleted.append(nb_id))

    res = core.sweep_ingest_notebooks(older_than_s=3600)

    assert set(res["deleted"]) == {"old-ing", "no-ts-ing"}
    assert "fresh-ing" not in res["deleted"]  # protetto: attività recente
    assert "keep-1" not in res["deleted"]      # non è uno scratch OCR
    assert res["skipped_recent"] == 1
    assert res["swept_ok"] is True


def test_sweep_riporta_i_fallimenti_senza_sollevare(monkeypatch) -> None:
    now = 1_000_000.0
    monkeypatch.setattr(core.time, "time", lambda: now)
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    monkeypatch.setattr(core, "nb_list", lambda: [
        {"id": "x", "title": "_ingest_1", "updated_at": _iso(now - 9999)}])

    def boom(nb_id):
        raise core.NLMError("no")

    monkeypatch.setattr(core, "nb_delete", boom)

    res = core.sweep_ingest_notebooks(older_than_s=3600)
    assert res["deleted"] == []
    assert res["failed"] and res["failed"][0]["id"] == "x"
    assert res["swept_ok"] is False


def test_sweep_rispetta_max_deletes(monkeypatch) -> None:
    now = 1_000_000.0
    monkeypatch.setattr(core.time, "time", lambda: now)
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    nbs = [{"id": f"ing-{i}", "title": f"_ingest_{i}", "updated_at": _iso(now - 9999)}
           for i in range(5)]
    monkeypatch.setattr(core, "nb_list", lambda: nbs)
    deleted: list[str] = []
    monkeypatch.setattr(core, "nb_delete", lambda nb_id: deleted.append(nb_id))

    res = core.sweep_ingest_notebooks(older_than_s=3600, max_deletes=2)
    assert len(res["deleted"]) == 2
    assert res["candidates"] == 5  # visti tutti, cancellati solo 2 per il tetto
