#!/usr/bin/env bash
# diagnosi-h55.sh — «le unit girano come root?» e cosa serve per ripararlo.
#
# 🔴 PERCHÉ ESISTE, e la ragione è un errore mio (`abdd732a`, 01/08).
#   Avevo dato a Neo un `sed -i 's/^User=root/User=vps1777/'` come cura. Sarebbe
#   stato un guasto: quel comando fa UNA delle cose che servono, e le altre due
#   le scopri solo quando il servizio non riparte.
#     · l'utente `vps1777` potrebbe NON ESISTERE (se l'install è nato da root,
#       quasi certamente non esiste) → systemd: «Failed to determine user
#       credentials» e le unit non partono più;
#     · le unit hanno anche `Group=@OPERATOR_USER@` → il sed su `User=` sole
#       lascia `Group=root`, uno stato che nessun installer produce mai e che
#       quindi nessuno sa diagnosticare dopo;
#     · l'operatore deve POSSEDERE il repo (`WorkingDirectory=`), altrimenti
#       l'updater non può scrivere dove lavora.
# ⭐ LA FORMA: **un consiglio di sicurezza va provato contro gli ALTRI
#   meccanismi** — qui contro «il servizio deve restare su». Con `User=root` il
#   sistema funziona MALE ma FUNZIONA: cambiarlo alla cieca è l'unico modo di
#   trasformare un difetto di sicurezza in un'interruzione.
#
# 🛡️ QUESTO SCRIPT NON MODIFICA NULLA. Legge, e stampa il comando da eseguire
#   — che resta una decisione di chi lo lancia. Il rollback è stampato PRIMA
#   del fix, non dopo: se il fix non riparte, la riga per tornare indietro è
#   già sullo schermo e non va cercata mentre il servizio è giù.
#
#   Uso:  bash tools/diagnosi-h55.sh          (sulla macchina dove vps1777 GIRA)
set -u
D=/etc/systemd/system
echo "── DIAGNOSI H55 · $(date '+%Y-%m-%d %H:%M:%S') · $(hostname 2>/dev/null || echo '?')"
echo

shopt -s nullglob
UNITS=("$D"/vps1777-*.service)
if [ ${#UNITS[@]} -eq 0 ]; then
  echo "  ✅ nessuna unit vps1777-*.service in $D"
  echo "     ⇒ vps1777 non è installato QUI. H55 non ti riguarda su questa macchina."
  exit 0
fi

echo "① LE UNIT — chi le fa girare"
UTENTI=""; GRUPPI=""; REPO=""
for u in "${UNITS[@]}"; do
  uu="$(grep -m1 '^User='  "$u" 2>/dev/null | cut -d= -f2)"
  gg="$(grep -m1 '^Group=' "$u" 2>/dev/null | cut -d= -f2)"
  wd="$(grep -m1 '^WorkingDirectory=' "$u" 2>/dev/null | cut -d= -f2)"
  printf '   %-42s User=%-12s Group=%s\n' "$(basename "$u")" "${uu:-<assente>}" "${gg:-<assente>}"
  [ -n "$uu" ] && UTENTI="$UTENTI $uu"
  [ -n "$gg" ] && GRUPPI="$GRUPPI $gg"
  [ -z "$REPO" ] && REPO="$wd"
done
# shellcheck disable=SC2086  # lo split di $UTENTI è VOLUTO: la variabile accumula
# più utenti separati da spazio (righe 47-48) e serve una riga per utente per
# `sort -u`. Virgolettarla stamperebbe una riga sola e il conteggio dei distinti
# direbbe sempre 1. ⇒ eccezione DICHIARATA con la ragione, non soglia alzata:
# un'eccezione è UNA cosa con un nome, una soglia ne nasconde N. [b82df434, 01/08]
U_UNICI="$(printf '%s\n' $UTENTI | sort -u | tr '\n' ' ')"
echo
echo "② IL REPO — chi lo possiede (è QUI che si legge l'utente giusto)"
if [ -n "$REPO" ] && [ -d "$REPO" ]; then
  echo "   $REPO → proprietario: $(stat -c '%U:%G' "$REPO" 2>/dev/null || echo '?')"
  PROP="$(stat -c '%U' "$REPO" 2>/dev/null)"
else
  echo "   🔴 WorkingDirectory «${REPO:-<assente>}» non è una cartella esistente"
  PROP=""
fi
echo
echo "③ L'UTENTE PROPOSTO dalla documentazione (installer/engine.py) è «vps1777»"
if id vps1777 >/dev/null 2>&1; then
  echo "   ✅ esiste  ($(id vps1777 2>/dev/null))"
  ESISTE=1
else
  echo "   🔴 NON esiste su questa macchina"
  ESISTE=0
fi

echo
echo "── VERDETTO"
case "$U_UNICI" in
  *root*)
    echo "  🔴 almeno una unit gira come ROOT: l'updater automatico ha i privilegi"
    echo "     pieni della macchina a ogni avvio. È H55, e qui NON è teorico."
    echo
    # L'utente giusto è chi possiede il repo: le unit ci lavorano dentro.
    if [ -n "$PROP" ] && [ "$PROP" != "root" ]; then
      NUOVO="$PROP"
      echo "  ⇒ l'utente giusto è «$NUOVO» (possiede $REPO), non per forza «vps1777»."
    elif [ "$ESISTE" = "1" ]; then
      NUOVO="vps1777"
      echo "  ⚠️  il repo è di root, ma l'utente «vps1777» esiste."
      echo "     Serve ANCHE:  sudo chown -R vps1777:vps1777 $REPO"
    else
      echo "  🛑 NON C'È UN FIX DA UNA RIGA, e va detto invece di improvvisarlo:"
      echo "     il repo è di root E l'utente «vps1777» non esiste ⇒ l'installazione"
      echo "     è interamente di root. Crearlo al volo su una macchina che gira"
      echo "     significa useradd + chown -R + sudoers whitelist: sono i tre gesti"
      echo "     che 'installer/engine.py' fa insieme (righe 308-310, 369, 322)."
      echo "     ⇒ la strada pulita è re-installare con QUELL'installer, non un sed."
      exit 2
    fi
    echo
    echo "  ROLLBACK (leggilo PRIMA di eseguire il fix, non dopo):"
    echo "     sudo sed -i -e 's/^User=.*/User=root/' -e 's/^Group=.*/Group=root/' \\"
    echo "        $D/vps1777-*.service && sudo systemctl daemon-reload"
    echo
    echo "  FIX:"
    echo "     sudo sed -i -e 's/^User=root\$/User=$NUOVO/' -e 's/^Group=root\$/Group=$NUOVO/' \\"
    echo "        $D/vps1777-*.service"
    echo "     sudo systemctl daemon-reload"
    echo "     systemctl status vps1777-check-update.timer   # ← DEVE ripartire"
    ;;
  *)
    echo "  ✅ nessuna unit gira come root (utenti: $U_UNICI)"
    echo "     ⇒ su questa macchina H55 non ha nulla da riparare."
    ;;
esac
