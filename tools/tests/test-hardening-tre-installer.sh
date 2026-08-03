#!/usr/bin/env bash
# I TRE installer devono fare lo STESSO hardening host — e finora niente lo imponeva.
#
# Il difetto che questo test esiste per fermare non è ipotetico: è stato misurato
# QUATTRO volte sulla stessa riga di codice, ogni volta scoprendo che una copia
# faceva una cosa che le altre due no.
#   26/07  il blocco esisteva in deploy.sh e engine.py, NON in setup.sh
#   02/08  solo engine.py faceva `dpkg -s` prima di installare
#   03/08  solo engine.py scriveva /etc/apt/apt.conf.d/20auto-upgrades  ← questo
#
# ⭐ E il rilievo che ha chiuso il cerchio è ESTERNO, dall'audit del round-16:
#   «ci.yml nomina setup.sh/deploy.sh solo come perimetro di shellcheck — nessun job
#    li istanzia e compara». *Una regola che nessuno strumento impone è persa con la
#   faccia di essere al sicuro.* Le tre rettifiche della voce 55cc4f32 dicevano tutte
#   «serve una fonte di verità unica», e per una settimana nessuna l'ha scritta: il
#   presidio che manca non è la fonte unica, è QUALCOSA CHE SE NE ACCORGA.
#
# 🖐️ Questo test NON unifica le tre copie: verifica che siano d'accordo.
#   La fonte unica resta il fix strutturale giusto (voce 55cc4f32, progetto scritto
#   nelle sue rettifiche), e non è qui perché due dei tre installer mandano il blocco
#   dentro un heredoc QUOTATO via SSH (`deploy.sh:541 <<'PREP'`) o dentro bash
#   generato da Python: incorporarlo tocca il percorso critico dell'installazione,
#   che non è provabile senza una VPS viva. ⇒ prima il presidio, poi la struttura —
#   così quando la struttura arriva, c'è già chi verifica che non abbia rotto niente.
#
# Il blocco si LEGGE dai file al momento del test: una copia proverebbe se stessa.
# Uso:  bash tools/tests/test-hardening-tre-installer.sh
set -uo pipefail

RADICE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FALLITI=0
ESEGUITI=0

ok()   { printf 'ok   %s\n' "$1"; }
fail() { printf 'FAIL %s\n     %s\n' "$1" "$2"; FALLITI=$((FALLITI + 1)); }

# I tre installer, col nome con cui li chiama chi legge i rilievi.
INSTALLER=("setup.sh" "deploy.sh" "installer/engine.py")

# Le CAPACITÀ attese, non le righe: una regex sul testo esatto si romperebbe al primo
# refactoring e direbbe «divergono» quando sono solo scritte diverse. Qui si chiede
# «questo installer fa X?», e X è descritto da un pattern volutamente largo.
#
# ⚠️ `20auto-upgrades` è quella che mancava a due su tre, ed è la più insidiosa: senza
#   di lei unattended-upgrades resta ABILITATO e la sua cadenza dipende dal default
#   della distribuzione. Un servizio attivo e mai eseguito si legge come protezione.
CAPACITA=(
  "installa unattended-upgrades|unattended-upgrades"
  "installa fail2ban|fail2ban"
  "abilita unattended-upgrades|systemctl enable --now unattended-upgrades"
  "abilita fail2ban|systemctl enable --now fail2ban"
  "scrive la periodicità apt|20auto-upgrades"
)

for voce in "${CAPACITA[@]}"; do
  nome="${voce%%|*}"
  pat="${voce#*|}"
  mancanti=()
  for f in "${INSTALLER[@]}"; do
    percorso="$RADICE/$f"
    if [ ! -f "$percorso" ]; then
      # Un installer che non esiste non è «una capacità mancante»: è un test che sta
      # guardando un repo diverso da quello che crede. Va detto come tale.
      mancanti+=("$f(ASSENTE)")
    elif ! grep -qF -- "$pat" "$percorso"; then
      mancanti+=("$f")
    fi
  done
  ESEGUITI=$((ESEGUITI + 1))
  if [ ${#mancanti[@]} -eq 0 ]; then
    ok "tutti e ${#INSTALLER[@]} gli installer: $nome"
  else
    fail "$nome" "manca in: ${mancanti[*]} — le tre copie sono divergenti, ed è la classe che ha già colpito 4 volte (voce 55cc4f32)"
  fi
done

# ── E la prova che il test sa dire di NO ────────────────────────────────────────
# Un test che passa sempre è indistinguibile da un test che funziona, finché non
# serve. Qui si prova la POLARITÀ su una capacità inventata: se anche questa
# «passasse», il ciclo sopra non starebbe guardando niente.
ESEGUITI=$((ESEGUITI + 1))
_trovata=0
for f in "${INSTALLER[@]}"; do
  grep -qF -- "capacita-che-non-esiste-1777" "$RADICE/$f" 2>/dev/null && _trovata=1
done
if [ "$_trovata" -eq 0 ]; then
  ok "polarità: una capacità inventata NON viene trovata (il test sa dire di no)"
else
  fail "polarità" "una stringa inventata è stata trovata: il confronto non sta leggendo i file che crede"
fi

printf '\n%s test · %s falliti\n' "$ESEGUITI" "$FALLITI"
[ "$FALLITI" -eq 0 ] || exit 1
