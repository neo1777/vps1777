"""H102: prima di OGNI avvio dei servizi passa `tools/permessi-servizi.sh`.

Il rimedio provvisorio per le macchine con l'uid 1000 occupato regge solo se nessun punto che
avvia i servizi lo salta: un segreto riscritto a 600 (rotazione, ripristino, installazione) torna
illeggibile ai servizi, e l'avvio dopo fallisce con un «Permission denied» che non dice perché.
Qui si contano gli avvii nei file che li fanno e si pretende lo strumento davanti a ognuno.
Che lo strumento FACCIA il suo lavoro lo prova `test-permessi-servizi.sh`, in un contenitore.
"""
from __future__ import annotations

import re
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]
STRUMENTO = "permessi-servizi.sh"


def _righe(nome: str) -> list[str]:
    return (RADICE / nome).read_text(encoding="utf-8").split("\n")


def _eseguita(riga: str) -> bool:
    r = riga.strip()
    return bool(r) and not r.startswith("#") and not r.startswith(("log ", 'log "', "warn ", "echo ", '"'))


def test_ogni_avvio_dei_servizi_passa_prima_dai_permessi():
    mancanti: list[str] = []
    # installatori: lo strumento sta nella STESSA riga di comando, subito prima di `up -d`
    for nome, avvio in (("deploy.sh", r"\$COMPOSE_CMD up -d"), ("installer/engine.py", r"\{cmd\} up -d")):
        for n, riga in enumerate(_righe(nome), 1):
            if re.search(avvio, riga) and _eseguita(riga) and "def " not in riga:
                if not re.search(STRUMENTO + r" \. && (\{env\} )?" + avvio, riga):
                    mancanti.append(f"{nome}:{n}")
    # setup.sh, rotazione: lo strumento sta nella riga PRIMA dell'avvio o del riavvio
    for nome, avvio in (("setup.sh", r'^\s+docker compose "\$\{COMPOSE_FILES\[@\]\}".* up -d'),
                        ("tools/rotate-secret.sh", r"^\s+docker compose restart ")):
        righe = _righe(nome)
        for n, riga in enumerate(righe, 1):
            if re.search(avvio, riga) and STRUMENTO not in righe[n - 2]:
                mancanti.append(f"{nome}:{n}")
    # CLI: `permessi_servizi(repo)` nella riga prima di ogni `compose … up -d`
    righe = _righe("tools/vps1777.py")
    for n, riga in enumerate(righe, 1):
        if re.search(r'run\(\[\*compose_cmd\(repo\), "up", "-d"\]', riga) and "permessi_servizi(repo)" not in righe[n - 2]:
            mancanti.append(f"tools/vps1777.py:{n}")
    assert not mancanti, "avvii dei servizi senza permessi-servizi.sh davanti: " + ", ".join(mancanti)


def test_gli_avvii_contati_sono_quelli_noti():
    """Se un file smette di avere avvii (o ne nasce uno di forma nuova) il conto qui sopra potrebbe
    non vedere più niente e restare verde: il numero è fissato, chi lo cambia guarda perché."""
    conto = {
        "deploy.sh": sum("permessi-servizi.sh . && $COMPOSE_CMD up -d" in r for r in _righe("deploy.sh")),
        "installer/engine.py": sum("permessi-servizi.sh ." in r for r in _righe("installer/engine.py")),
        "setup.sh": sum(STRUMENTO in r for r in _righe("setup.sh")),
        "tools/rotate-secret.sh": sum(STRUMENTO in r for r in _righe("tools/rotate-secret.sh")),
        "tools/vps1777.py": sum(r.strip() == "permessi_servizi(repo)" for r in _righe("tools/vps1777.py")),
        "tools/restore.sh": sum(STRUMENTO in r for r in _righe("tools/restore.sh")),
    }
    assert conto == {"deploy.sh": 4, "installer/engine.py": 5, "setup.sh": 2, "tools/rotate-secret.sh": 4,
                     "tools/vps1777.py": 5, "tools/restore.sh": 1}, conto


def test_lo_strumento_viaggia_nel_pacchetto_di_runtime():
    """La rotazione e la CLI lo chiamano sulla macchina: se il pacchetto non lo porta, dopo il primo
    aggiornamento non c'è più."""
    assert " permessi-servizi.sh;" in (RADICE / "tools" / "assembla-pacchetto.sh").read_text(encoding="utf-8")


def test_gli_installatori_mettono_l_operatore_nel_gruppo_dei_servizi():
    for nome in ("deploy.sh", "installer/engine.py"):
        testo = (RADICE / nome).read_text(encoding="utf-8")
        assert "groupadd -g 1000 vps1777-servizi" in testo and "usermod -aG \"$(getent group 1000" in testo, nome
