"""Test dell'audit log (stdlib-only, offline) — H17.

audit.py accede alle settings via il seam `_settings()` (lazy): qui lo si
sostituisce con un finto che punta a un file temporaneo, così la logica pura
(scrittura, tail-read, potatura, contatore di fallimenti) si prova senza il
gateway né pydantic.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import audit  # noqa: E402


def _wire(monkeypatch, tmp_path: Path, *, retention_days: int = 30) -> Path:
    """Punta audit a un log in tmp_path e azzera lo stato di salute globale."""
    log_path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit, "_settings", lambda: types.SimpleNamespace(
        audit_log_path=str(log_path), audit_retention_days=retention_days))
    monkeypatch.setattr(audit, "_write_failures", 0)
    monkeypatch.setattr(audit, "_last_error", "")
    monkeypatch.setattr(audit, "_next_prune_at", audit._PRUNE_SIZE)
    return log_path


# ── tail-read: legge dalla CODA, non tutto il file in RAM ────────────────────

def test_read_recent_torna_gli_ultimi_in_ordine(monkeypatch, tmp_path) -> None:
    _wire(monkeypatch, tmp_path)
    for i in range(500):
        audit.audit({"event": "e", "i": i})
    got = audit.read_recent(10)
    assert [e["i"] for e in got] == list(range(490, 500))  # ultimi 10, in ordine


def test_read_recent_clampa_il_limite(monkeypatch, tmp_path) -> None:
    _wire(monkeypatch, tmp_path)
    audit.audit({"event": "e"})
    # un limite assurdo non deve diventare "leggi tutto il file"
    assert len(audit.read_recent(10_000_000)) <= audit.MAX_READ_LIMIT
    assert audit.read_recent(0) == []


def test_read_recent_file_assente(monkeypatch, tmp_path) -> None:
    _wire(monkeypatch, tmp_path)  # non scrivo niente: il file non esiste
    assert audit.read_recent(50) == []


def test_read_recent_tollera_righe_corrotte(monkeypatch, tmp_path) -> None:
    log = _wire(monkeypatch, tmp_path)
    log.write_text('{"event":"ok","i":1}\nNON-JSON\n\n{"event":"ok","i":2}\n',
                   encoding="utf-8")
    got = audit.read_recent(50)
    assert [e["i"] for e in got] == [1, 2]


def test_tail_lines_su_righe_piu_lunghe_del_blocco(monkeypatch, tmp_path) -> None:
    # una riga più lunga di _TAIL_BLOCK non deve mandare in confusione la risalita
    log = _wire(monkeypatch, tmp_path)
    monkeypatch.setattr(audit, "_TAIL_BLOCK", 64)
    big = "A" * 500
    log.write_text(
        json.dumps({"event": "big", "v": big}) + "\n"
        + json.dumps({"event": "last", "v": "z"}) + "\n", encoding="utf-8")
    got = audit.read_recent(1)
    assert got[-1]["event"] == "last"


# ── H17: l'except non è più muto — c'è un contatore ESPOSTO ───────────────────

def test_fallimento_scrittura_incrementa_il_contatore(monkeypatch, tmp_path) -> None:
    _wire(monkeypatch, tmp_path)
    # una settings che esplode → la scrittura fallisce, ma audit() non solleva
    monkeypatch.setattr(audit, "_settings",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    audit.audit({"event": "e"})           # non deve sollevare
    h = audit.audit_health()
    assert h["healthy"] is False
    assert h["write_failures"] == 1
    assert "boom" in h["last_error"]


def test_ripristino_scrive_record_e_azzera(monkeypatch, tmp_path) -> None:
    log = _wire(monkeypatch, tmp_path)
    good = lambda: types.SimpleNamespace(  # noqa: E731
        audit_log_path=str(log), audit_retention_days=30)
    bad = lambda: (_ for _ in ()).throw(RuntimeError("giu"))  # noqa: E731

    monkeypatch.setattr(audit, "_settings", bad)
    audit.audit({"event": "perso1"})
    audit.audit({"event": "perso2"})
    assert audit.audit_health()["write_failures"] == 2

    monkeypatch.setattr(audit, "_settings", good)
    audit.audit({"event": "tornato"})
    assert audit.audit_health()["healthy"] is True          # contatore azzerato

    events = audit.read_recent(50)
    kinds = [e.get("event") for e in events]
    assert "audit_write_recovered" in kinds                  # la serie è DICHIARATA nel log
    rec = next(e for e in events if e["event"] == "audit_write_recovered")
    assert rec["dropped"] == 2


def test_audit_health_di_default_e_sana(monkeypatch, tmp_path) -> None:
    _wire(monkeypatch, tmp_path)
    assert audit.audit_health()["healthy"] is True


# ── potatura per retention (streaming, non read_text di tutto il file) ────────

def test_prune_toglie_le_voci_scadute(monkeypatch, tmp_path) -> None:
    log = _wire(monkeypatch, tmp_path)
    log.write_text(
        json.dumps({"event": "vecchio", "ts": "2000-01-01T00:00:00+00:00"}) + "\n"
        + json.dumps({"event": "nuovo", "ts": "2999-01-01T00:00:00+00:00"}) + "\n",
        encoding="utf-8")
    audit._prune(log, retention_days=30)
    kept = [json.loads(ln)["event"] for ln in log.read_text().splitlines() if ln.strip()]
    assert kept == ["nuovo"]  # lo scaduto è potato, il vivo resta


# ── redazione: l'audit accetta solo ciò che SA (d96526b5) ────────────────────

def test_chiave_non_dichiarata_non_finisce_nel_log(monkeypatch, tmp_path) -> None:
    """Il vettore vero: un chiamante che infila un campo nuovo con dentro un segreto."""
    log = _wire(monkeypatch, tmp_path)
    audit.audit({"event": "prova", "password": "hunter2-questo-non-deve-uscire"})
    riga = log.read_text(encoding="utf-8")
    assert "hunter2" not in riga            # il valore NON c'è
    assert "password" in riga               # ma la chiave sì: il buco resta visibile
    assert "non dichiarata" in riga


def test_le_chiavi_note_passano_intatte(monkeypatch, tmp_path) -> None:
    log = _wire(monkeypatch, tmp_path)
    audit.audit({"event": "admin_login_ok", "email": "a@b.c", "ip": "10.0.0.1"})
    rec = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert rec["email"] == "a@b.c" and rec["ip"] == "10.0.0.1"


def test_un_valore_lunghissimo_viene_troncato(monkeypatch, tmp_path) -> None:
    """`error` è ammessa ma a contenuto libero: si limita la superficie, non si indovina."""
    log = _wire(monkeypatch, tmp_path)
    audit.audit({"event": "boom", "error": "x" * 5000})
    rec = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert len(rec["error"]) < 600 and "troncati" in rec["error"]


def test_OGNI_chiave_usata_nel_repo_e_dichiarata(monkeypatch) -> None:
    """Il presidio vero: se qualcuno aggiunge una chiave e non la dichiara, QUI si rompe.

    Senza questo test l'allowlist diventa silenziosamente una censura: il campo nuovo
    smette di essere scritto e nessuno se ne accorge finché non serve leggerlo.
    Le chiavi si estraggono con l'AST — un grep si ferma a fine riga e sulle chiamate
    multi-riga ne perde (misurato: 24 col grep, 30 con l'AST).
    """
    import ast
    from pathlib import Path
    radice = Path(__file__).resolve().parents[3]
    usate, non_letterali = set(), 0
    for p in radice.rglob("*.py"):
        if ".git" in p.parts or "test_" in p.name:
            continue
        try:
            albero = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for n in ast.walk(albero):
            if not (isinstance(n, ast.Call)
                    and getattr(n.func, "id", getattr(n.func, "attr", "")) == "audit"):
                continue
            for a in n.args:
                if isinstance(a, ast.Dict):
                    for k in a.keys:
                        if isinstance(k, ast.Constant):
                            usate.add(k.value)
                        else:
                            non_letterali += 1
                else:
                    non_letterali += 1
    assert usate, "nessuna chiamata trovata: la sonda non sta guardando il repo giusto"
    mancanti = usate - audit._CHIAVI_NOTE
    assert not mancanti, f"chiavi usate ma NON dichiarate in _CHIAVI_NOTE: {sorted(mancanti)}"
    # un dict costruito a runtime sfugge all'allowlist statica: va saputo, non scoperto dopo
    assert non_letterali == 0, (
        f"{non_letterali} chiamate ad audit() con un dict non letterale: questo test non "
        "può vederne le chiavi, e la garanzia vale solo per quelle statiche")
