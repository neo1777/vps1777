#!/usr/bin/env bash
# ESEGUE TUTTI I TEST BASH DI tools/tests/ — perché una LISTA è ciò che si dimentica.
#
# 🔓 PERCHÉ ESISTE. `ci.yml` lo dichiara da sé: «`pytest tools/tests/` NON vede i file
#    .sh». La risposta, dal 20/07, era elencarli a mano — e la lista si è fermata al
#    primo. Misurato il 03/08: 5 file `.sh` in `tools/tests/`, 1 eseguito dalla CI,
#    1 raccolto da un test pytest, **3 mai eseguiti da nessuno**.
#
#    ⚠️ E il commento che spiega il difetto è NELLO STESSO FILE, scritto il 20/07:
#    «Un test che non gira non è una verifica: è un commento con le parentesi.»
#    Da allora ne sono arrivati tre, uno dei quali (`test-hardening-tre-installer.sh`)
#    porta scritto dentro «una regola che nessuno strumento impone è persa con la
#    faccia di essere al sicuro». ⇒ *il problema non era sapere la regola.*
#
# 🔑 QUINDI NON AGGIUNGO UNA VOCE ALLA LISTA: tolgo la lista. Chi scriverà il sesto
#    test non deve ricordarsi di niente — il file entra in `tools/tests/`, e da lì
#    gira. L'unico modo di restare fuori è non essere un `.sh` in quella directory.
#
# ⚠️ COSA NON FA, dichiarato: non conosce i requisiti dei singoli test. Se uno di
#    essi ha bisogno di rete o di una VPS viva, qui fallirà — e va risolto in quel
#    test (saltando con un esito dichiarato), non escludendolo da qui. *Un'eccezione
#    in questo file ricrea la lista che questo file esiste per togliere.*
#
# ESITO   0 = tutti passati · 1 = almeno uno FALLITO · 2 = non misurabile
#         (2 è il caso in cui non trovo nessun test: uno ZERO non è un verde —
#          se la directory cambia nome, un ciclo su zero file gira a vuoto e
#          tace, che è esattamente come si perde una suite.)
#
# USO     bash tools/esegui-test-bash.sh
#         bash tools/esegui-test-bash.sh --autoprova   ← prova che sa FALLIRE
set -uo pipefail

RADICE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIR_TEST="${DIR_TEST_BASH:-$RADICE/tools/tests}"

esegui_tutti() {
  local dir="$1"
  local -a trovati=()
  # `find … -print0` e non un glob: un glob che non trova niente lascia il pattern
  # letterale e il ciclo girerebbe su un file inesistente.
  while IFS= read -r -d '' f; do trovati+=("$f"); done \
    < <(find "$dir" -maxdepth 1 -name '*.sh' -type f -print0 2>/dev/null | sort -z)

  if [ ${#trovati[@]} -eq 0 ]; then
    printf '⚪ NON MISURATO — nessun test .sh in «%s».\n' "$dir"
    printf '   Non è un verde: o la directory è cambiata, o la suite è sparita.\n'
    return 2
  fi

  local falliti=0
  for f in "${trovati[@]}"; do
    local nome; nome="$(basename "$f")"
    local out; out="$(bash "$f" 2>&1)"; local rc=$?
    if [ "$rc" -eq 0 ]; then
      printf '  ✅ %-38s exit 0\n' "$nome"
    else
      falliti=$((falliti + 1))
      printf '  🔴 %-38s exit %s\n' "$nome" "$rc"
      # L'output del test rosso, rientrato: chi guarda la CI deve vedere PERCHÉ
      # senza riaprire il file. Le ultime righe, dove i test di questo repo
      # mettono il riepilogo.
      printf '%s\n' "$out" | tail -12 | sed 's/^/       /'
    fi
  done

  printf '\n%s test bash · %s falliti\n' "${#trovati[@]}" "$falliti"
  [ "$falliti" -eq 0 ] || return 1
  return 0
}

autoprova() {
  # Un runner che non sa fallire dà verde su una suite rotta, ed è peggio di non
  # averlo: la CI direbbe di sì al posto dei test. Qui glielo si chiede in una
  # directory finta, senza toccare quella vera.
  local ok=0 d; d="$(mktemp -d)"
  # shellcheck disable=SC2064
  trap "rm -rf '$d'" RETURN

  # ⚠️ QUI NIENTE `$( ... )` NEL RAMO CHE SEGNA L'ESITO, e la ragione è un difetto
  #    VERO che ha vissuto in questo file: la prima stesura scriveva
  #      printf '%s …' "$([ "$rc" -eq 2 ] && echo ✅ || { ok=1; echo 🔴; })"
  #    e `ok=1` finiva in una SUBSHELL: stampava 🔴 e tornava comunque 0. ⇒ era
  #    l'autoprova a non sapere fallire — cioè esattamente ciò che deve escludere.
  #    Preso da shellcheck della CI (SC2030/SC2031) e NON dalla mia prova locale,
  #    che girava con `-S warning` mentre il gate del repo non alza soglie apposta.
  #    ⭐ Stessa forma di `${2:?…}` dentro `$( )`: l'effetto esce, il processo no.
  segna() {  # $1=descrizione  $2=atteso  $3=ottenuto  [$4=condizione extra, 0=ok]
    local esito=0
    [ "$2" = "$3" ] || esito=1
    [ "${4:-0}" -eq 0 ] || esito=1
    if [ "$esito" -eq 0 ]; then
      printf '  ✅ %-26s → esito %s (atteso %s)\n' "$1" "$3" "$2"
    else
      printf '  🔴 %-26s → esito %s (atteso %s)\n' "$1" "$3" "$2"
      ok=1
    fi
  }

  printf 'AUTOPROVA — il runner sa dire di no?\n'

  # ① directory vuota → 2, non 0. È il caso che un ciclo ingenuo sbaglia.
  DIR_TEST="$d" esegui_tutti "$d" >/dev/null 2>&1; local rc=$?
  segna "nessun test" 2 "$rc"

  # ② un test che passa → 0
  printf '#!/usr/bin/env bash\nexit 0\n' > "$d/test-verde.sh"
  esegui_tutti "$d" >/dev/null 2>&1; rc=$?
  segna "un test verde" 0 "$rc"

  # ③ un test che fallisce → 1, ed è il caso per cui il runner esiste. Non basta
  #    l'esito: deve anche NOMINARLO, o chi guarda la CI sa che qualcosa è rotto
  #    e non cosa.
  printf '#!/usr/bin/env bash\necho "il difetto finto"\nexit 1\n' > "$d/test-rosso.sh"
  local out; out="$(esegui_tutti "$d" 2>&1)"; rc=$?
  local nomina=1
  printf '%s' "$out" | grep -q 'test-rosso.sh' && nomina=0
  segna "un test rosso, e lo nomina" 1 "$rc" "$nomina"

  # ④ il rosso non deve essere coperto dal verde che gli sta accanto: `sort` mette
  #    test-rosso prima di test-verde, quindi ② non prova che l'esito sopravviva a
  #    un passaggio successivo. Qui il verde viene DOPO.
  printf '#!/usr/bin/env bash\nexit 0\n' > "$d/test-zzz-verde.sh"
  esegui_tutti "$d" >/dev/null 2>&1; rc=$?
  segna "rosso seguito da verde" 1 "$rc"


  # 🔬 SONDA DIAGNOSTICA — NON È UN TEST (df446a42, 16/08, voce 30b9d346)
  #    Non tocca $ok, non fa fallire niente, non ha un verdetto: STAMPA e basta.
  #    Esiste per chiudere UNA domanda che in locale non si chiude, e la storia è
  #    questa: il gate `contract` ha bocciato la #174 mentre il corpo DICHIARAVA il
  #    salto, e nel log del job c'era «printf: write error: Broken pipe» su
  #    ci.yml:341. L'ipotesi era `printf | grep -q` sotto pipefail: grep esce al
  #    match, printf prende EPIPE, la pipeline RIUSCITA diventa falsa.
  #    ⚠️ Kilo l'ha cercata in locale con 8 misure (60k → 4 MB): PIPESTATUS (0 0)
  #       SEMPRE, zero broken pipe, bash 5.2.21. In locale NON si riproduce.
  #    ⇒ o la causa è nell'AMBIENTE del runner, o il broken pipe è un effetto.
  #       Questa sonda è l'unico modo di distinguerle: gira DOVE succede.
  #
  #    🔑 PERCHÉ RIPRODUCE INVECE DI OSSERVARE: `pipefail` NON è attivo in questo
  #       file, ma lo è negli step `shell: bash` di GitHub — ed è la condizione
  #       senza la quale il difetto non può manifestarsi. Osservare una pipeline
  #       qualunque qui direbbe «tutto bene» misurando un caso che non è quello.
  #    🔑 E NON FA FALLIRE LA CI DI PROPOSITO: se il difetto c'è, lo dice il log.
  #       Un rosso su un file che gira per tutte, senza accordo, costa più della
  #       diagnosi che porta.
  _sonda_pipestatus() {
    local big grande rc_pf rc_no ps_no
    # 65.681 byte: la dimensione MISURATA di $RATIFICA nel job 95135773669
    big="$(head -c 65681 /dev/zero | tr '\0' 'a')"
    grande="ago${big}"
    (
      set -o pipefail
      printf '%s' "$grande" | grep -qF -- 'ago'
    ) 2>/dev/null; rc_pf=$?
    printf '%s' "$grande" | grep -qF -- 'ago' 2>/dev/null; rc_no=$? ps_no="${PIPESTATUS[*]}"
    printf '\n[SONDA-PIPESTATUS] byte=%s · con-pipefail rc=%s · senza-pipefail rc=%s PIPESTATUS=(%s) · bash=%s grep=%s\n' \
      "${#grande}" "$rc_pf" "$rc_no" "$ps_no" "$BASH_VERSION" "$(grep --version | head -1 | awk '{print $NF}')"
    printf '[SONDA-PIPESTATUS] lettura: rc=0 in ENTRAMBI = il costrutto NON è la causa (cerca altrove); rc≠0 con-pipefail = riprodotto, la cura here-string è quella giusta\n\n'
  }
  _sonda_pipestatus

  if [ "$ok" -eq 0 ]; then
    printf '\n✅ il runner sa fallire.\n'
  else
    printf '\n🔴 AUTOPROVA FALLITA — il runner non è affidabile.\n'
  fi
  return "$ok"
}

case "${1:-}" in
  --autoprova) autoprova ;;
  "")          printf 'Test bash di %s\n' "${DIR_TEST#"$RADICE"/}"; esegui_tutti "$DIR_TEST" ;;
  *)           printf 'uso: %s [--autoprova]\n' "$(basename "$0")" >&2; exit 2 ;;
esac
