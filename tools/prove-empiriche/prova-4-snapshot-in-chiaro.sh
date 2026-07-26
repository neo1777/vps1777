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
# Lo snapshot PIÙ RECENTE è protetto per costruzione dal fix 6d06240 (cmd_check passa
# keep=snapshot_latest(repo), non keep=None): resta anche oltre le 72h, ed è giusto che
# resti — è il punto di ripristino. Quindi NON entra nel conteggio dei «vecchi».
# 🔴 PERCHÉ QUESTA RIGA ESISTE: prima del fix la prova dava FAIL se QUALSIASI snapshot
# superava le 72h. Dopo il fix quel criterio è più severo della garanzia, e un presidio
# più severo del vero non è prudenza: è un rosso su un sistema corretto, e al terzo
# nessuno lo guarda più. (setaccio, 26/07: la prova che trova un difetto eredita il
# criterio di quando il difetto c'era.)
# 🔴 L'ATTESO NON SI RICAVA DAI DATI CHE SI STANNO GIUDICANDO — rilievo di 71d540e6, ed era
# il difetto peggiore della prima stesura: prendevo il più recente per mtime, cioè lo stesso
# criterio del codice. Se `snapshot_latest()` cambiasse criterio o fallisse, la prova si
# ADATTEREBBE e direbbe PASS. Una prova che si auto-conferma dà un verde che nessuno controlla.
# Qui l'atteso viene da una fonte INDIPENDENTE: la versione IN ESECUZIONE. Lo snapshot che
# deve risultare protetto è quello dell'update a QUELLA versione — e se il codice ne protegge
# un altro, è un FAIL, non un adattamento.
VERS=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("current",""))' \
       "$REPO/onboarding/update_status.json" 2>/dev/null)
if [ -z "$VERS" ]; then
  echo "   ⚠️  versione in esecuzione non leggibile (onboarding/update_status.json)"
  echo "   ⇒ NON è un PASS: senza l'ancoraggio esterno questa prova non sa cosa DEVE essere protetto."
  exit 2
fi
echo "   versione in esecuzione (fonte esterna): $VERS"
atteso=$(find "$BASE" -mindepth 1 -maxdepth 1 -type d -name "${VERS}-*" 2>/dev/null | sort | tail -1)
# e questo è ciò che il CODICE proteggerebbe (più recente per mtime, come snapshot_latest)
protetto=$(find "$BASE" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' 2>/dev/null \
           | sort -rn | head -1 | cut -d' ' -f2-)
if [ -n "$atteso" ] && [ "$atteso" != "$protetto" ]; then
  echo "   🔴 DIVERGENZA: il codice proteggerebbe «$(basename "$protetto")» ma la versione in"
  echo "      esecuzione è $VERS, il cui snapshot è «$(basename "$atteso")»."
  echo "🔴 FAIL — il punto di ripristino protetto NON è quello della versione che gira."
  exit 1
fi
[ -z "$atteso" ] && echo "   ⚠️  nessuno snapshot per la versione $VERS: il rollback dati non ha un punto di ritorno"
while IFS= read -r d; do
  [ -z "$d" ] && continue
  tot=$((tot+1))
  mt=$(stat -c %Y "$d"); age=$(( (now - mt) / 3600 ))
  sz=$(du -sh "$d" 2>/dev/null | cut -f1)
  # cifrato? gli .age/.gpg hanno un magic; qui basta l'estensione + un check grossolano
  cif="NO"
  if find "$d" -maxdepth 1 -type f \( -name '*.age' -o -name '*.gpg' \) | grep -q .; then cif="sì"; fi
  flag=""
  if [ "$d" = "$protetto" ]; then
    flag="  🛡️  CORRENTE — protetto da keep=snapshot_latest (6d06240): non conta come vecchio"
  elif [ "$age" -gt 72 ]; then vecchi=$((vecchi+1)); flag="  🔴 OLTRE 72h"; fi
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
if [ "$tot" -eq 1 ]; then
  echo "✅ PASS — resta il solo snapshot CORRENTE, e supera le 72h di proposito."
  echo "   Non è un'omissione della prova: è la garanzia dopo 6d06240 — keep=snapshot_latest"
  echo "   protegge il punto di ripristino a qualunque età. Un verde che non spiega perché"
  echo "   quell'uno non conta sarebbe indistinguibile da «non ho guardato»."
  exit 0
fi
echo "✅ PASS — nessuno snapshot oltre le 72h oltre al corrente (protetto)."
exit 0
