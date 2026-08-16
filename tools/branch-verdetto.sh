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

# ── LE RIGHE FUORI — quante righe il branch aggiunge che main NON ha da nessuna parte.
#    Imposta `tot` (righe uniche non vuote del branch) e `fuori`.
#
#    🔴 PERCHÉ INSIEMISTICO E NON A CAMPIONE (b82df434, 15/08, misurato):
#      il campione a 20 righe che questo strumento usava dà «20/20 già in main» su
#      `hook-versionati` — che di righe fuori ne ha CINQUANTA (433 uniche, 50 fuori).
#      ⭐ Un campione non rappresentativo non è una misura più debole: è una
#        RASSICURAZIONE FALSA, e su un verdetto «CANCELLABILE» è la direzione peggiore.
#      Il confronto è `test/proxy-check-bearer`: 206 righe uniche, 0 fuori. Due branch
#      che il campione dava identici (20/20) e che qui escono 50 contro 0.
#
#    COSTO: `git grep -h ''` su main è ~1,6s e si fa UNA volta per invocazione
#    (39k righe uniche in cache), poi ogni branch costa un `comm`. Il campione
#    costava 20 `git grep` per branch: sopra i due branch questo è anche più veloce.
#
#    ⚠️ SECONDO LIMITE, e va detto perché è quello che inganna di più: IL CRITERIO È
#    INSENSIBILE AL FILE. Una riga identica che sta in un ALTRO file di main conta come
#    «presente» — quindi risponde a «questo contenuto è perso?» e NON a «è dentro DOVE
#    SERVE?». Trovato da abdd732a (15/08) verificando questo metodo prima di cedergli il
#    passo, e la sua controprova è il pezzo che lo rende usabile lo stesso:
#      feat/voice-tagging  839 righe uniche, di cui 30 più corte di 12 char (`}`, `#`)
#      delle 491 righe LUNGHE (>60 char): ZERO mancano da main
#      ⇒ il verdetto «tutte in main» non è un artefatto delle righe banali.
#    *Un limite misurato da chi aveva interesse a smentirlo vale più di uno dichiarato
#    da chi ha scritto il codice.*
#
#    ⚠️ LIMITE DICHIARATO: il confronto è per riga NORMALIZZATA (spazi ai bordi tolti).
#    Una riga riscritta da main — stessa idea, parole diverse — risulta «fuori» pur non
#    essendo lavoro perso: è il caso di `release/0.41.0` («86 commit in sette giorni» →
#    «tutto quello che è entrato dopo la 0.40.14»). Il numero dice DOVE guardare, non
#    cosa concludere.
_MAINRIGHE=""; _BRRIGHE=$(mktemp); trap 'rm -f "$_MAINRIGHE" "$_BRRIGHE"' EXIT
righe_fuori() {
  local br="$1"
  if [ -z "$_MAINRIGHE" ]; then
    _MAINRIGHE=$(mktemp)
    git grep -h '' origin/main 2>/dev/null \
      | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | grep -vE '^$' | sort -u > "$_MAINRIGHE"
  fi
  git diff "origin/main...origin/$br" 2>/dev/null | grep '^+' | grep -v '^+++' \
    | sed 's/^+//;s/^[[:space:]]*//;s/[[:space:]]*$//' | grep -vE '^$' | sort -u > "$_BRRIGHE"
  tot=$(wc -l < "$_BRRIGHE")
  fuori=$(comm -23 "$_BRRIGHE" "$_MAINRIGHE" | wc -l)
}

# ⚠️ L'AVVISO PROSA ERA COPERTO A METÀ, e la metà scoperta era la più grossa
#    (rilievo di abdd732a sulla #175, confermato da b82df434 sugli stessi dati).
#    Nasceva DENTRO il ramo `else` di HA-LAVORO, raggiungibile solo se il branch ha
#    una PR mergiata sull'head: i branch senza PR escono prima come DA-LEGGERE e
#    **non lo ricevevano mai**. Nel run del 16/08 restavano fuori `docs/roadmap`
#    (5 file, tutti .md — il backlog condiviso, 957 righe) e `docs/8080-stato-di-
#    esercizio`: cioè i due casi di prosa più grossi che abbiamo.
# 🔑 La popolazione «è prosa» e la popolazione «ha una PR» non coincidono, e la cura
#    stava dentro il recinto della seconda. *Una cura giusta può essere messa in un
#    posto che ne restringe il dominio senza dirlo — e il referto non lo dichiarava.*
# 📌 SCELTA DICHIARATA: NON su qualunque verdetto. L'avviso serve dove il verdetto si
#    fonda sul CONTEGGIO DI RIGHE per dire «c'è lavoro da salvare» — HA-LAVORO — e
#    dove il referto manda un umano a contarle a mano — DA-LEGGERE. Su SUPERATO
#    («tutte le righe sono già in main») non c'è nulla da salvare e l'avviso sarebbe
#    rumore; su CANCELLABILE il verdetto non chiede di salvare niente. *Stamparlo
#    ovunque lo renderebbe più coperto e meno letto.*
avviso_prosa() {
  local b="$1" tot_file solo_prosa
  tot_file=$(git diff --name-only "origin/main...origin/$b" 2>/dev/null | wc -l)
  solo_prosa=$(git diff --name-only "origin/main...origin/$b" 2>/dev/null | grep -cv '\.md$')
  # `tot_file` NON è ridondante: su zero file `grep -c` risponde 0, che qui si
  # leggerebbe come «tutti .md» — uno ZERO PLAUSIBILE. Zero file non è «solo prosa»,
  # è NESSUN DATO. (Guardia originale di 71d540e6, provata su feat/ledger-anti-amnesia.)
  [ "${tot_file:-0}" -gt 0 ] && [ "${solo_prosa:-1}" -eq 0 ] || return 0
  printf '%-46s %-12s %s\n' "" "└─ ⚠️ PROSA" \
    "tocca SOLO .md: «righe non in main» NON misura lavoro perduto. Cerca in main un DETTAGLIO che il branch non ha — se main ne ha di più, main è il successore"
}

# ── L'AVVISO CHE VALE ANCHE SUL CODICE, e copre il caso che «PROSA» lasciava fuori.
#    🔴 16/08 (71d540e6): l'avviso qui sopra l'ho scritto io la mattina diagnosticando
#      «su prosa il verdetto non vale». Era vero e TROPPO STRETTO — misurato tre ore
#      dopo su `presidio-lock`, che è CODICE:
#        lo strumento   HA-LAVORO · 3/220 righe non in main ⇒ «apri una PR, NON cancellare»
#        le 3 righe     le pipeline `printf|grep -q` che la #176 aveva tolto 20 min prima
#        un'ora prima   lo STESSO strumento diceva SUPERATO sullo stesso branch
#      Aprire quella PR avrebbe RIMESSO IN main il difetto appena curato.
#    🔑 Una riga del branch assente da main ha DUE spiegazioni opposte e il passo 4 le
#      equipara: (a) lavoro nuovo mai entrato, (b) la versione VECCHIA di una riga che
#      main ha CORRETTO — cioè il PASSATO di main, non il suo futuro.
#    ⭐ E il falso positivo lo fabbrica la NOSTRA cura: ogni riga corretta in main regala
#      una «riga mancante» a ogni branch vecchio che la contiene. *Più curiamo, più lo
#      strumento grida al lavoro perduto* — e cresce da solo col tempo, senza che nessuno
#      tocchi il branch.
#    ⚠️ Il verdetto sbagliava DALLA PARTE DELLA PRUDENZA, ed è la ragione per cui nessuno
#      lo rileggeva: «non cancellare» non allarma. *Un consiglio conservativo va verificato
#      quanto uno distruttivo — sbagliano nella stessa misura, solo il secondo viene riletto.*
avviso_eta() {
  local b="$1" bts mts files
  files=$(git diff --name-only "origin/main...origin/$b" 2>/dev/null)
  [ -n "$files" ] || return 0
  bts=$(git log -1 --format=%ct "origin/$b" 2>/dev/null)
  # shellcheck disable=SC2086
  mts=$(git log -1 --format=%ct origin/main -- $files 2>/dev/null)
  if [ -z "$mts" ]; then
    # ⚠️ TERZO CASO, e la prima versione di questa sonda lo sbagliava IN SILENZIO:
    #   `git log` su file che main non ha MAI avuto non stampa niente, e un `${mts:-0}`
    #   lo fa cadere nel ramo «main fermo da allora» — cioè il ramo che NON avvisa.
    #   Trovato guardando l'output invece del verdetto: la data usciva «01/01 01:00»,
    #   cioè epoch 0. Caso vero: docs/roadmap, 5 file mai visti da main, fermo da un
    #   mese, e lo strumento lo dava DA-LEGGERE — il verdetto più muto che ha.
    printf '%-46s %-12s %s\n' "" "└─ 🆕 FILE NUOVI" \
      "main non ha MAI avuto questi file: qui «non in main» significa davvero lavoro mai entrato"
    return 0
  fi
  [ "${mts:-0}" -gt "${bts:-0}" ] || return 0
  printf '%-46s %-12s %s\n' "" "└─ ⏳ main È AVANTI" \
    "main ha toccato questi file DOPO l'ultimo commit del branch ($(date -d "@$mts" '+%d/%m %H:%M') vs $(date -d "@$bts" '+%d/%m %H:%M')): le righe «fuori» possono essere il PASSATO di main — LEGGILE prima di aprire una PR che le rimette"
}

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
    avviso_prosa "$b"
    avviso_eta "$b"
    continue
  fi
  merged="${pr#*|}"

  # ── PASSO 3 — commit DOPO il merge? Necessario, NON sufficiente.
  #    ⚠️ Niente soglie temporali: una sonda «se Δ > 60s» ha dato ✅ a `presidio-lock`
  #    per TRE SECONDI, su un numero che nessuno aveva misurato.
  dopo=$(git log --oneline --since="$merged" "origin/$b" 2>/dev/null | wc -l)
  if [ "${dopo:-0}" -eq 0 ]; then
    # Il verdetto è già deciso: qui le righe non decidono, DICONO PERCHÉ. Un branch
    # senza commit dopo il merge può comunque portare righe che main non ha più —
    # versioni vecchie di righe che main ha evoluto. Cancellarlo resta giusto, ma
    # chi legge deve saperlo senza rifare la misura: un referto che dice COSA e non
    # PERCHÉ costringe a rimisurare, e chi rimisura in fretta salta.
    righe_fuori "$b"
    if [ "${fuori:-0}" -gt 0 ]; then
      printf '%-46s %-12s %s\n' "$b" "CANCELLABILE" \
        "PR #${pr%%|*} mergiata, nessun commit dopo · $fuori/$tot righe non sono in main: main le ha EVOLUTE (non perse)"
    else
      printf '%-46s %-12s %s\n' "$b" "CANCELLABILE" \
        "PR #${pr%%|*} mergiata, nessun commit dopo · tutte le $tot righe sono in main"
    fi
    continue
  fi

  # ── PASSO 4 — LE RIGHE. È l'unico che decide davvero: un commit dopo il merge può
  #    essere la stessa cosa arrivata per un'altra strada (`presidio-lock`: 6 righe su 6
  #    già in main), oppure lavoro vero mai entrato (`fix/tetto-upload-prima-del-body`:
  #    0 righe su 20 in main, 29 insertions con un test — l'unico su 20 branch).
  #    ⚠️ Il campione salta le righe che ATTRAVERSANO un a capo: `grep` legge una riga
  #    per volta, e una frase spezzata risponde «non c'è» anche quando c'è.
  righe_fuori "$b"
  if [ "${tot:-0}" -gt 0 ] && [ "${fuori:-0}" -eq 0 ]; then
    printf '%-46s %-12s %s\n' "$b" "SUPERATO" "PR #${pr%%|*} + $dopo commit dopo, ma tutte le $tot righe sono già in main"
  else
    printf '%-46s %-12s %s\n' "$b" "HA-LAVORO" "PR #${pr%%|*} + $dopo commit dopo · $fuori/$tot righe NON sono in main ⇒ apri una PR, NON cancellare"
    # 🔴 16/08 (71d540e6, autrice del passo 4): SU PROSA QUESTO VERDETTO NON VALE, e
    #    l'avviso sta QUI e non solo nel referto in coda perché il momento in cui
    #    serve è questo — *un guardiano che parla nel momento sbagliato non è un
    #    guardiano*. Il passo 4 confronta RIGHE: su codice una riga è la cosa, su
    #    prosa è una FORMULAZIONE. Chi riscrive meglio la stessa affermazione produce
    #    righe testualmente diverse al 100% ⇒ «$fuori/$tot NON in main» e HA-LAVORO
    #    con la massima sicurezza **proprio quando qualcuno ha già fatto il lavoro,
    #    meglio**. Caso vero: docs/finestra-onboarding-8080 → 9/11 «non in main»,
    #    mentre main SECURITY.md:57-69 aveva la stessa cosa riscritta *e più
    #    completa* (nomina admin.py:105, il branch no). Peggio: il testo del branch
    #    era INVECCHIATO (diceva 0.0.0.0, main ha ${ONBOARDING_BIND:-127.0.0.1})
    #    ⇒ «salvare quel lavoro» avrebbe rimesso in SECURITY.md una garanzia falsa.
    #    ⚠️ `tot_file` NON è ridondante: su zero file `grep -c` risponde 0, che qui
    #       si leggerebbe come «tutti .md» — uno ZERO PLAUSIBILE. Zero file non è
    #       «solo prosa», è NESSUN DATO. Trovato provando la condizione su tutti i
    #       branch invece che sul mio caso: feat/ledger-anti-amnesia (0 file) dava SÌ.
    avviso_prosa "$b"
    avviso_eta "$b"
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
