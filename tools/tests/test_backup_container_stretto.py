"""Il container di backup gira stretto (H82, 13/10/2026): no-new-privileges, tre capability
misurate, repo in sola lettura.

Resta root, perché `apk add` a ogni avvio e crond lo vogliono. Le capability sono quelle
misurate sulla VPS di riferimento con un backup vero e un lavoro di cron vero:

    CHOWN, DAC_OVERRIDE, DAC_READ_SEARCH, FOWNER, SETUID, SETGID   backup ok, cron parte
    DAC_OVERRIDE, SETUID, SETGID                                   backup ok, cron parte
    DAC_OVERRIDE                                                   backup ok, cron NON parte

L'ultima riga è il motivo di questo file: togliere SETUID o SETGID «perché il backup a mano
funziona» spegne in silenzio il backup delle 03:00. E aggiungerne una «per sicurezza» allarga
un container che legge tutti i volumi e i secret.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def _backup() -> dict:
    c = yaml.safe_load((REPO / "compose.ops.backup.yaml").read_text(encoding="utf-8"))
    return c["services"]["backup"]


def test_niente_nuovi_privilegi_e_tutte_le_capability_tolte():
    b = _backup()
    assert "no-new-privileges:true" in (b.get("security_opt") or [])
    assert b.get("cap_drop") == ["ALL"]


def test_le_capability_sono_esattamente_le_tre_misurate():
    assert sorted(_backup().get("cap_add") or []) == ["DAC_OVERRIDE", "SETGID", "SETUID"], (
        "senza SETUID/SETGID crond non lancia il lavoro delle 03:00 (misurato il 13/10); "
        "una in più va misurata prima, non aggiunta")


def test_il_repo_si_monta_in_sola_lettura_e_backups_a_parte():
    vol = _backup()["volumes"]
    repo = [v for v in vol if isinstance(v, str) and v.split(":")[1:2] == ["/vps1777"]]
    assert repo == [".:/vps1777:ro"], repo
    assert "./backups:/backups:rw" in vol


def test_backup_sh_non_scrive_nel_repo():
    """Il repo è :ro: se backup.sh tornasse a scrivere sotto di sé fallirebbe solo di notte.
    Scrive in $TMP (mktemp) e in $BACKUP_DIR, che nel container è /backups."""
    testo = (REPO / "tools" / "backup.sh").read_text(encoding="utf-8")
    assert 'BACKUP_DIR="${BACKUP_DIR:-$REPO_ROOT/backups}"' in testo
    env = _backup().get("environment") or {}
    assert env.get("BACKUP_DIR") == "/backups"
