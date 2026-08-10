#!/usr/bin/env bash
# installa.sh — punta git agli hook VERSIONATI di questo repo.
#
# 🔴 PERCHÉ ESISTE, e il caso è del 10/08/2026.
#
# Il `pre-commit` di questo repo — 205 righe, con dentro il **gate anti-leak** e
# **shellcheck** — viveva solo in `.git/hooks/`, che git non versiona. Nessuno script lo
# installava, nessun file del repo lo nominava. Misurato:
#
#     git config core.hooksPath                       → non impostato
#     grep -rl 'hooks/pre-commit|core.hooksPath' .    → niente
#
# Un `git clone` su un'altra macchina, o un reimage di questa, e quei presìdi non ci sono
# più — **senza che nessun file del repo cambi e senza che nessun test diventi rosso**.
# Il gate anti-leak è quello che quella mattina aveva bloccato un commit con indirizzi
# veri dentro i casi di test: non è un rischio teorico, è il controllo che ha già lavorato.
#
# ⭐ È la lezione del giorno applicata un livello sopra, ed è il motivo per cui nessuno
#    l'aveva vista: quella mattina avevamo scoperto due *strumenti* untracked e li avevamo
#    messi in git — «uno strumento che non è in git non esiste per chi rientra». Poi
#    abbiamo guardato gli strumenti e non **il file che li fa rispettare**.
#    *Il controllore dei presìdi non era presidiato.*
#
# ## Perché `core.hooksPath` e non una copia in `.git/hooks/`
#
# Copiare funziona, e introduce un modo di sbagliare che prima non c'era: la copia su
# disco e il file in git possono divergere in silenzio, e la divergenza non ha sintomi —
# è la stessa forma del difetto che questo file cura. Con `core.hooksPath` **non esiste
# una copia**: git esegue il file versionato, e ciò che leggi in una PR è ciò che gira.
# Il prezzo è che la config è per-clone e va data una volta: è questo script.
#
# USO:   bash tools/hooks/installa.sh            (dalla radice del repo)
#        bash tools/hooks/installa.sh --stato    dice com'è messo, non tocca niente
#
# ⚠️ Su un albero CONDIVISO fra più sessioni, `core.hooksPath` è config del repository:
#    cambia il comportamento di tutti i worktree nello stesso istante. Lo script lo
#    DICE prima di scrivere, invece di lasciartelo scoprire dal primo commit di un'altra.
set -uo pipefail

RADICE="$(git rev-parse --show-toplevel 2>/dev/null)" || {
    echo "✗ non sono in un repository git" >&2; exit 2; }
cd "$RADICE" || exit 2
ATTESO="tools/hooks"
ATTUALE="$(git config --get core.hooksPath || true)"

stato() {
    echo "── hook di $(basename "$RADICE") ──"
    echo "  core.hooksPath : ${ATTUALE:-(non impostato → .git/hooks)}"
    echo "  versionati     : $(git ls-files "$ATTESO" | tr '\n' ' ')"
    # 🔴 `ls .git/hooks/` NON funziona in un worktree: lì `.git` è un FILE che punta
    #   altrove, e il comando fallisce in silenzio dicendo «(nessuno)» — cioè
    #   esattamente il contrario del vero, sull'unica riga per cui esiste questa
    #   funzione. Trovato provando questo script in un worktree, il 10/08.
    #   ⇒ il path degli hook si CHIEDE a git, che sa dove sono in entrambi i casi.
    local dir_hook vecchi f
    dir_hook="$(git rev-parse --git-path hooks)"
    # glob e non `ls | grep` (SC2010, segnalato dal pre-commit stesso mentre lo
    # committavo): con un nome di file che contiene uno spazio, `ls` lo spezza.
    vecchi=""
    for f in "$dir_hook"/*; do
        [ -f "$f" ] || continue
        case "$f" in *.sample) continue;; esac
        vecchi="$vecchi$(basename "$f") "
    done
    echo "  in $dir_hook : ${vecchi:-(nessuno)}"
    if [ "$ATTUALE" = "$ATTESO" ]; then
        echo "  ✓ git esegue gli hook VERSIONATI: ciò che leggi in una PR è ciò che gira"
        [ -n "$vecchi" ] && echo "    ⓘ i file in .git/hooks non vengono più eseguiti: sono residui," \
                                 "non un secondo presidio. Toglili quando hai verificato."
    else
        echo "  ⚠️ git esegue .git/hooks/, che NON è versionato: su un altro clone quei"
        echo "     presìdi non esistono, e nessun file del repo lo direbbe."
    fi
}

if [ "${1:-}" = "--stato" ]; then stato; exit 0; fi

# la guardia che serve davvero: non installare un hook che non gira. Un pre-commit
# con un errore di sintassi fallisce a OGNI commit, e l'unica via d'uscita che la gente
# trova è `--no-verify` per sempre — cioè il presidio spento invece che rotto.
for h in "$ATTESO"/*; do
    case "$h" in *.sh) continue;; esac       # installa.sh non è un hook
    [ -f "$h" ] || continue
    if ! bash -n "$h" 2>/dev/null; then
        echo "✗ $h non è bash valido: non lo installo (girerebbe a ogni commit)" >&2
        exit 1
    fi
    [ -x "$h" ] || chmod +x "$h"
done

if [ "$ATTUALE" = "$ATTESO" ]; then
    echo "già installato — niente da fare."; stato; exit 0
fi

if [ -n "$ATTUALE" ]; then
    echo "⚠️ core.hooksPath è già «$ATTUALE» e sto per cambiarlo in «$ATTESO»." >&2
fi
echo "ⓘ core.hooksPath è config del REPOSITORY: se questo albero è condiviso"
echo "  (worktree, più sessioni), la modifica vale per tutti nello stesso istante."
git config core.hooksPath "$ATTESO" || exit 1
ATTUALE="$ATTESO"
echo "✓ installato."
stato
