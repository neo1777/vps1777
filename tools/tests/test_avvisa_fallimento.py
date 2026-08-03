"""Un update che fallisce PRIMA di rompere qualcosa deve avere una voce.

🔴 IL FATTO CHE L'HA GENERATO, misurato sulla VPS viva il 03/08:
   `vps1777-auto-update.service` è fallito alle 04:32 e **nessuno l'ha saputo
   per dieci ore**. Il bundle della 0.41.0 era scaricato e verificato; si è rotto
   nel copiare la CLI nuova (step 6, self-update), con un CalledProcessError non
   gestito. Trovato solo leggendo il journal a mano.

⭐ L'ASIMMETRIA che lo spiega, dal codice:
     fallimento DOPO aver toccato lo stack → rollback → telegram_notify ✅
     fallimento PRIMA (preflight/fetch/self-update) → traceback → SILENZIO 🔴
   ⇒ la notifica viveva DENTRO la routine di rollback: copriva solo il
     fallimento che rompe qualcosa. **Quello che non rompe niente — e che
     quindi nessuno nota — era l'unico senza voce.**

🔑 Per questo la cura sta in `OnFailure=` di systemd e non nel flusso: systemd sa
   che la unit è fallita QUALUNQUE sia la ragione, incluso un crash che il
   codice non aveva previsto.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parents[2]
SYSTEMD = RADICE / "systemd"
CLI = (RADICE / "tools" / "vps1777.py").read_text(encoding="utf-8")

# le unit che, fallendo, lasciano la macchina indietro senza rompere niente
DA_SORVEGLIARE = ["vps1777-auto-update.service", "vps1777-update.service",
                  "vps1777-check-update.service", "vps1777-secrets-check.service"]


@pytest.mark.parametrize("nome", DA_SORVEGLIARE)
def test_la_unit_avvisa_se_fallisce(nome: str):
    p = SYSTEMD / nome
    assert p.is_file(), f"{nome} non esiste: il test non ha guardato niente"
    testo = p.read_text(encoding="utf-8")
    righe = [r for r in testo.splitlines()
             if r.strip().startswith("OnFailure=")]
    assert righe, (
        f"{nome} non ha OnFailure=: se fallisce, nessuno lo sa. È successo il "
        "03/08 alle 04:32 e l'abbiamo scoperto dieci ore dopo.")


def test_esiste_la_unit_che_avvisa():
    p = SYSTEMD / "vps1777-avvisa-fallimento@.service"
    assert p.is_file(), "manca la unit template che manda l'avviso"
    testo = p.read_text(encoding="utf-8")
    assert "avvisa-fallimento --unit %i" in testo, (
        "la unit non passa il nome della unit fallita: l'avviso direbbe che "
        "«qualcosa» è fallito, che è quasi come tacere")


def test_il_comando_e_REGISTRATO_nella_mappa_non_solo_definito():
    """Definito e non smistato è irraggiungibile — e non lascia traccia.

    Mi è successo scrivendolo: avevo aggiunto il parser e la funzione, e il
    dispatch di questo file è un DIZIONARIO, non una catena di `if`. Il comando
    esisteva e non partiva.
    """
    assert "def cmd_avvisa_fallimento(" in CLI, "la funzione non c'è"
    assert re.search(r'"avvisa-fallimento":\s*cmd_avvisa_fallimento', CLI), (
        "il comando non è nella mappa `handlers`: è definito e IRRAGGIUNGIBILE")


def test_l_avviso_non_puo_far_fallire_chi_lo_chiama():
    """`OnFailure` non ha un `OnFailure`: se l'avviso rompe, il silenzio torna."""
    i = CLI.index("def cmd_avvisa_fallimento(")
    corpo = CLI[i:CLI.index("\ndef ", i + 10)]
    assert corpo.count("except Exception") >= 2, (
        "il corpo non protegge entrambe le fasi (journal e notifica): "
        "un avviso che solleva è un secondo problema sopra il primo")
    assert "return 0" in corpo, "deve uscire 0 anche quando la notifica non parte"


def test_la_sonda_SA_DIRE_DI_NO():
    """Controprova: su una unit finta senza OnFailure gli assert devono fallire."""
    finta = "[Unit]\nDescription=x\n\n[Service]\nExecStart=/bin/true\n"
    assert not [r for r in finta.splitlines() if r.strip().startswith("OnFailure=")]


def test_OGNI_unit_che_chiama_la_CLI_ha_un_OnFailure():
    """La regola non è una LISTA di quattro nomi: è una RELAZIONE.

    🔑 PERCHÉ. `71d540e6` propone che la sua notifica (dentro `_esci()`) TACCIA
       sotto systemd, così un fallimento non manda due avvisi: fuori da systemd
       parla la sua, dentro parla `OnFailure`. **La partizione è giusta e non
       lascia buchi — a UNA condizione: che ogni unit che invoca la CLI abbia un
       `OnFailure`.** Se domani ne nascesse una senza, quel percorso resterebbe
       muto da entrambe le parti: la sua tace perché è sotto systemd, la mia non
       c'è. *Un buco che nasce da due cure corrette messe insieme.*

    ⇒ Questo test è la condizione, resa eseguibile. Una lista di quattro nomi
      invecchierebbe al primo servizio nuovo; questa domanda no.
    """
    senza = []
    for u in sorted(SYSTEMD.glob("vps1777-*.service")):
        testo = u.read_text(encoding="utf-8")
        if "ExecStart=/usr/local/bin/vps1777" not in testo:
            continue
        if u.name.startswith("vps1777-avvisa-fallimento"):
            continue          # è LEI l'avviso: OnFailure sull'OnFailure non esiste
        if not [r for r in testo.splitlines() if r.strip().startswith("OnFailure=")]:
            senza.append(u.name)
    assert not senza, (
        f"unit che invocano la CLI senza OnFailure: {senza}. Con la notifica "
        "interna silenziata sotto systemd, questi percorsi non avvisano da "
        "NESSUNA delle due parti — un buco nato da due cure corrette insieme.")
