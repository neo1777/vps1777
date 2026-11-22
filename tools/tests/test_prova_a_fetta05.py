"""Le cure nate dalla quinta fetta della revisione col catalogo (la CLI `vps1777`): snapshot
interrotti, registro delle migrazioni, stato corrotto, estrazione del bundle, notifiche. La CLI è
il modulo vero; docker è sostituito."""
from __future__ import annotations

import importlib.util
import io
import subprocess
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("vps1777_fetta05", _ROOT / "tools" / "vps1777.py")
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)


def _esito(codice=0, out="", err=""):
    return subprocess.CompletedProcess([], codice, out, err)


# ── snapshot ────────────────────────────────────────────────────────────────────────────────

def test_uno_snapshot_senza_meta_non_e_il_piu_recente(tmp_path):
    base = tmp_path / "backups" / "pre-update"
    (base / "0.9.0-vecchio").mkdir(parents=True)
    (base / "0.9.0-vecchio" / "meta.json").write_text("{}")
    (base / "0.9.1-interrotto").mkdir()                    # più recente, ma senza meta.json
    (base / "0.9.1-interrotto" / "archive-db.tar").write_bytes(b"troncato")
    assert v.snapshot_latest(tmp_path).name == "0.9.0-vecchio"
    with pytest.raises(RuntimeError, match="incompleto"):
        v.snapshot_restore(tmp_path, base / "0.9.1-interrotto")


def test_uno_snapshot_che_fallisce_a_meta_non_resta(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "snapshot_purge_excluded", lambda repo: 0)
    chiamate = []

    def run(cmd, **k):
        chiamate.append(cmd)
        if len(chiamate) == 2:                              # il secondo volume: disco pieno
            raise subprocess.CalledProcessError(1, cmd)
        dst = next(a.split(":")[0] for a in cmd if a.endswith(":/dst"))
        (Path(dst) / "x.tar").write_bytes(b"dati")
        return _esito()

    monkeypatch.setattr(v, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        v.snapshot_create(tmp_path, "0.9.0", "0.9.1")
    base = tmp_path / "backups" / "pre-update"
    assert list(base.iterdir()) == [], "la cartella dello snapshot interrotto deve sparire"
    assert v.snapshot_latest(tmp_path) is None


# ── registro delle migrazioni ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("risposta, atteso", [
    (_esito(0, v._REGISTRO_ASSENTE + "\n"), []),
    (_esito(0, '{"schema": 1, "applied": [{"id": "m1"}]}'), [{"id": "m1"}]),
])
def test_il_registro_assente_o_sano_si_legge(monkeypatch, risposta, atteso):
    monkeypatch.setattr(v, "run", lambda cmd, **k: risposta)
    assert v.registry_read()["applied"] == atteso


@pytest.mark.parametrize("risposta", [
    _esito(125, "", "docker: errore"),          # docker non ha risposto
    _esito(0, ""),                              # c'è, ma è vuoto (troncato)
    _esito(0, '{"schema": 1, "appl'),           # JSON a metà
    _esito(0, '{"schema": 1}'),                 # senza l'elenco
    _esito(0, "[]"),
])
def test_un_registro_che_non_si_legge_non_vale_vuoto(monkeypatch, risposta):
    """Prima valeva «nessuna migrazione applicata» e le migrazioni ripartivano tutte."""
    monkeypatch.setattr(v, "run", lambda cmd, **k: risposta)
    with pytest.raises(v.MigrationError) as exc:
        v.registry_read()
    assert exc.value.mutated is False


def test_il_registro_si_scrive_su_un_temporaneo_e_poi_si_rinomina(monkeypatch):
    visti = {}
    monkeypatch.setattr(v.subprocess, "run", lambda cmd, **k: visti.update(cmd=cmd, k=k) or _esito())
    v._registry_write({"schema": 1, "applied": []})
    sh = visti["cmd"][-1]
    assert f"cat > /state/{v.REGISTRY_PATH}.tmp" in sh and f"mv -f /state/{v.REGISTRY_PATH}.tmp" in sh
    assert visti["k"]["timeout"] and visti["k"]["check"] is True


# ── stato dell'updater ──────────────────────────────────────────────────────────────────────

def test_uno_stato_corrotto_si_mette_da_parte_e_lo_stato_nuovo_lo_dichiara(tmp_path):
    p = v.state_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"current": "0.9.0", "update_in_pro')
    st = v.state_load(tmp_path)
    assert st["stato_perso"] and st["update_in_progress"] is None
    assert p.with_name(p.name + ".corrotto").is_file() and not p.exists()
    assert "stato_perso" not in v.state_load(tmp_path)       # assente: prima installazione


def test_il_comando_di_update_guarda_lo_stack_se_lo_stato_era_perso():
    src = (_ROOT / "tools" / "vps1777.py").read_text(encoding="utf-8")
    i = src.index("    if norm_ver(cur) == target:")
    blocco = src[i:src.index('ok(f"già aggiornato (v{target})")', i)]
    assert 'st.get("stato_perso")' in blocco and "health_gate(repo)" in blocco and "die(" in blocco


# ── estrazione del bundle ───────────────────────────────────────────────────────────────────

def test_senza_il_filtro_di_python_i_collegamenti_si_rifiutano():
    src = (_ROOT / "tools" / "vps1777.py").read_text(encoding="utf-8")
    i = src.index('tar.extractall(bundle, filter="data")')
    ripiego = src[i:src.index("tar.extractall(bundle)\n", i)]
    assert "except TypeError:" in ripiego and "m.isreg() or m.isdir()" in ripiego
    # e la condizione fa quello che dice: un collegamento non è né file né cartella
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        info = tarfile.TarInfo("dentro/link")
        info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
        t.addfile(info)
    buf.seek(0)
    with tarfile.open(fileobj=buf) as t:
        m = t.getmembers()[0]
        assert not (m.isreg() or m.isdir())


# ── download, notifiche, secret ─────────────────────────────────────────────────────────────

def test_il_download_ha_un_tetto(tmp_path, monkeypatch):
    class Risposta(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(v.urllib.request, "urlopen", lambda req, timeout=0: Risposta(b"x" * 5000))
    dest = tmp_path / "asset"
    with pytest.raises(OSError, match="oltre il tetto"):
        v.download("https://example.invalid/a", dest, massimo=1000)
    assert not dest.exists()
    v.download("https://example.invalid/a", dest, massimo=10_000)
    assert dest.stat().st_size == 5000


def test_la_notifica_dice_se_e_partita(tmp_path, monkeypatch):
    assert v.telegram_notify(tmp_path, "ciao") is False            # niente token: saltata
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "telegram_bot_token.txt").write_text("1" + "23:" + "finto")
    monkeypatch.setattr(v, "env_read", lambda repo: {"TELEGRAM_OWNER_ID": "1"})
    monkeypatch.setattr(v, "arma_redazione", lambda repo: None)

    def giu(req, timeout=0):
        raise OSError("rete giù")

    monkeypatch.setattr(v.urllib.request, "urlopen", giu)
    assert v.telegram_notify(tmp_path, "ciao") is False

    class Ok:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(v.urllib.request, "urlopen", lambda req, timeout=0: Ok())
    assert v.telegram_notify(tmp_path, "ciao") is True


def test_il_campanello_non_dice_mandata_se_non_e_partita():
    src = (_ROOT / "tools" / "vps1777.py").read_text(encoding="utf-8")
    i = src.index('ok("campanello: notifica mandata")')
    assert "if not telegram_notify(repo, testo):" in src[i - 500:i]


def test_secret_mancanti_non_sono_tutti_a_posto():
    src = (_ROOT / "tools" / "vps1777.py").read_text(encoding="utf-8")
    i = src.index('ok("tutti i secret entro la soglia")')
    prima = src[i - 500:i]
    assert "elif mancanti:" in prima and "secret attesi e non trovati" in prima


def test_l_elenco_in_testa_nomina_ogni_sottocomando():
    testa = v.__doc__ or ""
    parser = v.build_parser()
    azioni = next(a for a in parser._actions if isinstance(a.choices, dict))
    mancanti = [nome for nome in azioni.choices if nome not in testa and nome != "help"]
    assert not mancanti, f"sottocomandi non nominati in testa a vps1777.py: {mancanti}"


def test_l_avviso_finale_usa_il_repo_gia_risolto():
    src = (_ROOT / "tools" / "vps1777.py").read_text(encoding="utf-8")
    i = src.index("def _esci(codice: int) -> None:")
    assert "_REPO_RISOLTO or find_repo(None)" in src[i:]
    assert "_REPO_RISOLTO = repo" in src and SimpleNamespace  # main lo imposta
