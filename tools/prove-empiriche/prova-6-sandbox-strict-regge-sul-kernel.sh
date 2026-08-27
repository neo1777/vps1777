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
# 🔄 DA DICHIARATIVO A MISURATO (27/08/2026, per ordine dell'owner: «i 5 punti in
#   produzione, senza se e senza ma»). Fino a ieri questo ramo DICHIARAVA che la
#   misura mancava («lanciare un backup reale è una decisione di chi possiede il
#   server») e usciva 2. Ora il server ha VOLUMI VERI, e la decisione è presa: dove
#   docker e un volume vps1777_* ci sono, il §③ ESEGUE la misura che chiedeva.
# COSA MISURA, nei due versi — perché un solo verso è preso in prestito:
#   a) il gesto ESATTO di backup.sh (mktemp -d sull'host → bind-mount → tar del
#      volume in SOLA LETTURA) dentro la sandbox PROPOSTA: la DIMENSIONE del dump
#      deve essere > 0. L'exit code non conta niente, ed è tutto il punto.
#   b) CONTROPROVA: lo stesso gesto sotto PrivateTmp=yes deve produrre esattamente
#      il caso silenzioso che la unit dichiara — rc=0 E dump vuoto/assente. Se
#      invece il dump arriva pieno, la ragione scritta nella unit è da riverificare.
# Non tocca la produzione: il volume è montato :ro, si scrive solo in un mktemp.
echo
echo "   ③ IL CASO SILENZIOSO — mktemp + bind-mount del backup, MISURATO in dimensione"
non_misurato=0
if ! grep -q 'mktemp -d' "$REPO/tools/backup.sh" 2>/dev/null; then
  echo "      ⚠️  'mktemp -d' non trovato in tools/backup.sh — la ragione dichiarata nella unit"
  echo "         va riverificata: o il file è cambiato, o il repo è un altro."
  non_misurato=1
elif ! $SUDO docker ps >/dev/null 2>&1; then
  echo "      backup.sh usa mktemp -d          ✅ confermato sul file (la ragione della unit è reale)"
  echo "      ⚪ docker non disponibile qui ⇒ il dump reale non si può misurare su questa macchina."
  non_misurato=1
else
  # 🪤 Il glob `vps1777_*` su `docker volume ls` NON basta, e l'ha detto la CI:
  #   il ciclo backup→restore dei test bash crea volumi `vps1777_provaciclo-*`
  #   sullo stesso runner, e la prima versione di questo ramo ci ha misurato
  #   sopra — un PASS genuino nel meccanismo ma SENZA il sistema sotto, cioè
  #   esattamente il falso verde che la fase-b esiste per beccare (contract
  #   rosso del 27/08 su rc=0). Il sistema «in esercizio» lo dichiara un
  #   CONTAINER ATTIVO, non un volume: si misura solo su un volume montato in
  #   un container in esecuzione (stessa via di H54: i Mounts di `inspect`).
  VOL="$(for c in $($SUDO docker ps -q); do
           $SUDO docker inspect \
             --format '{{range .Mounts}}{{if eq .Type "volume"}}{{println .Name}}{{end}}{{end}}' "$c"
         done 2>/dev/null | grep '^vps1777_' | sort -u | head -1)"
  if [ -z "$VOL" ]; then
    echo "      ⚪ nessun volume vps1777_* montato in un container IN ESECUZIONE ⇒ il"
    echo "         prodotto non è in esercizio qui: niente dati reali da dumpare."
    non_misurato=1
  else
    echo "      volume reale sotto dump (ro): $VOL"
    dump_sotto() {  # <descrizione> <proprietà systemd-run extra...> → vero se il dump ha contenuto
      local desc="$1"; shift
      local out rc size resto
      # 🪤 TUTTO il gesto — mktemp, docker, stat — vive DENTRO la sandbox, come in
      #   backup.sh:55+182. La mia prima versione faceva il mktemp FUORI e passava
      #   il path dentro: così il path esiste sull'HOST, il demone docker lo
      #   risolve, e il dump arriva PIENO anche sotto PrivateTmp — *la sonda aveva
      #   il difetto che cercava*, e la controprova usciva rossa su un caso VERO.
      #   Il caso silenzioso nasce proprio perché il mktemp del SERVIZIO vive nel
      #   suo /tmp privato, che il demone non vede.
      out="$($SUDO systemd-run --quiet --wait --collect --pipe "$@" \
            /bin/sh -c "t=\$(mktemp -d); \
                        docker run --rm -v '$VOL':/src:ro -v \"\$t\":/dst alpine \
                          sh -c 'cd /src && tar cf /dst/dump.tar .' >/dev/null 2>&1; \
                        rc=\$?; \
                        size=\$(stat -c %s \"\$t/dump.tar\" 2>/dev/null || echo 0); \
                        rm -rf \"\$t\"; \
                        echo \"RC=\$rc SIZE=\$size T=\$t\"" 2>/dev/null)"
      rc="${out#*RC=}"; rc="${rc%% *}"
      size="${out#*SIZE=}"; size="${size%% *}"
      resto="${out#*T=}"
      # Sotto PrivateTmp il demone docker CREA il path sul /tmp dell'host (è il
      # meccanismo stesso del caso silenzioso): quel residuo va tolto dall'host.
      case "$resto" in /tmp/tmp.*) $SUDO rm -rf "$resto" 2>/dev/null ;; esac
      printf '      %-44s rc=%s dump=%s byte\n' "$desc" "${rc:-?}" "${size:-0}"
      [ "${size:-0}" -gt 0 ] 2>/dev/null
    }
    if dump_sotto "a) sandbox PROPOSTA (strict+RWP)" "${props[@]}"; then
      echo "         ✅ il dump ha CONTENUTO sotto la stretta proposta: il §③ regge"
    else
      echo "         🔴 dump VUOTO sotto la sandbox proposta ⇒ la stretta rompe il backup, in silenzio"
      falliti=$((falliti+1))
    fi
    if dump_sotto "b) CONTROPROVA PrivateTmp=yes" --property=PrivateTmp=yes; then
      echo "         🔴 controprova FALLITA: sotto PrivateTmp il dump è arrivato PIENO —"
      echo "            la ragione scritta nella unit («si romperebbe in silenzio») è da riverificare"
      falliti=$((falliti+1))
    else
      echo "         ✅ sotto PrivateTmp il dump esce vuoto (e docker non si lamenta):"
      echo "            il caso silenzioso ESISTE — la riga «NIENTE PrivateTmp» della unit è MISURATA"
    fi
  fi
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
# ⚠️ Il costo che questa scelta aveva («finché il caso silenzioso non è misurabile,
#   questa prova non darà MAI 0») si è ESTINTO il 27/08/2026: il §③ ora ESEGUE la
#   misura dove docker e un volume reale ci sono, e lì la prova può dare 0. Dove
#   mancano (un PC senza lo stack), il ramo qui sotto continua a dire 2 — «misurato
#   in parte» — che resta l'unico esito che non mente in nessuna delle due direzioni.
if [ "${non_misurato:-0}" -eq 1 ]; then
  echo "⚪ PASS PARZIALE — non è un verde, ed è un dato preciso su cosa è stato visto:"
  echo "   ✅ MISURATO   la sandbox consente i quattro path necessari (compreso /tmp)"
  echo "                 e nega /etc e /usr/bin: il MECCANISMO regge sul kernel."
  echo "   ⚪ NON VISTO  il caso silenzioso del §③: qui mancano docker o un volume"
  echo "                 vps1777_* reale, e senza un dump vero la dimensione non si misura."
  echo "   ⇒ su una macchina con lo stack (la VPS), il §③ misura da sé e la prova può dare 0."
  exit 2
fi
echo "✅ PASS — la sandbox proposta consente i quattro path necessari (compreso /tmp), nega /etc e /usr/bin,"
echo "   e il §③ è MISURATO: il dump reale ha contenuto sotto la stretta proposta, e la controprova"
echo "   PrivateTmp produce il vuoto-con-rc-0 che la unit dichiara."
echo "   ⚠️  NON significa che l'update reale non scriva altrove: questa prova misura il MECCANISMO."
echo "   Il passo che resta è un update vero sotto tracciamento delle scritture, e lo decide chi ha il server."
exit 0
