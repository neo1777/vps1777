"""Test della revoke-list della sessione admin (H20) — stdlib-only, offline.

Il fix che questi test proteggono: il logout deve REVOCARE il token, non solo
cancellare il cookie nel browser. Se la revoca non sopravvive a un restart, o se
la lista cresce all'infinito, il fix è finto.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import admin_core  # noqa: E402
import pytest  # noqa: E402


# ───── prune ─────

def test_prune_toglie_le_voci_scadute_e_tiene_le_vive():
    now = 1000.0
    entries = {"vecchio": 999.0, "adesso": 1000.0, "vivo": 1001.0}
    assert admin_core.prune(entries, now) == {"vivo": 1001.0}


def test_prune_su_lista_vuota():
    assert admin_core.prune({}, time.time()) == {}


# ───── revoca ─────

def test_revoca_e_controllo(tmp_path):
    rl = admin_core.RevocationList(tmp_path / "admin_revoked.json")
    assert rl.is_revoked("abc") is False
    assert rl.revoke("abc", time.time() + 3600) is True
    assert rl.is_revoked("abc") is True
    assert rl.is_revoked("altro") is False


def test_jti_vuoto_non_revoca_nulla(tmp_path):
    rl = admin_core.RevocationList(tmp_path / "admin_revoked.json")
    assert rl.revoke("", time.time() + 3600) is False
    assert rl.is_revoked("") is False


def test_la_revoca_sopravvive_al_restart(tmp_path):
    """Il caso che conta: gateway riavviato, il token rubato deve restare morto."""
    path = tmp_path / "admin_revoked.json"
    admin_core.RevocationList(path).revoke("rubato", time.time() + 3600)

    dopo_il_restart = admin_core.RevocationList(path)  # nuovo processo → rilegge il file
    assert dopo_il_restart.is_revoked("rubato") is True


def test_il_file_e_json_leggibile_jti_to_exp(tmp_path):
    path = tmp_path / "admin_revoked.json"
    rl = admin_core.RevocationList(path)
    rl.revoke("j1", 4000.0)
    data = json.loads(path.read_text())
    assert data == {"j1": 4000.0}
    assert len(rl) == 1


# ───── potatura: la lista non cresce all'infinito ─────

def test_le_voci_scadute_spariscono_alla_ricarica(tmp_path):
    path = tmp_path / "admin_revoked.json"
    now = 1_000_000.0
    rl = admin_core.RevocationList(path)
    rl.revoke("scaduto_presto", now + 10, now=now)
    rl.revoke("lunga_vita", now + 10_000, now=now)
    assert len(rl) == 2

    # un'ora dopo: il token "scaduto_presto" è morto da sé (exp passata) → la
    # verifica JWT lo rifiuta comunque, ricordarne il jti è solo peso.
    rl.reload(now=now + 3600)
    assert rl.is_revoked("scaduto_presto") is False
    assert rl.is_revoked("lunga_vita") is True
    assert len(rl) == 1


def test_la_potatura_finisce_su_disco_alla_prima_scrittura(tmp_path):
    path = tmp_path / "admin_revoked.json"
    now = 1_000_000.0
    rl = admin_core.RevocationList(path)
    rl.revoke("vecchio", now + 10, now=now)

    rl.revoke("nuovo", now + 10_000, now=now + 3600)  # `now` avanzato → pota
    assert json.loads(path.read_text()) == {"nuovo": now + 10_000}


# ───── robustezza ─────

def test_file_corrotto_non_fa_esplodere_nulla(tmp_path):
    path = tmp_path / "admin_revoked.json"
    path.write_text("{non json")
    rl = admin_core.RevocationList(path)
    assert len(rl) == 0
    assert rl.is_revoked("x") is False
    # e si riparte da un file valido
    assert rl.revoke("x", time.time() + 60) is True
    assert json.loads(path.read_text())["x"] > 0


def test_voce_corrotta_scarta_la_voce_non_il_file(tmp_path):
    path = tmp_path / "admin_revoked.json"
    path.write_text(json.dumps({"buono": 9_999_999_999, "rotto": "domani"}))
    rl = admin_core.RevocationList(path)
    assert rl.is_revoked("buono") is True
    assert rl.is_revoked("rotto") is False


def test_disco_non_scrivibile_revoca_in_memoria_e_lo_dichiara(tmp_path):
    """Se non riesce a persistere lo DICE (False) — chi chiama lo audita invece
    di credere a una revoca durevole che non c'è."""
    occupato = tmp_path / "file"
    occupato.write_text("non sono una directory")
    rl = admin_core.RevocationList(occupato / "sub" / "admin_revoked.json")
    assert rl.revoke("abc", time.time() + 60) is False  # persistenza fallita
    assert rl.is_revoked("abc") is True                 # ma la revoca vale QUI e ORA


def test_la_scrittura_non_lascia_file_temporanei(tmp_path):
    path = tmp_path / "admin_revoked.json"
    rl = admin_core.RevocationList(path)
    rl.revoke("j1", time.time() + 60)
    rl.revoke("j2", time.time() + 60)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["admin_revoked.json"]


def test_rilegge_se_il_file_cambia_sotto(tmp_path):
    """Due istanze sullo stesso file (domani: più worker): la revoca fatta da una
    la vede anche l'altra, senza restart."""
    path = tmp_path / "admin_revoked.json"
    a = admin_core.RevocationList(path)
    b = admin_core.RevocationList(path)
    a.revoke("nuovo", time.time() + 3600)
    assert b.is_revoked("nuovo") is True


# ───── H30: l'open-redirect è già tornato una volta in un rilievo "chiuso" ─────


BASE = "https://vps1777-1.tail0c1f07.ts.net"


@pytest.mark.parametrize("hostile", [
    "https://vps1777-1.tail0c1f07.ts.net.evil.com/",  # IL BYPASS: prefisso ≠ origine
    "https://vps1777-1.tail0c1f07.ts.netEVIL.com",     # prefisso senza separatore
    "//evil.com",                                       # protocol-relative
    "/\\evil.com",                                      # backslash
    "/\t/evil.com",                                     # tab: il browser la cancella → //evil.com
    "/\r\n//evil.com",                                  # CRLF
    "https://evil.com",                                 # esterno secco
    "http://vps1777-1.tail0c1f07.ts.net/x",             # schema diverso da public_base
])
def test_next_ostile_viene_scartato(hostile):
    assert admin_core.safe_next_url(hostile, BASE) == "/admin/setup"


@pytest.mark.parametrize("legit", [
    "/admin/audit",
    "/admin/setup?msg=ok",
    "https://vps1777-1.tail0c1f07.ts.net/admin/nlm",
    "https://vps1777-1.tail0c1f07.ts.net",
    "https://vps1777-1.tail0c1f07.ts.net?x=1",
])
def test_next_legittimo_passa(legit):
    # se questi non passano, il login legittimo è rotto
    assert admin_core.safe_next_url(legit, BASE) == legit


def test_next_vuoto_va_al_fallback():
    assert admin_core.safe_next_url("", BASE) == "/admin/setup"


def test_senza_public_base_solo_i_relativi_passano():
    assert admin_core.safe_next_url("/admin/audit", "") == "/admin/audit"
