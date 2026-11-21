#!/usr/bin/env bash
# Un volume che non si riesce a salvare FERMA il backup (giro di revisione del 21/11/2026).
#
# Prima un `tar` fallito era un avviso («dump fallito (vuoto?)»): lo script stampava «Volumi
# dumpati», cifrava un archivio con dentro solo config e segreti e usciva 0. La ritenzione lo
# contava come la copia della notte e la perdita si scopriva il giorno del restore.
# Qui il backup gira nel contesto CONTAINER (volumi montati, niente docker) con un `tar` finto
# che fallisce su UN volume: deve uscire ≠ 0, nominare il volume e non lasciare archivi.
set -uo pipefail
ROSSO=$'\033[31m'; VERDE=$'\033[32m'; GIALLO=$'\033[33m'; FINE=$'\033[0m'
ok() { printf '  %s✓%s %s\n' "$VERDE" "$FINE" "$1"; }
ko() { printf '  %s✗%s %s\n' "$ROSSO" "$FINE" "$1"; ESITO=1; }
ESITO=0
QUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$QUI/../.." && pwd)"

echo "💥 un dump fallito ferma il backup (test-backup-dump-fallito.sh)"
manca=""
for c in age age-keygen tar; do command -v "$c" >/dev/null || manca="$manca $c"; done
if [ -n "$manca" ]; then
  printf '  %s⊘ SALTATO%s — manca:%s  (exit 2 = non eseguito, NON è un verde)\n' "$GIALLO" "$FINE" "$manca"
  exit 2
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/repo/tools" "$TMP/volumi/buono" "$TMP/volumi/guasto" "$TMP/finti"
cp "$REPO/tools/backup.sh" "$TMP/repo/tools/"
printf 'dato\n' > "$TMP/volumi/buono/a.txt"
printf 'dato\n' > "$TMP/volumi/guasto/b.txt"
age-keygen -o "$TMP/chiave.txt" 2>/dev/null
grep 'public key' "$TMP/chiave.txt" | sed 's/.*: //' > "$TMP/repo/tools/age-recipients.txt"

# il tar finto: fallisce come un disco pieno quando l'archivio da scrivere è quello di «guasto»
VERO_TAR="$(command -v tar)"
cat > "$TMP/finti/tar" <<FINTO
#!/usr/bin/env bash
case "\$*" in *vps1777_guasto.tar*) echo "tar: write error: No space left on device" >&2; exit 1 ;; esac
exec "$VERO_TAR" "\$@"
FINTO
chmod +x "$TMP/finti/tar"

# ① col tar guasto: esito ≠ 0, il volume nominato, nessun archivio
if PATH="$TMP/finti:$PATH" BACKUP_VOLUMES_DIR="$TMP/volumi" \
     bash "$TMP/repo/tools/backup.sh" >"$TMP/backup.log" 2>&1; then
  ko "backup.sh è uscito 0 con un volume non salvato"
else
  ok "backup.sh esce ≠ 0"
fi
if grep -q "guasto" "$TMP/backup.log" && grep -q "No space left" "$TMP/backup.log"; then
  ok "dice quale volume e perché"
else
  ko "non nomina il volume o l'errore di tar"; tail -8 "$TMP/backup.log"
fi
if ls "$TMP/repo/backups"/vps1777-*.tar.age >/dev/null 2>&1; then
  ko "ha lasciato un archivio incompleto in backups/"
else
  ok "nessun archivio incompleto in backups/"
fi

# ② controprova: lo stesso giro col tar vero riesce (il test non passa «per un altro motivo»)
if BACKUP_VOLUMES_DIR="$TMP/volumi" bash "$TMP/repo/tools/backup.sh" >"$TMP/backup2.log" 2>&1 \
   && ls "$TMP/repo/backups"/vps1777-*.tar.age >/dev/null 2>&1; then
  ok "controprova: col tar vero il backup riesce"
else
  ko "controprova fallita: il backup non riesce nemmeno col tar vero"; tail -8 "$TMP/backup2.log"
fi

echo
if [ "$ESITO" -eq 0 ]; then echo "  ✅ passato"; else echo "  ❌ FALLITO"; fi
exit "$ESITO"
