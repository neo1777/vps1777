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
# ## Perché una COPIA in `.git/hooks/` e non `core.hooksPath`
#
# 🔴 QUESTA È UNA RETTIFICA, e il motivo è misurato. La prima versione di questo file
#   usava `core.hooksPath = tools/hooks` e dichiarava che era «più forte, perché non
#   esiste una copia che possa divergere». **È vero su un repo con un solo working tree,
#   ed è falso qui.** Misurato il 10/08 prima di eseguire il gesto:
#
#       git worktree list        →  9 alberi
#       quanti hanno tools/hooks/ →  3
#
#   `core.hooksPath` relativo si risolve dalla radice di CIASCUN working tree: nei sei
#   che quella cartella non ce l'hanno — branch aperti prima che gli hook entrassero in
#   git — git avrebbe puntato a una directory inesistente. **Non un hook vecchio:
#   NESSUN hook**, e in silenzio. Fra quei sei c'era `fix/anti-leak-gate`, il branch che
#   lavora sul gate anti-leak, che sarebbe rimasto senza il gate anti-leak.
#
# 🔑 E il dato che decide, dall'altro lato:
#
#       cd <un worktree qualsiasi> && git rev-parse --git-path hooks
#         → /home/…/vps1777/.git/hooks        ← lo STESSO per tutti e 9
#
#   `.git/hooks/` è l'unico posto che ogni worktree vede, sempre, qualunque sia il suo
#   branch. La copia lì copre tutti; `core.hooksPath` copriva un terzo.
#
# ⭐ Il difetto della copia — disco e git che divergono in silenzio — resta vero, e non
#   si cura scegliendo l'altra strada: si cura MISURANDOLO. `--stato` confronta i due
#   file e stampa il diff. *Un rischio che uno strumento stampa non è più silenzioso, e
#   quello era l'unico argomento che avevo contro la copia.*
#
# USO:   bash tools/hooks/installa.sh            (dalla radice del repo)
#        bash tools/hooks/installa.sh --stato    dice com'è messo, non tocca niente
set -uo pipefail

RADICE="$(git rev-parse --show-toplevel 2>/dev/null)" || {
    echo "✗ non sono in un repository git" >&2; exit 2; }
cd "$RADICE" || exit 2
SORGENTE="tools/hooks"
# il posto CONDIVISO da ogni worktree: si chiede a git, che lo sa in entrambi i casi
# (in un worktree `.git` è un FILE e `ls .git/hooks` fallisce dicendo «(nessuno)» —
# cioè il contrario del vero, sull'unica riga per cui esiste la funzione `stato`).
DESTINAZIONE="$(git rev-parse --git-path hooks)"

# i nomi che git riconosce: tutto il resto in `tools/hooks/` è corredo (questo script).
# Enumerati e non dedotti per esclusione, così aggiungerne uno è una decisione scritta.
NOMI_HOOK="pre-commit pre-push commit-msg prepare-commit-msg post-commit post-merge"

hook_sorgente() {
    local n
    for n in $NOMI_HOOK; do
        [ -f "$SORGENTE/$n" ] && printf '%s\n' "$n"
    done
}

stato() {
    local n src dst hp
    echo "── hook di $(basename "$RADICE") ──"
    echo "  sorgente     : $SORGENTE  (versionata: $(git ls-files "$SORGENTE" | wc -l) file)"
    echo "  destinazione : $DESTINAZIONE  (condivisa da $(git worktree list | wc -l) worktree)"
    hp="$(git config --get core.hooksPath || true)"
    [ -n "$hp" ] && echo "  ⚠️ core.hooksPath = «$hp»: git NON userà $DESTINAZIONE."
    for n in $(hook_sorgente); do
        src="$SORGENTE/$n"; dst="$DESTINAZIONE/$n"
        if [ ! -f "$dst" ]; then
            echo "  ✗ $n — NON installato: quel presidio non gira su questa macchina"
        elif cmp -s "$src" "$dst"; then
            echo "  ✓ $n — installato e IDENTICO alla sorgente versionata"
        else
            # ⭐ il difetto della copia (disco e git che divergono in silenzio) non si
            #   cura scegliendo un'altra strada: si cura MISURANDOLO. Qui diventa un
            #   dato stampato, e un rischio stampato non è più silenzioso.
            echo "  ⚠️ $n — installato ma DIVERSO dalla sorgente. Il diff:"
            diff -u "$dst" "$src" | sed -n '3,12p' | sed 's/^/       /'
            echo "       (rilancia senza --stato per riallineare)"
        fi
    done
}

if [ "${1:-}" = "--stato" ]; then stato; exit 0; fi

# la guardia che serve davvero: non installare un hook che non gira. Un pre-commit con
# un errore di sintassi fallisce a OGNI commit, e l'unica via d'uscita che si trova è
# `--no-verify` per sempre — cioè il presidio spento invece che rotto.
for n in $(hook_sorgente); do
    if ! bash -n "$SORGENTE/$n" 2>/dev/null; then
        echo "✗ $SORGENTE/$n non è bash valido: non lo installo (girerebbe a ogni commit)" >&2
        exit 1
    fi
done

if [ -z "$(hook_sorgente)" ]; then
    echo "✗ nessun hook in $SORGENTE: non c'è niente da installare, e un'installazione" >&2
    echo "  che non installa niente non deve dire «fatto»." >&2
    exit 1
fi

mkdir -p "$DESTINAZIONE" || exit 1
for n in $(hook_sorgente); do
    # il backup si fa UNA volta e non si sovrascrive: al secondo giro conserverebbe la
    # copia già installata da noi invece di quella che c'era prima.
    if [ -f "$DESTINAZIONE/$n" ] && [ ! -f "$DESTINAZIONE/$n.pre-vps1777" ] \
       && ! cmp -s "$SORGENTE/$n" "$DESTINAZIONE/$n"; then
        cp "$DESTINAZIONE/$n" "$DESTINAZIONE/$n.pre-vps1777"
        echo "  ⓘ il $n precedente è in $n.pre-vps1777 (via d'uscita: rimettilo al suo posto)"
    fi
    cp "$SORGENTE/$n" "$DESTINAZIONE/$n" && chmod +x "$DESTINAZIONE/$n"
done
echo "✓ installato in $DESTINAZIONE — vale per tutti i worktree di questo repo."
stato
