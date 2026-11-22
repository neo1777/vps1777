#!/usr/bin/env bash
# Il pacchetto di runtime, costruito due volte dagli stessi sorgenti, è lo stesso file (22/11/2026).
#
# Che cosa prova: due copie del repo fatte in momenti diversi, con le date dei file diverse, danno
# la stessa impronta; e la prova SA diventare rossa: con una data diversa l'impronta cambia, e la
# ricetta di prima (`tar czf`, quella che stava in release.yml) dà due impronte diverse.
# Che cosa NON prova: le immagini dei container, che non sono riproducibili per scelta (vedi la testa
# di tools/assembla-pacchetto.sh).
set -uo pipefail
QUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; REPO="$(cd "$QUI/../.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
ESITO=0
ok() { printf '  ✓ %s\n' "$1"; }
ko() { printf '  ✗ %s\n' "$1"; ESITO=1; }

copia() {  # una copia dei soli pezzi che il pacchetto usa, con le date dei file spostate
  mkdir -p "$1/tools"
  ( cd "$REPO" && cp -r compose*.yaml CHANGELOG.md ingress migrations systemd "$1/" \
      && cp -r tools/prove-empiriche tools/assembla-pacchetto.sh "$1/tools/" \
      && for f in backup.sh restore.sh rotate-secret.sh backup-container-setup.sh bootstrap.sh vps1777.py; do cp "tools/$f" "$1/tools/"; done )
  printf '{"gateway": "ghcr.io/example/vps1777-gateway@sha256:%064d"}\n' 0 > "$1/images.lock"
  find "$1" -exec touch -d "$2" {} +
}
impronta() { cut -d' ' -f1 "$1/SHA256SUMS" 2>/dev/null; }

copia "$T/a" "2020-01-02 03:04:05"
copia "$T/b" "2024-06-07 08:09:10"
# La seconda copia ha i permessi di chi clona con umask 077 (trovato da un controllo esterno il
# 22/11/2026: con permessi diversi sui sorgenti il pacchetto usciva diverso). Solo «gruppo e altri»:
# il bit di esecuzione del proprietario è un dato del sorgente e resta.
chmod -R go-rwx "$T/b"
SOURCE_DATE_EPOCH=1700000000 bash "$T/a/tools/assembla-pacchetto.sh" 9.9.9 "$T/out-a" >/dev/null 2>"$T/err-a" || ko "la prima build è fallita: $(cat "$T/err-a")"
( umask 077; SOURCE_DATE_EPOCH=1700000000 bash "$T/b/tools/assembla-pacchetto.sh" 9.9.9 "$T/out-b" >/dev/null 2>"$T/err-b" ) || ko "la seconda build è fallita: $(cat "$T/err-b")"
A="$(impronta "$T/out-a")"; B="$(impronta "$T/out-b")"
if [ "${#A}" -eq 64 ] && [ "$A" = "$B" ]; then ok "due build, stessa impronta ($A)"; else ko "due build, impronte diverse: «$A» e «$B»"; fi
cmp -s "$T/out-a/vps1777-runtime-v9.9.9.tar.gz" "$T/out-b/vps1777-runtime-v9.9.9.tar.gz" || ko "i due pacchetti non sono uguali byte per byte"

# il pacchetto contiene quello che deve (un confronto fra due file vuoti sarebbe un verde falso)
PACCO="$T/out-a/vps1777-runtime-v9.9.9.tar.gz"
ELENCO="$(tar tzf "$PACCO" 2>/dev/null)"
N="$(grep -c . <<<"$ELENCO")"
N_PROVE="$(grep -c '^\./tools/prove-empiriche/prova-[0-9].*\.sh$' <<<"$ELENCO")"
if [ "${N:-0}" -gt 30 ] && grep -qx './tools/vps1777.py' <<<"$ELENCO" && [ "$(tar xzOf "$PACCO" ./VERSION)" = "9.9.9" ]; then
  ok "il pacchetto ha $N voci, l'updater e la versione del tag"
else
  ko "il pacchetto è incompleto ($N voci)"
fi
# H51 (d): le prove empiriche devono arrivare sulla macchina, tutte quelle del repo
N_REPO="$(find "$REPO/tools/prove-empiriche" -maxdepth 1 -name 'prova-[0-9]*.sh' | grep -c .)"
if [ "$N_PROVE" -ge 8 ] && [ "$N_PROVE" -eq "$N_REPO" ]; then
  ok "le $N_PROVE prove empiriche sono dentro il pacchetto"
else
  ko "nel pacchetto ci sono $N_PROVE prove, nel repo $N_REPO"
fi

# controprova 1: la data è un ingresso, quindi cambiandola l'impronta DEVE cambiare
SOURCE_DATE_EPOCH=1700000001 bash "$T/a/tools/assembla-pacchetto.sh" 9.9.9 "$T/out-c" >/dev/null 2>&1
C="$(impronta "$T/out-c")"
if [ "${#C}" -eq 64 ] && [ "$C" != "$A" ]; then
  ok "con un'altra data l'impronta cambia: il confronto sa distinguere"
else
  ko "data diversa, stessa impronta: il confronto non misura niente"
fi

# controprova 2: la ricetta di prima non era ripetibile (se lo fosse, questa prova non proverebbe niente)
tar czf "$T/v1.tgz" -C "$T/a" . && tar czf "$T/v2.tgz" -C "$T/b" .
if cmp -s "$T/v1.tgz" "$T/v2.tgz"; then
  ko "anche «tar czf» dà due file uguali: la prova non distingue la cura dal difetto"
else
  ok "«tar czf» sulle stesse due copie dà due file diversi: era il difetto"
fi

# senza la data dichiarata si rifiuta, non usa l'orologio
( unset SOURCE_DATE_EPOCH; bash "$T/a/tools/assembla-pacchetto.sh" 9.9.9 "$T/out-d" >/dev/null 2>&1 ); RC=$?
if [ "$RC" -eq 2 ] && [ ! -e "$T/out-d/SHA256SUMS" ]; then
  ok "senza SOURCE_DATE_EPOCH esce 2 e non scrive niente"
else
  ko "senza data dichiarata è uscito $RC"
fi

# release.yml usa questa ricetta e non una sua
if grep -q 'bash tools/assembla-pacchetto.sh' "$REPO/.github/workflows/release.yml" && ! grep -q 'tar czf' "$REPO/.github/workflows/release.yml"; then
  ok "release.yml costruisce il pacchetto con questa ricetta"
else
  ko "release.yml non usa tools/assembla-pacchetto.sh (o ha ancora un «tar czf» suo)"
fi
exit "$ESITO"
