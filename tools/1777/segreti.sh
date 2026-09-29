#!/usr/bin/env bash
# segreti.sh — Ka.10: una chiave non deve poter finire nel codice che va al client.
# Guarda la FORMA, non il valore: nei repo AI Studio il valore non è mai nel repo (sta nel
# .env ignorato) e arriva nel bundle al build. Gli scanner di valori (gitleaks, trufflehog)
# non lo vedono; security-vite legge una riga alla volta e manca il `define` su più righe
# (misurato su acroform1777, T7). Qui ogni regola legge il file INTERO, su più righe.
#
# Stampa file, riga e regola. MAI il valore, e nemmeno la riga trovata.
#
# Regole:
#   define-chiave         (TS)   un `define` nel config di Vite con una chiave *_KEY/_TOKEN/_SECRET
#   loadenv-senza-prefisso(TS)   loadEnv(…, …, '') : carica TUTTE le variabili, anche le chiavi
#   vite-env-chiave       (TS)   import.meta.env.VITE_*KEY letto dal client
#   dart-define-chiave    (Dart) --dart-define / --dart-define-from-file con un *_KEY
#   dart-asset-segreto    (Dart) un .env o un file di chiavi dichiarato come asset in pubspec.yaml
#   env-tracciato         (tutti) un .env (non .env.example) dentro git
#   canarino              (TS)   al build, una chiave finta passata nella variabile vera
#                                finisce in dist/ (per valore: vale per AIza e per AQ.)
#
# Uso: bash tools/1777/segreti.sh                 la forma, più il canarino se c'è package.json (check)
#      bash tools/1777/segreti.sh --no-canarino   solo la forma: il build è lento (pre-commit)
# Esce 0 se pulito, 1 se trova qualcosa, 2 se non può misurare (fail-loud).
set -uo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "✗ segreti: non sono in un repo git" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "[⚪] segreti: NON MISURATO — python3 manca" >&2; exit 2; }

CANARINO=1
[ "${1:-}" = "--no-canarino" ] && CANARINO=0

python3 - <<'PY'
import re, subprocess, sys, pathlib

def righe(testo, pos):
    return testo.count("\n", 0, pos) + 1

files = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"],
                       capture_output=True, text=True, check=True).stdout.split("\0")
files = [f for f in files if f and pathlib.Path(f).is_file()]
trovati = []
def rosso(f, riga, regola):
    trovati.append(f"{f}:{riga}: [{regola}]")

CHIAVE = r"[A-Za-z0-9_]*(?:_KEY|_TOKEN|_SECRET)\b"
dart = pathlib.Path("pubspec.yaml").is_file()

for f in files:
    p = pathlib.Path(f)
    try:
        t = p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        continue
    nome = p.name
    # --- TS: il config di Vite (e simili), letto intero
    if re.match(r"(vite|vitest)\.config\.(c|m)?[jt]s$", nome):
        for m in re.finditer(r"\bdefine\s*:\s*\{", t):
            # il blocco fino alla graffa che lo chiude
            i, prof = m.end(), 1
            while i < len(t) and prof:
                prof += {"{": 1, "}": -1}.get(t[i], 0); i += 1
            blocco = t[m.end():i]
            for k in re.finditer(CHIAVE, blocco):
                rosso(f, righe(t, m.end() + k.start()), "define-chiave")
        for m in re.finditer(r"\bloadEnv\s*\((?:[^()]|\([^()]*\))*?,(?:[^()]|\([^()]*\))*?,\s*(''|\"\"|``)\s*\)", t, re.S):
            rosso(f, righe(t, m.start()), "loadenv-senza-prefisso")
    # --- TS: il client che legge una chiave dall'env di Vite
    if re.search(r"\.(c|m)?[jt]sx?$|\.(vue|svelte)$", nome) and not re.match(r"(vite|vitest)\.config\.", nome):
        for m in re.finditer(r"import\s*\.\s*meta\s*\.\s*env\s*\.\s*VITE_[A-Za-z0-9_]*(?:KEY|TOKEN|SECRET)\b", t, re.S):
            rosso(f, righe(t, m.start()), "vite-env-chiave")
    # --- Dart: la chiave passata al build (finisce nell'app)
    if dart:
        for m in re.finditer(r"--dart-define(?:-from-file)?[=\s]+[\"']?([^\s\"']+)", t):
            val = m.group(1)
            if re.search(CHIAVE, val):
                rosso(f, righe(t, m.start()), "dart-define-chiave")
            elif m.group(0).startswith("--dart-define-from-file"):
                q = pathlib.Path(val)
                if q.is_file() and re.search(CHIAVE, q.read_text(encoding="utf-8", errors="replace")):
                    rosso(f, righe(t, m.start()), "dart-define-chiave")
        if nome == "pubspec.yaml":
            for m in re.finditer(r"^\s*-\s*[\"']?([^\s\"'#]+)", t, re.M):
                a = m.group(1).lower()
                if a.endswith(".env") or "/.env" in a or a == ".env" or re.search(r"secret|_key|apikey", a):
                    rosso(f, righe(t, m.start()), "dart-asset-segreto")
    # --- tutti: un .env dentro git
for f in subprocess.run(["git", "ls-files"], capture_output=True, text=True).stdout.split("\n"):
    n = pathlib.Path(f).name
    if re.fullmatch(r"\.env(\..+)?", n) and n != ".env.example":
        rosso(f, 1, "env-tracciato")

for r in trovati:
    print("✗ segreti", r, file=sys.stderr)
if trovati:
    print(f"✗ segreti: {len(trovati)} rilievi (file, riga, regola; il valore non si stampa mai)", file=sys.stderr)
    sys.exit(1)
print("✓ segreti: forma pulita")
PY
rc=$?
[ "$rc" -eq 0 ] || exit "$rc"

# --- il canarino (TS): solo se c'è un build npm e non siamo nel pre-commit
if [ "$CANARINO" = 1 ] && [ -f package.json ]; then
  command -v npm >/dev/null 2>&1 || { echo "[⚪] canarino: NON MISURATO — npm manca" >&2; exit 2; }
  can="canarino1777x$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')"
  # la variabile vera, più ogni *_KEY/_TOKEN/_SECRET dichiarata in .env.example
  vars="GEMINI_API_KEY API_KEY"
  [ -f .env.example ] && vars="$vars $(grep -oE '^[A-Za-z0-9_]*(_KEY|_TOKEN|_SECRET)=' .env.example | tr -d '=' | tr '\n' ' ')"
  envs=(); for v in $vars; do envs+=("$v=$can"); done
  out="$(mktemp -d)"
  if ! env "${envs[@]}" npm run build >"$out/log" 2>&1; then
    echo "✗ canarino: il build è fallito, non posso misurare (log: $out/log)" >&2; exit 2
  fi
  [ -d dist ] || { echo "[⚪] canarino: NON MISURATO — il build non ha prodotto dist/" >&2; exit 2; }
  if grep -rlF "$can" dist/ >"$out/dove"; then
    sed 's/^/✗ segreti [canarino] la chiave finta è nel bundle: /' "$out/dove" >&2
    exit 1
  fi
  rm -rf "$out"
  echo "✓ canarino: nessuna chiave finta nel bundle (variabili: $(echo "$vars" | wc -w))"
fi
exit 0
