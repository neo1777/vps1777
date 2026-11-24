"""Gli altri difetti veri del campione di precisione della prova B (schede C07, C09, C10, C14, C16, C24, C43).

Segnalati da revisori automatici sul gateway e verificati uno per uno il 23/11/2026. Gira con le deps del lock (audit e notifiche leggono le impostazioni).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app import audit, notifiche, ratelimit


# ── C07: il limite di frequenza conta la rete /64, non il singolo indirizzo IPv6 ─────────────────
def test_ipv6_cambiare_indirizzo_dentro_la_stessa_rete_non_aggira_il_limite():
    lim = ratelimit.RateLimiter(max_calls=3, window_s=60)
    esiti = [lim.allow(f"2001:db8:aa:bb::{i:x}", 10.0) for i in range(1, 8)]
    assert esiti == [True, True, True, False, False, False, False]
    assert lim.allow("2001:db8:aa:cc::1", 10.0)            # un'altra rete /64 ha il suo conto


@pytest.mark.parametrize("ip, attesa", [
    ("203.0.113.7", "203.0.113.7"),
    ("::ffff:203.0.113.7", "203.0.113.7"),                  # IPv4 scritto dentro un IPv6
    ("2001:db8:1:2:3:4:5:6", "2001:db8:1:2::/64"),
    ("2001:DB8:1:2::1", "2001:db8:1:2::/64"),
    ("non-un-indirizzo", "non-un-indirizzo"),
])
def test_la_chiave_del_conto(ip, attesa):
    assert ratelimit.chiave(ip) == attesa


# ── C14, C16, C24: ciò che si rinomina sopra un file buono va prima portato su disco ─────────────
@pytest.fixture
def fsync_visti(monkeypatch):
    """Registra, in ordine, gli fsync e le rinomine: l'fsync del file nuovo deve venire PRIMA."""
    passi: list[tuple[str, str]] = []
    vero_fsync, vero_replace = os.fsync, os.replace

    def fsync(fd):
        passi.append(("fsync", os.readlink(f"/proc/self/fd/{fd}")))
        return vero_fsync(fd)

    def replace(a, b):
        passi.append(("replace", str(a)))
        return vero_replace(a, b)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(Path, "replace", lambda self, b: replace(self, b))
    return passi


def _fsync_prima_della_rinomina(passi, suffisso):
    nomi = [n for _, n in passi if n.endswith(suffisso)]
    assert nomi, f"nessun passo su un file {suffisso}: {passi}"
    assert passi.index(("fsync", nomi[0])) < passi.index(("replace", nomi[0]))


def test_la_coda_degli_avvisi_va_su_disco_prima_della_rinomina(tmp_path, monkeypatch, fsync_visti):
    monkeypatch.setattr(notifiche, "_file", lambda: tmp_path / "notifiche.json")
    notifiche.accoda("prova", "ciao")
    _fsync_prima_della_rinomina(fsync_visti, ".tmp")
    assert json.loads((tmp_path / "notifiche.json").read_text())[0]["text"] == "ciao"


def _audit_grande(f: Path, righe: int) -> None:
    riga = json.dumps({"ts": "2099-01-01T00:00:00+00:00", "event": "x", "error": "y" * 400}) + "\n"
    f.write_text(riga * righe, encoding="utf-8")


def test_la_potatura_per_eta_va_su_disco_prima_della_rinomina(tmp_path, fsync_visti):
    f = tmp_path / "audit.jsonl"
    _audit_grande(f, 50)
    audit._prune(f, 30)
    _fsync_prima_della_rinomina(fsync_visti, ".tmp")
    assert f.read_text().count("\n") == 50


def test_il_taglio_alla_coda_va_su_disco_prima_della_rinomina(tmp_path, monkeypatch, fsync_visti):
    f = tmp_path / "audit.jsonl"
    _audit_grande(f, 50)
    monkeypatch.setattr(audit, "_MAX_BYTES", 4096)
    audit._taglia_alla_coda(f)
    _fsync_prima_della_rinomina(fsync_visti, ".coda")
    prima = json.loads(f.read_text().splitlines()[0])
    assert prima["event"] == "audit_trimmed" and f.stat().st_size < 4096


# ── C09: un avviso consegnato non si rimanda, anche se non si riesce a toglierlo dal disco ───────
def test_un_avviso_consegnato_non_torna_se_la_coda_non_si_svuota(tmp_path, monkeypatch):
    monkeypatch.setattr(notifiche, "_file", lambda: tmp_path / "notifiche.json")
    monkeypatch.setattr(notifiche, "_consegnati_non_tolti", [])
    notifiche.accoda("a", "primo")
    scrivi_vero = notifiche._scrivi
    monkeypatch.setattr(notifiche, "_scrivi", lambda items: False)       # disco pieno: non si svuota
    assert [x["text"] for x in notifiche.preleva()] == ["primo"]
    assert notifiche.preleva() == []                                      # prima: «primo» di nuovo, per sempre
    assert notifiche.preleva() == []
    monkeypatch.setattr(notifiche, "_scrivi", scrivi_vero)                # il disco torna
    notifiche.accoda("a", "secondo")
    assert [x["text"] for x in notifiche.preleva()] == ["secondo"]        # il nuovo esce, il vecchio no
    assert notifiche.preleva() == []
    assert json.loads((tmp_path / "notifiche.json").read_text()) == []


# ── C43: la finestra degli eventi anonimi è una per tipo ────────────────────────────────────────
def test_un_tipo_di_evento_anonimo_non_nasconde_gli_altri(monkeypatch):
    monkeypatch.setattr(audit, "_finestra_anonimi", {})
    ora = "2026-11-23T10:00:05+00:00"
    for _ in range(audit._ANONIMI_AL_MINUTO):
        assert audit._da_sopprimere("notifiche_denied", ora) is False
    assert audit._da_sopprimere("notifiche_denied", ora) is True          # il suo minuto è pieno
    assert audit._da_sopprimere("proxy_secret_mismatch", ora) is False    # prima: soppresso anche questo
    riepilogo = audit._da_sopprimere("notifiche_denied", "2026-11-23T10:01:00+00:00")
    assert riepilogo["event"] == "audit_suppressed" and riepilogo["dropped"] == 1
    assert "notifiche_denied" in riepilogo["reason"]


# ── C10: dopo una potatura la soglia successiva non supera il tetto dichiarato ──────────────────
def test_la_soglia_della_prossima_potatura_non_supera_il_tetto():
    """Presidio sul testo: la soglia è una variabile del modulo aggiornata dentro `audit()`, e provarla
    dal vivo vorrebbe scrivere 20 MB. La forma che conta è il `min` col tetto."""
    sorgente = Path(audit.__file__).read_text(encoding="utf-8")
    assert "_next_prune_at = min(_MAX_BYTES," in sorgente
