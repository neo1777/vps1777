"""I tre installer devono dare a fail2ban una jail che PARTE su Debian 12.

🔴 PERCHÉ ESISTE — misurato sulla VPS viva il 17/08, non ipotizzato:
   `fail2ban` era **morto da quattro settimane**, un secondo dopo il boot:

       19/07 11:43:22  systemd: Started fail2ban.service
       19/07 11:43:23  ERROR Failed during configuration:
                       Have not found any log file for sshd jail
       19/07 11:43:23  Main process exited, status=255/EXCEPTION

   e nello stesso momento `ss -ltn` mostrava `LISTEN 0.0.0.0:22`.
   ⇒ **ssh pubblico senza anti-brute-force, per quattro settimane** — mentre
   l'installer aveva stampato «Hardening host attivo».

🔑 LA CAUSA NON È UN GUASTO: su Debian 12 i log di sshd stanno solo nel journal,
   `/var/log/auth.log` non esiste, e la jail `sshd` di default cerca un file.
   *La configurazione non è invecchiata: non è mai stata adatta alla distribuzione
   che installiamo.* Serve `backend = systemd`.

⭐ E IL DIFETTO CHE L'HA RESA INVISIBILE È UN'ALTRA RIGA: `systemctl enable --now`
   esce **0** anche se il servizio muore un istante dopo, e il `|| true` copriva
   pure quello. *Un comando che attiva non è una prova che sia attivo: la prova è
   rileggere lo stato dell'oggetto.* ⇒ qui si pretendono ENTRAMBE le cose, perché
   da sole nessuna delle due basta: senza il backend il servizio muore, senza la
   verifica muore **in silenzio**.

⚠️ COSA QUESTO TEST NON FA, dichiarato: è statico. Legge il testo dei tre installer
   e vede che le due righe ci sono. Non prova che fail2ban parta davvero — quello
   vuole una macchina Debian 12 e un boot, cioè la fase (c) del collaudo FORMAT.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INSTALLER = {
    "setup.sh": REPO / "setup.sh",
    "deploy.sh": REPO / "deploy.sh",
    "installer/engine.py": REPO / "installer" / "engine.py",
}


def _testo(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def test_tutti_e_tre_scrivono_il_backend_systemd():
    """Senza questa riga la jail sshd non trova il log e fail2ban esce 255."""
    mancanti = [
        nome for nome, p in INSTALLER.items()
        # `\\n` in engine.py (è dentro uno script generato), `\n` negli .sh:
        # si cerca la coppia chiave→valore, non la riga formattata.
        if not re.search(r"backend\s*=\s*systemd", _testo(p))
    ]
    assert not mancanti, (
        f"questi installer non danno alla jail sshd il backend systemd: {mancanti}. "
        "Su Debian 12 fail2ban partirà e morirà subito, e ssh resterà senza "
        "anti-brute-force mentre l'installer dichiara «hardening attivo»."
    )


def test_tutti_e_tre_scrivono_jail_local():
    """Il backend va scritto DOVE fail2ban lo legge, non solo nominato."""
    mancanti = [n for n, p in INSTALLER.items()
                if "/etc/fail2ban/jail.local" not in _testo(p)]
    assert not mancanti, f"non scrivono /etc/fail2ban/jail.local: {mancanti}"


def test_tutti_e_tre_verificano_che_sia_ATTIVO():
    """⭐ La riga che rende il difetto visibile invece che silenzioso.

    `enable --now` esce 0 anche su un servizio che muore un istante dopo: senza un
    `is-active` riletto, l'installer dice «attivo» di qualcosa che non c'è più.
    """
    mancanti = [n for n, p in INSTALLER.items()
                if not re.search(r"is-active\s+--quiet\s+fail2ban", _testo(p))]
    assert not mancanti, (
        f"questi installer non RILEGGONO lo stato di fail2ban dopo averlo attivato: "
        f"{mancanti}. È il difetto per cui la VPS ha detto «hardening attivo» per "
        "quattro settimane con fail2ban morto."
    )


def test_il_caso_vero_del_17_08_non_puo_tornare_muto():
    """Controprova d'insieme: le tre proprietà devono stare INSIEME.

    Il backend senza la verifica lascia il prossimo guasto silenzioso; la verifica
    senza il backend segnala un guasto che avremmo potuto non avere. Le une senza
    le altre non chiudono il caso — e questo test esiste per dirlo se qualcuno ne
    togliesse una sola.
    """
    for nome, p in INSTALLER.items():
        t = _testo(p)
        assert re.search(r"backend\s*=\s*systemd", t), f"{nome}: manca il backend"
        assert re.search(r"is-active\s+--quiet\s+fail2ban", t), f"{nome}: manca la verifica"
