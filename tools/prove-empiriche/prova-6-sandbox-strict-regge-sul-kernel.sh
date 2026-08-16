#!/usr/bin/env bash
# prova-6-sandbox-strict-regge-sul-kernel.sh — la proposta ②-1 del round-4 REGGE sul kernel?
#
# 🔀 NATA COME «prova-5» E RINOMINATA, perché due sessioni hanno scritto una prova-5
#   nello stesso minuto (16:58 del 26/07) sullo stesso bersaglio. I due script NON
#   sono lo stesso test e nessuno dei due va buttato:
#     · prova-5-sandbox-update-service.sh  → OSSERVA senza toccare: enumera dal
#       sorgente i path che l'update dichiara di scrivere, guarda se ~/.sigstore
#       esiste, controlla che l'ultimo backup abbia CONTENUTO.
#     · questa (prova-6)                  → COSTRUISCE la sandbox proposta con
#       systemd-run e misura cosa il kernel consente e cosa nega, con controprova.
#   ⇒ la 5 dice «cosa serve», la 6 dice «se la stretta lo permette». Servono entrambe,
#   e in quest'ordine. *Ho rinominato solo il MIO file: il lavoro di un'altra non lo
#   sposto io.* (setaccio)
#
# LA PROPOSTA (audio round-4, esito ② sul bersaglio-1 / H43): invece di rinunciare
#   al sandboxing filesystem su `vps1777-update.service`, applicare
#   `ProtectSystem=strict` + `ReadWritePaths=` espliciti. L'audio propone quattro
#   path: /usr/local/bin, /etc/systemd/system, /var/lib/gateway, la home utente.
#
# ⚠️ PERCHÉ QUESTA PROVA ESISTE, E NON È UNA FORMALITÀ. Le quattro ragioni che la
#   unit dichiara e i quattro path della proposta hanno lo STESSO NUMERO e un
#   INSIEME DIVERSO (misurato elemento-per-elemento, non sul totale):
#     · /tmp             → MANCA nella proposta, e la unit lo dichiara come il caso
#                          il cui fallimento è SILENZIOSO: backup.sh/restore.sh
#                          passano un `mktemp -d` come SORGENTE di un bind-mount
#                          `docker run`, e il mount lo risolve il DEMONE docker,
#                          fuori dal /tmp privato dell'unit ⇒ «il dump/restore
#                          leggerebbe una dir vuota e il backup (o l'auto-rollback)
#                          si romperebbe in silenzio».
#     · /var/lib/gateway → NON è nella unit: nel repo è un mount point DENTRO il
#                          container (compose.yaml: gateway-data:/var/lib/gateway).
#                          La unit gira sull'HOST. Un ReadWritePaths= su un path
#                          host inesistente IMPEDISCE L'AVVIO della unit (serve il
#                          prefisso `-`) ⇒ la stretta pensata per proteggere
#                          l'updater può impedire all'updater di partire.
#     · ~/.sigstore      → è l'unica delle quattro ragioni che la unit stessa marca
#                          come NON verificata: «non verificabile su questa
#                          macchina, quindi non si azzarda».
#
# COSA MISURA, e il come conta più del cosa: NON lancia l'updater. Costruisce la
#   sandbox proposta con `systemd-run` e prova a SCRIVERE nei path — così misura il
#   MECCANISMO (cosa il kernel consente e cosa nega) invece dell'applicazione. Più
#   una CONTROPROVA NEGATIVA: una scrittura in un path che deve essere negato. Un
#   test che vede solo dei PASS non ha dimostrato di saper vedere un FAIL.
#
# COSA NON PROVA, dichiarato: che l'update REALE non scriva in path che qui non
#   sono elencati (un mktemp annidato, una cache docker che cambia nome fra
#   versioni). Quello richiede un update vero sotto tracciamento delle scritture, ed
#   è una decisione di chi possiede il server — non di uno script. ⇒ questa prova
#   dice se la proposta è SBAGLIATA; non può dire che è COMPLETA.
#
# EXIT: 0 = tutti i path necessari sono scrivibili sotto la sandbox e la controprova
#           nega ciò che deve negare  ·  1 = almeno un path necessario è NEGATO
#           (⇒ la proposta romperebbe l'update o il backup)  ·  2 = non eseguibile.
set -uo pipefail

REPO="${VPS1777_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
UNIT="$REPO/systemd/vps1777-update.service"
HOME_DIR="${HOME:-/root}"

echo "── prova-6 · la sandbox proposta regge sul kernel?   $(date '+%F %T')"
echo "   repo: $REPO"

# ─── prerequisiti: senza questi non si misura, e «non misurato» non è «PASS» ───
command -v systemd-run >/dev/null 2>&1 || {
  echo "   ✗ systemd-run assente ⇒ la sandbox non si può costruire. Serve una macchina con systemd."; exit 2; }
if [ "$(id -u)" -ne 0 ] && ! sudo -n true 2>/dev/null; then
  echo "   ✗ serve root o sudo -n: la unit reale gira con User= e ProtectSystem si applica al servizio."
  echo "   ⇒ NON è un PASS: è un'assenza di dato. Rilancia con sudo."; exit 2
fi
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo -n"
[ -f "$UNIT" ] || { echo "   ✗ unit non trovata: $UNIT (usa VPS1777_REPO=<path>)"; exit 2; }

# ─── ① il DELTA fra le ragioni dichiarate nella unit e i path della proposta ───
# Si legge dalla unit, non dalla memoria di chi scrive: se il file cambia, cambia la prova.
echo
echo "   ① DELTA — cosa la unit dichiara vs cosa la proposta copre"
for p in /usr/local/bin /etc/systemd/system /tmp "$HOME_DIR/.sigstore"; do
  if grep -q -- "$p" "$UNIT" 2>/dev/null || { [ "$p" = "$HOME_DIR/.sigstore" ] && grep -q '\.sigstore' "$UNIT"; }; then
    printf '      %-28s dichiarato nella unit\n' "$p"
  else
    printf '      %-28s ⚠️  NON dichiarato nella unit\n' "$p"
  fi
done
if grep -q '/var/lib/gateway' "$UNIT" 2>/dev/null; then
  echo "      /var/lib/gateway             presente nella unit (⇒ il reperto del round-4 è superato: riverifica)"
else
  echo "      /var/lib/gateway             🔴 assente dalla unit — proposto dall'audio, mai dichiarato qui"
  if [ -d /var/lib/gateway ]; then
    echo "                                   ma ESISTE sull'host ⇒ un ReadWritePaths= non impedirebbe l'avvio"
  else
    echo "                                   e NON esiste sull'host ⇒ ReadWritePaths=/var/lib/gateway"
    echo "                                   IMPEDISCE L'AVVIO della unit (serve il prefisso '-')"
  fi
fi

# ─── ② la sandbox proposta, costruita e messa alla prova ───
# I path NECESSARI includono /tmp: è la ragione che la proposta omette, ed è quella
# il cui fallimento è silenzioso. Se /tmp è negato, il verdetto è FAIL.
RWP="/usr/local/bin /etc/systemd/system /tmp $HOME_DIR"
echo
echo "   ② SANDBOX — ProtectSystem=strict + ReadWritePaths=$RWP"
props=(--property=ProtectSystem=strict)
for p in $RWP; do props+=("--property=ReadWritePaths=$p"); done

prova_scrittura() {  # <path> <atteso: ok|negato>
  local dir="$1" atteso="$2" f rc
  f="$dir/.prova5-$$"
  $SUDO systemd-run --quiet --wait --collect --pipe "${props[@]}" \
        /bin/sh -c "touch '$f' 2>/dev/null && rm -f '$f'" >/dev/null 2>&1
  rc=$?
  if [ "$atteso" = "ok" ]; then
    if [ $rc -eq 0 ]; then printf '      %-28s scrivibile        ✅\n' "$dir"; return 0
    else                   printf '      %-28s NEGATO            🔴  (la proposta romperebbe questo)\n' "$dir"; return 1; fi
  else
    if [ $rc -ne 0 ]; then printf '      %-28s negato            ✅ (controprova: la sandbox MORDE)\n' "$dir"; return 0
    else                   printf '      %-28s scrivibile        🔴 (controprova FALLITA: non isola niente)\n' "$dir"; return 1; fi
  fi
}

falliti=0
for d in /usr/local/bin /etc/systemd/system /tmp "$HOME_DIR"; do
  [ -d "$d" ] || { printf '      %-28s inesistente sull'\''host — salto\n' "$d"; continue; }
  prova_scrittura "$d" ok || falliti=$((falliti+1))
done
# CONTROPROVA NEGATIVA, obbligatoria: se questa passa, tutte le altre non valgono niente.
for d in /etc /usr/bin; do
  prova_scrittura "$d" negato || falliti=$((falliti+1))
done

# ─── ③ il caso silenzioso: il bind-mount del backup vede DATI, non un exit code ───
echo
echo "   ③ IL CASO SILENZIOSO — mktemp + bind-mount del backup"
non_misurato=0
if grep -q 'mktemp -d' "$REPO/tools/backup.sh" 2>/dev/null; then
  echo "      backup.sh usa mktemp -d          ✅ confermato sul file (la ragione della unit è reale)"
  echo "      ⚠️  E QUI L'EXIT CODE NON BASTA: sotto PrivateTmp/ProtectSystem il demone docker"
  echo "         risolve il bind-mount FUORI dal /tmp del servizio ⇒ il dump può risultare VUOTO"
  echo "         con rc=0. Chi verifica la stretta deve guardare la DIMENSIONE del dump prodotto,"
  echo "         non il suo codice di uscita. Questa prova non lo fa: lanciare un backup reale"
  echo "         è una decisione di chi possiede il server."
  non_misurato=1
else
  echo "      ⚠️  'mktemp -d' non trovato in tools/backup.sh — la ragione dichiarata nella unit"
  echo "         va riverificata: o il file è cambiato, o il repo è un altro."
  non_misurato=1
fi

# ─── verdetto ───
echo
if [ "$falliti" -gt 0 ]; then
  echo "🔴 FAIL — $falliti prove non attese. La proposta ②-1 NON si committa così com'è."
  echo "   Se il negato è /tmp: la stretta rompe il BACKUP, non l'update — e in silenzio."
  exit 1
fi
# 🔴 IL DIFETTO CHE CHIUDE (abdd732a, 02/08, MISURATO lanciando tutte e nove le prove
#   su un PC che il sistema NON ha): otto davano `exit 2` — «non eseguibile» — e questa
#   dava `exit 0`, cioè **un PASS su una macchina dove non c'era niente da misurare**.
# ⭐ E la ragione non era un prerequisito mancante: era che il §③ QUI SOPRA DICHIARA di
#   non aver misurato il caso silenzioso («questa prova non lo fa») e l'esito restava
#   comunque un ✅ verde. *La prova sapeva di non aver guardato, e diceva di sì.*
# 🔑 Il contratto della famiglia è dichiarato in `prova-8` e rispettato da
#   `lancia-tutte.sh:76` — **0 = PASS · 1 = FAIL · 2 = non eseguibile** — e mancava
#   il quarto stato reale: «misurato in PARTE». Mapparlo su 0 afferma più di quanto
#   si è visto; mapparlo su 1 sarebbe un falso rosso su un meccanismo che regge.
#   ⇒ va su **2**, che nel contratto significa esattamente «non ho potuto guardare
#     tutto», ed è l'unico esito che non mente in nessuna delle due direzioni.
# ⚠️ Conseguenza dichiarata, perché è un costo vero: **finché il caso silenzioso non è
#   misurabile, questa prova non darà MAI 0.** Non è un difetto della cura — è che il
#   §③ richiede un backup reale sul server, e nessuno l'ha ancora fatto. Il giorno che
#   qualcuno lo esegue e guarda la DIMENSIONE del dump, questo ramo diventa un PASS
#   pieno. *Una prova che non può passare finché manca una misura è il modo giusto di
#   ricordare che la misura manca: un verde se la dimentica.*
if [ "${non_misurato:-0}" -eq 1 ]; then
  echo "⚪ PASS PARZIALE — non è un verde, ed è un dato preciso su cosa è stato visto:"
  echo "   ✅ MISURATO   la sandbox consente i quattro path necessari (compreso /tmp)"
  echo "                 e nega /etc e /usr/bin: il MECCANISMO regge sul kernel."
  echo "   ⚪ NON VISTO  il caso silenzioso del §③: sotto PrivateTmp il dump del backup"
  echo "                 può uscire VUOTO con rc=0, e qui non è stato provato."
  echo "   ⇒ per completarla serve un backup REALE sul server e la DIMENSIONE del dump."
  echo "      Finché manca, questa prova esce 2 («non eseguibile per intero»), non 0."
  exit 2
fi
echo "✅ PASS — la sandbox proposta consente i quattro path necessari (compreso /tmp) e nega /etc e /usr/bin."
echo "   ⚠️  NON significa che l'update reale non scriva altrove: questa prova misura il MECCANISMO."
echo "   Il passo che resta è un update vero sotto tracciamento delle scritture, e lo decide chi ha il server."
exit 0
