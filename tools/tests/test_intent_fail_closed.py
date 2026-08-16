"""`consume_intent` — i controlli devono FERMARE, non spegnersi, quando il dato manca.

Il difetto che questi test proteggono ha una forma sola, ripetuta due volte nella
stessa funzione: **una guardia scritta `if dato and <condizione>` non protegge dal
caso in cui il dato è assente — lo lascia passare in silenzio.**

    if nonce and nonce in nonces:   →  intent senza nonce: replay non rilevato,
    if nonce: nonces.append(nonce)     e nemmeno REGISTRATO ⇒ riusabile all'infinito
    if known_latest and target != …  →  nota assente/vuota: anti-downgrade inerte

Il secondo caso non è teorico: c'è un percorso, dentro il gateway, che scrive
`latest: ""` da solo quando la risposta di GitHub non porta il `tag_name`
(services/gateway/app/admin.py, curato nello stesso commit di questi test).

Solo stdlib. Nessun docker, nessuna rete.
"""
from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("vps1777_cli", _ROOT / "tools" / "vps1777.py")
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)

_VERSIONE = "0.41.0"


def _scrivi_intent(repo: Path, *, target: str = _VERSIONE, nonce: str | None = "abc123",
                   requested_at: float | None = None) -> Path:
    """L'intent come lo scrivono admin.py / miniapp.py. `nonce=None` = campo assente."""
    intent: dict = {
        "target_version": target,
        "requested_by": "chi@example.invalid",
        "requested_at": time.time() if requested_at is None else requested_at,
    }
    if nonce is not None:
        intent["nonce"] = nonce
    p = v.onboarding_dir(repo) / "update_pending_update.json"
    p.write_text(json.dumps(intent) + "\n")
    return p


def _scrivi_nota(repo: Path, contenuto) -> Path:
    """`update_status.json`. Una stringa grezza serve a simulare il file corrotto."""
    p = v.onboarding_dir(repo) / "update_status.json"
    p.write_text(contenuto if isinstance(contenuto, str)
                 else json.dumps(contenuto) + "\n")
    return p


# ───────────────────────────── il nonce ─────────────────────────────

def test_intent_senza_nonce_e_rifiutato(tmp_path):
    """Il caso che passava: nessuno dei due scrittori omette il nonce, quindi un
    intent che non ce l'ha non viene da loro."""
    _scrivi_intent(tmp_path, nonce=None)
    _scrivi_nota(tmp_path, {"latest": _VERSIONE})
    p = v.onboarding_dir(tmp_path) / "update_pending_update.json"
    with pytest.raises(RuntimeError, match="nonce mancante"):
        v.consume_intent(tmp_path, p, {})


def test_intent_senza_nonce_non_e_riusabile_due_volte(tmp_path):
    """⭐ Il difetto vero non era «un replay non rilevato»: era che l'intent senza
    nonce non veniva nemmeno REGISTRATO (`if nonce:` saltava l'append), quindi
    restava buono per sempre. Qui la seconda volta deve fallire come la prima."""
    st: dict = {}
    _scrivi_nota(tmp_path, {"latest": _VERSIONE})
    p = v.onboarding_dir(tmp_path) / "update_pending_update.json"
    for _ in range(2):
        _scrivi_intent(tmp_path, nonce=None)
        with pytest.raises(RuntimeError, match="nonce mancante"):
            v.consume_intent(tmp_path, p, st)
    # e non ha sporcato lo stato con un nonce vuoto
    assert "" not in st.get("intent_nonces", [])


def test_intent_con_nonce_nuovo_passa_e_lo_registra(tmp_path):
    st: dict = {}
    p = _scrivi_intent(tmp_path, nonce="n-1")
    _scrivi_nota(tmp_path, {"latest": _VERSIONE})
    assert v.consume_intent(tmp_path, p, st) == _VERSIONE
    assert "n-1" in st["intent_nonces"]


def test_replay_dello_stesso_nonce_resta_rifiutato(tmp_path):
    """Controprova di polarità: la guardia che c'era già non deve essersi rotta."""
    st: dict = {"intent_nonces": ["n-1"]}
    p = _scrivi_intent(tmp_path, nonce="n-1")
    _scrivi_nota(tmp_path, {"latest": _VERSIONE})
    with pytest.raises(RuntimeError, match="già consumato"):
        v.consume_intent(tmp_path, p, st)


# ───────────────────────── la latest nota ───────────────────────────

def test_nota_assente_rifiuta_invece_di_spegnere_il_controllo(tmp_path):
    """Nessun `update_status.json`: prima known_latest restava "" e il confronto
    non scattava — qualunque target semver passava."""
    p = _scrivi_intent(tmp_path)
    with pytest.raises(RuntimeError, match="non leggibile"):
        v.consume_intent(tmp_path, p, {})


def test_nota_con_latest_vuota_rifiuta(tmp_path):
    """È lo stato che il gateway sapeva scriversi da solo: `{"latest": ""}`."""
    p = _scrivi_intent(tmp_path)
    _scrivi_nota(tmp_path, {"latest": "", "current": "0.40.14"})
    with pytest.raises(RuntimeError, match="latest nota vuota"):
        v.consume_intent(tmp_path, p, {})


def test_nota_illeggibile_rifiuta(tmp_path):
    p = _scrivi_intent(tmp_path)
    _scrivi_nota(tmp_path, "{questo non è json")
    with pytest.raises(RuntimeError, match="non leggibile"):
        v.consume_intent(tmp_path, p, {})


def test_nota_senza_il_campo_latest_rifiuta(tmp_path):
    """JSON valido, campo assente: `.get("latest", "")` dava "" ⇒ guardia spenta."""
    p = _scrivi_intent(tmp_path)
    _scrivi_nota(tmp_path, {"current": "0.40.14", "checked_at": "2026-08-03T00:00:00Z"})
    with pytest.raises(RuntimeError, match="latest nota vuota"):
        v.consume_intent(tmp_path, p, {})


def test_nota_non_leggibile_alza_RuntimeError_e_non_OSError(tmp_path):
    """Il chiamante (cmd_update, --from-intent) cattura `RuntimeError`. Un OSError —
    permessi negati, file sparito fra `is_file()` e la lettura — non era catturato
    da nessuno e sarebbe risalito oltre quel gestore."""
    p = _scrivi_intent(tmp_path)
    nota = _scrivi_nota(tmp_path, {"latest": _VERSIONE})
    nota.chmod(0o000)
    try:
        with pytest.raises(RuntimeError):
            v.consume_intent(tmp_path, p, {})
    finally:
        nota.chmod(0o644)


def test_target_diverso_dalla_latest_nota_resta_rifiutato(tmp_path):
    """Controprova di polarità sull'altra guardia."""
    p = _scrivi_intent(tmp_path, target="0.99.0")
    _scrivi_nota(tmp_path, {"latest": _VERSIONE})
    with pytest.raises(RuntimeError, match="≠ latest nota"):
        v.consume_intent(tmp_path, p, {})


def test_il_caso_buono_passa_ancora(tmp_path):
    """Una guardia che blocca anche il legittimo si finisce per disattivarla: questo
    è il test che dice che la cura non ha chiuso la porta a chi doveva entrare."""
    st: dict = {}
    p = _scrivi_intent(tmp_path, nonce="n-buono")
    _scrivi_nota(tmp_path, {"latest": _VERSIONE, "current": "0.40.14"})
    assert v.consume_intent(tmp_path, p, st) == _VERSIONE
    assert not p.exists(), "consume-before-act: l'intent va cancellato comunque"
