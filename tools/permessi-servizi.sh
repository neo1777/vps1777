#!/usr/bin/env bash
# permessi-servizi.sh — rende leggibili ai servizi i segreti quando l'operatore NON ha l'uid 1000.
#
# ⏳ RIMEDIO PROVVISORIO (scelta di Neo del 24/11/2026, finding H102). I servizi girano nei
# contenitori come uid 1000 fisso. Su una macchina vuota l'operatore nasce con l'uid 1000 e i
# conti tornano. Dove il 1000 è già di un altro utente (immagini cloud con un utente
# predefinito) l'operatore prende un altro numero, i segreti sono suoi con permessi 600 e i
# servizi non li leggono: l'installazione moriva al primo avvio con «Permission denied:
# /run/secrets/…». Qui si dà la lettura al GRUPPO 1000 (e a `onboarding/` la scrittura).
#
# 🔴 IL PREZZO, dichiarato: sull'host, chi ha il gruppo 1000 (di norma l'utente predefinito
# dell'immagine) può leggere i segreti di vps1777. La cura pulita è far girare i servizi col
# numero dell'operatore: quando c'è, questo file si toglie.
#
# Con l'operatore a uid 1000 NON FA NIENTE: su quelle macchine i permessi restano 600/700.
#
# Uso:  bash tools/permessi-servizi.sh [cartella-del-prodotto]     (come operatore, senza sudo; o come root)
# Esce: 0 fatto o non serve · 3 serve ma non posso (l'operatore non è nel gruppo 1000)
set -uo pipefail
R="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
UID_SERVIZI=1000
# Chi è l'operatore: chi lancia, oppure (se lancia root, come fanno setup.sh e l'installatore
# grafico) il proprietario della cartella del prodotto.
IO="$(id -u)"
OPERATORE="$IO"
[ "$IO" = 0 ] && OPERATORE="$(stat -c %u "$R" 2>/dev/null || echo 0)"
{ [ "$OPERATORE" = "$UID_SERVIZI" ] || [ "$OPERATORE" = 0 ]; } && exit 0
if [ "$IO" != 0 ] && ! id -G | tr ' ' '\n' | grep -qx "$UID_SERVIZI"; then
  echo "permessi-servizi: $(id -un) ha l'uid $(id -u) e non è nel gruppo $UID_SERVIZI: i servizi non leggeranno i segreti." >&2
  echo "  Cura (come root):  getent group $UID_SERVIZI || groupadd -g $UID_SERVIZI vps1777-servizi; usermod -aG $UID_SERVIZI $(id -un)" >&2
  exit 3
fi
esito=0
if [ -d "$R/secrets" ]; then
  chgrp "$UID_SERVIZI" "$R/secrets" && chmod 750 "$R/secrets" || esito=3
  for f in "$R"/secrets/*.txt; do
    [ -f "$f" ] || continue
    chgrp "$UID_SERVIZI" "$f" && chmod 640 "$f" || esito=3
  done
fi
if [ -d "$R/onboarding" ]; then
  # il gateway ci scrive (pending.json) e ci legge lo stato degli aggiornamenti: setgid, così
  # ciò che nasce lì dentro resta del gruppo e l'operatore lo può leggere e togliere
  chgrp "$UID_SERVIZI" "$R/onboarding" && chmod 2770 "$R/onboarding" || esito=3
  find "$R/onboarding" -mindepth 1 -user "$OPERATORE" -exec chgrp "$UID_SERVIZI" {} + -exec chmod g+rwX {} + 2>/dev/null || esito=3
fi
[ "$esito" = 0 ] || echo "permessi-servizi: qualche permesso non è stato messo (vedi sopra)" >&2
exit "$esito"
