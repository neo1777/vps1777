"""Le cure nate dalla prima fetta della revisione col catalogo (gateway: audit, limitatore,
notifiche, impostazioni). Solo libreria standard: nessuna app in piedi."""
from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

RADICE = Path(__file__).resolve().parents[1]


def _carica(nome: str):
    """Il modulo VERO, letto dal suo file con un nome suo: altri test di questa cartella mettono
    in `sys.modules` dei finti `app.audit` e `app.ratelimit`, e un `from app import …` qui
    prenderebbe quelli."""
    spec = importlib.util.spec_from_file_location(f"_fetta01_{nome}", RADICE / "app" / f"{nome}.py")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


audit = _carica("audit")
ratelimit = _carica("ratelimit")


def _su(monkeypatch, tmp_path, giorni=90):
    f = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit, "_settings", lambda: SimpleNamespace(
        audit_log_path=str(f), audit_retention_days=giorni))
    monkeypatch.setattr(audit, "_finestra_anonimi", {"minuto": "", "visti": 0, "soppressi": 0})
    return f


def test_la_lettura_dice_quante_righe_ha_scartato(monkeypatch, tmp_path):
    f = _su(monkeypatch, tmp_path)
    f.write_text('{"ts":"a","event":"x"}\nnon json\n[1,2]\n{"ts":"b","event":"y"}\n')
    eventi, stato = audit.leggi_recenti(50)
    assert [e["event"] for e in eventi] == ["x", "y"]
    assert stato == {"scartate": 2, "illeggibile": ""}
    assert audit.read_recent(50) == eventi


def test_un_file_assente_non_e_un_file_illeggibile(monkeypatch, tmp_path):
    f = _su(monkeypatch, tmp_path)
    assert audit.leggi_recenti(10) == ([], {"scartate": 0, "illeggibile": ""})
    f.mkdir()                                    # c'è, ma non si legge come file
    eventi, stato = audit.leggi_recenti(10)
    assert eventi == [] and stato["illeggibile"]


def test_senza_retention_il_tetto_di_dimensione_vale_lo_stesso(monkeypatch, tmp_path):
    f = _su(monkeypatch, tmp_path, giorni=0)
    monkeypatch.setattr(audit, "_MAX_BYTES", 2000)
    riga = json.dumps({"ts": "2026-01-01T00:00:00+00:00", "event": "x", "path": "p" * 60}) + "\n"
    f.write_text(riga * 100)
    audit._prune(f, 0)
    assert f.stat().st_size <= 2000
    assert json.loads(f.read_text().splitlines()[0])["event"] == "audit_trimmed"


def test_la_potatura_conta_le_righe_illeggibili(monkeypatch, tmp_path):
    f = _su(monkeypatch, tmp_path)
    f.write_text('rotta\n{"ts":"9999-01-01T00:00:00+00:00","event":"x"}\n"stringa"\n')
    audit._prune(f, 90)
    righe = [json.loads(r) for r in f.read_text().splitlines()]
    assert righe[0]["event"] == "x"
    assert righe[1]["event"] == "audit_trimmed" and righe[1]["dropped"] == 2


def test_i_dinieghi_delle_rotte_interne_hanno_il_freno(monkeypatch, tmp_path):
    f = _su(monkeypatch, tmp_path)
    for evento in ("archive_desc_denied", "archive_ruolo_denied", "notifiche_denied",
                   "oauth_refresh_revoked_client"):
        assert evento in audit._ANONIMI
    for _ in range(audit._ANONIMI_AL_MINUTO + 40):
        audit.audit({"event": "notifiche_denied", "reason": "not_internal"})
    assert len(f.read_text().splitlines()) == audit._ANONIMI_AL_MINUTO


def test_gli_eventi_senza_credenziali_sono_tutti_frenati():
    """Ogni `audit({"event": …})` che sta prima di un controllo di credenziali va in `_ANONIMI`.
    L'elenco qui è scritto a mano di proposito: chi aggiunge un rifiuto anonimo lo aggiunge qui."""
    attesi = {"proxy_secret_mismatch", "proxy_internal_blocked", "proxy_unknown_service",
              "proxy_auth_fail", "archive_desc_denied", "archive_ruolo_denied",
              "notifiche_denied", "oauth_refresh_revoked_client"}
    assert attesi <= audit._ANONIMI
    sorgenti = "".join((RADICE / "app" / n).read_text(encoding="utf-8")
                       for n in ("proxy.py", "routes.py", "oauth.py"))
    for evento in attesi:
        assert f'"{evento}"' in sorgenti, f"{evento} non esiste più: toglilo da _ANONIMI"


def test_il_limitatore_ha_un_tetto_alle_chiavi(monkeypatch):
    monkeypatch.setattr(ratelimit, "MAX_CHIAVI", 5)
    lim = ratelimit.RateLimiter(max_calls=3, window_s=60)
    for i in range(5):
        assert lim.allow(f"2001:db8::{i}", 100.0)
    assert not lim.allow("2001:db8::ffff", 100.0)       # un IP nuovo oltre il tetto: rifiutato
    assert lim.allow("2001:db8::1", 100.0)              # chi è già dentro non ne risente
    assert lim.allow("2001:db8::ffff", 200.0)           # passata la finestra c'è di nuovo posto
    assert len(lim._hits) <= 5


def test_ogni_variabile_delle_impostazioni_sta_nel_readme():
    """Una variabile che esiste nel codice e non nella tabella è una configurazione che nessuno
    sa di poter cambiare. I campi `*_file` valgono col loro nome; chi ha solo la variante senza
    `_FILE` come ricaduta per lo sviluppo è coperto dalla riga del file."""
    albero = ast.parse((RADICE / "app" / "settings.py").read_text(encoding="utf-8"))
    classe = next(n for n in ast.walk(albero) if isinstance(n, ast.ClassDef) and n.name == "Settings")
    campi = [n.target.id for n in classe.body
             if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
             and n.target.id != "model_config"]
    readme = (RADICE / "README.md").read_text(encoding="utf-8")
    nomi = set(re.findall(r"`([A-Z][A-Z0-9_]+)`", readme))
    mancanti = [c.upper() for c in campi
                if c.upper() not in nomi and f"{c.upper()}_FILE" not in nomi]
    assert not mancanti, f"variabili non documentate nel README del gateway: {mancanti}"


def test_il_gateway_non_chiama_telegram():
    """Il gateway non parla con Telegram (non ne monta il token): nel suo codice l'host dell'API
    può comparire solo in un commento o in una docstring, mai in una stringa che si usa."""
    for f in sorted((RADICE / "app").glob("*.py")):
        albero = ast.parse(f.read_text(encoding="utf-8"))
        doc = {id(n.body[0].value) for n in ast.walk(albero)
               if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
               and n.body and isinstance(n.body[0], ast.Expr)
               and isinstance(n.body[0].value, ast.Constant)}
        for n in ast.walk(albero):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc:
                assert "api.telegram.org" not in n.value, f"{f.name}:{n.lineno}"
