#!/usr/bin/env bash
# release.sh — il `mise run release <v>` di vps1777: i controlli di CONTRIBUTING («Releasing»)
# prima di passare la mano a tools/1777/rilascio.sh del contratto (albero pulito, check verde,
# tag annotato, NIENTE push: il tag lo spinge chi mantiene il repo, e release.yml costruisce, firma e pubblica).
set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 2

v="${1:-}"
if [ -z "$v" ]; then echo "✗ serve la versione, per esempio 0.63.5" >&2; exit 2; fi
if [ "$(git branch --show-current)" != main ]; then
  echo "✗ si tagga solo su main (CONTRIBUTING, Releasing)" >&2; exit 1
fi
if [ "$(cat VERSION)" != "$v" ]; then
  echo "✗ VERSION dice $(cat VERSION), non $v: il bump passa da una PR (CONTRIBUTING)" >&2; exit 1
fi
if ! grep -qF "## [$v]" CHANGELOG.md; then
  echo "✗ manca la sezione ## [$v] in CHANGELOG.md" >&2; exit 1
fi
exec bash tools/1777/rilascio.sh "$v"
