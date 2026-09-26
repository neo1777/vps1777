"""L'auto-update installa da solo solo un rilascio che ha almeno 48 ore di vita.

La ragione (H24, decisione di Neo del 27/09/2026): il gate umano sulla creazione dei tag
(un GitHub environment con revisore) in un repo con un solo account non è un confine —
il token che crea il tag può anche approvarlo via API. Il rischio vero stava più a valle:
`vps1777-auto-update.timer` installava l'ultimo rilascio appena usciva, quindi un tag
sbagliato arrivava sulla VPS senza che nessuno lo guardasse. La quarantena gli dà una
finestra per essere ritirato (segnato «prerelease» su GitHub, `/releases/latest` lo
esclude). Gemelli: `minimumReleaseAge` di Renovate, `cooldown` di Dependabot.

Tre cose da tenere ferme:
- la regola, come funzione pura: giovane → no; vecchio → sì; data illeggibile o nel
  futuro → no (una guardia che promette «non installo» nega quando non sa);
- `cmd_update` la chiama davvero, e SOLO senza `--version` (un target esplicito, a mano
  o dal pulsante, è una scelta umana e passa subito);
- la unit la chiede (`--eta-minima 48`) e il timer gira ogni giorno, altrimenti un
  rilascio giovane salterebbe una settimana intera.

Solo stdlib: la CI lancia questa suite con `uvx pytest`, senza dipendenze.
"""
from __future__ import annotations

import ast
import importlib.util
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("vps1777_cli", _ROOT / "tools" / "vps1777.py")
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)

ADESSO = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


def _rel(delta_ore: float | None = None, raw: str | None = None) -> dict:
    if raw is None:
        raw = (ADESSO - timedelta(hours=delta_ore)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"tag_name": "v9.9.9", "published_at": raw}


def test_rilascio_giovane_resta_in_quarantena():
    motivo = v.quarantena_blocca(_rel(47), 48, ADESSO)
    assert motivo and "47" in motivo and "48" in motivo


def test_rilascio_maturo_passa():
    assert v.quarantena_blocca(_rel(49), 48, ADESSO) is None


@pytest.mark.parametrize("raw", ["", "ieri", "2026-09-27T10:00:00"])
def test_data_illeggibile_o_senza_fuso_nega(raw):
    assert v.quarantena_blocca(_rel(raw=raw), 48, ADESSO)


def test_data_nel_futuro_nega():
    assert v.quarantena_blocca(_rel(-3), 48, ADESSO)


def test_senza_eta_minima_nessuna_quarantena():
    assert v.quarantena_blocca(_rel(1), 0, ADESSO) is None
    assert v.quarantena_blocca(_rel(1), None, ADESSO) is None


def test_il_parser_accetta_il_flag_della_unit():
    a = v.build_parser().parse_args(["update", "--yes", "--eta-minima", "48"])
    assert a.eta_minima == 48


def _cmd_update() -> ast.FunctionDef:
    albero = ast.parse((_ROOT / "tools" / "vps1777.py").read_text())
    return next(n for n in ast.walk(albero)
                if isinstance(n, ast.FunctionDef) and n.name == "cmd_update")


def test_cmd_update_chiama_la_quarantena_solo_senza_target_esplicito():
    """Si chiede all'AST (regge alle riformattazioni, cade sulla sostanza): la chiamata
    sta dentro un `if` che guarda sia `eta_minima` sia `target_req`."""
    for nodo in ast.walk(_cmd_update()):
        if not isinstance(nodo, ast.If):
            continue
        # anche le costanti: `getattr(args, "eta_minima", None)` nomina l'attributo
        # con una stringa
        nomi = {n.id for n in ast.walk(nodo.test) if isinstance(n, ast.Name)} | {
            n.attr for n in ast.walk(nodo.test) if isinstance(n, ast.Attribute)} | {
            n.value for n in ast.walk(nodo.test)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        if not {"eta_minima", "target_req"} <= nomi:
            continue
        chiamate = {n.func.id for s in nodo.body for n in ast.walk(s)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        if "quarantena_blocca" in chiamate:
            return
    pytest.fail("cmd_update non chiama quarantena_blocca sotto un if su eta_minima e "
                "target_req: la regola esisterebbe senza che nessuno la esegua")


def test_la_unit_chiede_la_quarantena_e_il_timer_e_giornaliero():
    service = (_ROOT / "systemd" / "vps1777-auto-update.service").read_text()
    exec_start = re.search(r"^ExecStart=(.*)$", service, re.M).group(1)
    assert "update" in exec_start and "--yes" in exec_start
    m = re.search(r"--eta-minima[ =](\d+)", exec_start)
    assert m and int(m.group(1)) == 48, exec_start
    timer = (_ROOT / "systemd" / "vps1777-auto-update.timer").read_text()
    assert re.search(r"^OnCalendar=daily$", timer, re.M), (
        "con la quarantena il timer deve girare ogni giorno: settimanale, un rilascio "
        "giovane al momento del giro aspetterebbe fino a 9 giorni")
