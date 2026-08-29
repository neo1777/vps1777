#!/usr/bin/env bash
# tools/backup-pull.sh — TIRA i backup cifrati dalla VPS su un disco tuo (PC, NAS, HD).
#
# Dal tuo PC, non dalla VPS: la VPS non conosce il tuo disco e non deve — «sei tu
# a scegliere dove portarli» (BACKUP-RESTORE.md). Questo è il gesto, scritto una
# volta invece di ricordato: rsync dei due livelli (`backups/*.tar.age` e
# `backups/archivio/`) più i sidecar `.meta`, SENZA `backups/pre-update/` (gli
# snapshot in chiaro per il rollback: grandi, e non devono lasciare la macchina).
#
# Mai `--delete`: la VPS pota per spazio, il tuo disco tiene la storia. Se un
# giorno vuoi potare anche qui, lo fai tu, a mano, guardando.
#
# Uso:
#   bash tools/backup-pull.sh <host-ssh> <cartella-di-destinazione> [<repo sulla VPS>]
#   es.  bash tools/backup-pull.sh vps1777 /media/io/HD/vps1777-backups
#        (`vps1777` è un alias di ~/.ssh/config: l'indirizzo vive lì, non qui)
#
# Esce 2 se la destinazione non esiste (HD non montato): NON è un verde, ed è
# apposta — un pull che «riesce» su una cartella vuota del disco di sistema è
# il modo in cui un backup finisce nel posto sbagliato senza che nessuno lo veda.
set -euo pipefail

HOST="${1:-}"
DEST="${2:-}"
REMOTE_REPO="${3:-/home/vps1777/vps1777}"
if [ -z "$HOST" ] || [ -z "$DEST" ]; then
  printf 'uso: %s <host-ssh> <cartella-di-destinazione> [<repo sulla VPS>]\n' "$0" >&2
  exit 2
fi
if [ ! -d "$DEST" ]; then
  printf '[✗] destinazione assente: %s (HD non montato?) — niente copiato, exit 2\n' "$DEST" >&2
  exit 2
fi
command -v rsync >/dev/null || { echo "[✗] rsync non installato" >&2; exit 1; }

echo "[*] pull da $HOST:$REMOTE_REPO/backups/ → $DEST/"
rsync -a --partial --human-readable --info=progress2,stats1 \
  --include='/vps1777-*.tar.age' --include='/vps1777-*.tar.age.meta' \
  --include='/archivio/' --include='/archivio/vps1777-archivio-*.tar.age' \
  --include='/archivio/vps1777-archivio-*.tar.age.meta' \
  --exclude='*' \
  "$HOST:$REMOTE_REPO/backups/" "$DEST/"

n_core="$(find "$DEST" -maxdepth 1 -name 'vps1777-*.tar.age' | wc -l)"
n_arch="$(find "$DEST/archivio" -maxdepth 1 -name 'vps1777-archivio-*.tar.age' 2>/dev/null | wc -l)"
echo "[✓] sul disco: $n_core backup core · $n_arch backup archivio · $(du -sh "$DEST" | cut -f1) totali"
echo "    per ripristinare: tools/restore.sh <file> (serve la chiave privata age del PC)"
