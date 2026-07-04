#!/usr/bin/env bash
# tools/bootstrap.sh — cutover one-shot di un'installazione vps1777 legacy
# (immagini buildate in locale) al canale di update controllato (pull da ghcr).
#
# Come si usa (dalla shell della VPS, come utente operatore vps1777):
#   cd ~/vps1777
#   VER=X.Y.Z   # ultima release: https://github.com/neo1777/vps1777/releases
#   curl -fsSLO "https://github.com/neo1777/vps1777/releases/download/v${VER}/vps1777-runtime-v${VER}.tar.gz"
#   curl -fsSLO "https://github.com/neo1777/vps1777/releases/download/v${VER}/SHA256SUMS"
#   sha256sum -c SHA256SUMS                       # verifica ESPLICITA — mai curl|bash
#   mkdir -p /tmp/vps1777-bundle && tar xzf "vps1777-runtime-v${VER}.tar.gz" -C /tmp/vps1777-bundle
#   bash /tmp/vps1777-bundle/tools/bootstrap.sh
#
# Questo wrapper è deliberatamente sottile: tutta la logica (backup, install
# CLI+unit, sync file, pull+verifica digest, cutover, health-gate, ripristino
# su fallimento) vive in `vps1777 bootstrap` — così viaggia in ogni bundle
# e resta un solo code path. Vedi docs/UPDATE.md.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Il bundle estratto ha bundle-manifest.json alla radice.
[ -f "$BUNDLE_DIR/bundle-manifest.json" ] || {
  echo "[✗] $BUNDLE_DIR non sembra un bundle estratto (manca bundle-manifest.json)" >&2
  echo "    Estrai il tarball della release e rilancia da lì." >&2
  exit 1
}

# Repo: $VPS1777_HOME > /home/vps1777/vps1777 > cwd (se ha compose.yaml)
REPO="${VPS1777_HOME:-}"
if [ -z "$REPO" ]; then
  if [ -f /home/vps1777/vps1777/compose.yaml ]; then
    REPO=/home/vps1777/vps1777
  elif [ -f "$PWD/compose.yaml" ]; then
    REPO="$PWD"
  else
    echo "[✗] repo vps1777 non trovato — esporta VPS1777_HOME=/path/del/repo" >&2
    exit 1
  fi
fi

command -v python3 >/dev/null || { echo "[✗] python3 mancante" >&2; exit 1; }

exec python3 "$BUNDLE_DIR/tools/vps1777.py" --home "$REPO" bootstrap --bundle "$BUNDLE_DIR" "$@"
