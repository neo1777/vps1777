#!/usr/bin/env python3
"""Ogni comando che la CLI esegue via `sudo -n` deve essere concesso dall'installer.

PERCHÉ ESISTE, per intero — serve a chi lo vedrà fallire.

Le unit del canale update girano come l'utente operatore e chiamano `tools/vps1777.py`,
che per i gesti da root usa una sola porta:

    def sudo(cmd, **kw):                                      # tools/vps1777.py:269-272
        # -n: mai prompt interattivo (l'utente operatore ha NOPASSWD; se non ce
        # l'ha meglio fallire subito che restare appesi in una unit systemd).
        return run(["sudo", "-n", *cmd], **kw)

`-n` significa **niente prompt**: se il comando non è in una regola NOPASSWD, `sudo`
esce ≠0 e la unit fallisce. Ed è per questo che `vps1777-update.service` e
`vps1777-auto-update.service` dichiarano `NoNewPrivileges=no` *apposta*: devono elevare.

## I due insiemi che devono combaciare

    RICHIESTI   i comandi passati a sudo() nella CLI          install · systemctl · chown
    CONCESSI    la whitelist che l'installer scrive in         deploy.sh:618
                /etc/sudoers.d/90-<operator>                   installer/engine.py:338
                    for _b in install systemctl chown; do …

Oggi combaciano. Nessuno strumento lo teneva vero: sono due liste in tre file diversi,
e chi domani aggiunge `sudo(["mount", …])` alla CLI non ha niente che gli ricordi la
whitelist. Il difetto arriverebbe **in produzione dentro una unit systemd**, cioè nel
posto dove nessuno lo guarda: un timer che fallisce di notte e un log che nessuno apre.

## L'eccezione, e perché è NOMINATA e non tolta

`setup.sh` **non scrive nessuna whitelist** — non crea l'utente operatore, usa quello
corrente. È una scelta del wizard, non una dimenticanza: chi lo esegue è già l'utente
che possiederà il repo. Ma la conseguenza va detta, perché è la stessa forma già pagata
in H45 («hardening host automatico all'install era falso per setup.sh: presente in
deploy.sh e engine.py, assente nel wizard»): *quello che due installer su tre fanno,
il terzo non lo fa, e la garanzia scritta vale per tutti e tre.*

⚠️ Questo test NON dice che l'auto-update installato via `setup.sh` sia rotto: non lo ha
misurato nessuno su una macchina viva. Dice che **la sua autorizzazione non è scritta da
nessuna parte** — e che se un giorno fallirà, fallirà così.

Stile: stdlib-only, legge i sorgenti (nessun sudo, nessuna macchina da installare).
Uso:  python3 tools/tests/test_sudo_whitelist_copre_la_cli.py     (esce 1 al primo difetto)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "tools/vps1777.py"

# Gli installer che SCRIVONO una whitelist sudoers, e dove.
CON_WHITELIST = {
    "deploy.sh": ROOT / "deploy.sh",
    "installer/engine.py": ROOT / "installer/engine.py",
}

# L'eccezione, nominata: installer → (ragione, conseguenza dichiarata).
# Aggiungerne una significa modificare questa riga, cioè dichiararla per iscritto.
SENZA_WHITELIST = {
    "setup.sh": (
        "wizard sull'host: non crea l'utente operatore, usa quello corrente",
        "l'autorizzazione dei gesti che le unit faranno non è scritta da nessuna parte",
    ),
}


def comandi_richiesti(src: str) -> set[str]:
    """I comandi passati a `sudo([...])` nella CLI — il primo elemento della lista."""
    return set(re.findall(r'sudo\(\[\s*"([a-z0-9_/-]+)"', src))


def comandi_concessi(src: str) -> set[str]:
    """La whitelist: `for _b in install systemctl chown; do`."""
    m = re.search(r"for\s+_b\s+in\s+([a-z0-9_ -]+);\s*do", src)
    return set(m.group(1).split()) if m else set()


def main() -> int:
    if not CLI.is_file():
        print("✗ tools/vps1777.py non trovato: la sonda non sta guardando il repo giusto")
        return 1

    richiesti = comandi_richiesti(CLI.read_text(encoding="utf-8"))
    if not richiesti:
        # Un insieme vuoto qui NON è un verde: o la CLI non usa più sudo (allora questo
        # test è senza oggetto e va tolto), o la forma della chiamata è cambiata e la
        # regex non la riconosce più — e in quel caso il test tacerebbe su tutto.
        print("✗ nessun `sudo([...])` riconosciuto in tools/vps1777.py.\n"
              "      O la CLI non eleva più (togli questo test), o la forma è cambiata\n"
              "      e la regex non la vede: NON è un verde, è una sonda cieca.")
        return 1
    print(f"la CLI chiede via sudo -n: {', '.join(sorted(richiesti))}")

    errori = 0
    for nome, path in CON_WHITELIST.items():
        if not path.is_file():
            errori += 1
            print(f"  ✗ {nome} non trovato")
            continue
        concessi = comandi_concessi(path.read_text(encoding="utf-8"))
        if not concessi:
            errori += 1
            print(f"  ✗ {nome}: non riconosco più la whitelist sudoers.\n"
                  f"      Cercavo `for _b in … ; do`. Se l'hai riscritta, aggiorna questo\n"
                  f"      test: così com'è non sa dire se sei coperto, e NON è un verde.")
            continue
        mancanti = richiesti - concessi
        if mancanti:
            errori += 1
            print(f"  ✗ {nome}: la CLI chiede {sorted(mancanti)} e la whitelist non li concede.\n"
                  f"      `sudo -n` non chiede la password: esce ≠0 e la unit systemd fallisce,\n"
                  f"      di notte, in un log che nessuno apre. Aggiungili alla riga `for _b in`.")
        else:
            print(f"  ✓ {nome}: concede {sorted(concessi)} ⊇ quanto la CLI chiede")

    for nome, (ragione, conseguenza) in SENZA_WHITELIST.items():
        path = ROOT / nome
        if not path.is_file():
            continue
        if comandi_concessi(path.read_text(encoding="utf-8")):
            errori += 1
            print(f"  ✗ {nome} ORA scrive una whitelist, ma è fra gli installer che\n"
                  f"      dichiarano di non averne. Togli l'eccezione e verificala come gli altri.")
        else:
            print(f"  ⚪ {nome}: nessuna whitelist — eccezione nominata ({ragione}).\n"
                  f"      Conseguenza dichiarata: {conseguenza}.")

    return 1 if errori else 0


if __name__ == "__main__":
    sys.exit(main())
