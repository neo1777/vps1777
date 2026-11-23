#!/usr/bin/env bash
# sudoers-operatore.sh — le regole sudo dell'operatore, con gli ARGOMENTI vincolati (issue #283).
#
# Che cosa stringe. Fino alla 0.98.7 l'operatore poteva lanciare con sudo `install`, `systemctl` e
# `chown` con QUALUNQUE argomento: `sudo systemctl stop ssh`, `sudo chown -R operatore /etc` e
# `sudo install x /etc/sudoers.d/y` passavano. Con queste regole passano solo gli usi che la CLI fa
# davvero (tools/vps1777.py, cerca `sudo([`): un test li tiene allineati.
#
# Che cosa NON chiude, detto prima: l'operatore resta equivalente a root. Può installare una unit
# `vps1777-*.service` scritta da lui (la CLI le rende da file suoi) e accenderla, e sta nel gruppo
# docker. È riduzione della superficie contro l'errore e l'abuso semplice, non un confine.
#
# Le regole usano le espressioni regolari di sudo (dalla 1.9.10; Debian 12 ha la 1.9.13, Debian 13
# la 1.9.16): gli argomenti di ogni regola sono UNA espressione sull'intera riga degli argomenti,
# da ^ a $. Niente caratteri jolly di sudo, che attraversano spazi e barre.
#
# Provate su una macchina vera il 23/11/2026 (docs/collaudi/2026-11-23.yml): tabella 31 su 31,
# rollback e update riusciti con le regole in posto.
#
# Uso:  bash sudoers-operatore.sh <utente> <cartella-del-prodotto>              stampa le regole
#       bash sudoers-operatore.sh --installa <utente> <cartella-del-prodotto>   (da root) le installa
#         in /etc/sudoers.d/90-<utente> dopo averle validate, e toglie l'utente dal gruppo `sudo`
# Esce: 0 fatto · 2 argomenti non validi o non root · 3 sudo troppo vecchio: NON ho toccato niente
#         (resta la regola che c'era)
set -euo pipefail
INSTALLA=0; [ "${1:-}" = "--installa" ] && { INSTALLA=1; shift; }
U="${1:-}"; R="${2:-}"
[[ "$U" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || { echo "utente non valido: «$U»" >&2; exit 2; }
[[ "$R" =~ ^(/[A-Za-z0-9_-][A-Za-z0-9._-]*)+$ ]] || { echo "cartella non valida: «$R»" >&2; exit 2; }
RE="${R//./\\.}"                       # i punti del percorso, letterali nell'espressione
UNIT='vps1777-[a-z0-9@-]+\.(service|timer|path)'
ATT='vps1777-[a-z0-9-]+\.(timer|path)'     # ciò che si accende o spegne: mai un .service a mano
# un pezzo di percorso: non «.» né «..», niente spazi
PEZZO='(\.?[A-Za-z0-9_-][A-Za-z0-9._-]*)'
DIRS="$RE/(onboarding|var|backups|releases)(/$PEZZO)*"

# di chi possono diventare le cartelle: dell'operatore, e di nessun altro
if id "$U" >/dev/null 2>&1; then CHI="$(id -u "$U"):$(id -g "$U")"; else CHI='[0-9]+:[0-9]+'; fi
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
    "$d/chown ^-hR $CHI $DIRS( $DIRS)*\$"
  )
done
[ "${#regole[@]}" -gt 0 ] || { echo "nessun binario trovato" >&2; exit 2; }
stampa() {
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
}

if [ "$INSTALLA" -eq 0 ]; then stampa; exit 0; fi

[ "$(id -u)" -eq 0 ] || { echo "--installa va lanciato da root" >&2; exit 2; }
id "$U" >/dev/null 2>&1 || { echo "l'utente «$U» non esiste" >&2; exit 2; }
# le espressioni regolari negli argomenti esistono da sudo 1.9.10: con uno più vecchio le regole
# non corrisponderebbero a niente e l'operatore non potrebbe più aggiornare
V="$(sudo -V 2>/dev/null | sed -n '1s/.*version \([0-9]*\)\.\([0-9]*\)\.\([0-9]*\).*/\1 \2 \3/p')"
read -r v1 v2 v3 <<<"${V:-0 0 0}"
if [ "$(( v1 * 10000 + v2 * 100 + v3 ))" -lt 10910 ]; then
  echo "SUDOERS_ARGOMENTI_NON_APPLICATE: sudo ${v1}.${v2}.${v3} è più vecchio della 1.9.10" >&2; exit 3
fi
tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
stampa > "$tmp"
# MAI installare un sudoers non validato: un file rotto blocca sudo per tutti
visudo -cf "$tmp" >/dev/null 2>&1 || { echo "SUDOERS_ARGOMENTI_NON_APPLICATE: le regole non passano visudo" >&2; exit 2; }
install -m 0440 "$tmp" "/etc/sudoers.d/90-$U"
# Il gruppo `sudo` dà «tutto, con la password»: l'operatore non ha password, quindi oggi non gli dà
# niente, ma vanificherebbe queste regole il giorno in cui ne avesse una (visto il 23/11/2026).
if id -nG "$U" | tr ' ' '\n' | grep -qx sudo; then gpasswd -d "$U" sudo >/dev/null 2>&1 || true; fi
echo "SUDOERS_ARGOMENTI_OK"
