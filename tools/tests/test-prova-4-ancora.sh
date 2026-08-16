#!/usr/bin/env bash
# `prova-4` non deve poter uscire VERDE senza aver valutato la propria tesi.
#
# La tesi è: «il punto di ripristino protetto è quello della versione che gira».
# Per valutarla serve uno snapshot DELLA versione che gira — l'ancoraggio esterno.
# Senza, il confronto è saltato e la prova arrivava comunque a `exit 0`: il referto di
# `lancia-tutte.sh` la contava ✅ perché classifica sul CODICE D'USCITA, non sull'output,
# e il ⚠️ stampato su stdout non lo legge nessuno.
#
# `prova-4` dichiara in testa il proprio contratto — «0 = PASS · 1 = FAIL · 2 = non
# osservabile» — e gestisce già così il caso gemello (versione non leggibile → exit 2).
#
# Uso:  bash tools/tests/test-prova-4-ancora.sh
set -uo pipefail

RADICE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROVA="$RADICE/tools/prove-empiriche/prova-4-snapshot-in-chiaro.sh"
FALLITI=0
ESEGUITI=0

# Un repo finto: `prova-4` prende la radice da VPS1777_REPO, quindi non serve una VPS.
# $1 versione dichiarata in update_status.json ("" = campo assente)
# $2.. nomi delle directory-snapshot da creare sotto backups/pre-update
finto_repo() {
  local vers="$1"; shift
  local r; r="$(mktemp -d)"
  mkdir -p "$r/onboarding" "$r/backups/pre-update"
  if [ -n "$vers" ]; then
    printf '{"current": "%s", "latest": "%s"}\n' "$vers" "$vers" > "$r/onboarding/update_status.json"
  else
    printf '{}\n' > "$r/onboarding/update_status.json"
  fi
  local d
  for d in "$@"; do mkdir -p "$r/backups/pre-update/$d"; done
  printf '%s' "$r"
}

# $1 nome del caso · $2 exit code atteso · $3 repo finto
attendi_rc() {
  local nome="$1" atteso="$2" repo="$3"
  ESEGUITI=$((ESEGUITI + 1))
  local out rc
  out="$(VPS1777_REPO="$repo" bash "$PROVA" 2>&1)"; rc=$?
  if [ "$rc" -eq "$atteso" ]; then
    printf 'ok   %-46s rc=%s\n' "$nome" "$rc"
  else
    printf 'FAIL %-46s atteso rc=%s, ottenuto rc=%s:\n%s\n' "$nome" "$atteso" "$rc" "$out"
    FALLITI=$((FALLITI + 1))
  fi
  rm -rf "$repo"
}

# ① IL CASO DEL RILIEVO: gira la 0.40.14, gli snapshot ci sono ma NESSUNO è suo.
#    Prima: exit 0 (verde nel referto). Ora: exit 2 (non osservabile).
attendi_rc "ancora mancante → non-eseguita" 2 \
  "$(finto_repo "0.40.14" "0.39.0-20260801-000000")"

# ② Gemello già gestito, che deve restare com'è: la versione non si legge.
attendi_rc "versione non leggibile → non-eseguita" 2 \
  "$(finto_repo "" "0.40.14-20260801-000000")"

# ③ Nessuno snapshot: già gestito (non prova che la retention funzioni).
attendi_rc "nessuno snapshot → non-eseguita" 2 \
  "$(finto_repo "0.40.14")"

# ④ CONTROPROVA DI POLARITÀ: l'ancora c'è ed è anche il più recente ⇒ la tesi è
#    valutata e vera. Deve restare VERDE, o la cura avrebbe solo spento la prova.
attendi_rc "ancora presente e protetta → PASS" 0 \
  "$(finto_repo "0.40.14" "0.40.14-20260802-120000")"

echo "──────────────────────────────────────────────────────────"
if [ "$FALLITI" -eq 0 ]; then
  echo "✅ $ESEGUITI casi, tutti passati"
  exit 0
fi
echo "🔴 $FALLITI falliti su $ESEGUITI"
exit 1
