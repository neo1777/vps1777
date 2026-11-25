"""Il log del backup notturno sopravvive all'update (W5, 04/10/2026).

Fino alla 0.70.0 il cron del container backup scriveva in /var/log/backup.log, dentro il
container: ogni update ricrea il container, e il log se ne andava con lui. Il 04/10, per
capire che fine avesse fatto il notturno di quella notte, il log non c'era più: era
stato potato apposta (un solo core al giorno), ma dirlo è stato possibile solo dai nomi
dei file. Ora il log sta in backups/backup.log, sul volume, ed è tenuto corto.
"""
from __future__ import annotations

import re
from pathlib import Path

SETUP = Path(__file__).resolve().parents[2] / "tools" / "backup-container-setup.sh"


def test_il_cron_scrive_il_log_sul_volume_dei_backup_e_lo_tiene_corto() -> None:
    testo = SETUP.read_text(encoding="utf-8")
    righe = [r for r in testo.splitlines() if re.match(r"^[0-9*/,-]+ [0-9*/,-]+ [0-9*/,-]+ [0-9*/,-]+ [0-9*/,-]+ .*backup\.sh", r)]
    assert len(righe) == 1, "attesa una sola riga di crontab che lancia backup.sh"
    riga = righe[0]
    assert ">> /backups/backup.log 2>&1" in riga, "il log deve stare sul volume, non nel container"
    assert "/var/log/backup.log" not in testo
    assert re.search(r"tail -n \d+ /backups/backup\.log", riga), "senza un tetto il log cresce per sempre"


def _riga_del_cron_resa() -> str:
    """La riga del crontab COME ARRIVA nel container: l'heredoc di setup espande `$`, quindi
    la si fa espandere a una shell vera invece di leggerla dal sorgente."""
    import subprocess
    testo = SETUP.read_text(encoding="utf-8")
    corpo = testo.split("cat > /etc/crontabs/root <<EOF\n", 1)[1].split("\nEOF\n", 1)[0]
    resa = subprocess.run(["sh", "-c", f"cat <<EOF\n{corpo}\nEOF\n"], capture_output=True,
                          text=True, check=True, timeout=30).stdout
    righe = [r for r in resa.splitlines() if "backup.sh" in r and not r.startswith("#")]
    assert len(righe) == 1, resa
    return righe[0]


def test_il_cron_scrive_l_esito_del_giro_anche_quando_fallisce(tmp_path: Path) -> None:
    """Il comando del cron, eseguito davvero con un backup.sh finto che esce 3: in
    `ultimo-esito` deve finire 3 (non l'esito di `tail`, che viene dopo), e il log deve
    restare. È ciò che `vps1777 check` legge per avvisare la notte stessa."""
    import subprocess
    riga = _riga_del_cron_resa()
    comando = riga.split(None, 5)[5]                       # via i cinque campi dell'orario
    repo, backups = tmp_path / "vps1777", tmp_path / "backups"
    (repo / "tools").mkdir(parents=True)
    backups.mkdir()
    for esce, atteso in ((3, "3"), (0, "0")):
        (repo / "tools" / "backup.sh").write_text(f"echo giro\nexit {esce}\n", encoding="utf-8")
        vero = comando.replace("/vps1777", str(repo)).replace("/backups", str(backups))
        subprocess.run(["sh", "-c", vero], check=False, timeout=30)
        assert (backups / "ultimo-esito").read_text().strip() == atteso, riga
    assert (backups / "backup.log").read_text().count("giro") == 2
