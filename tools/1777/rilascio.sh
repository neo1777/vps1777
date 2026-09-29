#!/usr/bin/env bash
# rilascio.sh — `mise run release <versione>`: prepara un rilascio IN LOCALE.
# Albero pulito, `check` verde, tag annotato. NON fa push, NON pubblica, NON fa il deploy:
# quelli sono gesti del proprietario del repo, a mano, dopo aver guardato.
set -euo pipefail
ver="${1:-}"
[[ "$ver" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$ ]] || { echo "✗ versione «$ver»: serve X.Y.Z" >&2; exit 2; }
cd "$(git rev-parse --show-toplevel)"
[ -z "$(git status --porcelain)" ] || { echo "✗ l'albero non è pulito: prima un commit" >&2; exit 1; }
git rev-parse -q --verify "refs/tags/v$ver" >/dev/null && { echo "✗ il tag v$ver c'è già" >&2; exit 1; }
mise run check
git tag -a "v$ver" -m "v$ver"
echo "✓ tag v$ver creato in locale. Il push è a mano: git push origin v$ver"
