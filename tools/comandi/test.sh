#!/usr/bin/env bash
# test.sh — il `mise run test` di vps1777: le suite UNA ALLA VOLTA, come nel job contract della CI.
#
# Perché uno script e non un `run` inline: mise passa ogni `run` per Tera, e la logica bash
# (`${#…}`, `{{`) lì dentro rompe il task e chi ne dipende (`check`). Il `run` chiama, la
# logica sta qui (regola 1 in testa a mise.toml).
#
# Perché una alla volta: tools/tests e archive-mcp importano tutte e due un pacchetto `app`
# (CONTRIBUTING), e nella stessa invocazione di pytest si pestano.
#
# Il filtro (facoltativo, $1) va a `pytest -k`. pytest esce 5 quando non seleziona niente:
# col filtro, 5 in una suite vuol dire «non è qui»; il comando esce 5 solo se il filtro non
# trova nessun test in NESSUNA suite (K-b). Col filtro i test bash non girano.
#
# USO: bash tools/comandi/test.sh [filtro]      (dalla radice, di solito via `mise run test`)
set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 2

filtro="${1:-}"
k=()
if [ -n "$filtro" ]; then k=(-k "$filtro"); fi
trovati=0
rossi=0

suite() {
  local rc
  echo "── $*"
  "$@" -q "${k[@]}"
  rc=$?
  case "$rc" in
    0) trovati=$((trovati + 1)) ;;
    5) if [ -z "$filtro" ]; then rossi=$((rossi + 1)); fi ;;
    *) rossi=$((rossi + 1)) ;;
  esac
}

# le stesse righe del job contract (ci.yml), nello stesso ordine
suite uv run --locked --directory services/nb1777-mcp pytest tests/
suite uvx pytest services/gateway/tests/
suite uv run --locked --directory services/gateway --with pytest pytest tests_runtime/
suite uvx pytest services/archive-mcp/tests/
suite uv run --locked --directory services/archive-mcp --with pytest pytest tests/test_health.py \
  tests/test_superficie_tool.py tests/test_costruisci_indice.py tests/test_ibrida_verifica.py tests/test_sessioni.py
suite uvx --with bcrypt --with cryptography pytest tools/tests/

# i test bash girano qui; l'autoprova del runner (che sappia fallire) sta in `mise run check`,
# accanto alle altre autoprove dei presìdi: è un controllo del presidio, non un test.
if [ -z "$filtro" ]; then
  echo "── test bash"
  bash tools/esegui-test-bash.sh || rossi=$((rossi + 1))
fi

if [ "$rossi" -gt 0 ]; then
  echo "✗ test: $rossi suite rosse"
  exit 1
fi
if [ -n "$filtro" ] && [ "$trovati" -eq 0 ]; then
  echo "✗ test: il filtro «$filtro» non trova nessun test in nessuna suite (K-b)"
  exit 5
fi
echo "✓ test: $trovati suite verdi"
