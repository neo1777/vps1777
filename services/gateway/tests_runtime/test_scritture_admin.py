"""Giro di revisione del 21/11/2026: le scritture delle pagine admin sono tutto-o-niente.
Deps del lock (admin vero)."""
from __future__ import annotations

import json
import stat

from app import admin


def test_scrive_e_mette_i_permessi_prima_di_rinominare(tmp_path):
    f = tmp_path / "update_pending_update.json"
    assert admin._scrivi_json(f, {"nonce": "x"}, modo=0o640) is True
    assert json.loads(f.read_text()) == {"nonce": "x"}
    assert stat.S_IMODE(f.stat().st_mode) == 0o640
    assert [p.name for p in tmp_path.iterdir()] == [f.name]      # nessun temporaneo lasciato


def test_cartella_non_scrivibile_torna_false_e_non_solleva(tmp_path):
    assert admin._scrivi_json(tmp_path / "manca" / "stato.json", {"a": 1}) is False


def test_un_json_che_non_e_un_oggetto_vale_vuoto(tmp_path):
    f = tmp_path / "marchi.json"
    f.write_text("[1, 2]")
    assert admin._read_json(f) == {}
    assert admin._marchi_leggibili(f) is False
    f.write_text('{"3": "riservato"}')
    assert admin._marchi_leggibili(f) is True
    f.write_text("{rotto")
    assert admin._marchi_leggibili(f) is False
