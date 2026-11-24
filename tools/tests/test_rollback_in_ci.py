"""STA-06: la prova del rollback gira in CI su uno stack vivo, sana e sabotata.

`.github/workflows/rollback.yml` installa una release sul runner, aggiorna, e lancia la prova 9 col
controllo di salute forzato a fallire. Qui si presidia la FORMA che rende la prova una prova: il job
sabotato deve pretendere l'1, il sabotaggio deve entrare nella funzione che esiste davvero, e il
gettone per l'API va solo all'API. Che il rollback AVVENGA lo dice la corsa, non questo file.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import yaml

RADICE = Path(__file__).resolve().parents[2]
WF = RADICE / ".github" / "workflows" / "rollback.yml"
_spec = importlib.util.spec_from_file_location("vps1777_cli_rollback", RADICE / "tools" / "vps1777.py")
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)


def _wf() -> dict:
    return yaml.safe_load(WF.read_text(encoding="utf-8"))


def test_i_due_job_hanno_i_nomi_che_lo_standard_legge():
    job = _wf()["jobs"]["rollback"]
    assert job["name"] == "rollback-${{ matrix.modo }}"
    assert job["strategy"]["matrix"]["modo"] == ["sano", "sabotato"]
    assert job["strategy"]["fail-fast"] is False       # il sabotato deve girare anche se il sano cade


def test_gira_a_calendario_almeno_due_volte_al_mese():
    """Chi legge l'ultima corsa su main ha un tetto di 31 giorni: una corsa al mese lo sfiora."""
    on = _wf()[True]                                    # YAML legge la chiave `on` come booleano
    giorni = on["schedule"][0]["cron"].split()[2].split(",")
    assert len(giorni) >= 2 and "workflow_dispatch" in on and "push" not in on


def test_il_sabotato_pretende_l_uno_e_il_sano_lo_zero():
    testo = WF.read_text(encoding="utf-8")
    assert 'ATTESO=0; [ "${{ matrix.modo }}" = sabotato ] && ATTESO=1' in testo
    assert 'if [ "$RC" != "$ATTESO" ]; then' in testo
    assert "prova-9-il-fail-closed-torna-indietro-davvero.sh --esegui" in testo


def test_il_sabotaggio_entra_nella_funzione_che_esiste(tmp_path):
    """Il sed del workflow lavora sulla forma di `_rollback_routine`: qui lo si applica alla CLI vera."""
    import subprocess
    passo = next(s for s in _wf()["jobs"]["rollback"]["steps"] if "Sabotaggio" in s.get("name", ""))
    assert passo["if"] == "matrix.modo == 'sabotato'"
    sed = re.search(r"sudo sed -i '(.*?)' \"\$CLI\"", passo["run"], re.S).group(1)
    copia = tmp_path / "vps1777.py"
    copia.write_text((RADICE / "tools" / "vps1777.py").read_text(encoding="utf-8"), encoding="utf-8")
    subprocess.run(["sed", "-i", sed, str(copia)], check=True)
    righe = copia.read_text(encoding="utf-8").split("\n")
    i = next(n for n, r in enumerate(righe) if r.startswith("def _rollback_routine("))
    fine = next(n for n in range(i, i + 6) if righe[n].endswith("-> int:"))
    assert righe[fine + 1].strip().startswith("return 1  # SABOTAGGIO"), righe[i:fine + 3]
    compile(copia.read_text(encoding="utf-8"), str(copia), "exec")


def test_il_gettone_va_solo_all_api_di_github(monkeypatch):
    monkeypatch.setenv("VPS1777_GITHUB_TOKEN", "ghs_" + "a" * 36)
    assert cli._intestazioni_github()["Authorization"] == "Bearer ghs_" + "a" * 36
    assert cli.API_BASE.startswith("https://api.github.com/")
    sorgente = (RADICE / "tools" / "vps1777.py").read_text(encoding="utf-8")
    assert sorgente.count("_intestazioni_github()") == 2          # la definizione e github_json: nessun altro
    assert sorgente.count("VPS1777_GITHUB_TOKEN") <= 3


def test_senza_gettone_o_con_un_valore_strano_la_chiamata_resta_anonima(monkeypatch):
    monkeypatch.delenv("VPS1777_GITHUB_TOKEN", raising=False)
    assert "Authorization" not in cli._intestazioni_github()
    for strano in ("", "corto", "con spazio dentro e lungo abbastanza", "riga\nnuova" + "x" * 30):
        monkeypatch.setenv("VPS1777_GITHUB_TOKEN", strano)
        assert "Authorization" not in cli._intestazioni_github(), strano


def test_il_workflow_non_riavvia_il_runner_e_non_ha_permessi_di_scrittura():
    testo = WF.read_text(encoding="utf-8")
    assert "VPS1777_SALTA_RIAVVIO=1" in testo
    wf = _wf()
    assert wf["permissions"] == {} and wf["jobs"]["rollback"]["permissions"] == {"contents": "read"}
