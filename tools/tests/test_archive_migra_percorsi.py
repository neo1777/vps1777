"""Le strade di `vps1777 archive-migra`: che cosa lancia, col lucchetto in mano, e che cosa dice.

Il comando passa ogni DB dell'archivio dall'indexer in `--migra`, nel servizio `ingest` e col
lucchetto dell'archivio; a secco di default. Qui docker e l'archivio sono finti: si guarda che
cosa parte, in che ordine, e come si legge ciascun esito dell'indexer.
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("vps1777_cli_migra", _ROOT / "tools" / "vps1777.py")
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)


class Banco:
    def __init__(self, monkeypatch, trovati, risposte):
        self.detto, self.eventi = [], []
        risposte = iter(risposte)
        monkeypatch.setattr(v, "log", lambda s: self.detto.append(s))
        monkeypatch.setattr(v, "warn", lambda s: self.detto.append("⚠ " + s))
        monkeypatch.setattr(v, "compose_cmd", lambda repo: ["docker", "compose"])
        monkeypatch.setattr(v, "_db_archivio", lambda repo, cc, db: list(trovati))

        @contextlib.contextmanager
        def lucchetto(repo, chi, **kw):
            self.eventi.append(("preso", chi))
            yield
            self.eventi.append(("lasciato", chi))

        def run(cmd, **kw):
            self.eventi.append(("run", list(cmd), kw.get("timeout")))
            return next(risposte)

        monkeypatch.setattr(v, "lucchetto_archivio", lucchetto)
        monkeypatch.setattr(v, "run", run)


def _ok(**esito):
    return SimpleNamespace(returncode=0, stdout="rumore\n" + json.dumps(esito) + "\n", stderr="")


def _lancia(scrivi=False, db="", **altro):
    return v.cmd_archive_migra(Path("/repo"), SimpleNamespace(db=db, scrivi=scrivi, **altro))


def test_senza_db_non_c_e_niente_da_fare(monkeypatch):
    b = Banco(monkeypatch, [], [])
    assert _lancia() == 0
    assert b.detto == ["nessun DB nell'archivio: niente da migrare"] and b.eventi == []


def test_a_secco_gira_nel_servizio_ingest_col_lucchetto_e_senza_scrivi(monkeypatch):
    b = Banco(monkeypatch, ["/data/uno.db"], [_ok(strumenti=3, sistema=1, speaker_prima={"human": 9},
                                                 speaker_dopo={"human": 5})])
    assert _lancia() == 0
    assert [e[0] for e in b.eventi] == ["preso", "run", "lasciato"]
    cmd = b.eventi[1][1]
    assert cmd[:2] == ["docker", "compose"] and cmd[-2:] == ["/data/uno.db", "--migra"]
    assert all(x in cmd for x in v.INGEST_RUN) and "--scrivi" not in cmd and b.eventi[1][2] == 1800
    assert b.detto[0].startswith("modalità A SECCO")
    assert "  uno: 3 righe diventerebbero 'tool', 1 'system' · human 9 → 5" in b.detto
    assert b.detto[-1] == "niente è stato scritto. Ripeti con --scrivi per applicare."


def test_con_scrivi_il_comando_lo_porta_e_il_referto_cambia_verbo(monkeypatch):
    b = Banco(monkeypatch, ["/data/uno.db"], [_ok(strumenti=2, scritto=True, indice_project=True)])
    assert _lancia(scrivi=True) == 0
    assert b.eventi[1][1][-1] == "--scrivi"
    assert b.detto == ["  uno: indice per etichetta creato (idx_project)",
                       "  uno: 2 righe diventate 'tool', 0 'system' · human 0 → 0"]


def test_solo_l_indice_o_niente_da_migrare(monkeypatch):
    b = Banco(monkeypatch, ["/data/a.db", "/data/b.db"], [_ok(indice_project=True), _ok()])
    assert _lancia(scrivi=True) == 0
    assert b.detto == ["  a: indice per etichetta creerei (idx_project)", "  b: niente da migrare"]


def test_un_db_saltato_dall_indexer_non_e_un_fallimento(monkeypatch):
    b = Banco(monkeypatch, ["/data/vecchio.db"],
              [SimpleNamespace(returncode=2, stdout="", stderr="schema precedente al voice-tagging\n")])
    assert _lancia(scrivi=True) == 0
    assert b.detto == ["  vecchio: saltato — schema precedente al voice-tagging"]


@pytest.mark.parametrize("risposta, frase", [
    (SimpleNamespace(returncode=1, stdout="", stderr="disco pieno"), "migrazione fallita — disco pieno"),
    (SimpleNamespace(returncode=0, stdout="non è json", stderr=""), "output non interpretabile — non è json"),
    (SimpleNamespace(returncode=0, stdout="", stderr=""), "output non interpretabile"),
])
def test_un_db_che_fallisce_fa_uscire_uno_ma_gli_altri_si_fanno_lo_stesso(monkeypatch, risposta, frase):
    b = Banco(monkeypatch, ["/data/rotto.db", "/data/buono.db"], [risposta, _ok(sistema=4, scritto=True)])
    assert _lancia(scrivi=True) == 1
    assert any(frase in d and "«rotto»" in d for d in b.detto), b.detto
    assert "  buono: 0 righe diventate 'tool', 4 'system' · human 0 → 0" in b.detto
    assert [e[0] for e in b.eventi].count("run") == 2


def test_telegram_vuole_un_db_nominato_e_va_per_la_sua_strada(monkeypatch):
    b = Banco(monkeypatch, ["/data/tg.db"], [])
    assert _lancia(telegram=True) == 2 and "--telegram vuole --db" in b.detto[0] and b.eventi == []
    visto = []
    monkeypatch.setattr(v, "_archive_migra_telegram",
                        lambda repo, cc, trovati, scrivi: visto.append((trovati, scrivi)) or 5)
    assert _lancia(telegram=True, db="tg", scrivi=True) == 5
    assert visto == [(["/data/tg.db"], True)] and b.eventi == []
