#!/usr/bin/env bash
# test-backup-retention.sh — la ritenzione dei backup, provata su casi COSTRUITI
# di cui la risposta è nota prima di eseguirla.
#
# Perché esiste, e non è una formalità: la ritenzione è l'unico pezzo di
# vps1777 che CANCELLA dati che non si possono rigenerare. Fino al 27/07/2026
# non aveva una sola prova, e il difetto che ci ha nascosto — «7 daily» che
# contava sette FILE invece di sette GIORNI — è vissuto per mesi in bella vista.
#
# ⭐ IL METODO, e vale più dei casi: non basta chiedersi «la sonda sa diventare
# rossa?». Bisogna darle casi di cui si conosce già la risposta — COMPRESI
# quelli che deve lasciar passare e quelli che non la riguardano affatto. Una
# sonda che sbaglia in modo implausibile la si scopre; quella che sbaglia di
# poco viene pubblicata.
#
# Uso:
#   bash tools/tests/test-backup-retention.sh
#   BACKUP_SH=/percorso/altro/backup.sh bash tools/tests/test-backup-retention.sh
#
# La variabile BACKUP_SH serve alla CONTROPROVA: si punta alla versione
# PRECEDENTE dello script e il caso ① deve diventare rosso. Un presidio che non
# si è mai visto fallire non è un presidio.

set -uo pipefail

QUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$QUI/../.." && pwd)"
BACKUP_SH="${BACKUP_SH:-$REPO/tools/backup.sh}"

falliti=0
passati=0

# Esegue la ritenzione su una cartella popolata coi nomi dati, e confronta i
# SOPRAVVISSUTI con l'elenco atteso (entrambi ordinati).
verifica() {
  local nome="$1"; shift
  local attesi="$1"; shift
  local dir; dir="$(mktemp -d)"
  local f
  for f in "$@"; do
    : > "$dir/$f"
  done
  local out rc
  out="$(BACKUP_DIR="$dir" bash "$BACKUP_SH" --prune-only 2>&1)"; rc=$?
  # glob della shell invece di `ls`: già ordinato, e niente SC2012 da zittire in
  # un file il cui mestiere è controllare che i backup non spariscano.
  local sopravvissuti=""
  local g
  for g in "$dir"/*; do
    [ -e "$g" ] || continue
    sopravvissuti="$sopravvissuti ${g##*/}"
  done
  sopravvissuti="${sopravvissuti# }"
  rm -rf "$dir"

  if [ "$rc" -ne 0 ]; then
    printf '  ✗ %s — lo script è uscito con %d\n%s\n' "$nome" "$rc" "$out"
    falliti=$((falliti + 1))
    return
  fi
  if [ "$sopravvissuti" != "$attesi" ]; then
    printf '  ✗ %s\n      atteso: %s\n     ottenuto: %s\n' "$nome" "$attesi" "$sopravvissuti"
    falliti=$((falliti + 1))
    return
  fi
  printf '  ✓ %s\n' "$nome"
  passati=$((passati + 1))
}

n() { printf 'vps1777-%s.tar.age' "$1"; }

printf 'ritenzione backup — casi a risposta nota (script: %s)\n' "$BACKUP_SH"

# ─── ① IL CASO MISURATO IN PRODUZIONE il 27/07/2026 ─────────────────────────
# Otto notturni (20→27 luglio) più i QUATTRO backup pre-update della mattina
# del 27. Dodici file, otto giorni.
# RISPOSTA NOTA: devono restare SETTE GIORNI distinti — 21→27 — con un solo
# file per giorno, e per il 27 il più recente (11:50:05), che è quello fatto
# subito prima dell'ultimo update. Il 20 esce perché è l'ottavo giorno.
# 🔴 Con la ritenzione PRECEDENTE questo caso è rosso: teneva i sette FILE più
# recenti, cioè cinque file del 27 più il 26 e il 25 — tre giorni invece di sette.
verifica "① 4 update nello stesso giorno non mangiano la storia" \
  "$(n 2026-07-21-030000) $(n 2026-07-22-030000) $(n 2026-07-23-030000) $(n 2026-07-24-030000) $(n 2026-07-25-030000) $(n 2026-07-26-030000) $(n 2026-07-27-115005)" \
  "$(n 2026-07-20-030000)" "$(n 2026-07-21-030000)" "$(n 2026-07-22-030000)" \
  "$(n 2026-07-23-030000)" "$(n 2026-07-24-030000)" "$(n 2026-07-25-030000)" \
  "$(n 2026-07-26-030000)" "$(n 2026-07-27-030000)" "$(n 2026-07-27-055204)" \
  "$(n 2026-07-27-103936)" "$(n 2026-07-27-111016)" "$(n 2026-07-27-115005)"

# ─── ② LA CADENZA SANA — il livello weekly deve continuare a fare il suo ────
# Dieci notturni, uno al giorno, dal 18 al 27 luglio.
# RISPOSTA NOTA: i sette giorni distinti 21→27, PIÙ il 19 luglio, che il livello
# weekly tiene perché è l'unico superstite della settimana ISO 2026-29 (il 19 è
# domenica: ultimo giorno di quella settimana). Il 18 e il 20 escono — il 20
# perché la sua settimana, la 2026-30, ha già il suo rappresentante nel 26.
# ⚠️ Questo caso è quello che una «cura» sbagliata romperebbe per prima: serve a
# dimostrare che il fix del ① non ha spento il livello weekly.
verifica "② la cadenza sana tiene 7 giorni + il weekly più vecchio" \
  "$(n 2026-07-19-030000) $(n 2026-07-21-030000) $(n 2026-07-22-030000) $(n 2026-07-23-030000) $(n 2026-07-24-030000) $(n 2026-07-25-030000) $(n 2026-07-26-030000) $(n 2026-07-27-030000)" \
  "$(n 2026-07-18-030000)" "$(n 2026-07-19-030000)" "$(n 2026-07-20-030000)" \
  "$(n 2026-07-21-030000)" "$(n 2026-07-22-030000)" "$(n 2026-07-23-030000)" \
  "$(n 2026-07-24-030000)" "$(n 2026-07-25-030000)" "$(n 2026-07-26-030000)" \
  "$(n 2026-07-27-030000)"

# ─── ③ CIÒ CHE DEVE LASCIAR PASSARE ────────────────────────────────────────
# Tre backup, tre giorni: sotto la soglia, non c'è niente da potare.
# RISPOSTA NOTA: sopravvivono tutti e tre. Una ritenzione che cancella qualcosa
# qui è rotta anche se supera i casi ① e ②.
verifica "③ sotto soglia non cancella nulla" \
  "$(n 2026-07-25-030000) $(n 2026-07-26-030000) $(n 2026-07-27-030000)" \
  "$(n 2026-07-25-030000)" "$(n 2026-07-26-030000)" "$(n 2026-07-27-030000)"

# ─── ④ CIÒ CHE NON LA RIGUARDA ─────────────────────────────────────────────
# Un file estraneo che NON è un backup: non combacia col glob, quindi la
# ritenzione non deve né contarlo né toccarlo.
# RISPOSTA NOTA: sopravvive, e i tre backup pure.
verifica "④ un file che non è un backup resta dov'è" \
  "note-di-neo.txt $(n 2026-07-25-030000) $(n 2026-07-26-030000) $(n 2026-07-27-030000)" \
  "note-di-neo.txt" "$(n 2026-07-25-030000)" "$(n 2026-07-26-030000)" "$(n 2026-07-27-030000)"

# ─── ⑤ IL NOME CHE NON SI SA LEGGERE ────────────────────────────────────────
# Un file col nostro prefisso ma con una data che non è una data.
# RISPOSTA NOTA, e va detta com'è: NON occupa un posto (era il difetto SC2106
# curato il 27/07) ma VIENE CANCELLATO, perché non entra nell'insieme dei
# tenuti. Lo script ora lo dice con un warning invece di farlo in silenzio.
# I sette giorni veri sopravvivono tutti: è questo che il caso deve dimostrare.
verifica "⑤ un nome illeggibile non ruba un posto ai backup veri" \
  "$(n 2026-07-21-030000) $(n 2026-07-22-030000) $(n 2026-07-23-030000) $(n 2026-07-24-030000) $(n 2026-07-25-030000) $(n 2026-07-26-030000) $(n 2026-07-27-030000)" \
  "$(n non-una-data)" "$(n 2026-07-21-030000)" "$(n 2026-07-22-030000)" \
  "$(n 2026-07-23-030000)" "$(n 2026-07-24-030000)" "$(n 2026-07-25-030000)" \
  "$(n 2026-07-26-030000)" "$(n 2026-07-27-030000)"

# ─── ⑥ LA CARTELLA VUOTA ────────────────────────────────────────────────────
# RISPOSTA NOTA: nessun sopravvissuto e nessun errore. È il caso che scopre le
# guardie mancanti su array vuoti sotto `set -u`.
verifica "⑥ cartella vuota: niente da fare, e nessun errore" ""

printf '\n%d passati, %d falliti\n' "$passati" "$falliti"
[ "$falliti" -eq 0 ]
