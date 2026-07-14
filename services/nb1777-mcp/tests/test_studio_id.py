# Issue #42 — due bug su studio, entrambi verificati qui senza nlm reale
# (si monkeypatcha _run/_run_json, come test_core_argv).
#
#  ① studio_list deve restituire una proiezione COMPATTA per default (il focus
#     intero, 4-6 KB, resta fuori) e il JSON pieno solo con verbose=True.
#  ② studio_create_* deve risolvere l'id dell'artefatto APPENA creato per
#     DIFFERENZA di snapshot, non per posizione in lista (l'ordine di
#     `status artifacts` non è cronologico).
from __future__ import annotations

from app import core


# ── ① proiezione compatta vs verbose ─────────────────────────────────────────

def test_studio_list_compatto_nasconde_il_focus(monkeypatch) -> None:
    big = "F" * 5000
    monkeypatch.setattr(core, "_run_json", lambda args, **kw: [
        {"id": "A1", "type": "audio", "status": "completed", "custom_instructions": big},
    ])
    compact = core.studio_list("nb")
    assert compact == [{
        "id": "A1", "type": "audio", "status": "completed", "label": "F" * 80,
    }]
    # il label taglia a 80: niente 5 KB inline nel contesto
    assert len(compact[0]["label"]) == 80


def test_studio_list_verbose_restituisce_il_json_pieno(monkeypatch) -> None:
    big = "F" * 5000
    monkeypatch.setattr(core, "_run_json", lambda args, **kw: [
        {"id": "A1", "type": "audio", "custom_instructions": big},
    ])
    full = core.studio_list("nb", verbose=True)
    assert full[0]["custom_instructions"] == big


def test_studio_status_compatto_per_default(monkeypatch) -> None:
    big = "F" * 5000
    monkeypatch.setattr(core, "_run_json", lambda args, **kw: [
        {"id": "A1", "type": "audio", "status": "running", "custom_instructions": big},
    ])
    st = core.studio_status("nb", "A1")
    assert st["status"] == "running"
    assert "custom_instructions" not in st
    assert core.studio_status("nb", "A1", verbose=True)["custom_instructions"] == big


# ── ② l'id si risolve per differenza, non per ordine ─────────────────────────

def test_create_risolve_il_nuovo_id_per_differenza_non_per_ordine(monkeypatch) -> None:
    # Prima del create il NB ha già un artefatto "vecchio" (di ieri). Il create
    # ne aggiunge uno che compare IN TESTA alla lista: col vecchio `[-1]` si
    # sarebbe preso OLD. La differenza di snapshot prende NEW.
    state = {"arts": [{"id": "OLD", "type": "audio"}]}

    def fake_run(args, **kw):
        state["arts"] = [{"id": "NEW", "type": "audio"}] + state["arts"]
        return None

    monkeypatch.setattr(core, "_run", fake_run)
    monkeypatch.setattr(core, "_run_json", lambda args, **kw: list(state["arts"]))

    got = core._create_and_resolve_artifact_id("nb", ["audio", "create", "nb"], "audio", timeout=1)
    assert got == "NEW"


def test_create_ripiega_su_besteffort_se_nessun_id_nuovo(monkeypatch) -> None:
    # Il create non registra nulla di nuovo (0 id nuovi) → best-effort: ultimo
    # del tipo atteso.
    arts = [{"id": "A", "type": "audio"}, {"id": "B", "type": "audio"}]
    monkeypatch.setattr(core, "_run", lambda args, **kw: None)
    monkeypatch.setattr(core, "_run_json", lambda args, **kw: list(arts))
    got = core._create_and_resolve_artifact_id("nb", [], "audio", timeout=1)
    assert got == "B"


def test_create_disambigua_col_tipo_su_concorrenza(monkeypatch) -> None:
    # Nella finestra fra i due snapshot compaiono DUE id nuovi (un'altra sessione
    # ha creato un video). Si disambigua col kind atteso: fra i nuovi, l'unico
    # audio.
    state = {"arts": [{"id": "OLD", "type": "audio"}]}

    def fake_run(args, **kw):
        state["arts"] = [
            {"id": "NEWAUDIO", "type": "audio"},
            {"id": "OTHERVIDEO", "type": "video"},
        ] + state["arts"]
        return None

    monkeypatch.setattr(core, "_run", fake_run)
    monkeypatch.setattr(core, "_run_json", lambda args, **kw: list(state["arts"]))

    got = core._create_and_resolve_artifact_id("nb", [], "audio", timeout=1)
    assert got == "NEWAUDIO"
