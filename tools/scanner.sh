#!/usr/bin/env bash
# scanner.sh — gli scanner di sicurezza che leggono il repo, tutti dallo stesso comando (22/11/2026).
#
# Perché esiste. In CI c'erano ruff, shellcheck, il gate anti-leak e Trivy sulle immagini pubblicate.
# Mancavano tre letture del sorgente: i Dockerfile, le dipendenze dei lockfile, i segreti VIVI nella
# storia. Stanno qui e non dentro il workflow perché si possano lanciare uguali a mano, in CI e da chi
# vuole verificare che sappiano diventare rossi.
#
# Le classi:
#   contenitori  hadolint (come è scritto il Dockerfile) + trivy config (che cosa permette: per
#                esempio un Dockerfile senza USER, che hadolint NON segnala). Eccezioni dichiarate in
#                .hadolint.yaml e .trivyignore.yaml, ognuna col perché.
#   dipendenze   osv-scanner sui lockfile (uv.lock, requirements): versioni con vulnerabilità note.
#   segreti      trufflehog, solo i risultati verificati o non verificabili: cerca credenziali che
#                FUNZIONANO. La forma (chiavi, token, PEM) la guarda security/check_no_leaks.py, che
#                è un altro strumento e resta dov'è.
#
# Uso:   bash tools/scanner.sh contenitori|dipendenze|segreti|tutti [cartella]
#        bash tools/scanner.sh --autoprova      pianta un guasto per classe e pretende il rosso
# Esce:  0 pulito · 1 uno scanner ha trovato qualcosa · 2 non ho potuto guardare (docker assente,
#        immagine non scaricabile, niente da leggere): NON è un verde.
#
# Le immagini sono fissate per impronta, come tutto il resto: uno scanner che si aggiorna da solo
# cambia verdetto senza un commit.
set -uo pipefail
HADOLINT="hadolint/hadolint@sha256:30a8fd2e785ab6176eed53f74769e04f125afb2f74a6c52aef7d463583b6d45e"      # v2.12.0
TRIVY="aquasec/trivy@sha256:e2b22eac59c02003d8749f5b8d9bd073b62e30fefaef5b7c8371204e0a4b0c08"            # 0.67.2
OSV="ghcr.io/google/osv-scanner@sha256:fd62daecbaaed24442031574540e8af6dbaf0ab0a3e28c626bec0dd235a28346"  # v2.2.2
TRUFFLEHOG="ghcr.io/trufflesecurity/trufflehog@sha256:5dc064868ba7933601b5cbaea6954954d524ddd5dc6222a9667acea70068bf7d"  # 3.90.8
TETTO="${SCANNER_TIMEOUT_S:-900}"
QUI="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

dice() { printf '%s\n' "$*"; }
# Lancia un contenitore col repo in sola lettura. 124/125/126/127 = non ha guardato → 2.
gira() {
  local out rc
  out="$(timeout "$TETTO" docker run --rm -v "$DIR:/src:ro" -w /src "$@" 2>&1)"; rc=$?
  printf '%s\n' "$out" | tail -n 60
  case "$rc" in 0) return 0 ;; 124|125|126|127) return 2 ;; *) return 1 ;; esac
}
peggiore() { [ "$1" -gt "$2" ] && echo "$1" || echo "$2"; }

contenitori() {
  local -a file=(); local f rc=0 r
  while IFS= read -r -d '' f; do file+=("${f#"$DIR"/}"); done \
    < <(find "$DIR" -name 'Dockerfile*' -type f -not -path '*/.git/*' -not -path '*/node_modules/*' -print0 | sort -z)
  [ "${#file[@]}" -gt 0 ] || { dice "⚪ contenitori: nessun Dockerfile in $DIR — non è un verde"; return 2; }
  dice "── hadolint su ${#file[@]} Dockerfile"
  local -a conf=(); [ -f "$DIR/.hadolint.yaml" ] && conf=(--config /src/.hadolint.yaml)
  gira "$HADOLINT" hadolint --no-color "${conf[@]}" "${file[@]}"; r=$?; rc="$(peggiore "$r" "$rc")"
  dice "── trivy config su ${#file[@]} Dockerfile"
  local -a ign=(); [ -f "$DIR/.trivyignore.yaml" ] && ign=(--ignorefile /src/.trivyignore.yaml)
  # --exit-code 1: senza, trivy elenca e esce 0. Le severità tutte: un LOW nuovo si dichiara, non si tace.
  gira "$TRIVY" config --quiet --exit-code 1 --misconfig-scanners dockerfile "${ign[@]}" /src; r=$?; rc="$(peggiore "$r" "$rc")"
  return "$rc"
}

dipendenze() {
  local n
  n="$(find "$DIR" \( -name 'uv.lock' -o -name 'requirements*.txt' \) -type f -not -path '*/.git/*' | grep -c .)"
  [ "${n:-0}" -gt 0 ] || { dice "⚪ dipendenze: nessun lockfile in $DIR — non è un verde"; return 2; }
  dice "── osv-scanner su $n file di dipendenze"
  local out rc
  out="$(timeout "$TETTO" docker run --rm -v "$DIR:/src:ro" "$OSV" scan source -r /src 2>&1)"; rc=$?
  printf '%s\n' "$out" | tail -n 60
  # osv-scanner: 0 pulito, 1 vulnerabilità trovate; 128 = «nessun pacchetto trovato», che per noi è un non-misurato
  case "$rc" in 0) grep -q 'found [1-9][0-9]* package' <<<"$out" || { dice "⚪ dipendenze: nessun pacchetto letto"; return 2; }; return 0 ;; 1) return 1 ;; *) return 2 ;; esac
}

# SC2329: le tre classi le chiama il `case` in fondo, per nome
# shellcheck disable=SC2329
segreti() {
  dice "── trufflehog (solo credenziali verificate o non verificabili)"
  local out rc comune modo=(filesystem /src) monta=()
  # Con la storia git a disposizione si legge anche quella: un segreto tolto da un commit resta nei precedenti.
  if [ -d "$DIR/.git" ]; then
    modo=(git file:///src)
  elif [ -f "$DIR/.git" ] && comune="$(git -C "$DIR" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"; then
    # Un worktree (25/11/2026): `.git` è un FILE che punta alla cartella git comune, fuori da /src.
    # Prima si ripiegava sul filesystem, che legge anche le .venv non tracciate e dava un rosso falso
    # (gli URI d'esempio di pydantic). Si monta anche la cartella comune, allo STESSO percorso,
    # e si legge la storia come nel repo principale (misurato: stessi blocchi, stessi byte).
    modo=(git file:///src)
    monta=(-v "$comune:$comune:ro")
  fi
  out="$(timeout "$TETTO" docker run --rm -v "$DIR:/src:ro" "${monta[@]}" "$TRUFFLEHOG" "${modo[@]}" --no-update --results=verified,unknown --fail 2>&1)"; rc=$?
  if [ "$rc" -eq 183 ]; then
    # Un secondo sguardo prima del rosso (25/11/2026). «unknown» vuol dire che la verifica contro il
    # servizio non è riuscita: basta un momento storto della rete o un limite di richieste, e stringhe
    # innocue della storia (i riferimenti a 40 cifre nei workflow) escono come «non verificabili».
    # Misurato: 13 risultati così, spariti al rilancio senza cambiare niente. Una credenziale che
    # FUNZIONA resta verificata anche la seconda volta, e il rosso resta rosso.
    dice "   (trufflehog ha trovato qualcosa: riguardo una volta fra ${SCANNER_PAUSA_S:-20} s, prima di dirlo rosso)"
    sleep "${SCANNER_PAUSA_S:-20}"
    out="$(timeout "$TETTO" docker run --rm -v "$DIR:/src:ro" "${monta[@]}" "$TRUFFLEHOG" "${modo[@]}" --no-update --results=verified,unknown --fail 2>&1)"; rc=$?
  fi
  # Mai il valore nel log: solo le righe di riepilogo (questo output va in un log pubblico).
  grep -E '"msg":"finished scanning"|Detector Type|File:|Commit:' <<<"$out" | tail -n 40
  case "$rc" in
    0) grep -q 'finished scanning' <<<"$out" || { dice "⚪ segreti: trufflehog non dice di aver finito"; return 2; }; return 0 ;;
    183) return 1 ;;
    *) return 2 ;;
  esac
}

# shellcheck disable=SC2329
tutti() {
  local rc=0 r c
  for c in contenitori dipendenze segreti; do
    "$c"; r=$?; rc="$(peggiore "$r" "$rc")"
    case "$r" in 0) dice "✅ $c: pulito" ;; 1) dice "🔴 $c: ROSSO" ;; *) dice "⚪ $c: NON MISURATO" ;; esac
  done
  return "$rc"
}

autoprova() {
  # Uno scanner che non sa diventare rosso è una riga di log. Qui si pianta un guasto per classe in
  # una copia e si pretende esito 1; prima, la copia sana deve dare 0.
  local T ok=0 r; T="$(mktemp -d)"; trap 'rm -rf "$T"' RETURN
  ( cd "$QUI" && git ls-files -z | xargs -0 -I{} cp --parents {} "$T/" ) || { dice "⚪ autoprova: non riesco a copiare il repo"; return 2; }
  DIR="$T"
  atteso() { # $1 descrizione, $2 atteso, $3 ottenuto
    if [ "$2" -eq "$3" ]; then dice "  ✅ $1 → esito $3"; else dice "  🔴 $1 → esito $3 (atteso $2)"; ok=1; fi
  }
  contenitori >/dev/null 2>&1; atteso "contenitori, repo sano" 0 $?
  dipendenze  >/dev/null 2>&1; atteso "dipendenze, repo sano" 0 $?
  mkdir -p "$T/services/canarino"
  printf 'FROM alpine:3.20\nRUN echo canarino\nCMD ["true"]\n' > "$T/services/canarino/Dockerfile"
  contenitori >/dev/null 2>&1; atteso "contenitori, un Dockerfile senza USER" 1 $?
  rm -rf "$T/services/canarino"
  # una versione con vulnerabilità note da anni (Jinja2 2.4.1), nella forma di uv.lock
  printf '\n[[package]]\nname = "jinja2"\nversion = "2.4.1"\nsource = { registry = "https://pypi.org/simple" }\n' >> "$T/services/gateway/uv.lock"
  dipendenze >/dev/null 2>&1; atteso "dipendenze, una versione vulnerabile nel lockfile" 1 $?
  DIR="$T/vuota"; mkdir -p "$DIR"
  contenitori >/dev/null 2>&1; atteso "contenitori, cartella senza Dockerfile (non è un verde)" 2 $?
  dipendenze  >/dev/null 2>&1; atteso "dipendenze, cartella senza lockfile (non è un verde)" 2 $?
  dice "  (segreti: trufflehog diventa rosso solo su una credenziale che FUNZIONA, che qui non si pianta;"
  dice "   il rosso sulla forma lo dà security/check_no_leaks.py, che ha la sua prova)"
  return "$ok"
}

command -v docker >/dev/null || { dice "⚪ NON MISURATO — docker non c'è"; exit 2; }
COSA="${1:-}"; DIR="${2:-$QUI}"
if [ ! -d "$DIR" ]; then dice "cartella non trovata: $DIR"; exit 2; fi
DIR="$(cd "$DIR" && pwd)"
case "$COSA" in
  contenitori|dipendenze|segreti|tutti) "$COSA"; exit $? ;;
  --autoprova) dice "autoprova degli scanner"; autoprova; exit $? ;;
  *) dice "uso: bash tools/scanner.sh contenitori|dipendenze|segreti|tutti [cartella]  ·  --autoprova"; exit 2 ;;
esac
