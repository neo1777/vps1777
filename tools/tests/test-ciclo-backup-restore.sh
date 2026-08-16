#!/usr/bin/env bash
# Il CICLO VERO: backup → cifra → svuota → restore → i dati ci sono ancora.
#
# 🔴 PERCHÉ ESISTE — voce 7f76bfc9 del registro (aperta il 10/08, mandato di @Neo:
#    «preparalo al meglio poi lo verificheremo dopo la formattazione della vps»).
#    Il 16/08 il ciclo è stato eseguito A MANO ed è andato: backup exit 0, restore,
#    sha256 identici. Ma **una prova fatta a mano non lascia un presidio**: il giorno
#    dopo nessuno sa più se vale, e chi legge il repo trova solo test che ANALIZZANO
#    i due script senza eseguirli — `test_backup_copre_i_volumi_dichiarati` li legge
#    con `read_text()`, `test-backup-retention` prova la CANCELLAZIONE, e i test
#    statici controllano la coerenza del sorgente.
#    ⇒ misurato il 17/08: **nessun test eseguiva il ciclo**. Questo lo esegue.
#
# 🔑 COME È ISOLATO, e ognuno dei tre modi risponde a un rischio misurato:
#    ① il repo è una COPIA in tmp (solo `tools/`): `backup.sh` e `restore.sh` tarano
#       REPO_ROOT da `$SCRIPT_DIR/..`, quindi BACKUP_DIR, il file dei recipient e il
#       `cd` finiscono tutti nella copia. Di riflesso `docker compose down` di
#       restore.sh (r.109, INCONDIZIONATO) gira in una dir SENZA compose.yaml e non
#       ha nulla da fermare — su questa macchina c'è un container vivo di un altro
#       progetto, e non deve nemmeno sfiorarlo.
#    ② i volumi si chiamano `vps1777_provaciclo-<pid>-*`: `restore.sh` normalizza
#       SEMPRE a `vps1777_<nome>` (r.171), quindi l'isolamento non può stare nel
#       progetto compose — deve stare nel NOME, ed essere riconoscibile a occhio.
#    ③ la chiave age è generata qui e buttata: il ciclo prova la cifratura VERA
#       senza toccare la chiave di produzione.
#
# ⚠️ E la pulizia è un `trap`, non l'ultima riga: il 16/08 la prova a mano ha lasciato
#    tre volumi `vps1777_prova-br-*` sul sistema, trovati il giorno dopo. *L'ultimo
#    metro si paga in tracce.*
set -euo pipefail

ROSSO=$'\033[31m'; VERDE=$'\033[32m'; GIALLO=$'\033[33m'; FINE=$'\033[0m'
ok()   { printf '  %s✓%s %s\n' "$VERDE" "$FINE" "$1"; }
ko()   { printf '  %s✗%s %s\n' "$ROSSO" "$FINE" "$1"; ESITO=1; }
info() { printf '    %s\n' "$1"; }
ESITO=0

QUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$QUI/../.." && pwd)"
MARCA="provaciclo-$$"
VOLUMI=("vps1777_${MARCA}-alfa" "vps1777_${MARCA}-beta")
TMP=""

# shellcheck disable=SC2329  # invocata dal `trap` qui sotto: shellcheck non lo vede.
#   La disable è sull'INVOCAZIONE mancante, non sul contenuto — e sta scritta perché il
#   gate pre-commit locale è più severo della CI (rifiuta anche gli `info`), quindi il
#   prossimo che tocca questo file lo scoprirebbe con un commit respinto.
pulisci() {
  local rc=$?
  for v in "${VOLUMI[@]}"; do docker volume rm -f "$v" >/dev/null 2>&1 || true; done
  [ -n "$TMP" ] && rm -rf "$TMP"
  return "$rc"
}
trap pulisci EXIT

echo "🔄 ciclo backup → restore (test-ciclo-backup-restore.sh)"
echo

# ───── prerequisiti: SALTARE non è passare ─────
# Un test che non può girare deve dirlo con un exit code suo (2), non uscire 0:
# «verde» e «non eseguito» si leggono uguali in un log di CI, ed è il modo in cui un
# presidio smette di proteggere senza che nessuno se ne accorga.
manca=""
for c in docker age tar; do command -v "$c" >/dev/null || manca="$manca $c"; done
if [ -n "$manca" ]; then
  printf '  %s⊘ SALTATO%s — manca:%s\n' "$GIALLO" "$FINE" "$manca"
  echo "    (exit 2 = non eseguito. NON è un verde.)"
  exit 2
fi
docker info >/dev/null 2>&1 || {
  printf '  %s⊘ SALTATO%s — docker non risponde (demone spento o niente permessi)\n' "$GIALLO" "$FINE"
  exit 2
}

TMP="$(mktemp -d)"
mkdir -p "$TMP/repo/tools" "$TMP/volumi/${MARCA}-alfa/sotto" "$TMP/volumi/${MARCA}-beta"
cp "$REPO/tools/backup.sh" "$REPO/tools/restore.sh" "$TMP/repo/tools/"

# ───── i dati da salvare: contenuto noto, di cui conosciamo lo sha ─────
printf 'dato alfa, riga uno\n' > "$TMP/volumi/${MARCA}-alfa/uno.txt"
printf 'dato alfa, annidato\n' > "$TMP/volumi/${MARCA}-alfa/sotto/due.txt"
head -c 4096 /dev/urandom          > "$TMP/volumi/${MARCA}-alfa/binario.bin"
printf 'dato beta\n'               > "$TMP/volumi/${MARCA}-beta/tre.txt"
ATTESO="$(cd "$TMP/volumi" && find . -type f -print0 | sort -z \
          | xargs -0 sha256sum | sha256sum | cut -d' ' -f1)"
info "impronta dei dati di partenza: ${ATTESO:0:16}…  (4 file su 2 volumi)"

# ───── chiave age di prova, usata e buttata ─────
age-keygen -o "$TMP/chiave.txt" 2>/dev/null
grep 'public key' "$TMP/chiave.txt" | sed 's/.*: //' > "$TMP/repo/tools/age-recipients.txt"
[ -s "$TMP/repo/tools/age-recipients.txt" ] || { ko "age-keygen non ha dato una chiave"; exit 1; }

# ───── ① BACKUP ─────
if BACKUP_VOLUMES_DIR="$TMP/volumi" bash "$TMP/repo/tools/backup.sh" >"$TMP/backup.log" 2>&1; then
  ok "backup.sh esce 0"
else
  ko "backup.sh è fallito (rc $?)"; sed 's/^/      /' "$TMP/backup.log" | tail -15; exit 1
fi
# nomi generati da backup.sh (timestamp): nessun carattere strano — stessa disable di restore.sh:64
# shellcheck disable=SC2012
ARCHIVIO="$(ls -1t "$TMP/repo/backups"/vps1777-*.tar.age 2>/dev/null | head -1 || true)"
[ -n "$ARCHIVIO" ] || { ko "nessun archivio prodotto in backups/"; exit 1; }
ok "archivio cifrato: $(basename "$ARCHIVIO") ($(du -h "$ARCHIVIO" | cut -f1))"

# la cifratura è VERA: il contenuto in chiaro non si legge nell'archivio
if grep -qa 'dato alfa, riga uno' "$ARCHIVIO"; then
  ko "il testo in chiaro si legge DENTRO l'archivio: non è cifrato"
else
  ok "il testo in chiaro non compare nell'archivio (cifratura age applicata)"
fi

# ───── ② SVUOTA: i volumi di destinazione non esistono ─────
for v in "${VOLUMI[@]}"; do docker volume rm -f "$v" >/dev/null 2>&1 || true; done
esistenti="$(docker volume ls -q | grep -cE "^vps1777_${MARCA}-" || true)"
# if-then-else e non `A && ok || ko`: in quella forma un `ok` che fallisse farebbe
# partire ANCHE il `ko` (SC2015), e in un file il cui unico prodotto è un verdetto
# la fragilità sta proprio lì.
if [ "$esistenti" = "0" ]; then
  ok "partenza pulita: 0 volumi ${MARCA}"
else
  ko "c'erano già $esistenti volumi ${MARCA}"
fi

# ───── ③ RESTORE ─────
if AGE_KEY="$TMP/chiave.txt" bash "$TMP/repo/tools/restore.sh" --yes \
     --volumes-only "${VOLUMI[0]},${VOLUMI[1]}" "$ARCHIVIO" >"$TMP/restore.log" 2>&1; then
  ok "restore.sh esce 0"
else
  ko "restore.sh è fallito (rc $?)"; sed 's/^/      /' "$TMP/restore.log" | tail -20; exit 1
fi

# ───── ④ I DATI CI SONO ANCORA? il confronto è sui byte, non sui nomi ─────
mkdir -p "$TMP/riletto"
for v in "${VOLUMI[@]}"; do
  corto="${v#vps1777_}"
  mkdir -p "$TMP/riletto/$corto"
  docker run --rm -v "$v:/src:ro" -v "$TMP/riletto/$corto:/dst" \
    --entrypoint sh busybox:latest -c 'cp -a /src/. /dst/ 2>/dev/null || true' >/dev/null
done
RILETTO="$(cd "$TMP/riletto" && find . -type f -print0 | sort -z \
           | xargs -0 sha256sum | sha256sum | cut -d' ' -f1)"
if [ "$RILETTO" = "$ATTESO" ]; then
  ok "i dati ripristinati sono IDENTICI: sha ${RILETTO:0:16}…"
else
  ko "i dati ripristinati DIFFERISCONO"
  info "atteso  ${ATTESO:0:16}…"
  info "riletto ${RILETTO:0:16}…"
  info "file di partenza: $(cd "$TMP/volumi" && find . -type f | wc -l) · riletti: $(cd "$TMP/riletto" && find . -type f | wc -l)"
fi

# ⑤ la controprova che il confronto sappia dire di NO: se cambio un byte, deve differire.
# Senza, un'impronta calcolata male darebbe «identici» su qualunque cosa — è la forma
# che il 10/08 ci ha dato una CONFERMA FALSA (un predicato che non può fallire afferma).
printf 'x' >> "$TMP/riletto/${MARCA}-beta/tre.txt"
SPORCO="$(cd "$TMP/riletto" && find . -type f -print0 | sort -z \
          | xargs -0 sha256sum | sha256sum | cut -d' ' -f1)"
if [ "$SPORCO" != "$ATTESO" ]; then
  ok "controprova: un byte cambiato ⇒ l'impronta cambia"
else
  ko "controprova FALLITA: l'impronta non distingue i contenuti"
fi

echo
if [ "$ESITO" = 0 ]; then
  printf '%s✅ il ciclo backup → restore funziona end-to-end%s\n' "$VERDE" "$FINE"
else
  printf '%s⛔ il ciclo backup → restore è ROTTO%s\n' "$ROSSO" "$FINE"
fi
exit "$ESITO"
