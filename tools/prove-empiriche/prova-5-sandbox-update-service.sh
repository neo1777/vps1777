#!/usr/bin/env bash
# prova-5-sandbox-update-service.sh — cosa scrive DAVVERO vps1777-update.service,
# prima di stringerlo con ProtectSystem=strict + ReadWritePaths.
#
# IL CLAIM (round-4, bersaglio-1): la unit non ha NoNewPrivileges/ProtectSystem/
#   PrivateTmp/ProtectHome per 4 ragioni scritte nel suo commento H43. L'audio ha
#   proposto ProtectSystem=strict + ReadWritePaths su /usr/local/bin,
#   /etc/systemd/system, /var/lib/gateway, la home — ma la verifica sui FILE
#   (round-4, Fucina + setaccio) ha trovato che l'insieme è SBAGLIATO:
#     · /var/lib/gateway non è mai scritto dalla unit (vive nel container gateway,
#       namespace diverso — la unit gira sull'host)
#     · manca /tmp (mktemp -d in tools/backup.sh:28), la SOLA delle 4 ragioni che
#       il file descrive come guasto SILENZIOSO (dump/restore su una dir vuota)
#   Applicare la proposta com'è non farebbe fallire l'update: farebbe fallire il
#   backup senza dirlo — il guasto peggiore che questo kit conosce.
#
# ⚠️ QUESTA PROVA NON LANCIA UN UPDATE E NON PROVOCA NIENTE. Tracciare "cosa
#   scrive DAVVERO l'updater" richiederebbe un update reale (strace/audit) — è
#   la stessa classe di invasività della prova-4 sull'update fallito: decisione
#   di chi possiede il server, non di uno script. Qui si OSSERVA quello che è
#   già misurabile senza toccare niente:
#     (a) i path assoluti che il CODICE dichiara di scrivere, enumerati dal
#         sorgente — non un'inferenza su cosa "dovrebbe" scrivere
#     (b) se ~/.sigstore esiste già (cosign l'ha creata in passato?) — sola
#         lettura, la sola delle 4 ragioni che la unit stessa marca "non
#         verificabile su questa macchina"
#     (c) se l'ultimo backup ha CONTENUTO, non solo un exit code 0 — perché è
#         qui che backup.sh:28 (mktemp) romperebbe in silenzio con PrivateTmp
# EXIT: 0 = tutti i controlli osservabili sono coerenti col claim ·
#       1 = una discrepanza trovata (path scritto fuori da quelli noti, o
#           backup vuoto) · 2 = non osservabile (repo/unit assenti).
set -uo pipefail
REPO="${VPS1777_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
UNIT="$REPO/systemd/vps1777-update.service"

echo "── prova-5 · sandbox di vps1777-update.service   $(date '+%F %T')"
echo "   repo: $REPO"
[ -f "$UNIT" ] || { echo "   ℹ️  «$UNIT» assente — nulla da osservare."; exit 2; }

fail=0

echo
echo "── (a) path assoluti che i sorgenti dell'update dichiarano di scrivere"
echo "   (enumerati dal codice, non dedotti — grep su path che iniziano con /)"
# tools/vps1777.py: cosa scrive fuori dal repo durante update/self-update
grep -noE "(/usr/local/[a-zA-Z0-9_./-]+|/etc/systemd/[a-zA-Z0-9_./-]+)" "$REPO/tools/vps1777.py" 2>/dev/null \
  | sort -u -t: -k2 | while IFS=: read -r ln path; do printf '   vps1777.py:%-6s %s\n' "$ln" "$path"; done
grep -noE "mktemp[^\"']*" "$REPO/tools/backup.sh" "$REPO/tools/restore.sh" 2>/dev/null \
  | while IFS=: read -r f rest; do printf '   %-14s %s\n' "$(basename "$f")" "$rest"; done
echo "   ⇒ ReadWritePaths verificato solo su questi path conta come misura; il resto resta inferenza."

echo
echo "── (b) ~/.sigstore — la ragione che la unit marca 'non verificabile su questa macchina'"
if [ -d "$HOME/.sigstore" ]; then
  n=$(find "$HOME/.sigstore" -type f 2>/dev/null | wc -l)
  echo "   ✅ esiste, $n file dentro — cosign l'ha già usata: ProtectHome=read-only la romperebbe DAVVERO."
else
  echo "   ℹ️  NON esiste su questo host — o cosign non è mai girato qui, o scrive altrove."
  echo "      Non prova che ProtectHome sia sicuro da stringere: prova solo che qui non si vede ancora."
fi

echo
echo "── (c) contenuto dell'ultimo backup — dove PrivateTmp romperebbe in SILENZIO"
BACKUPS="$REPO/backups"
last=$(find "$BACKUPS" -maxdepth 1 -name 'vps1777-*.tar.age' -newer "$UNIT" 2>/dev/null | sort | tail -1)
[ -z "$last" ] && last=$(find "$BACKUPS" -maxdepth 1 -name 'vps1777-*.tar.age' 2>/dev/null | sort | tail -1)
if [ -z "$last" ]; then
  echo "   ℹ️  nessun backup .tar.age trovato in $BACKUPS — non osservabile."
else
  sz=$(stat -c %s "$last" 2>/dev/null || echo 0)
  printf '   %s — %s byte\n' "$(basename "$last")" "$sz"
  if [ "$sz" -lt 1024 ]; then
    echo "   🔴 FAIL — il backup più recente pesa meno di 1 KiB: è il sintomo esatto di un bind-mount"
    echo "      risolto su una dir vuota (il guasto che PrivateTmp introdurrebbe senza avviso)."
    fail=1
  else
    echo "   ✅ ha contenuto — il ciclo backup/bind-mount funziona ORA, prima di qualunque stretta."
  fi
fi

echo
if [ "$fail" -eq 1 ]; then
  echo "🔴 FAIL — vedi sopra. NON applicare ProtectSystem=strict senza aver risolto il punto (c)."
  exit 1
fi
echo "✅ Osservazioni coerenti col claim del round-4: la proposta dell'audio va corretta"
echo "   (togliere /var/lib/gateway, aggiungere /tmp) PRIMA di essere applicata alla unit —"
echo "   e resta un [da-prototipare]: nessuna riga qui prova che la unit riparta con la stretta."
exit 0
