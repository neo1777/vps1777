#!/usr/bin/env bash
# Le regole sudo dell'operatore (tools/sudoers-operatore.sh), provate DAVVERO: in un contenitore
# Debian 12 usa-e-getta si installano con --installa e si lancia la tabella «consentito / negato»
# come operatore. Non tocca la macchina su cui gira.
#
# Che cosa deve reggere:
#   1. con le regole installate: i 13 usi veri della CLI passano, i 19 abusi sono negati;
#   2. con la regola di prima (i tre binari, qualunque argomento) la tabella diventa ROSSA: è il
#      difetto, e prova che la tabella sa distinguere;
#   3. --installa toglie l'operatore dal gruppo sudo; con l'operatore nel gruppo la tabella si
#      rifiuta di misurare (esce 2) invece di dire «tutto consentito».
# Esce: 0 tutto regge · 1 qualcosa non regge · 2 non eseguito (docker assente): NON è un verde.
set -uo pipefail
QUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; STRUMENTI="$(cd "$QUI/.." && pwd)"
if ! command -v docker >/dev/null || ! docker info >/dev/null 2>&1; then
  echo "  ⊘ SALTATO — docker non c'è o non risponde (exit 2 = non eseguito, NON è un verde)"; exit 2
fi
# debian:12 fissata per impronta, come ogni immagine di terzi di questo repo
IMG="debian@sha256:268fb24c39bca92d326dd83ea3abebe4a3f7751c804ffef23bb6d857dd343ff8"
# SC2016: il testo fra apici singoli è lo script che gira DENTRO il contenitore: lì si espande
# shellcheck disable=SC2016
OUT="$(timeout 600 docker run --rm -v "$STRUMENTI:/t:ro" "$IMG" bash -c '
  apt-get update -qq >/dev/null 2>&1 && apt-get install -y -qq sudo systemd >/dev/null 2>&1 || { echo "ERRORE_APT"; exit 0; }
  useradd -m -u 1001 operatore && usermod -aG sudo operatore
  R=/home/operatore/vps1777
  echo "A nel gruppo sudo: $(su operatore -c "bash /t/sudoers-tabella.sh $R" >/dev/null 2>&1; echo $?)"
  bash /t/sudoers-operatore.sh --installa operatore $R | tail -1
  echo "B gruppi dopo: $(id -nG operatore)"
  su operatore -c "bash /t/sudoers-tabella.sh $R" > /tmp/nuova.log 2>&1; echo "C regole nuove: $? verdi=$(grep -c "✅" /tmp/nuova.log) rosse=$(grep -c "🔴" /tmp/nuova.log)"
  grep "🔴" /tmp/nuova.log
  printf "operatore ALL=(root) NOPASSWD: /usr/bin/install, /bin/install, /usr/bin/systemctl, /bin/systemctl, /usr/bin/chown, /bin/chown\n" > /etc/sudoers.d/90-operatore
  su operatore -c "bash /t/sudoers-tabella.sh $R" > /tmp/vecchia.log 2>&1; echo "D regola di prima: $? rosse=$(grep -c "🔴" /tmp/vecchia.log)"
  echo "E utente inesistente: $(bash /t/sudoers-operatore.sh --installa nessuno $R >/dev/null 2>&1; echo $?)"
' 2>&1)"
ESITO=0
ok() { printf '  ✓ %s\n' "$1"; }
ko() { printf '  ✗ %s\n' "$1"; ESITO=1; }
if grep -q "ERRORE_APT" <<<"$OUT"; then
  echo "  ⊘ SALTATO — il contenitore non ha potuto installare sudo (rete?): exit 2, NON è un verde"; exit 2
fi
atteso() { # $1 = espressione attesa nell'uscita, $2 = che cosa prova
  if grep -qE "$1" <<<"$OUT"; then ok "$2"; else ko "$2 — NON visto"; fi
}
atteso '^A nel gruppo sudo: 2$' "con l'operatore nel gruppo sudo la tabella si rifiuta di misurare (esce 2)"
atteso '^SUDOERS_ARGOMENTI_OK$' "--installa valida e installa le regole"
atteso '^B gruppi dopo: operatore$' "--installa toglie l'operatore dal gruppo sudo"
atteso '^C regole nuove: 0 verdi=32 rosse=0$' "regole nuove: 32 righe su 32 (13 usi veri consentiti, 19 abusi negati)"
atteso '^D regola di prima: 1 rosse=1[0-9]$' "con la regola di prima la tabella è rossa: sa distinguere"
atteso '^E utente inesistente: 2$' "--installa rifiuta un utente che non esiste"
[ "$ESITO" -eq 0 ] || printf '%s\n' "$OUT" | tail -30
exit "$ESITO"
