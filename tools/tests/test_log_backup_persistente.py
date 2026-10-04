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
