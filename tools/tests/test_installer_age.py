"""Il recipient age nasce sul PC anche con l'installer grafico (classe #208 rovesciata).

STORIA: deploy.sh allestisce la coppia age dal 0.4x; l'installer grafico si
limitava all'avviso nel referto. Trovato dal collaudo su macchina vergine
(27/08/2026): installazione col grafico → primo `vps1777 update` fermo fail-safe
sul backup («Nessun recipient age»). Lo stesso giorno il runbook ha imparato il
rimedio manuale (PR #213); questa è la cura che lo rende inutile per l'utente
nuovo.

COSA TIENE QUESTO FILE: la parte matematica del fallback Python — bech32 (BIP173)
e derivazione X25519 — contro un GOLDEN VECTOR generato da `age-keygen` vero
(27/08/2026, coppia sacrificale creata apposta ed è pubblicabile per intero), e
il contratto di `age_ensure_keypair_on_pc` (crea, riusa, permessi). La verifica
finale sul recipient VERO resta nel prodotto: step_age fa un round-trip
`age -r … -o /dev/null` sulla VPS e, se il recipient è rifiutato, lo RIMUOVE —
meglio nessun recipient (backup fermo e rumoroso) di uno rotto e muto.

CI: gira in `contract` con `--with cryptography` (il fallback la richiede; sul
PC c'è sempre perché è una dipendenza di paramiko, che l'installer usa).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

# paramiko stubbato come in test_installer_funnel.py: non è in CI, e qui si
# testano funzioni module-level che non lo toccano.
sys.modules.setdefault("paramiko", types.ModuleType("paramiko"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "installer"))

import engine  # noqa: E402

# Coppia SACRIFICALE generata con age-keygen v1.1+ il 27/08/2026 apposta per
# questo test: non protegge e non proteggerà mai nulla. La privata è qui perché
# il golden test deve poter derivare la pubblica senza dipendere da age-keygen.
GOLDEN_SECRET = "AGE-SECRET-KEY-1MVVQRU46TXFTLSR6PY0M6ZEYLNKZWXP7NUJ05AWAFLYK54V7X04S0QRUGU"
GOLDEN_PUBLIC = "age1enff59gj0zt5ctp5ctv5qv20yuns2e2eh0a58nkaff42rwrqwdhq7urr08"
GOLDEN_PUBLIC_RAW = bytes.fromhex(
    "ccd29a151278974c2c34c2d940314f2727056559bbfb43cedd4a6aa1b860736e")


def test_bech32_encode_riproduce_la_pubblica_golden():
    # bech32 puro, senza crypto: dai 32 byte raw alla stringa che age dichiara.
    assert engine.bech32_encode("age", GOLDEN_PUBLIC_RAW) == GOLDEN_PUBLIC


def test_derivazione_x25519_dalla_privata_golden():
    """La strada intera del fallback: privata bech32 → X25519 → pubblica bech32.

    Se questo test è verde, il fallback produce ESATTAMENTE ciò che age-keygen
    avrebbe prodotto — non «qualcosa che somiglia a una chiave age»."""
    cryptography = pytest.importorskip("cryptography")  # noqa: F841
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

    data5 = [engine._B32.find(c) for c in GOLDEN_SECRET.lower()
             .split("age-secret-key-1")[1]][:-6]
    raw = bytes(engine._b32_convert(data5, 5, 8, pad=False))
    priv = X25519PrivateKey.from_private_bytes(raw)
    pub_raw = priv.public_key().public_bytes(serialization.Encoding.Raw,
                                             serialization.PublicFormat.Raw)
    assert engine.bech32_encode("age", pub_raw) == GOLDEN_PUBLIC


def test_age_keypair_python_genera_una_coppia_coerente():
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

    sec, pub = engine.age_keypair_python()
    assert sec.startswith("AGE-SECRET-KEY-1") and pub.startswith("age1")
    assert len(pub) == len(GOLDEN_PUBLIC)  # stessa forma del vero
    # la pubblica dichiarata È quella derivabile dalla privata dichiarata
    data5 = [engine._B32.find(c) for c in sec.lower()
             .split("age-secret-key-1")[1]][:-6]
    raw = bytes(engine._b32_convert(data5, 5, 8, pad=False))
    priv = X25519PrivateKey.from_private_bytes(raw)
    pub_raw = priv.public_key().public_bytes(serialization.Encoding.Raw,
                                             serialization.PublicFormat.Raw)
    assert engine.bech32_encode("age", pub_raw) == pub


@pytest.mark.skipif(shutil.which("age") is None, reason="age non installato")
def test_una_coppia_python_viene_accettata_da_age_vero(tmp_path):
    """Il giudice esterno: age (il binario) cifra col nostro recipient?

    È il round-trip che step_age fa sulla VPS, qui in miniatura sul PC."""
    pytest.importorskip("cryptography")
    _sec, pub = engine.age_keypair_python()
    subprocess.run(["age", "-r", pub, "-o", str(tmp_path / "x.age")],
                   input=b"ok", check=True, timeout=15)


def test_ensure_keypair_crea_e_poi_riusa(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    pub1, path1, come1 = engine.age_ensure_keypair_on_pc()
    assert pub1.startswith("age1") and come1 in ("age-keygen", "python")
    kf = Path(path1)
    assert kf.is_file() and (kf.stat().st_mode & 0o777) == 0o600
    assert "# public key: " in kf.read_text()  # formato standard, riusabile da deploy.sh
    pub2, path2, come2 = engine.age_ensure_keypair_on_pc()
    assert (pub2, path2, come2) == (pub1, path1, "riusata")
