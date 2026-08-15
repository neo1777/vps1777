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

# ── IL CAMPIONE DELLE RIGHE, in un posto solo perché lo usano DUE passi (il 3 per
#    spiegare e il 4 per decidere). Non è pulizia: due copie divergono al primo che ne
#    migliora una, ed è il difetto che questo repo ha già curato con `importlib` nei test.
#    Imposta `tot` e `dentro` (globali, come le usava il passo 4).
#    ⚠️ Il campione salta le righe che ATTRAVERSANO un a capo: `grep` legge una riga per
#    volta, e una frase spezzata risponde «non c'è» anche quando c'è.
CAMPIONE_MAX="${CAMPIONE_MAX:-20}"
campiona() {
  local br="$1" tmp riga
  tmp=$(mktemp)
  git diff "origin/main...origin/$br" 2>/dev/null | grep '^+' | grep -v '^+++' \
    | sed 's/^+//' | grep -vE '^\s*$' | head -"$CAMPIONE_MAX" > "$tmp"
  tot=$(wc -l < "$tmp"); dentro=0
  while IFS= read -r riga; do
    git grep -qF -- "$riga" origin/main 2>/dev/null && dentro=$((dentro+1))
  done < "$tmp"
  # 🔑 rimosso SUBITO e non con un `trap ... EXIT` dentro il ciclo: il trap si
  #    riscrive a ogni giro e scatta una volta sola, quindi con N branch restavano
  #    N-1 file temporanei. (Difetto trovato estraendo questa funzione, 15/08.)
  rm -f "$tmp"
}
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
    # 🔴 IL REFERTO DICE ANCHE PERCHÉ, non solo COSA (limite dichiarato da 71d540e6 il
    #    15/08, trovato da abdd732a su `hook-versionati`): qui il verdetto è giusto e si
    #    ferma, ma tacere le righe nasconde CHE COSA si sta cancellando. Quel branch
    #    aveva 74 righe che main non ha più — non lavoro perduto: le VECCHIE stesure di
    #    righe che main ha poi evoluto (`EXPECTED_TOTAL = 67` contro 68, la garanzia
    #    senza il limite aggiunto dopo). ⇒ il conteggio si stampa ANCHE quando decide:
    #    non cambia il verdetto, cambia cosa sa chi lo legge.
    #    ⚠️ QUI NON SI CAMPIONA, e il primo tentativo lo faceva: `campiona` prende le
    #    prime 20 righe del diff e su `hook-versionati` rispondeva «20/20 già in main»
    #    — vero sul campione e FUORVIANTE sul branch, perché le righe che contano (i
    #    contatori del registro) stanno più giù. Un numero rassicurante nel posto dove
    #    serviva un allarme. ⇒ si conta il TOTALE, che è esatto e costa un comando.
    #    🔴 DUE PUNTI, non tre — e il primo tentativo usava i tre: `main...b` conta
    #    tutto ciò che il branch ha aggiunto DALLA MERGE-BASE, cioè anche ciò che è in
    #    main via lo squash. Dava 541 su `hook-versionati` (il vero è 74) e numeri a
    #    tre cifre su OGNI branch: un esito uniforme, che è la firma di uno strumento
    #    cieco e non di un repo pieno di fossili. `main..b` risponde alla domanda vera:
    #    che cosa ha il branch che main NON ha.
    agg=$(git diff --numstat "origin/main..origin/$b" 2>/dev/null | awk '{s+=$1} END{print s+0}')
    if [ "${agg:-0}" -gt 0 ]; then
      # 🔑 e QUI l'interpretazione è DEDOTTA, non inferita: siamo al passo 3, quindi la
      #    PR è mergiata E nessun commit è arrivato dopo ⇒ la punta del branch è ciò che
      #    è stato mergiato. Tutto ciò che il branch ha e main no è per costruzione
      #    qualcosa che main ha cambiato DOPO: stesure vecchie, non lavoro perduto.
      # 📌 il comando stampato è a DUE punti come il conteggio: un numero va sempre col
      #    comando che lo RIPRODUCE, o chi lo lancia vede una cifra diversa e non sa
      #    quale credere (coi tre punti qui uscirebbero 541 invece di 74).
      nota="⚠ porta $agg righe che main non ha più: stesure VECCHIE (main le ha evolute dopo il merge) — \`git diff origin/main..origin/$b\` per vederle"
    else
      nota="e non porta righe che main non abbia"
    fi
    printf '%-46s %-12s %s\n' "$b" "CANCELLABILE" "PR #${pr%%|*} mergiata, nessun commit dopo · $nota"
    continue
  fi

  # ── PASSO 4 — LE RIGHE. È l'unico che decide davvero: un commit dopo il merge può
  #    essere la stessa cosa arrivata per un'altra strada (`presidio-lock`: 6 righe su 6
  #    già in main), oppure lavoro vero mai entrato (`fix/tetto-upload-prima-del-body`:
  #    0 righe su 20 in main, 29 insertions con un test — l'unico su 20 branch).
  campiona "$b"
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
