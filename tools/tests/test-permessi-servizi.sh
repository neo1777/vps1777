#!/usr/bin/env bash
# tools/permessi-servizi.sh provato DAVVERO: in un contenitore Debian usa-e-getta si ricrea la
# macchina dove l'uid 1000 è già di un altro utente (H102), e si guarda chi legge che cosa.
# Non tocca la macchina su cui gira.
#
# Che cosa deve reggere:
#   A. prima della cura un processo con uid 1000 NON legge i segreti dell'operatore (è il difetto);
#   B. dopo la cura li legge, e scrive in onboarding/; un terzo utente continua a non leggerli;
#   C. un segreto riscritto a 600 (come fa la rotazione) torna leggibile rilanciando lo strumento;
#   D. lanciato da root fa lo stesso lavoro (setup.sh e l'installatore grafico lo lanciano così);
#   E. con l'operatore a uid 1000 non cambia NIENTE: i permessi restano 600 e 700;
#   F. se l'operatore non è nel gruppo 1000 esce 3 e dice la cura, non fa finta.
# Esce: 0 tutto regge · 1 qualcosa non regge · 2 non eseguito (docker assente): NON è un verde.
set -uo pipefail
QUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; STRUMENTI="$(cd "$QUI/.." && pwd)"
if ! command -v docker >/dev/null || ! docker info >/dev/null 2>&1; then
  echo "  ⊘ SALTATO — docker non c'è o non risponde (exit 2 = non eseguito, NON è un verde)"; exit 2
fi
IMG="debian@sha256:268fb24c39bca92d326dd83ea3abebe4a3f7751c804ffef23bb6d857dd343ff8"
# SC2016: il testo fra apici singoli è lo script che gira DENTRO il contenitore: lì si espande
# shellcheck disable=SC2016
OUT="$(timeout 300 docker run --rm --network none -v "$STRUMENTI:/t:ro" "$IMG" bash -c '
  prepara() {   # $1 = utente proprietario: una cartella del prodotto coi permessi che mette l installatore
    R=/home/$1/vps1777; rm -rf $R; mkdir -p $R/secrets $R/onboarding
    printf segreto > $R/secrets/gateway_secret.txt; printf x > $R/onboarding/update_status.json
    chmod 600 $R/secrets/*.txt; chmod 700 $R/secrets $R/onboarding; chown -R $1:$1 /home/$1
  }
  legge() { su "$1" -c "cat $R/secrets/gateway_secret.txt" >/dev/null 2>&1 && echo si || echo no; }
  useradd -m -u 1000 predefinito; useradd -m -u 1001 operatore; useradd -m -u 1002 terzo
  prepara operatore
  echo "A prima della cura, uid 1000 legge: $(legge predefinito)"
  echo "F fuori dal gruppo: $(su operatore -c "bash /t/permessi-servizi.sh $R" >/dev/null 2>&1; echo $?)"
  usermod -aG predefinito operatore
  echo "B esito: $(su operatore -c "bash /t/permessi-servizi.sh $R" 2>&1; echo $?)"
  echo "B uid 1000 legge: $(legge predefinito) · terzo legge: $(legge terzo)"
  echo "B uid 1000 scrive in onboarding: $(su predefinito -c "touch $R/onboarding/pending.json" 2>/dev/null && echo si || echo no)"
  echo "B operatore toglie ciò che il servizio ha scritto: $(su operatore -c "rm $R/onboarding/pending.json" 2>/dev/null && echo si || echo no)"
  echo "B permessi: $(stat -c %a $R/secrets) $(stat -c %a $R/secrets/gateway_secret.txt) $(stat -c %a $R/onboarding)"
  su operatore -c "printf nuovo > $R/secrets/gateway_secret.txt; chmod 600 $R/secrets/gateway_secret.txt"
  echo "C dopo una rotazione: $(legge predefinito) · rilanciato: $(su operatore -c "bash /t/permessi-servizi.sh $R"; legge predefinito)"
  prepara operatore
  echo "D da root: $(bash /t/permessi-servizi.sh $R; echo $?) · uid 1000 legge: $(legge predefinito)"
  userdel -r predefinito 2>/dev/null; userdel -r operatore 2>/dev/null; useradd -m -u 1000 operatore
  prepara operatore
  echo "E esito: $(su operatore -c "bash /t/permessi-servizi.sh $R"; echo $?) · permessi: $(stat -c %a $R/secrets) $(stat -c %a $R/secrets/gateway_secret.txt) $(stat -c %a $R/onboarding)"
  echo "E da root: $(bash /t/permessi-servizi.sh $R; echo $?) · permessi: $(stat -c %a $R/secrets) $(stat -c %a $R/secrets/gateway_secret.txt)"
' 2>&1)"
ESITO=0
ok() { printf '  ✓ %s\n' "$1"; }
ko() { printf '  ✗ %s\n' "$1"; ESITO=1; }
vuole() { if grep -qF -- "$1" <<<"$OUT"; then ok "$2"; else ko "$2 — atteso «$1»"; fi; }
vuole "A prima della cura, uid 1000 legge: no" "A. senza la cura i servizi non leggono i segreti (il difetto si vede)"
vuole "F fuori dal gruppo: 3" "F. operatore fuori dal gruppo 1000: esce 3"
vuole "B esito: 0" "B. la cura riesce"
vuole "B uid 1000 legge: si · terzo legge: no" "B. l'uid 1000 legge i segreti, un terzo utente no"
vuole "B uid 1000 scrive in onboarding: si" "B. il servizio scrive in onboarding/"
vuole "B operatore toglie ciò che il servizio ha scritto: si" "B. l'operatore toglie ciò che il servizio ha scritto"
vuole "B permessi: 750 640 2770" "B. permessi 750 / 640 / 2770"
vuole "C dopo una rotazione: no · rilanciato: si" "C. un segreto riscritto a 600 torna leggibile rilanciando"
vuole "D da root: 0 · uid 1000 legge: si" "D. lanciato da root fa lo stesso lavoro"
vuole "E esito: 0 · permessi: 700 600 700" "E. con l'operatore a uid 1000 non cambia niente"
vuole "E da root: 0 · permessi: 700 600" "E. idem lanciato da root"
[ "$ESITO" = 0 ] || { echo "── uscita del contenitore ──"; echo "$OUT"; }
exit "$ESITO"
