#!/usr/bin/env bash
# prova-4-snapshot-in-chiaro.sh — OSSERVA gli snapshot pre-update: quanti, che età, cifrati?
#
# IL CLAIM: lo snapshot pre-update NON è cifrato (per permettere il rollback
#   automatico senza la chiave Age, che sta fuori dal server) e viene potato
#   dopo 72h. Il round-1 ha trovato che `snapshot_prune` era chiamata SOLO allo
#   step-15 di un update riuscito ⇒ un update fallito lasciava lo snapshot in
#   chiaro a tempo indeterminato. Fix in 5ca0f98 (check giornaliero + rollback).
#
# ⚠️ QUESTA PROVA **OSSERVA**, NON PROVOCA. Non fa fallire un update: sarebbe
#   invasivo su una macchina in produzione, e la decisione di provocarlo è di
#   chi possiede il server, non di uno script. Qui si guarda lo stato reale.
# COSA NON FA: non cancella nulla, non tocca i backup, non lancia update.
# EXIT: 0 = nessuno snapshot oltre 72h · 1 = ce n'è almeno uno · 2 = non osservabile.
set -uo pipefail
REPO="${VPS1777_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
BASE="$REPO/backups/pre-update"

echo "── prova-4 · stato degli snapshot pre-update   $(date '+%F %T')"
echo "   repo: $REPO"
[ -d "$BASE" ] || { echo "   ℹ️  «$BASE» non esiste — nessuno snapshot mai creato (o repo diverso)."
                    echo "   ⇒ NON è un PASS: è un'assenza di dato. Usa VPS1777_REPO=<path> se il repo è altrove."; exit 2; }

now=$(date +%s); vecchi=0; tot=0
while IFS= read -r d; do
  [ -z "$d" ] && continue
  tot=$((tot+1))
  mt=$(stat -c %Y "$d"); age=$(( (now - mt) / 3600 ))
  sz=$(du -sh "$d" 2>/dev/null | cut -f1)
  # cifrato? gli .age/.gpg hanno un magic; qui basta l'estensione + un check grossolano
  cif="NO"
  if find "$d" -maxdepth 1 -type f \( -name '*.age' -o -name '*.gpg' \) | grep -q .; then cif="sì"; fi
  flag=""
  if [ "$age" -gt 72 ]; then vecchi=$((vecchi+1)); flag="  🔴 OLTRE 72h"; fi
  printf '   %-42s %5sh  %6s  cifrato=%s%s\n' "$(basename "$d")" "$age" "$sz" "$cif" "$flag"
done < <(find "$BASE" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort)

echo "   ── totale: $tot snapshot · oltre 72h: $vecchi"
if [ "$tot" -eq 0 ]; then
  echo "   ℹ️  nessuno snapshot presente adesso. Non prova che la retention funzioni:"
  echo "      prova solo che ora non ce n'è. La retention si verifica su uno snapshot ESISTENTE."
  exit 2
fi
if [ "$vecchi" -gt 0 ]; then
  echo "🔴 FAIL — $vecchi snapshot oltre le 72h dichiarate."
  echo "   Se non cifrati, contengono i dati dei volumi in chiaro sul disco."
  echo "   Attesa dopo 5ca0f98: il check giornaliero (vps1777-check-update.timer) li pota."
  echo "   → verifica anche:  systemctl is-enabled vps1777-check-update.timer"
  exit 1
fi
echo "✅ PASS — nessuno snapshot oltre le 72h."
exit 0
