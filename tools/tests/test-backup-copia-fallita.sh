#!/usr/bin/env bash
# Un file del core che c'è e non si copia FERMA il backup (prova A, fetta 06, 22/11/2026).
#
# Il gemello del dump fallito, rimasto fuori dalla cura del 21/11: `cp … || warn` (o `|| true`) e
# poi un «Config + secrets archiviati» incondizionato. Un backup senza i segreti non si
# ripristina, e usciva 0. Qui il backup gira nel contesto CONTAINER con un `cp` finto che
# fallisce sui segreti: deve uscire ≠ 0, dirlo e non lasciare archivi. Col `cp` vero deve riuscire.
set -uo pipefail
ROSSO=$'\033[31m'; VERDE=$'\033[32m'; GIALLO=$'\033[33m'; FINE=$'\033[0m'
ok() { printf '  %s✓%s %s\n' "$VERDE" "$FINE" "$1"; }
ko() { printf '  %s✗%s %s\n' "$ROSSO" "$FINE" "$1"; ESITO=1; }
ESITO=0
QUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$QUI/../.." && pwd)"

echo "💥 una copia fallita ferma il backup (test-backup-copia-fallita.sh)"
manca=""
for c in age age-keygen tar; do command -v "$c" >/dev/null || manca="$manca $c"; done
if [ -n "$manca" ]; then
  printf '  %s⊘ SALTATO%s — manca:%s  (exit 2 = non eseguito, NON è un verde)\n' "$GIALLO" "$FINE" "$manca"
  exit 2
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/repo/tools" "$TMP/repo/secrets" "$TMP/volumi/buono" "$TMP/finti"
cp "$REPO/tools/backup.sh" "$TMP/repo/tools/"
printf 'dato\n' > "$TMP/volumi/buono/a.txt"
printf 'X=1\n' > "$TMP/repo/.env"
printf 'finto\n' > "$TMP/repo/secrets/uno.txt"
age-keygen -o "$TMP/chiave.txt" 2>/dev/null
grep 'public key' "$TMP/chiave.txt" | sed 's/.*: //' > "$TMP/repo/tools/age-recipients.txt"

# il cp finto: fallisce come un disco pieno quando la destinazione è la cartella dei segreti
VERO_CP="$(command -v cp)"
cat > "$TMP/finti/cp" <<FINTO
#!/usr/bin/env bash
case "\${!#}" in */secrets/) echo "cp: errore di scrittura: No space left on device" >&2; exit 1 ;; esac
exec "$VERO_CP" "\$@"
FINTO
chmod +x "$TMP/finti/cp"

# ① col cp guasto: esito ≠ 0, la copia nominata, nessun «archiviati», nessun archivio
if PATH="$TMP/finti:$PATH" BACKUP_VOLUMES_DIR="$TMP/volumi" \
     bash "$TMP/repo/tools/backup.sh" >"$TMP/backup.log" 2>&1; then
  ko "backup.sh è uscito 0 senza aver copiato i segreti"
else
  ok "backup.sh esce ≠ 0"
fi
if grep -q "secrets/\*.txt" "$TMP/backup.log" && grep -q "No space left" "$TMP/backup.log"; then
  ok "dice quale copia e perché"
else
  ko "non nomina la copia fallita o l'errore"; tail -8 "$TMP/backup.log"
fi
if grep -q "Config + secrets archiviati" "$TMP/backup.log"; then
  ko "ha detto «archiviati» con una copia fallita"
else
  ok "non dice «archiviati»"
fi
if ls "$TMP/repo/backups"/vps1777-*.tar.age >/dev/null 2>&1; then
  ko "ha lasciato un archivio incompleto in backups/"
else
  ok "nessun archivio incompleto in backups/"
fi

# ② col cp vero: riesce, e l'archivio c'è (il test non è rosso per costruzione)
if BACKUP_VOLUMES_DIR="$TMP/volumi" bash "$TMP/repo/tools/backup.sh" >"$TMP/backup2.log" 2>&1 \
   && ls "$TMP/repo/backups"/vps1777-*.tar.age >/dev/null 2>&1; then
  ok "col cp vero il backup riesce e scrive l'archivio"
else
  ko "col cp vero il backup NON riesce"; tail -8 "$TMP/backup2.log"
fi
exit "$ESITO"
