#!/usr/bin/env bash
# lint.sh — il `mise run lint` di vps1777: le due righe veloci del job lint della CI.
#   1. ruff 0.15.22 (la versione pinnata in ci.yml) su services/ tools/ security/
#   2. shellcheck con la STESSA immagine per digest della CI, sullo stesso perimetro:
#      `git ls-files '*.sh'` più i file tracciati con uno shebang bash/sh.
# Il resto del job lint (rilievi, installer, anti-leak, doc, compose) sta in `mise run check`.
#
# Perché uno script: `${#S[@]}` in un `run` di mise apre un commento Tera (regola 1 in
# testa a mise.toml; nella prova del template su questo repo aveva fermato il task).
set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 2

uvx ruff@0.15.22 check services/ tools/ security/ || exit 1

mapfile -t S < <({
  git ls-files '*.sh'
  git ls-files | while IFS= read -r f; do
    [ -f "$f" ] || continue
    case "$f" in *.sh) continue ;; esac
    head -1 "$f" 2>/dev/null | grep -qaE '^#!.*\b(ba)?sh\b' && printf '%s\n' "$f"
  done
} | sort -u)
echo "shellcheck su ${#S[@]} script"
docker run --rm -v "$PWD:/mnt" -w /mnt \
  koalaman/shellcheck@sha256:61862eba1fcf09a484ebcc6feea46f1782532571a34ed51fedf90dd25f925a8d "${S[@]}"
