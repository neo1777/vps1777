#!/usr/bin/env python3
"""`setup.sh` viene ESEGUITO, non solo letto — ed e' il comando con cui nasce ogni macchina.

🔴 IL BUCO, misurato il 16/08: **cinque test nominano `setup.sh` e tutti e cinque lo
LEGGONO come sorgente** (`test_install_version_non_conflata`, `test_tre_installer_stessa
_lista_unit`, `test_env_perm_verificato`, `test_vps1777`, `test_sudo_whitelist_copre_la
_cli`). Nessuno lo lancia. La CI lo cita solo nei commenti.
⇒ *lo script che installa il prodotto era l'unico pezzo del prodotto che nessuno eseguiva*,
e il primo a scoprirlo rotto sarebbe stato chi installa da zero — cioe' chi ha meno modo
di capire cos'e' andato storto.

⭐ **PERCHE' NON ERA COLPA DI NESSUNO, ed e' la parte che vale:** fino alla #165 setup.sh
**non era testabile senza una persona che digita** — le risposte arrivavano da `read` e non
c'era modo di passarle. Quella PR ha aperto la porta (`SETUP_<VAR>` per le domande,
`SETUP_YES` per le conferme) **e nessuno e' entrato**: la cura che rende possibile un
presidio non lo crea. *Fra «adesso si puo' fare» e «adesso e' fatto» non c'e' nessun
automatismo, e la distanza non la segnala niente — nessun test diventa rosso.*

## Cosa fa questo test

Esegue `setup.sh` per intero in una copia usa-e-getta del repo, con le risposte passate
da variabili, e verifica che produca cio' che deve **senza avviare niente**:

    SETUP_ADMIN_EMAIL · SETUP_TG_OWNER_ID · SETUP_INGRESS_NUM=1 (tailscale)
    SETUP_ADMIN_PWD   (una password che passa la policy H16)
    SETUP_YES=n       → risponde «no» a TUTTE e due le conferme:
                        ① «genero io la password?» → no ⇒ usa SETUP_ADMIN_PWD
                        ② «Procedo ora?»           → no ⇒ **niente `docker compose up`**

🔑 Le due conferme vogliono risposte opposte e `SETUP_YES` ne da' una sola — sembra un
limite del contratto e non lo e': il ramo «no» della prima e' proprio quello che accetta
`SETUP_ADMIN_PWD`, e la password passata resta sottoposta a `pw_weak_reason` come quella
digitata. *Un contratto non-interattivo che aggirasse la policy sarebbe una porta di
servizio; qui la comodita' non compra una password piu' debole.*

## Il verso dell'errore, dichiarato

Se mancano `docker`/`docker compose`/`python3`, setup.sh esce subito con `die` — e il test
**si salta** invece di fallire: non e' il suo compito misurare la macchina che lo ospita.
Uno `skip` dichiarato non e' un verde: dice che non ha potuto guardare.

Stile stdlib-only: la CI esegue `tools/tests/` con `uvx pytest` senza dipendenze.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
# passa la policy H16 (min 16, >=3 classi, niente pattern comuni) senza essere un segreto:
# e' una stringa di test, generata a mano e valida solo dentro la copia usa-e-getta.
PWD_DI_PROVA = "Qz7mKp2wLr9xTv4B"


def _requisiti_presenti() -> str:
    """Il messaggio dello skip, o "" se si puo' girare. Non indovina: prova i comandi."""
    if not shutil.which("docker"):
        return "docker non installato"
    if subprocess.run(["docker", "compose", "version"],
                      capture_output=True).returncode != 0:
        return "docker compose v2 non disponibile"
    if not shutil.which("python3"):
        return "python3 non installato"
    # 🔴 IL REQUISITO CHE LA DOC NON DICHIARA, e questo test l'ha trovato al primo giro:
    #   setup.sh:306 fa `python3 -m pip install --user bcrypt` se bcrypt manca, e su
    #   Debian/Ubuntu `python3` e `python3-pip` sono DUE pacchetti distinti. Il runner
    #   della CI usa il python di `uv`, che non ha pip: «Impossibile installare bcrypt».
    #   docs/INSTALL.md riga 17 chiede solo «python3 3.10+».
    #   ⚠️ e il verso è pessimo: setup.sh muore DOPO aver scritto .env e 3 secret.
    #   (curato a parte: il requisito va verificato in testa, non a meta' installazione)
    if subprocess.run(["python3", "-c", "import bcrypt"], capture_output=True).returncode != 0:
        if subprocess.run(["python3", "-m", "pip", "--version"],
                          capture_output=True).returncode != 0:
            return "bcrypt assente e pip non disponibile per questo python3"
    return ""


@contextlib.contextmanager
def _copia_usa_e_getta():
    """Un worktree temporaneo: setup.sh scrive `.env` e `secrets/*` nella CWD.

    Non deve toccare il repo di chi lancia i test — ne' lasciare residui se fallisce.
    """
    motivo = _requisiti_presenti()
    if motivo:
        pytest.skip(f"{motivo} — questo test misura setup.sh, non la macchina")
    tmp = tempfile.mkdtemp(prefix="setup-sh-prova-")
    copia = Path(tmp) / "vps1777"
    subprocess.run(["git", "-C", str(REPO), "worktree", "add", "--detach", str(copia), "HEAD"],
                   capture_output=True, check=True)
    try:
        yield copia
    finally:
        subprocess.run(["git", "-C", str(REPO), "worktree", "remove", "--force", str(copia)],
                       capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)


def _ambiente(pwd: str) -> dict:
    return {**os.environ, "SETUP_ADMIN_EMAIL": "prova@example.com",
            "SETUP_TG_OWNER_ID": "123456789", "SETUP_INGRESS_NUM": "1",
            "SETUP_ADMIN_PWD": pwd, "SETUP_YES": "n"}


def test_gira_e_produce_i_file_senza_avviare_niente() -> None:
    with _copia_usa_e_getta() as copia:
        res = subprocess.run(["bash", "setup.sh"], cwd=copia, env=_ambiente(PWD_DI_PROVA),
                             capture_output=True, text=True, timeout=600)
        coda_out = (res.stdout + res.stderr)[-2500:]
        assert res.returncode == 0, f"setup.sh e' uscito {res.returncode}:\n{coda_out}"

        env_file = copia / ".env"
        assert env_file.is_file(), f"nessun .env prodotto:\n{coda_out}"
        testo = env_file.read_text(encoding="utf-8")
        assert "prova@example.com" in testo, "l'email passata non e' finita nel .env"
        assert "123456789" in testo, "il TELEGRAM_OWNER_ID passato non e' finito nel .env"

        attesi = ["gateway_secret.txt", "oauth_signing_secret.txt", "admin_password_bcrypt.txt"]
        mancanti = [n for n in attesi if not (copia / "secrets" / n).is_file()]
        assert not mancanti, f"secret non generati: {mancanti}\n{coda_out}"

        # e NON ha avviato niente: la conferma finale ha risposto «no».
        # Si guarda l'OUTPUT del comando, non `docker ps`: un container di un'altra prova
        # sulla stessa macchina renderebbe il controllo un falso allarme.
        assert "Creating" not in coda_out
        assert "Container vps1777" not in coda_out


def test_una_password_debole_da_variabile_viene_RIFIUTATA() -> None:
    """L'autoprova di questo test: la porta non-interattiva non aggira la policy H16.

    Se questo passasse in silenzio, il contratto sarebbe una porta di servizio sulla
    robustezza — e il test sopra darebbe verde comunque. *Un presidio che non sa
    rifiutare non prova niente.*
    """
    with _copia_usa_e_getta() as copia:
        res = subprocess.run(["bash", "setup.sh"], cwd=copia, env=_ambiente("password"),
                             capture_output=True, text=True, timeout=600)
        assert res.returncode != 0, (
            "una password debole passata da variabile e' stata ACCETTATA: "
            "il contratto non-interattivo sta aggirando la policy H16")
        assert "policy" in (res.stdout + res.stderr), (
            "e' fallito, ma non per la policy: verificare che fallisca per la RAGIONE "
            "che questo test dichiara, non per una qualsiasi")
