#!/usr/bin/env bash
# branch-verdetto.sh — «questo branch si può cancellare?», con la domanda giusta.
#
# 🔴 PERCHÉ ESISTE, ed è la storia del 15/08/2026: quattro sessioni hanno censito gli
#    stessi branch con quattro strumenti diversi e hanno ottenuto quattro numeri diversi,
#    TUTTI difendibili e nessuno sufficiente. Il repo mergia con SQUASH, e lo squash rompe
#    ogni scorciatoia:
#
#      git merge-base --is-ancestor   il branch non è antenato di main anche quando il
#                                     lavoro È dentro   → dava «57 orfani» su 64
#      git cherry                     «ogni commit ha un patch-id gemello» ≠ «il contenuto
#                                     è dentro»          → dava 19
#      git diff main <b>   (2 punti)  conta anche ciò che MAIN ha in più
#                                     → dava «64 su 64 con contenuto proprio», assurdo
#      git diff main...<b> (3 punti)  meglio, ma sottostima: main evolve i file dopo
#                                     → dava 7, contro 33 branch con PR mergiata
#
#    ⇒ nessuno dei quattro risponde alla domanda che sembra rispondere. Questo script
#      applica i QUATTRO PASSI che ne sono usciti, in ordine, e si ferma al primo che
#      decide. Ogni passo ha un caso vero che l'ha reso necessario.
#
# USO:  bash tools/branch-verdetto.sh [<branch>...]      (senza argomenti: tutti i remoti)
# ESCE: 0 sempre — è un REFERTO, non un gate. La cancellazione resta un gesto umano.

set -uo pipefail
REPO="${REPO:-neo1777/vps1777}"
git fetch -q --prune origin 2>/dev/null || true

# ⚠️ SI CHIEDE AL SERVER, non alla cache locale: `git branch -r` include ref di ALTRI
#    namespace (qui 111 `pr/*`, le pull request) e li somma ai branch → 151 invece di 40.
#    Il prune non li tocca, perché il refspec di origin pota solo refs/remotes/origin/*.
elenco() { git ls-remote --heads origin 2>/dev/null | awk '{print $2}' | sed 's#refs/heads/##' | grep -v '^main$'; }
BRANCHES=("$@"); [ $# -eq 0 ] && mapfile -t BRANCHES < <(elenco)

for b in "${BRANCHES[@]}"; do

  # ── PASSO 0 — ATTACCAMENTI. Un worktree sopra BLOCCA la cancellazione, qualunque sia
  #    il contenuto. (Caso vero: `feat/ledger-anti-amnesia`, worktree in vps1777-installer;
  #    trovato da b82df434 verificando la classe A di 71d540e6, che aveva misurato il
  #    CONTENUTO e non gli ATTACCAMENTI.)
  if git worktree list 2>/dev/null | grep -q "\[$b\]"; then
    printf '%-46s %-12s %s\n' "$b" "BLOCCATO" "ha un worktree attivo: rimuovilo prima"
    continue
  fi

  # ── PASSO 1 — diff a TRE punti vuoto ⇒ non aggiunge nulla. Decide da solo, in positivo.
  if [ -z "$(git diff --stat "origin/main...origin/$b" 2>/dev/null | tail -1)" ]; then
    printf '%-46s %-12s %s\n' "$b" "RIDONDANTE" "diff a 3 punti vuoto: non aggiunge nulla"
    continue
  fi

  # ── PASSO 2 — esiste una PR MERGIATA su questo head? Necessario, NON sufficiente.
  pr=$(gh pr list --repo "$REPO" --state merged --head "$b" --json number,mergedAt \
       --jq '.[0] | "\(.number)|\(.mergedAt)"' 2>/dev/null)
  if [ -z "$pr" ] || [ "${pr%%|*}" = "null" ]; then
    # ⚠️ «nessuna PR con questo head» NON vuol dire «lavoro mai entrato»: può essere
    #    arrivato da un BRANCH GEMELLO con un altro nome. Caso vero: `pr130b` — nessuna
    #    PR sua, ma il fix H6 era in main dalla #130, e in main il test aveva 191 righe
    #    contro le 173 del branch. Mergiarlo sarebbe stata una REGRESSIONE.
    printf '%-46s %-12s %s\n' "$b" "DA-LEGGERE" "nessuna PR su questo head — cerca un branch gemello prima di concludere"
    continue
  fi
  merged="${pr#*|}"

  # ── PASSO 3 — commit DOPO il merge? Necessario, NON sufficiente.
  #    ⚠️ Niente soglie temporali: una sonda «se Δ > 60s» ha dato ✅ a `presidio-lock`
  #    per TRE SECONDI, su un numero che nessuno aveva misurato.
  dopo=$(git log --oneline --since="$merged" "origin/$b" 2>/dev/null | wc -l)
  if [ "${dopo:-0}" -eq 0 ]; then
    printf '%-46s %-12s %s\n' "$b" "CANCELLABILE" "PR #${pr%%|*} mergiata, nessun commit dopo"
    continue
  fi

  # ── PASSO 4 — LE RIGHE. È l'unico che decide davvero: un commit dopo il merge può
  #    essere la stessa cosa arrivata per un'altra strada (`presidio-lock`: 6 righe su 6
  #    già in main), oppure lavoro vero mai entrato (`fix/tetto-upload-prima-del-body`:
  #    0 righe su 20 in main, 29 insertions con un test — l'unico su 20 branch).
  #    ⚠️ Il campione salta le righe che ATTRAVERSANO un a capo: `grep` legge una riga
  #    per volta, e una frase spezzata risponde «non c'è» anche quando c'è.
  tmp=$(mktemp); trap 'rm -f "$tmp"' EXIT
  git diff "origin/main...origin/$b" 2>/dev/null | grep '^+' | grep -v '^+++' \
    | sed 's/^+//' | grep -vE '^\s*$' | head -20 > "$tmp"
  tot=$(wc -l < "$tmp"); dentro=0
  while IFS= read -r r; do git grep -qF -- "$r" origin/main 2>/dev/null && dentro=$((dentro+1)); done < "$tmp"
  if [ "${tot:-0}" -gt 0 ] && [ "$dentro" -eq "$tot" ]; then
    printf '%-46s %-12s %s\n' "$b" "SUPERATO" "PR #${pr%%|*} + $dopo commit dopo, ma $dentro/$tot righe già in main"
  else
    printf '%-46s %-12s %s\n' "$b" "HA-LAVORO" "PR #${pr%%|*} + $dopo commit dopo · solo $dentro/$tot righe in main ⇒ apri una PR, NON cancellare"
  fi
done

cat <<'NOTA'

── COSA QUESTO REFERTO NON DICE ─────────────────────────────────────────────
  · il campione del passo 4 è di 20 righe: un verdetto SUPERATO su un branch
    grosso va riletto a mano prima di cancellare.
  · «RIDONDANTE» e «CANCELLABILE» non cancellano niente: salva sempre lo sha
    prima (git rev-parse origin/<b>), il ripristino è
    git push origin <sha>:refs/heads/<b>.
  · un TAG con lo stesso nome NON è una rete: sui release/0.41.x il tag puntava
    a un commit DIVERSO dalla punta del branch, su tutti e tre.
NOTA
