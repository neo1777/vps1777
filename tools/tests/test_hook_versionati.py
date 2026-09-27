#!/usr/bin/env python3
"""Gli hook git di questo repo stanno IN GIT, e sono eseguibili — non solo presenti.

PERCHÉ ESISTE, per intero — serve a chi lo vedrà fallire.

Il 10/08/2026 il `pre-commit` di questo repo erano 205 righe con dentro il **gate
anti-leak** e **shellcheck**, e viveva soltanto in `.git/hooks/`, che git non versiona.
Nessuno script lo installava, nessun file del repo lo nominava:

    git config core.hooksPath                       → non impostato
    grep -rl 'hooks/pre-commit|core.hooksPath' .    → niente

Un `git clone` su un'altra macchina, o un reimage di quella, e i presìdi sparivano —
**senza che nessun file del repo cambiasse e senza che nessun test diventasse rosso**.
Il gate anti-leak è quello che quella stessa mattina aveva bloccato un commit con
indirizzi veri nei casi di test: non era un rischio ipotetico, era un controllo che aveva
già lavorato.

⭐ È la lezione del giorno un livello sopra, ed è per questo che nessuno l'aveva vista:
   la mattina avevamo trovato due *strumenti* untracked e li avevamo messi in git — «uno
   strumento che non è in git non esiste per chi rientra» — poi abbiamo guardato gli
   strumenti e non **il file che li fa rispettare**. *Il controllore non era presidiato.*

## Cosa misura, e cosa deliberatamente NON misura

Misura che gli hook siano **versionati, sintatticamente validi e col bit di esecuzione**:
un hook non eseguibile git lo salta **in silenzio**, che è il modo peggiore di non avere
un presidio — sembra installato.

NON misura che siano ATTIVI su questa macchina: l'installazione (`tools/hooks/installa.sh`
copia gli hook in `.git/hooks`, dalla v2, e toglie `core.hooksPath` se c'era) è uno stato
locale per-clone, e in CI non c'è alcun clone da configurare. Un test che pretendesse
l'attivazione sarebbe rosso in CI per sempre, cioè spento. *Il confine fra ciò che sta
nel repo e ciò che sta nella macchina è reale, e questo file sta di qua* — di là ci pensa
`tools/hooks/installa.sh --stato`, che lo dice a chi ha la macchina davanti.

Stile: stdlib-only, nessuna dipendenza.
Uso:  python3 tools/tests/test_hook_versionati.py      (esce 1 al primo difetto)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "tools" / "hooks"

# I nomi che git riconosce come hook: tutto il resto in quella cartella è corredo
# (l'installatore). Enumerati invece che dedotti per esclusione, così aggiungerne uno
# è una decisione scritta e non un effetto collaterale di un nome di file.
NOMI_HOOK = {
    "pre-commit", "pre-push", "commit-msg", "prepare-commit-msg",
    "post-commit", "post-merge", "pre-rebase", "post-checkout",
}


def hook_versionati() -> list[Path]:
    return sorted(p for p in HOOKS.glob("*") if p.is_file() and p.name in NOMI_HOOK)


def main() -> int:
    print(f"hook versionati in {HOOKS.relative_to(ROOT)} · radice: {ROOT}")
    if not HOOKS.is_dir():
        print("  ✗ la cartella non esiste: gli hook non sono nel repo, e su un clone\n"
              "      nuovo il gate anti-leak e shellcheck semplicemente non ci sono.")
        return 1

    hook = hook_versionati()
    if not hook:
        # la guardia della guardia: senza, questo test passerebbe a mani vuote — ed è la
        # forma «il presidio non trova il bersaglio e tace» che il repo ha già pagato.
        print("  ✗ nessun hook trovato. Se sono stati rimossi di proposito, va tolto\n"
              "      anche questo test: un presidio che sorveglia il vuoto è rumore.")
        return 1

    errori = 0
    for h in hook:
        rel = h.relative_to(ROOT)

        # ① versionato DAVVERO: esistere sul disco non basta — è esattamente l'errore
        #    che ha generato questo file (un `pre-commit` c'era, e non era in git).
        tracciato = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "--error-unmatch", str(rel)],
            capture_output=True, text=True, check=False).returncode == 0
        if not tracciato:
            errori += 1
            print(f"  ✗ {rel}: sul disco ma NON in git. È il difetto originale,\n"
                  f"      rifatto dentro la cartella che lo cura.")
            continue

        # ② eseguibile: git salta un hook senza bit x SENZA DIRE NIENTE.
        if not os.access(h, os.X_OK):
            errori += 1
            print(f"  ✗ {rel}: manca il bit di esecuzione. git lo salterebbe in\n"
                  f"      silenzio — un presidio che sembra installato e non gira.\n"
                  f"      Cura: chmod +x {rel} && git update-index --chmod=+x {rel}")
            continue

        # ③ bash valido: un hook rotto fallisce a OGNI commit, e l'unica via d'uscita
        #    che si trova è `--no-verify` per sempre — il presidio spento, non rotto.
        r = subprocess.run(["bash", "-n", str(h)], capture_output=True, text=True, check=False)
        if r.returncode != 0:
            errori += 1
            print(f"  ✗ {rel}: non è bash valido ({r.stderr.strip().splitlines()[:1]}).\n"
                  f"      Girerebbe a ogni commit e insegnerebbe a usare --no-verify.")
            continue

        print(f"  ✓ {rel} — in git, eseguibile, sintassi valida")

    # ④ l'installatore deve esserci: senza, gli hook sono versionati e nessuno sa come
    #    attivarli, che è metà del difetto originale (il file c'era, il modo no).
    inst = HOOKS / "installa.sh"
    if not inst.is_file():
        errori += 1
        print(f"  ✗ manca {inst.relative_to(ROOT)}: gli hook sono nel repo ma nessun\n"
              f"      file dice come si attivano. «Versionato» non è «in vigore».")
    else:
        print(f"  ✓ {inst.relative_to(ROOT)} — l'attivazione è scritta, non tramandata")

    return 1 if errori else 0


def test_gli_hook_sono_versionati_ed_eseguibili() -> None:
    """Il gancio che rende questo file un test PER PYTEST, non solo per la mano.

    Senza, `uvx pytest tools/tests/` RACCOGLIE il file (il nome combacia) e non esegue
    niente: nessuna funzione `test_*`, nessun errore, verde.
    """
    assert main() == 0


def _ci() -> str:
    return (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def test_installatore_e_test_riconoscono_gli_stessi_hook() -> None:
    """Audit della doc (27/09): il test ne riconosceva 8, l'installatore 6. Un
    `pre-rebase` versionato passava qui e non veniva installato."""
    import re
    testo = (HOOKS / "installa.sh").read_text(encoding="utf-8")
    m = re.search(r'^NOMI_HOOK="([^"]+)"', testo, re.M)
    assert m, "NOMI_HOOK non trovato in installa.sh"
    assert set(m.group(1).split()) == NOMI_HOOK


def test_il_pre_commit_usa_gli_strumenti_della_ci() -> None:
    """Il pre-commit anticipa il verdetto della CI: se usa un'altra versione dello
    strumento, anticipa un altro verdetto (è l'incidente raccontato in ci.yml per
    shellcheck, 0.9.0 contro 0.11.0). Stessa versione di ruff, stesso digest di
    shellcheck."""
    import re
    hook = (HOOKS / "pre-commit").read_text(encoding="utf-8")
    ci = _ci()
    ruff_ci = re.search(r"ruff==([0-9.]+)", ci).group(1)
    assert f"ruff@{ruff_ci}" in hook, f"il pre-commit non usa ruff {ruff_ci} come la CI"
    sc_ci = re.search(r"koalaman/shellcheck@(sha256:[0-9a-f]{64})", ci).group(1)
    assert sc_ci in hook, "il pre-commit non usa lo shellcheck della CI (digest)"
    assert "shellcheck:stable" not in hook


def test_il_pre_commit_non_dice_di_non_bloccare_mai() -> None:
    """L'intestazione diceva «Non blocca mai» e il corpo blocca su tre gate: chi legge
    l'intestazione per sapere cosa aspettarsi riceveva il contrario (rilievo di Sagoma,
    27/09)."""
    testa = "\n".join((HOOKS / "pre-commit").read_text(encoding="utf-8").splitlines()[:5])
    assert "Non blocca mai" not in testa


if __name__ == "__main__":
    sys.exit(main())
