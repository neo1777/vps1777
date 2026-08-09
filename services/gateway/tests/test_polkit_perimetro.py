"""La regola polkit concede SOLO `reload-daemon` — stdlib-only, offline.

Presidia il perimetro di `polkit/49-vps1777-daemon-reload.rules` (voce a329f659),
non la sua sintassi: quella si valida con un motore JS e in CI non c'è.

⚠️ Perché un test su un file INERTE: la regola oggi non è installata da nessuno (via A
in vigore, vedi la testa del .rules). Ma il giorno in cui si passasse alla via B verrà
installata, e la tentazione naturale di chi la trova insufficiente è ALLARGARLA —
`manage-units` «così funziona tutto». Quello darebbe start/stop/restart di QUALUNQUE
unit all'utente operatore, che è un permesso di ordine diverso.

Il test costa niente e vive nella suite che gira già. Sta in `services/gateway/tests/`
e non in una suite propria per la stessa ragione per cui ci sta `test_tetti_coerenti`:
è lì che gira `uvx pytest` senza dipendenze.
"""
from __future__ import annotations

import re
from pathlib import Path

_REGOLA = Path(__file__).resolve().parents[3] / "polkit" / "49-vps1777-daemon-reload.rules"

# Le azioni che NON devono comparire, con il perché accanto: chi le aggiunge deve
# leggere cosa concede, non solo far passare il test.
_VIETATE = {
    "org.freedesktop.systemd1.manage-units": "start/stop/restart di qualunque unit",
    "org.freedesktop.systemd1.manage-unit-files": "enable/disable di qualunque unit",
    "org.freedesktop.systemd1.set-environment": "iniezione di variabili nel manager",
}


def _righe_di_codice() -> list[str]:
    """Le righe SENZA i commenti: la regola sono i comportamenti, non la prosa.

    Il file è pieno di commenti che NOMINANO le azioni vietate (per spiegare perché
    sono escluse). Un test che cercasse le stringhe nel testo grezzo fallirebbe su
    quelle spiegazioni — è la stessa trappola per cui H48 ha dato un rosso su un mio
    commento nel `compose.yaml` la notte del 08/09.
    """
    fuori = []
    for riga in _REGOLA.read_text(encoding="utf-8").splitlines():
        nuda = riga.strip()
        if nuda.startswith("//") or not nuda:
            continue
        fuori.append(nuda)
    return fuori


def test_la_regola_esiste_ed_e_leggibile():
    assert _REGOLA.is_file(), f"regola polkit assente: {_REGOLA}"


def test_concede_solo_reload_daemon():
    codice = "\n".join(_righe_di_codice())
    assert "org.freedesktop.systemd1.reload-daemon" in codice, (
        "la regola non nomina più `reload-daemon`: era la sola ragione per cui esiste."
    )
    for azione, cosa in _VIETATE.items():
        assert azione not in codice, (
            f"la regola concede anche `{azione}` ({cosa}).\n"
            f"Era stata scritta stretta di proposito: `reload-daemon` rilegge i file e "
            f"non avvia niente, le altre sì. Se serve davvero allargarla, la decisione "
            f"va motivata nella voce a329f659 — non fatta passare cambiando un test."
        )


def test_e_legata_all_utente_operatore_e_non_a_tutti():
    codice = "\n".join(_righe_di_codice())
    assert re.search(r"subject\.user\s*==", codice), (
        "la regola non vincola più `subject.user`: così vale per CHIUNQUE, che è "
        "esattamente il contrario del suo scopo."
    )
    assert "vps1777" in codice, (
        "l'utente non è più `vps1777` (OPERATOR_USER in installer/engine.py:30)"
    )


def test_non_richiede_una_sessione_locale_o_attiva():
    """Il timer gira SENZA sessione: una guardia su `subject.local`/`active` lo escluderebbe.

    È il difetto «la condizione esclude proprio il caso per cui la regola esiste» —
    e sarebbe invisibile, perché a mano (con una sessione viva) funzionerebbe.
    """
    codice = "\n".join(_righe_di_codice())
    for prop in ("subject.local", "subject.active"):
        assert prop not in codice, (
            f"la regola usa `{prop}`: il self-update automatico gira da un timer "
            f"systemd, SENZA sessione — la condizione lo escluderebbe, e il difetto si "
            f"vedrebbe solo in produzione perché a mano funziona."
        )
