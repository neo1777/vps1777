#!/usr/bin/env bash
# prova-controlli.sh — i guasti costruiti (DD-P8.9, AP.1, AP.5).
#
# Un controllo che non si è mai visto rosso è decorativo: si chiama «controllo proposto»
# finché non va in rosso sul suo guasto costruito (AP.5). Questo script rompe il repo
# apposta, in un CLONE FRESCO dentro una cartella temporanea (mai nel repo vero), e per
# ogni controllo guarda tre tempi:
#   tempo 1  agganciato  il controllo è davvero chiamato (da `check`, o da `setup` per l'hook)
#   tempo 2  rosso       sul guasto costruito va in rosso, e PER LA RAGIONE GIUSTA (la regola
#                        attesa compare nel messaggio: un controllo che passa o fallisce per una
#                        ragione sbagliata non conta, M4)
#   tempo 3  verde       sul clone sano esce 0 (un controllo sempre rosso è spento quanto uno
#                        sempre verde, diagnosing-bugs)
# Alla fine scrive C3, la cella derivata «visto rosso» (AP.1): tools/1777/visto-rosso.tsv per le
# macchine e il blocco fra <!-- C3:inizio --> e <!-- C3:fine --> in RIGHE.md (in ogni lingua che
# il repo ha, K5: il blocco inglese ha i titoli in inglese). Mai a mano.
# C3 dice anche DOVE è stato visto: «locale», o «CI run <id>» se gira in GitHub Actions (legge
# GITHUB_RUN_ID); in CI la tabella va anche nel riassunto del run.
#
# Uso: bash tools/1777/prova-controlli.sh              i guasti, poi C3
#      bash tools/1777/prova-controlli.sh --c3-da F    solo C3, da un visto-rosso.tsv già fatto
#                                                      (per esempio l'artefatto di un run di CI:
#                                                      gh run download <id> -n visto-rosso)
# Esce 0 solo se ogni controllo applicabile è visto rosso su tutti i suoi guasti.
set -uo pipefail
RADICE="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "✗ non sono in un repo git" >&2; exit 2; }
command -v mise >/dev/null 2>&1 || { echo "[⚪] prova-controlli: NON MISURATO — mise non è nel PATH" >&2; exit 2; }
cd "$RADICE" || exit 2
risposta() { sed -n "s/^$1: *//p" .copier-answers.yml 2>/dev/null | tr -d "'\"" | head -1; }
STACK="$(risposta stack)"
# il testo che l'hook stampa quando ferma un commit: la ragione giusta del tempo 2 (F.7)
HOOK_MARCATORE="$(risposta hook_marcatore)"; HOOK_MARCATORE="${HOOK_MARCATORE:-commit fermato}"
[ -n "$STACK" ] || { [ -f pubspec.yaml ] && STACK=dart; [ -f package.json ] && STACK=ts; [ -f pyproject.toml ] && STACK=python; }
[ -n "$STACK" ] || { echo "[⚪] prova-controlli: NON MISURATO — non so lo stack" >&2; exit 2; }
DATA="$(date -u +%FT%TZ)"
if [ -n "${GITHUB_RUN_ID:-}" ]; then DOVE="CI run ${GITHUB_RUN_ID}"; else DOVE="locale"; fi

# --- C3: si scrive da un TSV, mai a mano (AP.1). La usano la fine della prova e --c3-da.
scrivi_c3() { # tsv — stampa la tabella italiana; scrive il blocco in ogni RIGHE del repo
  python3 - "$1" "$RADICE" <<'C3'
import sys, pathlib, collections
tsv, radice = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
sys.path.insert(0, str(radice / "tools/1777"))
import lingue
per = collections.OrderedDict(); quando = set()
for ln in tsv.read_text(encoding="utf-8").splitlines()[1:]:
    c = ln.split("\t")
    if len(c) < 7:
        continue
    dove = c[7] if len(c) > 7 else "locale"
    per.setdefault(c[0], []).append(c + [dove])
    quando.add(f"{dove}, {c[6]}")
TESTI = {
    "it": ("scritto da tools/1777/prova-controlli.sh, non a mano (AP.1)", "C3 vista", "mai",
           "«visto rosso» = rosso su ogni suo guasto, per la ragione giusta, e verde sul sano.",
           "| controllo | C3 visto rosso | dove, quando | guasti (✓ visto · ✗ no · — non si applica) |",
           {"sì": "sì", "no": "**no: proposto**", "na": "non si applica"}, ("CI run", "locale")),
    "en": ("written by tools/1777/prova-controlli.sh, never by hand (AP.1)", "C3 seen", "never",
           "«seen red» = red on each of its built faults, for the right reason, and green on the healthy repo. The fault names are in Italian, as the script writes them.",
           "| check | C3 seen red | where, when | faults (✓ seen · ✗ no · — not applicable) |",
           {"sì": "yes", "no": "**no: proposed**", "na": "not applicable"}, ("CI run", "local")),
}
def blocco(lingua):
    inizio, vista, mai, legenda, testa, esiti, (ci, loc) = TESTI[lingua]
    dv = lambda d: d if lingua == "it" else d.replace("locale", loc)
    out = [f"<!-- C3:inizio — {inizio} -->",
           f"{vista}: {'; '.join(sorted(dv(q) for q in quando)) or mai}. {legenda}", "", testa, "|---|---|---|---|"]
    for k, v in per.items():
        if all(x[5] == "non si applica" for x in v): esito = esiti["na"]
        else: esito = esiti["sì"] if all(x[5] in ("sì", "non si applica") for x in v) else esiti["no"]
        dq = "; ".join(sorted({f"{dv(x[-1])}, {x[6][:10]}" for x in v}))
        g = " · ".join(("✓ " if x[5] == "sì" else "— " if x[5] == "non si applica" else "✗ ") + x[1] for x in v)
        out.append(f"| `{k}` | {esito} | {dq} | {g} |")
    out.append("<!-- C3:fine -->")
    return out
pubblico, docs = lingue.piano(radice)
righe = [(it, "it") for b, it, en in docs if b == "RIGHE"] + [(en, "en") for b, it, en in docs if b == "RIGHE" and en]
for nome, lingua in righe:
    f = radice / nome
    if lingua == "en" and not f.is_file():
        continue
    out = blocco(lingua)
    t = f.read_text(encoding="utf-8") if f.is_file() else ""
    a, b = t.find("<!-- C3:inizio"), t.find("<!-- C3:fine -->")
    t = (t[:a] + "\n".join(out) + t[b + len("<!-- C3:fine -->"):]) if a >= 0 and b > a else (t + "\n" + "\n".join(out) + "\n")
    f.write_text(t, encoding="utf-8")
print("\n".join(blocco("it")[1:-1]))
C3
}
if [ "${1:-}" = "--c3-da" ]; then
  [ -f "${2:-}" ] || { echo "✗ --c3-da: serve un visto-rosso.tsv che esista" >&2; exit 2; }
  [ "$(realpath "$2")" = "$(realpath -m "$RADICE/tools/1777/visto-rosso.tsv")" ] || cp "$2" "$RADICE/tools/1777/visto-rosso.tsv" || exit 2
  scrivi_c3 "$RADICE/tools/1777/visto-rosso.tsv" >/dev/null || exit 2
  echo "── C3 riscritta in RIGHE (ogni lingua del repo) da $2"; exit 0
fi

T="$(mktemp -d)"; trap 'git -C "$RADICE" worktree prune 2>/dev/null; rm -rf "$T"' EXIT
export MISE_TRUSTED_CONFIG_PATHS="$T${MISE_TRUSTED_CONFIG_PATHS:+:$MISE_TRUSTED_CONFIG_PATHS}"
export GIT_AUTHOR_NAME=prova-controlli GIT_AUTHOR_EMAIL=prova@example.invalid
export GIT_COMMITTER_NAME=prova-controlli GIT_COMMITTER_EMAIL=prova@example.invalid

# --- la base: l'albero di lavoro ATTUALE (anche non committato), fotografato in un clone.
# Si clona e poi si copia sopra l'albero: un `cp -a` di un worktree porterebbe con sé il file
# .git che punta al repo vero, e i commit di prova finirebbero lì.
git clone -q "$RADICE" "$T/base" || exit 2
git ls-files -co --exclude-standard -z | tar --null -T - -cf - 2>/dev/null | tar -xf - -C "$T/base"
git ls-files -d -z | (cd "$T/base" && xargs -0 -r rm -f)
(cd "$T/base" && git add -A && git commit -qm "fotografia per prova-controlli" --no-verify --allow-empty) || exit 2

# nei TS le dipendenze si installano una volta nella base, e ogni clone le prende con hardlink:
# un `npm ci` dentro un clone cancella i suoi link, non la base
if [ -f "$T/base/package.json" ]; then
  (cd "$T/base" && { [ -f package-lock.json ] && npm ci --silent || npm install --silent; }) >/dev/null 2>&1 \
    || { echo "[⚪] prova-controlli: NON MISURATO — npm non installa le dipendenze" >&2; exit 2; }
fi
clona() { rm -rf "$T/c" "$T/wt"; git clone -q "$T/base" "$T/c" && cd "$T/c" || return 1
          [ -d "$T/base/node_modules" ] && cp -al "$T/base/node_modules" node_modules; return 0; }
TSV="$T/visto-rosso.tsv"; printf 'controllo\tguasto\ttempo1\ttempo2\ttempo3\tvisto\tdata\tdove\n' > "$TSV"
ok=0; ko=0; na=0
registra() { # id guasto t1 t2 t3 visto
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" "$5" "$6" "$DATA" "$DOVE" >> "$TSV"
  if [ "$6" = "sì" ]; then ok=$((ok+1)); echo "  ok   $1 · $2  [t1 $3 · t2 $4 · t3 $5]"
  elif [ "$6" = "non si applica" ]; then na=$((na+1)); echo "  --   $1 · $2: non si applica ($STACK)"
  else ko=$((ko+1)); echo "  KO   $1 · $2  [t1 $3 · t2 $4 · t3 $5]"; fi
}
agganciato() { # il controllo è chiamato da check (o da setup)?
  local task="$1" pezzo="$2"
  (cd "$T/base" && mise tasks info "$task" --json 2>/dev/null) | grep -qF -- "$pezzo" && echo sì || echo no
}
declare -A VERDE
verde() { # tempo 3, una volta per comando: il clone sano esce 0 (risultato in $T3)
  local cmd="$1"
  if [ -z "${VERDE[$cmd]:-}" ]; then
    clona >/dev/null
    if (eval "$cmd") >"$T/out3" 2>&1; then VERDE[$cmd]=sì; else VERDE[$cmd]=no; sed 's/^/        | /' "$T/out3" | tail -5; fi
    cd "$RADICE" || exit 2
  fi
  T3="${VERDE[$cmd]}"
}

# prova ID "guasto" 'rompi' 'controllo' ATTESO TESTO [task-aggancio pezzo-aggancio [controllo-sul-sano]]
#   ATTESO: rosso (≠0) | 2 ; TESTO: deve comparire nell'output (la ragione giusta; vuoto = solo il codice)
#   controllo-sul-sano: per il tempo 3, quando il guasto sta nel comando stesso (il filtro vuoto,
#   il PATH senza mise): lì sul sano si lancia la forma normale del comando
prova() {
  local id="$1" guasto="$2" rompi="$3" cmd="$4" atteso="$5" testo="$6" task="${7:-check}" pezzo="${8:-}" sano="${9:-$4}" t1 t2 t3 rc
  t1="$( [ -n "$pezzo" ] && agganciato "$task" "$pezzo" || echo "—")"
  verde "$sano"; t3="$T3"
  clona >/dev/null; (eval "$rompi") >/dev/null 2>&1
  (eval "$cmd") >"$T/out2" 2>&1; rc=$?
  if { [ "$atteso" = rosso ] && [ "$rc" -ne 0 ]; } || [ "$rc" = "$atteso" ]; then
    if [ -z "$testo" ] || grep -qF -- "$testo" "$T/out2"; then t2=sì; else t2="no (rc $rc, senza «$testo»)"; fi
  else t2="no (rc $rc)"; fi
  cd "$RADICE" || exit 2
  if [ "$t1" != no ] && [ "$t2" = sì ] && [ "$t3" = sì ]; then registra "$id" "$guasto" "$t1" "$t2" "$t3" sì
  else registra "$id" "$guasto" "$t1" "$t2" "$t3" no; sed 's/^/        | /' "$T/out2" | tail -6; fi
}
# il guasto AL CONTRARIO: un caso che NON deve andare in rosso (per esempio un file pigro)
prova_contrario() {
  local id="$1" caso="$2" rompi="$3" cmd="$4" rc
  clona >/dev/null; (eval "$rompi") >/dev/null 2>&1; (eval "$cmd") >"$T/out2" 2>&1; rc=$?; cd "$RADICE" || exit 2
  if [ "$rc" -eq 0 ]; then registra "$id" "al contrario: $caso" — "verde come deve" — sì
  else registra "$id" "al contrario: $caso" — "rosso (rc $rc): falso positivo" — no; sed 's/^/        | /' "$T/out2" | tail -4; fi
}
salta() { registra "$1" "$2" — — — "non si applica"; }

CONF='python3 tools/1777/conformita.py'
SEGR='bash tools/1777/segreti.sh'
ASS='python3 tools/1777/asserzioni.py'
RIL='python3 tools/1777/rilievi.py conta'

echo "── prova-controlli · stack $STACK · $DATA"

# ---------- la conformità (DD-P8.9, Ka.11, DD-P8.3, Ka.5)
prova descrizione   "task senza description" "printf '\n[tasks.senza]\nrun = \"true\"\n' >> mise.toml" "$CONF" rosso "[descrizione]" check tools/1777/conformita.py
prova comandi       "AGENTS.md nomina un comando che non c'è" "echo 'Poi \`mise run fantasma\`.' >> AGENTS.md" "$CONF" rosso "[comandi]" check tools/1777/conformita.py
prova comandi       "un comando del contratto tolto" "python3 -c \"import re,pathlib;p=pathlib.Path('mise.toml');p.write_text(re.sub(r'\\[tasks\\.build\\][^\\[]*','',p.read_text()))\"" "$CONF" rosso "[comandi]" check tools/1777/conformita.py
prova file-nominati "AGENTS.md nomina un file che non c'è" "echo 'Vedi \`docs/non-esiste.md\`.' >> AGENTS.md" "$CONF" rosso "[file]" check tools/1777/conformita.py
prova file-nominati "RIGHE.md nomina un file che non c'è (F.2)" "echo '| x | vedi \`tools/non-esiste.sh\` |' >> RIGHE.md" "$CONF" rosso "RIGHE.md nomina" check tools/1777/conformita.py
# in ogni lingua del repo, come farebbe chi scrive (K5): l'italiano dice «pigro», l'inglese «lazy»
prova_contrario file-nominati "file nominato ma dichiarato pigro (o lazy)" "python3 - <<'PY'
import sys, pathlib; sys.path.insert(0, 'tools/1777'); import lingue
for b, it, en in lingue.piano(pathlib.Path('.'))[1]:
    if b == 'AGENTS':
        for n, s in ((it, 'Vedi \`docs/nascera.md\` (pigro: nasce quando serve).'), (en, 'See \`docs/nascera.md\` (lazy: born when needed).')):
            if n:
                p = pathlib.Path(n); p.write_text(p.read_text(encoding='utf-8') + s + '\\n', encoding='utf-8')
PY
python3 tools/1777/lingue.py registra" "$CONF"
prova claude-import "CLAUDE.md senza @AGENTS.md" "echo 'regole solo di Claude' > CLAUDE.md" "$CONF" rosso "[claude-import]" check tools/1777/conformita.py
prova_contrario claude-import "CLAUDE.md con @AGENTS.md" "printf '@AGENTS.md\n' > CLAUDE.md" "$CONF"
prova tera          "un run con \${#ARR[@]} (Tera lo legge come commento)" "printf '\n[tasks.conta]\ndescription = \"conta\"\nrun = %s\n' \"'A=(1 2); echo \\\${#A[@]}'\" >> mise.toml" "$CONF" rosso "[tera]" check tools/1777/conformita.py
prova filo          "setup senza l'installatore (filo tolto)" "sed -i '/tools\/hooks\/installa.sh/d' mise.toml" "$CONF" rosso "[filo]" check tools/1777/conformita.py
prova ci-mise       "mise-action per tag, non per sha" "sed -i -E 's#jdx/mise-action@[0-9a-f]{40}#jdx/mise-action@v4#' .github/workflows/check.yml" "$CONF" rosso "[ci]" check tools/1777/conformita.py
prova ci-mise       "versione di mise diversa da min_version" "sed -i -E 's#^( *version: *).*#\\12026.1.1#' .github/workflows/check.yml" "$CONF" rosso "[ci]" check tools/1777/conformita.py
prova ci-mise       "uno step apt nella CI (F.8)" "sed -i 's#^\\( *\\)- run: mise run setup#\\1- run: sudo apt-get install -y age\\n\\1- run: mise run setup#' .github/workflows/check.yml" "$CONF" rosso "non è un comando del contratto" check tools/1777/conformita.py
prova ci-mise       "actions/checkout per tag" "sed -i -E 's#actions/checkout@[0-9a-f]{40}#actions/checkout@v7#' .github/workflows/check.yml" "$CONF" rosso "actions/checkout@v7" check tools/1777/conformita.py
prova ci-mise       "mise.lock tolto" "git rm -q mise.lock && git commit -qm via-lock --no-verify" "$CONF" rosso "mise.lock non fissa" check tools/1777/conformita.py
prova gitignore-env ".env tolto da .gitignore" "sed -i '/^\\.env\$/d' .gitignore" "$CONF" rosso "[gitignore]" check tools/1777/conformita.py
prova src-path      "repo pubblico nato da una cartella di casa (F.9)" "sed -i -E 's#^_src_path:.*#_src_path: /percorso/locale/template1777#; s#^pubblico:.*#pubblico: true#' .copier-answers.yml; grep -q '^pubblico:' .copier-answers.yml || echo 'pubblico: true' >> .copier-answers.yml" "$CONF" rosso "[src-path]" check tools/1777/conformita.py
prova ci-mise       "runs-on a ubuntu-latest (F2.4)" "sed -i -E 's#^( *runs-on: *).*#\\1ubuntu-latest#' .github/workflows/check.yml" "$CONF" rosso "runs-on: ubuntu-latest" check tools/1777/conformita.py
if grep -q '^UV_PYTHON' mise.toml; then
  prova ci-mise     "il python di uv non fissato: UV_PYTHON tolto (F2.4)" "sed -i '/^UV_PYTHON/d' mise.toml" "$CONF" rosso "il python di uv non è fissato" check tools/1777/conformita.py
else salta ci-mise "il python di uv non fissato (solo Python senza python in [tools])"; fi
# ---------- le lingue (K5) e il glossario (F2.3): tools/1777/lingue.py, chiamato da conformità
# una lingua che manca: il repo si dichiara pubblico (se non lo era) e il file italiano sparisce
# (se c'era la coppia). In un privato cade sull'inglese che manca, in un pubblico sull'italiano.
prova lingua        "repo pubblico con una lingua sola" "grep -q '^pubblico: true' .copier-answers.yml && rm -f AGENTS.it.md AGENTS.en.md; sed -i -E 's#^pubblico:.*#pubblico: true#' .copier-answers.yml; grep -q '^pubblico:' .copier-answers.yml || echo 'pubblico: true' >> .copier-answers.yml" "$CONF" rosso "[lingua]" check tools/1777/conformita.py
if grep -q '^pubblico: true' .copier-answers.yml 2>/dev/null; then
  SORG_IT="$(python3 -c 'import sys,pathlib;sys.path.insert(0,"tools/1777");import lingue;print(lingue.piano(pathlib.Path("."))[1][0][1])')"
  export SORG_IT
  prova lingua      "traduzione stantia: l'italiano cambia, l'inglese no" "echo 'Una regola nuova, solo in italiano.' >> \"\$SORG_IT\"" "$CONF" rosso "traduzione STANTIA" check tools/1777/conformita.py
  prova lingua      "disallineate: una riga di tabella solo nell'inglese" "python3 - <<'PY'
import sys, pathlib; sys.path.insert(0, 'tools/1777'); import lingue
en = [en for b, it, en in lingue.piano(pathlib.Path('.'))[1] if b == 'RIGHE'][0]
f = pathlib.Path(en); f.write_text(f.read_text(encoding='utf-8').replace('\n## ', '\n| X.1 | a row only in English | \n\n## ', 1), encoding='utf-8')
PY" "$CONF" rosso "non sono allineati" check tools/1777/conformita.py
  prova_contrario lingua "tradotto e registrato: l'italiano e l'inglese cambiano insieme, poi registra" "python3 - <<'PY'
import sys, pathlib; sys.path.insert(0, 'tools/1777'); import lingue
for b, it, en in lingue.piano(pathlib.Path('.'))[1]:
    if b == 'AGENTS':
        for n, s in ((it, 'Una nota in più.'), (en, 'One more note.')):
            p = pathlib.Path(n); p.write_text(p.read_text(encoding='utf-8') + s + '\n', encoding='utf-8')
PY
python3 tools/1777/lingue.py registra" "$CONF"
else
  salta lingua "traduzione stantia (solo nei repo pubblici)"
  salta lingua "disallineate (solo nei repo pubblici)"
fi
prova glossario     "una sigla che il glossario non spiega" "echo 'Vedi anche Kd.9.' >> AGENTS.md" "$CONF" rosso "[glossario]" check tools/1777/conformita.py
prova prova         "una riga controllo senza prova" "printf '| fantasma | x | derivata: \`fantasma\` |\n' >> RIGHE.md" "$CONF" rosso "[prova]" check tools/1777/conformita.py
# esportata: la usa il comando della prova qui sotto, dentro un eval (shellcheck non lo vede)
export SENZA_MISE
SENZA_MISE="$(printf '%s' "$PATH" | tr ':' '\n' | grep -vxF "$(dirname "$(command -v mise)")" | paste -sd:)"
prova fail-loud     "mise tolto dal PATH" "true" "PATH=\"\$SENZA_MISE\" $CONF" 2 "NON MISURATO" check tools/1777/conformita.py "$CONF"
if [ "$STACK" = ts ]; then
  prova prepare "prepare che chiama altro" "python3 -c \"import json;p='package.json';d=json.load(open(p));d['scripts']['prepare']='husky';json.dump(d,open(p,'w'),indent=2)\"" "$CONF" rosso "[prepare]" check tools/1777/conformita.py
else salta prepare "prepare in package.json"; fi
if [ "$STACK" = dart ]; then
  prova env-example-dart "un *_KEY in .env.example" "echo 'GEMINI_API''_KEY=' >> .env.example" "$CONF" rosso "[env-example]" check tools/1777/conformita.py
else salta env-example-dart "un *_KEY in .env.example"; fi

# ---------- i test (K-b, Kb.1, Kb.2)
case "$STACK" in python) PERCHE_VUOTO="deselected" ;; ts) PERCHE_VUOTO="nessun test eseguito" ;; dart) PERCHE_VUOTO="No tests match" ;; esac
prova filtro-vuoto  "filtro che non trova nessun test" "true" "mise run test nessuno-si-chiama-cosi-1777" rosso "$PERCHE_VUOTO" check test "mise run test"
prova asserzioni    "file di test senza asserzioni" "mkdir -p tests && printf 'def test_vuoto():\n    x = 1\n' > tests/test_vuoto.py" "$ASS" rosso "[asserzioni]" check tools/1777/asserzioni.py
prova asserzioni    "test vitest senza expect" "mkdir -p src && printf 'import {test} from \"vitest\";\ntest(\"x\", () => {});\n' > src/vuoto.test.ts" "$ASS" rosso "[asserzioni]" check tools/1777/asserzioni.py
prova_contrario asserzioni "test Dart con solo expectLater (Pr.4)" "mkdir -p test && printf 'void main() {\n  test(\"x\", () async { await expectLater(f(), completes); });\n}\n' > test/later_test.dart" "$ASS"

# ---------- i segreti (Ka.10): le stringhe sono spezzate, così questo file non fa scattare il controllo
prova segreti-forma "define di GEMINI_API_KEY su più righe" "printf 'export default defineConfig(({mode}) => {\n  const env = loadEnv(mode, \".\", \"x\");\n  return {\n    define: {\n      \"process.env.GEMINI\"\n        + \"_API_KEY\": JSON.stringify(env.GEMINI_API''_KEY),\n    },\n  };\n});\n' > vite.config.ts" "$SEGR --no-canarino" rosso "[define-chiave]" check tools/1777/segreti.sh
prova segreti-forma "loadEnv senza prefisso" "printf 'const env = loadEnv(\n  mode,\n  \".\",\n  \"\"\n);\n' > vite.config.mts" "$SEGR --no-canarino" rosso "[loadenv-senza-prefisso]" check tools/1777/segreti.sh
prova segreti-forma "il client legge VITE_*KEY" "mkdir -p src && printf 'const k = import.meta\n  .env.VITE_GEMINI''_KEY;\n' > src/chiave.ts" "$SEGR --no-canarino" rosso "[vite-env-chiave]" check tools/1777/segreti.sh
prova segreti-forma "--dart-define con un *_KEY" "printf 'name: x\n' > pubspec.yaml && printf 'flutter build web --dart-''define=GEMINI_API''_KEY=\$K\n' > build.sh" "$SEGR --no-canarino" rosso "[dart-define-chiave]" check tools/1777/segreti.sh
prova segreti-forma ".env dichiarato come asset" "printf 'name: x\nflutter:\n  assets:\n    - .env\n' > pubspec.yaml" "$SEGR --no-canarino" rosso "[dart-asset-segreto]" check tools/1777/segreti.sh
prova segreti-forma ".env dentro git" "echo 'A=1' > .env && git add -f .env && git commit -qm env --no-verify" "$SEGR --no-canarino" rosso "[env-tracciato]" check tools/1777/segreti.sh
# il valore non si stampa mai: il guasto ha un valore riconoscibile, e l'output non deve contenerlo
prova_contrario segreti-forma "il valore non compare nell'output" "printf 'export default { define: {\n  X_API''_KEY: \"valore-da-non-stampare\" } };\n' > vite.config.js" "! $SEGR --no-canarino 2>&1 | grep -qF valore-da-non-stampare"
if [ "$STACK" = ts ]; then
  # sfugge alla regola di forma (nel define non c'è nessun *_KEY) e la prende solo il canarino
  prova canarino "chiave nel bundle, per una via che la forma non vede" "python3 - <<'PY'
import pathlib, re
p = pathlib.Path('vite.config.ts'); t = p.read_text()
t = t.replace('export default defineConfig({', 'const k = process.env.GEMINI_API' + '_KEY;\nexport default defineConfig({\n  define: { \"process.env.CHIAVE\": JSON.stringify(k) },', 1)
p.write_text(t)
m = pathlib.Path('src/main.ts'); m.write_text(m.read_text() + '\nconsole.log(process.env.CHIAVE);\n')
PY" "$SEGR" rosso "[canarino]" check tools/1777/segreti.sh
else salta canarino "chiave nel bundle"; fi

# ---------- il deposito dei riti (R.1)
prova rilievi "riga malformata nel registro" "echo '{\"id\": 1}' >> RILIEVI.ndjson" "$RIL" rosso "[rilievi]" check tools/1777/rilievi.py
prova_contrario rilievi "il conto col denominatore" "python3 tools/1777/rilievi.py deposita --rito prova --cosa x --responsabile y --data 2000-01-01 && python3 tools/1777/rilievi.py deposita --rito prova --cosa z --responsabile y" "$RIL | grep -qF '1 aperti da più di 14 giorni, su 2 aperti'"

# ---------- setup idempotente (Ka.3): due volte di fila, la seconda esce 0 e non cambia file tracciati
idem() { mise run setup >/dev/null 2>&1 || { echo "primo setup fallito"; return 2; }
         git add -A >/dev/null; git commit -qm dopo-setup --no-verify >/dev/null 2>&1
         mise run setup >/dev/null 2>&1 || { echo "secondo setup fallito"; return 1; }
         local d; d="$(git status --porcelain --untracked-files=no)"
         [ -z "$d" ] || { echo "il secondo setup cambia file tracciati: $d"; return 1; }; }
prova setup-idempotente "setup che scrive in un file tracciato" "sed -i 's#^run = \\[#run = [\\n  \"echo x >> .gitignore\",#' mise.toml && sed -n '/tasks.setup/,/^\\]/p' mise.toml | grep -q 'echo x' && git commit -qam guasto --no-verify" "idem" rosso "cambia file tracciati" setup "tools/hooks/installa.sh"

# ---------- l'hook, a tre tempi su un clone fresco (Kc.1)
case "$STACK" in
  python) SPORCO='printf "import os\n" > sporco_prova.py; git add sporco_prova.py' ;;
  *)      SPORCO='printf "const k = import.meta.env.VITE_PROVA''_KEY;\n" > sporco.ts; git add sporco.ts' ;;
esac
PULITO='echo "una nota" > nota-pulita.txt; git add nota-pulita.txt'
hookdir() { echo "$(git rev-parse --path-format=absolute --git-common-dir)/hooks"; }   # chiesto QUI, dal posto in cui si guarda (T4 C.5, errore 1)
prova_hook() { # id guasto rompi innesco tempo-che-deve-cadere
  local id="$1" guasto="$2" rompi="$3" innesco="$4" deve="$5" t1 t2 t3 tw
  clona >/dev/null; (eval "$rompi") >/dev/null 2>&1; git commit -qam "guasto: $guasto" --no-verify >/dev/null 2>&1
  (eval "$innesco") >"$T/outh" 2>&1
  if [ -x "$(hookdir)/pre-commit" ]; then t1=sì; else t1=no; fi
  # sporco FERMATO, e dall'hook? Lo dice il suo marcatore (risposta copier hook_marcatore; col
  # pre-commit del template è «commit fermato», con quello di vps1777 «[✗]»)
  if (eval "$SPORCO"; git commit -qm sporco) >"$T/outs" 2>&1; then t2=no
  elif grep -qF -- "$HOOK_MARCATORE" "$T/outs"; then t2=sì
  else t2="fermato, ma senza «$HOOK_MARCATORE»"; fi
  cat "$T/outs" >>"$T/outh"
  git reset -q --hard HEAD >/dev/null 2>&1; git clean -qfd >/dev/null 2>&1
  if (eval "$PULITO"; git commit -qm pulito) >>"$T/outh" 2>&1; then t3=sì; else t3=no; fi   # pulito PASSA?
  if git worktree add -q "$T/wt" -b prova-wt >/dev/null 2>&1; then                            # sporco FERMATO anche nel worktree?
    if (cd "$T/wt" && eval "$SPORCO" && git commit -qm sporco-wt) >>"$T/outh" 2>&1; then tw=no; else tw=sì; fi
  else tw="non creato"; fi
  cd "$RADICE" || exit 2
  if [ "$deve" = nessuno ]; then
    if [ "$t1$t2$t3$tw" = sìsìsìsì ]; then registra "$id" "$guasto" "$t1" "$t2 (worktree $tw)" "$t3" sì
    else registra "$id" "$guasto" "$t1" "$t2 (worktree $tw)" "$t3" no; tail -8 "$T/outh" | sed 's/^/        | /'; fi
  else
    local caduto; case "$deve" in 1) caduto=$t1;; 2) caduto=$t2;; 3) caduto=$t3;; esac
    if [ "$caduto" = no ]; then registra "$id" "$guasto" "$t1" "$t2" "$t3" sì
    else registra "$id" "$guasto" "$t1" "$t2" "$t3" "no (il tempo $deve non è caduto)"; fi
  fi
}
prova_hook hook "sano: setup, sporco fermato, pulito passa, worktree coperto" "true" "mise run setup" nessuno
TOGLI_PREPARE="python3 -c \"import json;p='package.json';d=json.load(open(p));d['scripts'].pop('prepare');json.dump(d,open(p,'w'),indent=2)\""
if [ "$STACK" = ts ]; then
  # nei TS i fili sono due (Kc.3): setup lancia npm ci, e npm ci lancia prepare. Tolto uno, l'altro
  # copre: è la ridondanza voluta, e si prova come tale. Il guasto che deve far cadere il tempo 1
  # è tutti e due i fili tolti.
  prova_hook hook "filo di setup tolto: prepare lo copre ancora" "sed -i '/tools\/hooks\/installa.sh/d' mise.toml" "mise run setup" nessuno
  prova_hook hook "tutti e due i fili tolti (setup e prepare)" "sed -i '/tools\/hooks\/installa.sh/d' mise.toml && $TOGLI_PREPARE" "mise run setup" 1
else
  prova_hook hook "filo tolto (setup non chiama l'installatore)" "sed -i '/tools\/hooks\/installa.sh/d' mise.toml" "mise run setup" 1
fi
prova_hook hook "hook sdentato (esce sempre 0)" "sed -i '1a exit 0' tools/hooks/pre-commit" "mise run setup" 2
prova_hook hook "hook-muro (esce sempre 1)" "sed -i '1a exit 1' tools/hooks/pre-commit" "mise run setup" 3
if [ "$STACK" = ts ]; then
  prova_hook hook "sano con npm ci (l'altro innesco, Kc.3)" "true" "npm ci" nessuno
  prova_hook hook "prepare tolto, innesco npm ci" "$TOGLI_PREPARE" "npm ci" 1
fi

# ---------- C3: si scrive, non si compila a mano
cp "$TSV" "$RADICE/tools/1777/visto-rosso.tsv"
TABELLA="$(scrivi_c3 "$RADICE/tools/1777/visto-rosso.tsv")"
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  { echo "## C3 · visto rosso ($DOVE, $DATA)"; echo; echo "$TABELLA"; echo
    echo "**$ok visti rossi · $ko NO · $na non si applicano**"; } >> "$GITHUB_STEP_SUMMARY"
fi
echo "── $ok visti rossi · $ko NO · $na non si applicano · C3 scritta in tools/1777/visto-rosso.tsv e RIGHE.md ($DOVE, $DATA)"
[ "$ko" -eq 0 ]
