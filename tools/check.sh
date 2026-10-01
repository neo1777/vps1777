#!/usr/bin/env bash
# check.sh — quello che fanno i job `lint` e `contract` della CI, in locale, con un comando.
#
# PERCHÉ ESISTE. Prima di aprire una PR i controlli da rifare erano una dozzina di
#   comandi, ciascuno con le sue opzioni: ruff col pin, shellcheck per digest, una
#   decina di guardiani (cinque con la loro autoprova), le suite UNA ALLA VOLTA con tre
#   modi diversi di lanciarle. Chi arriva sul repo li deve riscoprire, e a volte ne salta uno —
#   e il controllo saltato è quello che la CI boccia dopo il push.
#
# LA FONTE DI VERITÀ RESTA `.github/workflows/ci.yml` (e `verify-features.yml`). Questo
#   file NON la sostituisce: la RIPETE. Perché non resti indietro c'è
#   `tools/tests/test_check_sh_segue_la_ci.py`: legge i workflow e fallisce se uno
#   script di guardia, una suite o un pin della CI non compare qui.
#
# E `tools/gate-locale.py`? Esegue gli step di `ci.yml` LEGGENDOLI dal workflow, ed è la
#   riproduzione più fedele. Questo è il comando di tutti i giorni, con tre differenze
#   volute: non installa niente (ruff via `uvx`, non `uv tool install`), copre anche il
#   ledger di `verify-features.yml`, e chiude con un riepilogo verde/rosso per controllo.
#
# ESITO  0 = tutto verde
#        1 = almeno un controllo ROSSO
#        2 = nessun rosso, ma qualcosa NON MISURATO (manca docker, uv, …). Non è un
#            verde: «non ho potuto guardare» non è «va bene».
#
# COSA NON FA, detto qui perché non lo si scopra da un rosso in CI:
#   • il job `build` (immagini e import nell'immagine): serve buildx, ci pensa la CI;
#   • «la rigenerazione di un lock dichiara i salti»: chiede che la PR NOMINI pacchetto
#     e versione di ogni salto, e in locale il corpo della PR non esiste;
#   • non riscrive MAI un file tracciato: in coda lo verifica, e se è successo è rosso.
#
# USO    bash tools/check.sh                  → lint, guardiani e test (circa due minuti)
#        bash tools/check.sh lint             → ruff + shellcheck
#        bash tools/check.sh guardiani        → i controlli della CI che non sono test
#        bash tools/check.sh test             → le suite, una alla volta, e i test bash
#        bash tools/check.sh lint guardiani   → più fasi, nell'ordine dato
set -uo pipefail

RADICE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RADICE" || exit 2

# Gli strumenti della CI, alla STESSA versione: un linter diverso dà verdetti diversi
# sullo stesso codice (ci.yml racconta i due casi, ruff e shellcheck). Il test che
# segue la CI confronta queste due righe con ci.yml.
RUFF_VERSIONE="0.15.22"
SHELLCHECK_IMG="koalaman/shellcheck@sha256:61862eba1fcf09a484ebcc6feea46f1782532571a34ed51fedf90dd25f925a8d"
# Il flag delle autoprove è composto e non scritto per intero: un file che lo contiene
# viene letto da `test_ogni_autoprova_e_agganciata.py` come un presidio che DICHIARA
# un'autoprova, e questo file le lancia soltanto.
AUTOPROVA="--auto""prova"

NOMI=() ESITI=() DURATE=() NOTE=()

uso() { sed -n '/^# USO/,/^set -uo/p' "$0" | sed '$d; s/^# \{0,1\}//'; }

adesso_us() { printf '%s' "${EPOCHREALTIME/[.,]/}"; }

registra() { NOMI+=("$1"); ESITI+=("$2"); DURATE+=("$3"); NOTE+=("${4:-}"); }

# `printf %-Ns` conta i BYTE, e un «—» ne vale tre: la colonna si calcola sui caratteri.
col() { printf '%s%*s' "$1" "$(( 52 - ${#1} > 0 ? 52 - ${#1} : 0 ))" ''; }

# manca <nome> <strumento>… — vero (0) se uno strumento non c'è: registra il controllo
# come NON MISURATO e lo dice. Per docker non basta il binario: serve il demone.
manca() {
  local nome="$1" s
  shift
  local assenti=()
  for s in "$@"; do
    if [ "$s" = docker ]; then
      command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1 \
        || assenti+=("docker (binario o demone)")
    else
      command -v "$s" >/dev/null 2>&1 || assenti+=("$s")
    fi
  done
  [ "${#assenti[@]}" -eq 0 ] && return 1
  registra "$nome" nonmisurato 0 "manca ${assenti[*]}"
  printf '  ⚪ %s NON MISURATO — manca %s\n' "$(col "$nome")" "${assenti[*]}"
  return 0
}

# passo <nome> <comando>… — esegue, misura, registra. L'output va nel log; se è rosso
# se ne stampano le ultime righe, così si vede PERCHÉ senza rilanciare.
passo() {
  local nome="$1"
  shift
  local log
  log="$LOG/$(printf '%02d' "${#NOMI[@]}").log"
  local t0 rc dt
  t0="$(adesso_us)"
  "$@" >"$log" 2>&1
  rc=$?
  dt=$(( ($(adesso_us) - t0) / 1000000 ))
  if [ "$rc" -eq 0 ]; then
    registra "$nome" verde "$dt"
    printf '  ✅ %s %4ss\n' "$(col "$nome")" "$dt"
  else
    registra "$nome" rosso "$dt" "exit $rc"
    printf '  🔴 %s %4ss  exit %s\n' "$(col "$nome")" "$dt" "$rc"
    tail -n 30 "$log" | sed 's/^/     │ /'
  fi
}

# ── lint ──────────────────────────────────────────────────────────────────────
# Il perimetro di shellcheck è quello di ci.yml, copiato com'è: i `.sh` tracciati più
# ogni file tracciato con uno shebang bash/sh (il criterio è lo shebang, non il nome:
# `tools/hooks/pre-commit` non finisce per `.sh`).
# SC2329: la chiama `passo`, che riceve il nome della funzione come argomento: shellcheck
# non segue la chiamata indiretta e la crede inutilizzata.
# shellcheck disable=SC2329
_shellcheck() {
  local -a script
  mapfile -t script < <(
    { git ls-files '*.sh'
      git ls-files | while IFS= read -r f; do
          [ -f "$f" ] || continue
          case "$f" in *.sh) continue ;; esac
          head -1 "$f" 2>/dev/null | grep -qaE '^#!.*\b(ba)?sh\b' && printf '%s\n' "$f"
        done
    } | sort -u
  )
  if [ "${#script[@]}" -eq 0 ]; then
    echo "nessuno script trovato: questo controllo non ha guardato NIENTE"
    return 1
  fi
  echo "shellcheck su ${#script[@]} script"
  docker run --rm -v "$PWD:/mnt" -w /mnt "$SHELLCHECK_IMG" "${script[@]}"
}

fase_lint() {
  echo "── lint (job «lint» di ci.yml)"
  manca "ruff $RUFF_VERSIONE" uvx \
    || passo "ruff $RUFF_VERSIONE" uvx "ruff@$RUFF_VERSIONE" check services/ tools/ security/
  manca "shellcheck (immagine della CI, per digest)" docker \
    || passo "shellcheck (immagine della CI, per digest)" _shellcheck
}

# ── guardiani ─────────────────────────────────────────────────────────────────
# `pyproject` e `uv.lock` concordano, per ogni lock tracciato. La guardia sullo zero è
# quella di ci.yml: un glob vuoto farebbe uscire verde un ciclo che non ha girato.
# SC2329: la chiama `passo`, che riceve il nome della funzione come argomento: shellcheck
# non segue la chiamata indiretta e la crede inutilizzata.
# shellcheck disable=SC2329
_lock_concordano() {
  local -a lock
  mapfile -t lock < <(git ls-files 'services/*/uv.lock')
  if [ "${#lock[@]}" -eq 0 ]; then
    echo "nessun services/*/uv.lock trovato: questo controllo non ha guardato NIENTE"
    return 1
  fi
  local l esito=0
  for l in "${lock[@]}"; do
    echo "── $(dirname "$l")"
    (cd "$(dirname "$l")" && uv lock --check) || esito=1
  done
  return "$esito"
}

# Le migrazioni pubblicate sono immutabili. In CI si confronta con origin/main; qui con
# il punto in cui il ramo si è staccato (merge-base), CONTANDO anche le modifiche non
# ancora committate. Niente `git fetch`: questo comando non tocca i ref del repo.
# SC2329: la chiama `passo`, che riceve il nome della funzione come argomento: shellcheck
# non segue la chiamata indiretta e la crede inutilizzata.
# shellcheck disable=SC2329
_migrazioni_intatte() {
  local base="$1" mb cambiate
  mb="$(git merge-base "$base" HEAD)" || {
    echo "merge-base con «$base» non calcolabile: nessun verdetto, e non è un verde"
    return 1
  }
  if ! cambiate="$(git diff --no-renames --diff-filter=MD --name-only "$mb" -- \
        'migrations/*/run.py' 'migrations/*/migration.json')"; then
    echo "il confronto con «$base» è FALLITO: non so dire se le migrazioni siano intatte"
    return 1
  fi
  if [ -n "$cambiate" ]; then
    echo "migrazioni esistenti modificate o rimosse rispetto a «$base»:"
    echo "$cambiate"
    return 1
  fi
  echo "nessuna migrazione pubblicata toccata rispetto a «$base» (merge-base ${mb:0:12})"
}

base_di_confronto() {
  local r
  for r in "${CHECK_BASE:-}" origin/main main; do
    [ -n "$r" ] && git rev-parse --verify --quiet "$r^{commit}" >/dev/null && {
      printf '%s' "$r"
      return 0
    }
  done
  return 1
}

fase_guardiani() {
  echo "── guardiani (job «lint» e «contract» di ci.yml, e verify-features.yml)"
  manca "registro dei rilievi (check_findings)" uv \
    || passo "registro dei rilievi (check_findings)" uv run --with pyyaml security/check_findings.py
  passo "i tre installer concordano — autoprova" python3 security/confronta-installer.py "$AUTOPROVA"
  passo "i tre installer concordano" python3 security/confronta-installer.py
  passo "gate anti-leak (check_no_leaks)" python3 security/check_no_leaks.py
  passo "i doc nominano file che esistono — autoprova" python3 tools/doc-riferimenti.py "$AUTOPROVA"
  passo "i doc nominano file che esistono" python3 tools/doc-riferimenti.py
  passo "i numeri nei doc — autoprova" python3 tools/fatti-nei-doc.py "$AUTOPROVA"
  passo "i numeri nei doc li conta il codice" python3 tools/fatti-nei-doc.py
  if ! manca "compose valido (produzione e sviluppo)" docker; then
    passo "compose valido (produzione)" docker compose -f compose.yaml config -q
    passo "compose valido (sviluppo, overlay di build)" \
      docker compose -f compose.yaml -f compose.build.yaml config -q
  fi
  local base
  if base="$(base_di_confronto)"; then
    passo "migrazioni pubblicate intatte" _migrazioni_intatte "$base"
  else
    registra "migrazioni pubblicate intatte" nonmisurato 0 "nessuna base (origin/main, main, CHECK_BASE)"
    printf '  ⚪ %s NON MISURATO — nessuna base con cui confrontare (CHECK_BASE=<ref>)\n' \
      "$(col "migrazioni pubblicate intatte")"
  fi
  manca "pyproject e uv.lock concordano" uv \
    || passo "pyproject e uv.lock concordano" _lock_concordano
  passo "il runner dei test bash sa fallire — autoprova" bash tools/esegui-test-bash.sh "$AUTOPROVA"
  passo "le coordinate nei doc — autoprova" python3 tools/coordinate-nei-doc.py "$AUTOPROVA"
  passo "le coordinate nei doc puntano dentro il file" python3 tools/coordinate-nei-doc.py
  manca "gate locale — autoprova" uv \
    || passo "gate locale — autoprova" uv run --with pyyaml python3 tools/gate-locale.py "$AUTOPROVA"
  passo "le nove prove non mentono a macchina nuda" bash tools/prove-empiriche/onesta-a-macchina-nuda.sh
  # verify-features.yml installa PyYAML dallo stesso file, con gli hash.
  manca "ledger delle feature (verify-features)" uv \
    || passo "ledger delle feature (verify-features)" \
      uv run --with-requirements .github/requirements-verify-features.txt python3 tools/verify-features.py
}

# ── test ──────────────────────────────────────────────────────────────────────
# Le suite girano UNA ALLA VOLTA, come nel job contract: `tools/tests/` e archive-mcp
# importano entrambe un package `app`, e nella stessa invocazione di pytest si pestano.
# `--locked` e non `uv sync`: se il lock non concorda col pyproject il comando si ferma
# invece di riscriverlo (ed è quello che il guardiano dei lock direbbe comunque).
fase_test() {
  echo "── test (job «contract» di ci.yml, suite una alla volta)"
  if manca "suite pytest" uv uvx; then
    return
  fi
  passo "nb1777-mcp (contract-test, nlm pinnato)" \
    uv run --locked --directory services/nb1777-mcp pytest -q tests/
  passo "gateway (stdlib)" uvx pytest -q services/gateway/tests/
  passo "gateway gamba-2 XFF (uvicorn del lock)" \
    uv run --locked --directory services/gateway --with pytest pytest -q tests_runtime/
  passo "archive-mcp (stdlib)" uvx pytest -q services/archive-mcp/tests/
  passo "archive-mcp /health e indice (deps del lock)" \
    uv run --locked --directory services/archive-mcp --with pytest pytest -q \
      tests/test_health.py tests/test_superficie_tool.py tests/test_costruisci_indice.py \
      tests/test_ibrida_verifica.py tests/test_sessioni.py
  passo "CLI e presìdi del repo (tools/tests)" \
    uvx --with bcrypt --with cryptography --with pyyaml pytest -q tools/tests/
  # Il ciclo backup → restore cifra per davvero con `age` e usa docker: senza, esce 2
  # («SALTATO») e il runner lo conta rosso, di proposito. Qui lo si dice PRIMA.
  local nota=""
  command -v age >/dev/null 2>&1 || nota="manca age: il ciclo backup → restore uscirà SALTATO, cioè rosso"
  [ -n "$nota" ] && printf '  ⚠️  %s\n' "$nota"
  passo "test bash di tools/tests" bash tools/esegui-test-bash.sh
}

# ── principale ────────────────────────────────────────────────────────────────
FASI=()
[ "$#" -eq 0 ] && set -- tutto
for a in "$@"; do
  case "$a" in
    lint | guardiani | test) FASI+=("$a") ;;
    tutto) FASI+=(lint guardiani test) ;;
    -h | --help) uso; exit 0 ;;
    *) printf 'argomento sconosciuto: «%s»\n\n' "$a" >&2; uso >&2; exit 2 ;;
  esac
done
LOG="$(mktemp -d "${TMPDIR:-/tmp}/check-vps1777.XXXXXX")" || exit 2

# Nessun controllo deve riscrivere un file tracciato: lo stato si fotografa prima e si
# confronta dopo, file per file. Le modifiche che avevi già in corso non contano — conta
# ciò che è cambiato DURANTE il check, ed è quello che si nomina.
stato_tracciati() {
  git diff HEAD --name-only -z 2>/dev/null | while IFS= read -r -d '' f; do
    if [ -e "$f" ]; then printf '%s %s\n' "$(git hash-object -- "$f")" "$f"
    else printf 'cancellato %s\n' "$f"; fi
  done | sort
}
PRIMA="$(stato_tracciati)"
T0="$(adesso_us)"

# Il dispatch è scritto per esteso e non `"fase_$f"`: così shellcheck vede chi chiama chi.
for f in "${FASI[@]}"; do
  case "$f" in
    lint) fase_lint ;;
    guardiani) fase_guardiani ;;
    test) fase_test ;;
  esac
done

DOPO="$(stato_tracciati)"
if [ "$DOPO" != "$PRIMA" ]; then
  registra "nessun file tracciato riscritto" rosso 0 "un controllo ha modificato il repo"
  printf '  🔴 %s un controllo ha MODIFICATO file tracciati:\n' "$(col "nessun file tracciato riscritto")"
  diff <(printf '%s\n' "$PRIMA") <(printf '%s\n' "$DOPO") \
    | sed -n 's/^[<>] [^ ]* //p' | sort -u | sed 's/^/     │ /'
fi

TOT=$(( ($(adesso_us) - T0) / 1000000 ))
verdi=0 rossi=0 nonmis=0
echo
echo "── riepilogo: ${FASI[*]} — ${TOT} s ──"
for i in "${!NOMI[@]}"; do
  case "${ESITI[$i]}" in
    verde) verdi=$((verdi + 1)); faccia="✅ verde      " ;;
    rosso) rossi=$((rossi + 1)); faccia="🔴 ROSSO      " ;;
    *) nonmis=$((nonmis + 1)); faccia="⚪ non misurato" ;;
  esac
  printf '  %s %s %4ss%s\n' "$faccia" "$(col "${NOMI[$i]}")" "${DURATE[$i]}" "${NOTE[$i]:+  ${NOTE[$i]}}"
done
echo "  $verdi verdi · $rossi rossi · $nonmis non misurati"
echo "  (non coperti qui: il job «build» e la ratifica dei salti di lock, che vive nel corpo della PR)"

if [ "$rossi" -gt 0 ]; then
  echo "🔴 check: $rossi controlli rossi — i log interi sono in $LOG"
  exit 1
fi
rm -rf "$LOG"
if [ "$nonmis" -gt 0 ]; then
  echo "⚪ check: nessun rosso, ma $nonmis controlli NON MISURATI — non è un verde"
  exit 2
fi
echo "✅ check: tutto verde"
exit 0
