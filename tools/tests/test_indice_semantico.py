"""`tools/indice_semantico.py aggiorna`: i sei passi, e soprattutto le guardie.

L'esecutore è finto: simula la VPS (copia del DB, indice presente o no, sha del DB
remoto) e il costruttore, e registra i comandi. Le guardie che contano: niente
caricamento se il DB sulla VPS è cambiato dopo la copia; niente costruzione senza
perimetro su un DB che non ha indice; niente costruzione su una copia incoerente;
e il caricamento passa da un nome d'attesa poi rinominato.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import sqlite3
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("indice_semantico", _ROOT / "tools" / "indice_semantico.py")
isem = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(isem)


class VpsFinta:
    def __init__(self, lavoro: Path, *, vec_remoto: bool, db_cambiato: bool = False,
                 copia_rotta: bool = False) -> None:
        self.lavoro, self.vec_remoto = lavoro, vec_remoto
        self.db_cambiato, self.copia_rotta = db_cambiato, copia_rotta
        self.comandi: list[str] = []

    def __call__(self, cmd, **kw) -> subprocess.CompletedProcess:
        testo = " ".join(cmd)
        self.comandi.append(testo)
        ok = subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[0] == "bash" and "arch.db:" not in testo and "/arch.db" in testo and "tar -x" in testo:
            db = self.lavoro / "arch.db"
            c = sqlite3.connect(db)
            c.execute("CREATE TABLE IF NOT EXISTS messages(uuid TEXT)")
            c.commit()
            c.close()
            if self.copia_rotta:
                with open(db, "r+b") as f:
                    f.seek(100)
                    f.write(b"\xff" * 3000)
            return ok
        if cmd[0] == "bash" and "arch.vec.db" in testo and "tar -x" in testo:
            (self.lavoro / "arch.vec.db").write_bytes(b"indice-remoto")
            return ok
        if "test -f" in testo:
            return subprocess.CompletedProcess(cmd, 0 if self.vec_remoto else 1, "", "")
        if "sha256sum" in testo:
            sha = hashlib.sha256((self.lavoro / "arch.db").read_bytes()).hexdigest()
            if self.db_cambiato:
                sha = "0" * 64
            return subprocess.CompletedProcess(cmd, 0, f"{sha}  /var/lib/archive/db/arch.db\n", "")
        if cmd[:2] == ["uv", "run"]:
            (self.lavoro / "arch.vec.db").write_bytes(b"indice-nuovo")
            return ok
        return ok


def _args(lavoro: Path, **kw) -> argparse.Namespace:
    a = isem.build_parser().parse_args(["aggiorna", "--host", "vps", "--db", "arch",
                                        "--lavoro", str(lavoro), "--modello", "/m"])
    for k, v in kw.items():
        setattr(a, k, v)
    return a


def test_percorso_intero_incrementale_dall_indice_della_vps(tmp_path):
    vps = VpsFinta(tmp_path, vec_remoto=True)
    assert isem.aggiorna(_args(tmp_path), esegui=vps, stampa=lambda *_: None) == 0
    c = vps.comandi
    costr = [x for x in c if x.startswith("uv run")]
    assert len(costr) == 2 and "--controlla" in costr[1]
    assert "--tutto" not in costr[0], "con un indice di partenza la costruzione è incrementale"
    carico = next(i for i, x in enumerate(c) if "docker cp - " in x)
    assert "arch.vec.db.caricamento" in c[carico], "arriva col nome d'attesa"
    assert "tar -c" in c[carico] and "ssh vps" in c[carico], "in streaming, in una pipe"
    assert "mv /var/lib/archive/db/arch.vec.db.caricamento /var/lib/archive/db/arch.vec.db" in c[carico + 1]
    assert c.index(next(x for x in c if "sha256sum" in x)) < carico, "il confronto viene PRIMA del carico"


def test_db_cambiato_sulla_vps_non_si_carica(tmp_path):
    vps = VpsFinta(tmp_path, vec_remoto=True, db_cambiato=True)
    with pytest.raises(isem.Rifiuto, match="cambiato"):
        isem.aggiorna(_args(tmp_path), esegui=vps, stampa=lambda *_: None)
    assert not any("docker cp - " in x for x in vps.comandi)


def test_senza_indice_e_senza_perimetro_non_costruisce(tmp_path):
    vps = VpsFinta(tmp_path, vec_remoto=False)
    with pytest.raises(isem.Rifiuto, match="perimetro|--tutto"):
        isem.aggiorna(_args(tmp_path), esegui=vps, stampa=lambda *_: None)
    assert not any(x.startswith("uv run") for x in vps.comandi)


def test_prima_costruzione_col_perimetro(tmp_path):
    vps = VpsFinta(tmp_path, vec_remoto=False)
    assert isem.aggiorna(_args(tmp_path, tutto=True), esegui=vps, stampa=lambda *_: None) == 0
    assert "--tutto" in next(x for x in vps.comandi if x.startswith("uv run"))


def test_copia_incoerente_si_ferma_prima_di_costruire(tmp_path):
    vps = VpsFinta(tmp_path, vec_remoto=True, copia_rotta=True)
    with pytest.raises(isem.Fallito, match="coerente"):
        isem.aggiorna(_args(tmp_path), esegui=vps, stampa=lambda *_: None)
    assert not any(x.startswith("uv run") for x in vps.comandi)


def test_non_caricare_si_ferma_dopo_il_controllo(tmp_path):
    vps = VpsFinta(tmp_path, vec_remoto=True)
    assert isem.aggiorna(_args(tmp_path, non_caricare=True), esegui=vps, stampa=lambda *_: None) == 0
    assert not any("docker cp - " in x for x in vps.comandi)
