#!/usr/bin/env bash
# prova-8-le-unit-si-comportano-come-dichiarano.sh
#   Le direttive di sandboxing scritte nelle unit sono APPLICATE dal kernel,
#   o sono solo righe di testo in un file?
#
# COSA VERIFICA. Per ogni `systemd/*.service` del repo, prende le direttive di
# sandboxing che il file DICHIARA e chiede al demone systemd che cosa ha
# effettivamente applicato (`systemctl show`). Se il file dice
# `ProtectKernelTunables=true` e il demone risponde `no`, la garanzia non esiste
# — e nessuna lettura del sorgente avrebbe potuto dirlo.
#
# PERCHÉ ESISTE (27/07/2026, round-7 del loop-audit). L'analisi esterna ha
# formulato l'accusa meglio di come l'avevamo formulata noi:
#
#   «Il registro convalida un'ETICHETTA DI TESTO: cerca la stringa nel file
#    sorgente invece di collaudare il comportamento che quella riga dovrebbe
#    generare nel sistema operativo. Avere 41 voci dichiarate chiuse basandosi
#    sulla lettura del bugiardino crea un falso senso di invulnerabilità.»
#
# È vera: `security/check_findings.py` fa `if needle not in text` — un match di
# sottostringa. Il presidio scritto il 26/07 lega il TITOLO di una voce al FILE
# che nomina, e nei suoi limiti dichiarava già di non verificare «che l'evidenza
# dica qualcosa di vero». Nessuno l'aveva trasformato in un'azione. Questa prova
# è quell'azione.
#
# 🔴 E PERCHÉ NON SEGUE IL SUGGERIMENTO ALLA LETTERA. L'analisi proponeva:
#   «la pipeline esegua `systemctl show vps1777-update` e FALLISCA se non
#    restituisce NoNewPrivileges=yes».
#   Applicato così, IL TEST FALLIREBBE SEMPRE: `vps1777-update.service` non può
#   avere `NoNewPrivileges` — usa `sudo`, che è setuid, e lo bloccherebbe. Sta
#   scritto nella unit stessa, riga 17. Misurato sulla macchina viva:
#       systemctl show vps1777-update.service -p NoNewPrivileges  →  no
#   L'analisi ha mescolato due unit proprio nel passaggio in cui accusa il
#   registro di guardare l'unit sbagliata. ⇒ Il consiglio è GIUSTO NELLA
#   SOSTANZA e ROTTO NELL'ESEMPIO: si prende la sostanza, non l'esempio.
#   Per questo la prova non ha una lista fissa di direttive attese: legge quelle
#   che OGNI unit dichiara per sé. Una unit che non può avere una direttiva non
#   la dichiara, e qui non viene accusata di non averla.
#
# COSA NON FA: non avvia, non ferma e non modifica nessuna unit; solo `grep` sui
#   file del repo e `systemctl show`, che è di sola lettura.
# EXIT: 0 = PASS · 1 = FAIL (una garanzia dichiarata non è applicata) · 2 = non eseguibile.
set -uo pipefail

REPO="${VPS1777_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]:-.}")/../.." 2>/dev/null && pwd)}"
[ -n "${REPO:-}" ] && [ -d "$REPO/systemd" ] || {
  echo "⚠️  repo non trovato (manca systemd/) — usa VPS1777_REPO=<path>"; exit 2; }
command -v systemctl >/dev/null || {
  echo "⚠️  systemctl assente: senza un demone systemd questa prova non è eseguibile."
  echo "    NON è un PASS — è il caso in cui non ho saputo vedere."; exit 2; }
systemctl show --version >/dev/null 2>&1 || systemctl --version >/dev/null 2>&1 || {
  echo "⚠️  systemd non risponde (container senza init?) — prova non eseguibile"; exit 2; }

# Le direttive che ci interessano: quelle di CONTENIMENTO, non tutta la unit.
# Se il repo ne aggiunge una nuova, va aggiunta qui — ed è deliberato: una
# whitelist che cresce a mano è un elenco che qualcuno guarda.
DIRETTIVE="NoNewPrivileges ProtectSystem ProtectHome ProtectKernelTunables \
ProtectKernelModules ProtectControlGroups ProtectClock ProtectHostname \
RestrictRealtime LockPersonality PrivateTmp RestrictSUIDSGID MemoryDenyWriteExecute"

echo "── prova-8 · le unit si comportano come dichiarano?   $(date '+%F %T %Z')"

# `true` nel file → `yes` dal demone. systemd normalizza i booleani, e
# confrontarli come stringhe grezze darebbe un rosso su un sistema sano.
norm() { case "${1,,}" in true|yes|on|1) echo yes ;; false|no|off|0) echo no ;; *) echo "${1,,}" ;; esac; }

falliti=0; controllate=0; unit_viste=0; saltate=0

for f in "$REPO"/systemd/*.service; do
  [ -f "$f" ] || continue
  unit="$(basename "$f")"
  # Le unit templata (@PLACEHOLDER@) esistono nel repo in forma non renderizzata:
  # sull'host ne gira la versione sostituita. Se il demone non la conosce, si
  # DICHIARA saltata — non si finge di averla controllata.
  if ! systemctl cat "$unit" >/dev/null 2>&1; then
    echo "   ⏭  $unit — non caricata su questo host: NON controllata (non è un PASS)"
    saltate=$((saltate+1)); continue
  fi
  unit_viste=$((unit_viste+1))
  echo "   ── $unit"
  for d in $DIRETTIVE; do
    # solo le righe attive: un `#` davanti è un commento, e i commenti di questo
    # repo dicono spesso «NIENTE <direttiva>, perché…» — accusarli sarebbe
    # leggere una spiegazione come una promessa.
    dichiarato=$(grep -E "^[[:space:]]*${d}=" "$f" | tail -1 | cut -d= -f2- | tr -d '[:space:]')
    [ -n "$dichiarato" ] || continue
    effettivo=$(systemctl show "$unit" -p "$d" --value 2>/dev/null | tr -d '[:space:]')
    controllate=$((controllate+1))
    if [ "$(norm "$dichiarato")" = "$(norm "$effettivo")" ]; then
      printf "      ✅ %-26s file dice %-6s · il demone applica %s\n" "$d" "$dichiarato" "$effettivo"
    else
      printf "      🔴 %-26s file dice %-6s · IL DEMONE APPLICA %s\n" "$d" "$dichiarato" "${effettivo:-<vuoto>}"
      falliti=$((falliti+1))
    fi
  done
done

# ── la controprova: lo strumento sa distinguere un sì da un no? ──
# Senza questa, un `systemctl show` che rispondesse «yes» a qualunque domanda
# darebbe un verde perfetto e falso. Si cerca una direttiva NON dichiarata da
# nessuna unit e si pretende che il demone risponda «no».
echo "   ── controprova dello strumento"
cp_ok=0
for f in "$REPO"/systemd/*.service; do
  [ -f "$f" ] || continue
  unit="$(basename "$f")"
  systemctl cat "$unit" >/dev/null 2>&1 || continue
  if ! grep -qE "^[[:space:]]*ProtectSystem=" "$f"; then
    v=$(systemctl show "$unit" -p ProtectSystem --value 2>/dev/null | tr -d '[:space:]')
    if [ "$(norm "${v:-no}")" = "no" ]; then
      echo "      ✅ $unit non dichiara ProtectSystem e il demone risponde «${v:-no}»: sa dire di no"
      cp_ok=1; break
    fi
  fi
done
[ "$cp_ok" -eq 1 ] || echo "      ⚠️  controprova non eseguita: non concludo che lo strumento sappia dire di no"

echo
if [ "$unit_viste" -eq 0 ]; then
  echo "⚠️  nessuna unit del repo è caricata su questo host — prova non eseguibile"; exit 2
fi
if [ "$falliti" -gt 0 ]; then
  echo "🔴 FAIL — $falliti garanzie DICHIARATE non sono APPLICATE dal kernel."
  echo "   Il file lo dice, il sistema no. È la distanza fra il bugiardino e il farmaco:"
  echo "   ogni voce del registro che si appoggia a quelle righe è chiusa su una stringa."
  exit 1
fi
echo "✅ PASS — $controllate direttive su $unit_viste unit: dichiarate E applicate."
[ "$saltate" -gt 0 ] && echo "   ⚠️  $saltate unit NON controllate (non caricate su questo host): il verde non le copre."
echo "   ⚠️  Limite: verifica che ciò che è dichiarato sia effettivo. NON dice se manca"
echo "       una direttiva che SAREBBE opportuna: quella domanda è di una review, non di una prova."
exit 0
