"""L'update lascia la SEQUENZA degli step, non solo l'ultimo stato (ops.update-progress-journal).

Il difetto (trovato il 20/07 da b82df434, rinviato «un fix per release»): `progress_write`
sovrascriveva un file solo, `onboarding/update_progress.json`. A update finito restava
l'ultimo stato: un update RIUSCITO non lasciava prova dell'ordine degli step (che il
pre-flight fosse girato prima del backup non era leggibile da nessuna parte), e un
auto-update delle 4 del mattino non raccontava niente a chi guardava alle 9.

La cura: ogni `progress_write` aggiunge anche una riga a `onboarding/update_journal.ndjson`.
Il file ha un tetto (le ultime `_JOURNAL_MAX_RIGHE` righe), e come il resto della
telemetria non può far cadere l'update.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("vps1777_cli", _ROOT / "tools" / "vps1777.py")
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)


def _righe(repo: Path) -> list[dict]:
    p = repo / "onboarding" / "update_journal.ndjson"
    return [json.loads(r) for r in p.read_text().splitlines()]


def test_un_update_riuscito_lascia_la_sequenza(tmp_path):
    v._TELEMETRIA_MUTA = False
    passi = [(1, "preflight", "running"), (4, "backup", "running"),
             (6, "preflight-secrets-bundle", "running"), (9, "health-gate", "done")]
    for n, nome, stato in passi:
        v.progress_write(tmp_path, "9.9.9", n, nome, stato, f"d{n}")
    righe = _righe(tmp_path)
    assert [(r["step"], r["step_name"], r["status"]) for r in righe] == passi
    assert all(r["target"] == "9.9.9" and r["updated_at"] for r in righe)
    # lo stato per i pannelli resta quello di prima: l'ultimo
    stato = json.loads((tmp_path / "onboarding" / "update_progress.json").read_text())
    assert stato["step"] == 9 and stato["status"] == "done"


def test_il_journal_si_accumula_fra_due_update(tmp_path):
    v._TELEMETRIA_MUTA = False
    v.progress_write(tmp_path, "1.0.0", 9, "health-gate", "done")
    v.progress_write(tmp_path, "1.0.1", 1, "preflight", "running")
    assert [r["target"] for r in _righe(tmp_path)] == ["1.0.0", "1.0.1"]


def test_il_journal_ha_un_tetto(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "_JOURNAL_MAX_RIGHE", 10)
    v._TELEMETRIA_MUTA = False
    for n in range(25):
        v.progress_write(tmp_path, "1.0.0", n, f"s{n}", "running")
    righe = _righe(tmp_path)
    assert len(righe) <= 10 and righe[-1]["step"] == 24, "tiene le ULTIME, non le prime"


def test_journal_non_scrivibile_non_ferma_l_update(tmp_path):
    if os.geteuid() == 0:
        return  # da root il chmod non morde
    ob = tmp_path / "onboarding"
    ob.mkdir()
    ob.chmod(0o500)
    try:
        v._TELEMETRIA_MUTA = False
        v.progress_write(tmp_path, "1.0.0", 1, "preflight", "running")
    finally:
        ob.chmod(0o700)
