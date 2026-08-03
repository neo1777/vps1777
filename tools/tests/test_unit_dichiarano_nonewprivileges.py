"""Ogni unit systemd DICHIARA `NoNewPrivileges`. Ometterlo non è una scelta.

🔓 PERCHÉ ESISTE — un guasto vero, non un'ipotesi. Il 03/08 alle 04:32 l'auto-update
   della VPS è fallito:

       sudo: The "no new privileges" flag is set, which prevents sudo from
       running as root.

   `vps1777-auto-update.service` NON impostava `NoNewPrivileges`. L'intenzione era
   scritta nel commento in testa al file — «Perciò NIENTE NoNewPrivileges
   (romperebbe sudo/setuid)» — ed era **giusta**. È stata realizzata **togliendo la
   riga**, e systemd ha riempito lo spazio da sé: con un filtro seccomp
   (`ProtectKernelModules`, `LockPersonality`, `RestrictRealtime`…) su un servizio
   che gira come utente NON privilegiato, `NoNewPrivileges` si accende di
   conseguenza. Nessuno l'aveva impostato.

   📏 Misurato con unit transitorie sulla VPS:
       le sei direttive, come root             -> NoNewPrivs: 0
       le sei + User=<operator> (la unit vera) -> NoNewPrivs: 1
       solo User=<operator>, senza hardening   -> NoNewPrivs: 0
     => né l'hardening da solo né l'utente da solo: la COMBINAZIONE.

   ⚠️ E `systemctl show -p NoNewPrivileges` rispondeva `no` mentre il processo aveva
   `1`: riporta il valore DICHIARATO, non l'effettivo. Due fonti (il commento e
   `systemctl show`) concordavano ed erano fuorvianti; l'unica vera era lo stderr di
   sudo. *Su una proprietà di runtime il verdetto sta nel processo.*

🔑 LA REGOLA CHE QUESTO TEST IMPONE, e non è sul VALORE:
   `NoNewPrivileges=true` va benissimo dove non serve sudo (`check-update`,
   `secrets-check` ce l'hanno, con la ragione accanto). `=no` va benissimo dove
   serve. **Ciò che non va bene è l'ASSENZA**, perché l'assenza si legge come «non
   ci interessa» mentre significa «decide systemd».
   ⇒ questo test non giudica la scelta: chiede che ce ne sia una, scritta.

⚠️ COSA NON FA: non verifica il valore EFFETTIVO su una macchina viva — qui non c'è
   una macchina. Verifica che la unit dica la sua. La misura sul vivo resta
   `grep NoNewPrivs /proc/<pid>/status`, e nessun test statico può sostituirla.
"""

from __future__ import annotations

from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parents[2]
UNIT_DIR = RADICE / "systemd"


def solo_codice(testo: str) -> str:
    """Le righe che systemd esegue — i commenti no.

    ⚠️ Serve davvero: «NoNewPrivileges» compare NEL COMMENTO in testa alle unit che
    l'hanno omesso, per dire che non lo si vuole. Uno script che cerca la stringa nel
    file intero lo trova lì e conclude che c'è. È successo mentre scrivevo questo
    fix, alla prima esecuzione — e la stessa cecità era stata trovata oggi in due
    presidi diversi del repo: *la cura, spiegandosi, scrive la stringa che il
    controllo cerca.*
    """
    return "\n".join(r for r in testo.splitlines() if not r.lstrip().startswith("#"))


def unit_di_servizio() -> list[Path]:
    return sorted(p for p in UNIT_DIR.glob("*.service"))


def test_ci_sono_unit_da_controllare() -> None:
    """Zero unit non è un verde: vorrebbe dire che questo test guarda altrove."""
    assert unit_di_servizio(), (
        f"nessun *.service in {UNIT_DIR} — questo test non ha guardato niente, "
        "e un ciclo su zero elementi passa in silenzio"
    )


@pytest.mark.parametrize("unit", unit_di_servizio(), ids=lambda p: p.name)
def test_ogni_unit_DICHIARA_nonewprivileges(unit: Path) -> None:
    codice = solo_codice(unit.read_text(encoding="utf-8"))
    righe = [r.strip() for r in codice.splitlines() if r.strip().startswith("NoNewPrivileges")]
    assert righe, (
        f"{unit.name} non dichiara NoNewPrivileges.\n"
        "  Non è un dettaglio di stile: con un filtro seccomp e User= non-root "
        "systemd lo accende da sé, e `sudo` smette di funzionare — è così che si è "
        "rotto l'auto-update il 03/08.\n"
        "  Scrivi `NoNewPrivileges=true` se il servizio non ha bisogno di elevare, "
        "`=no` se usa sudo. Con la ragione accanto, come fanno le altre unit."
    )


@pytest.mark.parametrize("unit", unit_di_servizio(), ids=lambda p: p.name)
def test_la_dichiarazione_ha_una_RAGIONE_accanto(unit: Path) -> None:
    """Un flag di sicurezza senza il perché è una riga che il prossimo toglie.

    Cerca un commento nelle 25 righe che precedono la direttiva: è la forma che le
    unit già usano ("Il check non ha bisogno di privilegi: niente sudo").
    """
    righe = unit.read_text(encoding="utf-8").splitlines()
    idx = [i for i, r in enumerate(righe)
           if r.strip().startswith("NoNewPrivileges") and not r.lstrip().startswith("#")]
    if not idx:
        pytest.skip("assenza già coperta dal test qui sopra — qui non aggiungerei nulla")
    i = idx[0]
    contesto = righe[max(0, i - 25):i]
    assert any(r.lstrip().startswith("#") and len(r.strip()) > 12 for r in contesto), (
        f"{unit.name}: NoNewPrivileges è dichiarato ma senza una ragione scritta sopra.\n"
        "  Un flag di sicurezza nudo è una riga che il prossimo toglie «per pulizia»."
    )


# ── ② E IL PRESIDIO QUI SOPRA NON PRENDE IL GUASTO. Provato, non temuto. ─────────────
#
# Il test precedente chiede che `NoNewPrivileges` sia DICHIARATO. È nato dalla prima
# diagnosi — «la riga manca» — e quella diagnosi era **incompleta**: la cura scritta su
# quella base (`NoNewPrivileges=no`, PR #101) è finita in `main` e **non ha riparato
# niente**. La riga da sola non vince sull'implicazione.
#
# 📏 LA MISURA CHE LO DIMOSTRA, fatta il 03/08 su questo stesso file di test:
#     le unit di `origin/main` (curate)            -> 11 passed
#     la unit di 37bf7d5^ — quella con cui l'auto-update  -> 11 passed   🔴
#     è FALLITO DAVVERO sulla macchina (User= non-root
#     + le sei direttive + NoNewPrivileges=no)
#   => il presidio dà VERDE su una unit rotta. Non è un'ipotesi: quello stato è
#      esistito, in produzione, e questo test l'avrebbe lasciato passare.
#
# 🔑 PERCHÉ SUCCEDE, ed è la forma generale: **un presidio nasce tarato sulla diagnosi
#   del momento, e resta tarato su quella anche quando la diagnosi viene corretta.**
#   La diagnosi vera (misurata sulla VPS, vedi il commento in testa) è che a rompere è
#   la COMBINAZIONE: `User=` non-root + una direttiva che tira dentro seccomp. Nessuna
#   delle due da sola.
#
# ⚠️ PERCHÉ UN'ALLOWLIST VUOTA E NON UN ELENCO DI DIRETTIVE VIETATE. L'elenco di ciò
#   che systemd implica non è nella `man systemd.exec` di questa macchina (verificato:
#   documenta l'implicazione solo per `DynamicUser=`), e la prova sulla VPS ha misurato
#   le SEI insieme — non sappiamo quale delle sei lo accenda, né se ce ne siano altre.
#   ⇒ Su una unit che dichiara di dover ELEVARE non si indovina cosa è innocuo: si
#   vieta tutto il sandboxing e si dichiara ciò che è stato PROVATO innocuo. Fail-closed,
#   come `_CHIAVI_NOTE` in `audit.py`. Oggi la lista dei provati è **vuota**, e le due
#   unit che elevano non hanno nessuna direttiva: il test non ha falsi positivi da curare.
#
# ⚠️ COSA NON FA: non sa se una unit usa `sudo`. Si fida di ciò che la unit DICHIARA —
#   `NoNewPrivileges=no` è la dichiarazione «io devo elevare». Una unit che usa sudo e
#   scrive `=true` resta rotta e questo test tace: quel caso lo prende solo la macchina
#   (`prova-8`, e `grep NoNewPrivs /proc/<pid>/status`).

# Prefissi delle direttive di sandboxing di systemd. Non è l'elenco di ciò che implica
# NoNewPrivileges — è più largo di proposito: su una unit che eleva, tutto ciò che
# somiglia a sandboxing va guardato da una persona prima di entrare.
_PREFISSI_SANDBOX = (
    "Protect", "Restrict", "Lock", "Private", "Memory", "System", "Capability",
    "RemoveIPC", "DynamicUser", "AmbientCapabilities",
)

# Direttive PROVATE innocue su una unit che eleva: si aggiunge qui SOLO dopo aver
# misurato `NoNewPrivs` in `/proc/<pid>/status` con la direttiva attiva. Vuota non è
# una svista: è lo stato di `main` dopo la #104.
SANDBOX_PROVATE_INNOCUE: frozenset[str] = frozenset()


def _direttive_attive(testo: str) -> list[tuple[str, str]]:
    """(nome, riga) delle direttive che systemd esegue. I commenti no — vedi sopra."""
    out = []
    for r in solo_codice(testo).splitlines():
        r = r.strip()
        if "=" in r and r[:1].isalpha():
            out.append((r.split("=", 1)[0].strip(), r))
    return out


def _dichiara_di_elevare(testo: str) -> bool:
    for nome, riga in _direttive_attive(testo):
        if nome == "NoNewPrivileges":
            return riga.split("=", 1)[1].strip().lower() in ("no", "false", "off", "0")
    return False


@pytest.mark.parametrize("unit", unit_di_servizio(), ids=lambda p: p.name)
def test_le_unit_che_elevano_non_portano_sandbox(unit: Path) -> None:
    testo = unit.read_text(encoding="utf-8")
    if not _dichiara_di_elevare(testo):
        pytest.skip("non dichiara NoNewPrivileges=no: qui non è in gioco")
    colpevoli = [
        riga for nome, riga in _direttive_attive(testo)
        if nome.startswith(_PREFISSI_SANDBOX)
        and nome != "NoNewPrivileges"
        and nome not in SANDBOX_PROVATE_INNOCUE
    ]
    assert not colpevoli, (
        f"{unit.name} dichiara `NoNewPrivileges=no` (deve elevare: usa sudo) e insieme "
        f"{len(colpevoli)} direttive di sandboxing:\n"
        + "".join(f"    {r}\n" for r in colpevoli)
        + "  Con `User=` non-root queste RIACCENDONO NoNewPrivileges da sé, e `=no` non\n"
        "  vince: è così che l'auto-update è morto il 03/08 alle 04:32, con la riga\n"
        "  `NoNewPrivileges=no` già presente nel file.\n"
        "  Se una di queste è stata PROVATA innocua (NoNewPrivs=0 in /proc/<pid>/status\n"
        "  con la direttiva attiva), aggiungila a SANDBOX_PROVATE_INNOCUE con la misura."
    )


def test_questo_test_guarda_almeno_una_unit_che_eleva() -> None:
    """Se nessuna unit dichiara `=no`, sopra è tutto skip e il verde non copre niente.

    È il gemello di `test_ci_sono_unit_da_controllare`: lì zero unit, qui zero unit
    IN GIOCO. Un parametrize che salta tutto ha lo stesso colore di uno che passa.
    """
    che_elevano = [u.name for u in unit_di_servizio()
                   if _dichiara_di_elevare(u.read_text(encoding="utf-8"))]
    assert che_elevano, (
        "nessuna unit dichiara NoNewPrivileges=no: il test qui sopra ha saltato tutto.\n"
        "  Se è cambiato per davvero (nessun servizio eleva più) togli questo blocco; "
        "se invece è cambiata la forma della dichiarazione, il presidio è cieco."
    )
