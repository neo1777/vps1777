#!/usr/bin/env bash
# sudoers-operatore.sh — CANDIDATA per la issue #283: le regole sudo dell'operatore con gli ARGOMENTI vincolati.
#
# ⚠️ NON È IN USO. I tre installatori scrivono ancora la lista dei soli binari (install, systemctl, chown
#    con qualunque argomento). Questa è la cura proposta, da provare su una macchina viva prima di
#    toccare gli installatori: una regola sbagliata qui brucia il canale che aggiorna la macchina.
#
# Che cosa stringe. Oggi `sudo systemctl stop ssh`, `sudo chown -R operatore /etc` e
# `sudo install x /etc/sudoers.d/y` passano. Con queste regole passano solo i 12 usi che la CLI fa
# davvero (censiti in tools/vps1777.py, cerca `sudo([`).
#
# Che cosa NON chiude, detto prima: l'operatore resta equivalente a root. Può installare una unit
# `vps1777-*.service` scritta da lui (la CLI le rende da file suoi) e accenderla, e sta nel gruppo
# docker. È riduzione della superficie contro l'errore e l'abuso semplice, non un confine.
#
# Le regole usano le espressioni regolari di sudo (dalla 1.9.10; Debian 12 ha la 1.9.13): gli
# argomenti di ogni regola sono UNA espressione sull'intera riga degli argomenti, da ^ a $. Niente
# caratteri jolly di sudo, che attraversano spazi e barre.
#
# Uso:  bash sudoers-operatore.sh <utente> <cartella-del-prodotto>     stampa le regole
# Esce: 0 stampate · 2 argomenti non validi
set -euo pipefail
U="${1:-}"; R="${2:-}"
[[ "$U" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || { echo "utente non valido: «$U»" >&2; exit 2; }
[[ "$R" =~ ^(/[A-Za-z0-9_-][A-Za-z0-9._-]*)+$ ]] || { echo "cartella non valida: «$R»" >&2; exit 2; }
RE="${R//./\\.}"                       # i punti del percorso, letterali nell'espressione
UNIT='vps1777-[a-z0-9@-]+\.(service|timer|path)'
ATT='vps1777-[a-z0-9-]+\.(timer|path)'     # ciò che si accende o spegne: mai un .service a mano
# un pezzo di percorso: non «.» né «..», niente spazi
PEZZO='(\.?[A-Za-z0-9_-][A-Za-z0-9._-]*)'
DIRS="$RE/(onboarding|var|backups|releases)(/$PEZZO)*"

regole=()
for d in /usr/bin /bin; do
  [ -x "$d/install" ] && regole+=(
    "$d/install ^-m 755 $RE/\\.cosign-dl /usr/local/bin/cosign\$"
    "$d/install ^-m 755 $RE/(releases/v[0-9][0-9A-Za-z.-]*/bundle/)?tools/vps1777\\.py /usr/local/bin/vps1777\$"
    "$d/install ^-m 644 $RE/var/\\.$UNIT\\.rendered /etc/systemd/system/$UNIT\$"
  )
  [ -x "$d/systemctl" ] && regole+=(
    "$d/systemctl ^daemon-reload\$"
    "$d/systemctl ^(enable|disable) --now $ATT( $ATT)*\$"
  )
  # -h: se l'argomento è un collegamento simbolico si cambia il collegamento, non ciò a cui punta
  # (senza, bastava un collegamento verso /etc per prendersi un file di sistema). La CLI passa -hR.
  [ -x "$d/chown" ] && regole+=(
    "$d/chown ^-hR [0-9]+:[0-9]+ $DIRS( $DIRS)*\$"
  )
done
[ "${#regole[@]}" -gt 0 ] || { echo "nessun binario trovato" >&2; exit 2; }
printf '# vps1777: sudo dell'"'"'operatore, argomenti vincolati (issue #283). Generato, non modificare a mano.\n'
printf 'Cmnd_Alias VPS1777_OPS = \\\n'
n=${#regole[@]}; i=0
for r in "${regole[@]}"; do
  i=$((i+1))
  # in sudoers la virgola, i due punti e l'uguale negli argomenti vanno protetti; la barra rovesciata
  # dell'espressione NO (provato: raddoppiata, la regola non corrisponde più a niente)
  r="${r//,/\\,}"; r="${r//:/\\:}"; r="${r//=/\\=}"
  if [ "$i" -lt "$n" ]; then printf '    %s, \\\n' "$r"; else printf '    %s\n' "$r"; fi
done
printf '%s ALL=(root) NOPASSWD: VPS1777_OPS\n' "$U"
