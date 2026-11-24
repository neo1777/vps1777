#!/usr/bin/env bash
# assembla-pacchetto.sh — costruisce il pacchetto di runtime della release, SEMPRE UGUALE a parità di sorgenti.
#
# Perché esiste (22/11/2026). Il pacchetto nasceva da venti righe scritte dentro release.yml: nessuno poteva
# costruirlo due volte e confrontarlo, e `tar czf` ci metteva l'ora della build (nelle date dei file e
# nell'intestazione gzip). Due build dello stesso commit davano due impronte diverse: chi verifica la firma
# sa che il pacchetto viene dalla nostra CI, ma non può rifarlo da sé e ottenere lo stesso file.
# Ora la ricetta sta qui, la usa release.yml e la prova tools/tests/test-pacchetto-riproducibile.sh.
#
# Che cosa è riproducibile e che cosa no. Questo file: sì, byte per byte, dati gli stessi sorgenti, lo
# stesso images.lock e la stessa data (SOURCE_DATE_EPOCH). Le immagini dei container: no, per scelta —
# fanno `apt-get upgrade` per prendere le correzioni uscite dopo la base, quindi sono uguali solo a
# parità di giorno. Il pacchetto le fissa per impronta in images.lock.
#
# Uso:   SOURCE_DATE_EPOCH=<secondi> bash tools/assembla-pacchetto.sh <versione> <cartella-di-uscita>
#        (images.lock deve esistere nella radice del repo: lo scrive release.yml prima di chiamarci)
# Esce:  0 pacchetto e SHA256SUMS scritti nella cartella di uscita · 2 non ho potuto costruirlo
set -euo pipefail
umask 022
export LC_ALL=C TZ=UTC

VERSIONE="${1:-}"; USCITA="${2:-}"
[[ "$VERSIONE" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?$ ]] || { echo "versione mancante o malformata: «$VERSIONE»" >&2; exit 2; }
[ -n "$USCITA" ] || { echo "manca la cartella di uscita" >&2; exit 2; }
RADICE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if ! mkdir -p "$USCITA"; then echo "cartella di uscita non creabile: $USCITA" >&2; exit 2; fi
USCITA="$(cd "$USCITA" && pwd)"
# La data è un ingresso, mai l'orologio: senza, il pacchetto non sarebbe ripetibile e lo diciamo.
[[ "${SOURCE_DATE_EPOCH:-}" =~ ^[0-9]+$ ]] || { echo "SOURCE_DATE_EPOCH mancante: la data del pacchetto si dichiara (es. quella del commit)" >&2; exit 2; }
[ -s "$RADICE/images.lock" ] || { echo "images.lock assente o vuoto in $RADICE" >&2; exit 2; }

LAVORO="$(mktemp -d)"; trap 'rm -rf "$LAVORO"' EXIT
B="$LAVORO/bundle"; mkdir -p "$B/tools"
cd "$RADICE"
cp compose*.yaml CHANGELOG.md images.lock "$B/"
cp -r ingress migrations systemd "$B/"
# VERSION nel pacchetto = versione del TAG, non il file del repo: per le prerelease il repo tiene la
# base (0.9.0 col tag 0.9.0-rc.1) e `vps1777 bootstrap` scaricherebbe un tag che non esiste.
printf '%s\n' "$VERSIONE" > "$B/VERSION"
for f in backup.sh restore.sh rotate-secret.sh backup-container-setup.sh bootstrap.sh vps1777.py sudoers-operatore.sh sudoers-tabella.sh permessi-servizi.sh; do
  cp "tools/$f" "$B/tools/"
done
# H51 (d): le prove empiriche vanno sulla macchina, altrimenti il giorno del guasto non ci sono.
cp -r tools/prove-empiriche "$B/tools/"
# Niente residui di esecuzioni locali: cambierebbero il pacchetto da una macchina all'altra.
find "$B" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$B" -name '*.pyc' -delete

VERSION="$VERSIONE" python3 - "$B" <<'PY'
import hashlib, json, os, sys
root = sys.argv[1]
files = {}
for dirpath, _, names in os.walk(root):
    for n in sorted(names):
        p = os.path.join(dirpath, n)
        with open(p, "rb") as fh:
            files[os.path.relpath(p, root)] = hashlib.sha256(fh.read()).hexdigest()
with open(os.path.join(root, "bundle-manifest.json"), "w") as fh:
    json.dump({"version": os.environ["VERSION"], "files": files}, fh, indent=2, sort_keys=True)
PY

NOME="vps1777-runtime-v${VERSIONE}.tar.gz"
# Ordine dei nomi, data, proprietario, permessi e intestazione gzip fissati: sono le cose che cambiano
# da una build all'altra senza che cambi una riga dei sorgenti. I permessi: 644, o 755 per ciò che è
# eseguibile nel sorgente; senza, un clone fatto con umask 077 dava un pacchetto diverso.
tar --sort=name --mtime="@${SOURCE_DATE_EPOCH}" --owner=0 --group=0 --numeric-owner --mode=u+rw,go=rX \
    --format=gnu -cf - -C "$B" . | gzip -n -9 > "$USCITA/$NOME"
[ -s "$USCITA/$NOME" ] || { echo "il pacchetto è vuoto" >&2; exit 2; }
( cd "$USCITA" && sha256sum "$NOME" > SHA256SUMS && cat SHA256SUMS )
