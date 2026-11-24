#!/usr/bin/env bash
# prova-9 — il fail-closed dell'update TORNA INDIETRO DAVVERO (M4-b).
#
# ⚠️ È LA PRIMA PROVA DI QUESTA CARTELLA CHE **ROMPE APPOSTA**. Le otto precedenti
#    osservano; questa provoca un rollback vero, con i container che si riavviano.
#    Per questo: non parte senza `--esegui`, e la lancia Neo.
#
# PERCHÉ ESISTE. `tools/vps1777.py`, passo 14 dell'update:
#     healthy, why = health_gate(repo, env=env_new)
#     if not healthy: return _rollback_routine(...)
# È il ramo che protegge la macchina da una release rotta, ed è l'unico pezzo
# importante di quel file che **nessun test tocca**: richiede docker, systemd e una
# release davvero malata. La scorciatoia era certificarlo staticamente
# (`assert "_rollback_routine" in getsource(...)`) — e sarebbe stata H52 rifatta da
# noi: un verde su una STRINGA accanto a un ramo mai eseguito.
#
# COME SI FA SENZA SABOTARE NIENTE. `VPS1777_COLLAUDO_HEALTH_KO=1` forza il gate a
# fallire (aggancio in `health_gate`, commit 42ff63a). L'aggancio può SOLO dire no:
# non esiste modo di usarlo per far passare un update malato. Il peggio che causa è
# un rollback non necessario — cioè il comportamento che questa prova collauda.
#
# ✅ HA VISTO IL ROLLBACK (collaudo su macchina vergine del 23/11/2026, referto in
#    docs/collaudi/2026-11-23.yml): update 0.98.5 → 0.98.6 col gate forzato, rollback partito,
#    versione rimasta 0.98.5, sei container su. Fino a quel giorno era una proposta di prova:
#    aveva girato una volta sola (27/08/2026) fermandosi su un errore suo, poi corretto.
#    Quel giro ha anche mostrato un difetto dell'aggancio: faceva fallire pure il controllo di
#    salute DOPO il rollback, e l'update usciva 2 («serve intervento») su un rollback riuscito.
#    Dalla 0.98.7 l'aggancio scatta una volta sola: l'esito atteso dell'update è 1.
#    L'ha vista anche la VPS di riferimento (23/11/2026, PASS) e dal 24/11/2026 gira in CI su
#    uno stack vivo: `.github/workflows/rollback.yml`, due job. «rollback-sano» pretende lo 0;
#    «rollback-sabotato» spegne `_rollback_routine` e pretende l'1 (una prova che resta verde
#    col rollback spento non misura niente).
#
# Uso:
#   bash prova-9-il-fail-closed-torna-indietro-davvero.sh            # dice cosa farebbe, exit 2
#   bash prova-9-il-fail-closed-torna-indietro-davvero.sh --esegui   # lo fa davvero
#
# Exit: 0 PASS · 1 FAIL · 2 NON MISURATO (comprese le precondizioni mancanti)
set -uo pipefail

REPO="${VPS1777_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]:-.}")/../.." 2>/dev/null && pwd)}"
ESEGUI=0
[ "${1:-}" = "--esegui" ] && ESEGUI=1

dice(){ printf '%s\n' "$*"; }
non_misurato(){ dice "⚪ NON MISURATO — $*"; exit 2; }

dice "prova-9 — il fail-closed dell'update torna indietro davvero"
dice "──────────────────────────────────────────────────────────"

# ── 1. precondizioni. Ognuna che manca è NON MISURATO, mai «a posto» ──────────
command -v docker >/dev/null || non_misurato "docker non c'è: questa prova vive sulla macchina"
[ -d "$REPO" ]              || non_misurato "repo non trovato in $REPO (VPS1777_REPO per cambiarlo)"
CLI="$REPO/tools/vps1777.py"
[ -f "$CLI" ]               || non_misurato "$CLI non c'è"
grep -q "VPS1777_COLLAUDO_HEALTH_KO" "$CLI" \
    || non_misurato "l'aggancio di collaudo non è in questa versione del codice: aggiorna prima"

# 🔴 Era `$REPO/state.json` — un path scritto A MANO che il file non ha MAI
# avuto: la CLI lo tiene in `var/state.json` dalla sua nascita (443e7a0,
# `_state_path`). La prova è nata dopo (b7d7303) col path inventato, quindi
# «NON MISURATO» a ogni lancio: non ha mai misurato niente in vita sua, e il
# suo esito grigio sembrava un prerequisito d'ambiente invece di un suo bug.
# Trovato al collaudo vergine (27/08/2026), col file LÌ, fresco di un minuto.
STATO="$REPO/var/state.json"
[ -f "$STATO" ] || non_misurato "var/state.json non trovato: non so quale versione gira"
CORRENTE="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('current') or '')" "$STATO" 2>/dev/null)"
[ -n "$CORRENTE" ] || non_misurato "state.json non dichiara una versione corrente"

IN_CORSO="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('update_in_progress') or '')" "$STATO" 2>/dev/null)"
[ -z "$IN_CORSO" ] || non_misurato "c'è già un update in corso ($IN_CORSO): non ci si mette in mezzo"

# Un rollback ha bisogno di qualcosa a cui tornare. Se non c'è, la prova non si fa:
# collaudare un ritorno senza punto di ritorno è il modo di scoprire che non c'era.
SNAP="$REPO/backups/pre-update"
N_SNAP=$( (ls -1d "$SNAP"/*/ 2>/dev/null || true) | grep -c . || true)
[ "${N_SNAP:-0}" -gt 0 ] || non_misurato "nessuno snapshot in $SNAP: senza punto di ritorno questa prova non si lancia"

# 🔴 La prima stesura passava `--version $CORRENTE` («non si cambia versione:
# si esercita solo gate + rollback») — ma la CLI corto-circuita PRIMA del gate:
# `norm_ver(cur) == target → «già aggiornato», exit 0` (vps1777.py, e fa bene:
# un update inutile non si esegue). Misurato al PRIMO giro vero della prova
# (collaudo vergine, 27/08/2026): exit 0, nessun gate, nessun rollback — il
# difetto era QUI, come l'avvertenza in fondo metteva in conto. Il fail-closed
# si esercita solo su un SALTO vero: serve una release DIVERSA dalla corrente.
TARGET="$(python3 -c "import json,sys;print((json.load(open(sys.argv[1])).get('latest') or ''))" "$REPO/onboarding/update_status.json" 2>/dev/null || true)"
[ -n "$TARGET" ] || non_misurato "nessuna 'latest' nota (onboarding/update_status.json): lancia prima vps1777 check"
[ "$TARGET" != "$CORRENTE" ] || non_misurato "latest ($TARGET) == corrente: il fail-closed si esercita su un salto vero — riprova quando c'è una release nuova"

dice "  ✅ precondizioni: versione corrente v$CORRENTE · target v$TARGET · $N_SNAP snapshot disponibili"
dice ""

# ── 2. cosa farà, detto PRIMA ─────────────────────────────────────────────────
dice "  COSA FA, e cosa costa:"
dice "    · lancia l'update VERO v$CORRENTE → v$TARGET col gate di health sabotato"
dice "    · con VPS1777_COLLAUDO_HEALTH_KO=1 il gate rifiuta"
dice "    · attesa: parte _rollback_routine, i container SI RIAVVIANO e si RESTA alla v$CORRENTE"
dice "    · costo reale: il servizio è indisponibile per la durata del rollback"
dice "    · dopo il verde: l'update alla v$TARGET si rifà pulito, senza il sabotaggio"
dice ""
if [ "$ESEGUI" -eq 0 ]; then
  dice "  ⚪ giro a secco, NON MISURATO: non ho toccato niente (il rollback si provoca solo con --esegui)."
  dice "     Per farlo davvero:  bash $(basename "$0") --esegui"
  dice "     ⚠️ e prima dillo a chi usa la macchina: questa fa cadere il servizio."
  exit 2
fi

# ── 3. l'esecuzione ───────────────────────────────────────────────────────────
# Il log dell'update vive in un file temporaneo: a prova riuscita si cancella, a prova
# fallita resta (serve per capire) e il messaggio dice dov'è e che va tolto a mano.
LOG="$(mktemp)"
TETTO="${PROVA9_TIMEOUT_S:-3600}"
dice "  ▶ eseguo… (log in $LOG, tempo massimo ${TETTO}s)"
# Niente `set -e` da qui in poi (c'era): con lui una lettura fallita dello stato faceva
# uscire 1 SENZA una riga, cioè un «non ho potuto guardare» travestito da FAIL.
timeout "$TETTO" env VPS1777_COLLAUDO_HEALTH_KO=1 python3 "$CLI" update --version "$TARGET" --yes >"$LOG" 2>&1
RC=$?
dice "  ▶ exit dell'update: $RC"
if [ "$RC" -eq 124 ]; then
  dice "🔴 FAIL — l'update non ha concluso entro ${TETTO}s ed è stato fermato."
  dice "   GUARDA SUBITO la macchina: «vps1777 status», poi il log in $LOG (cancellalo dopo)."
  exit 1
fi

# ── 4. il verdetto, su OSSERVABILI e non sull'exit ────────────────────────────
# L'exit dell'update non basta: un rollback riuscito può uscire con codici diversi
# a seconda di dove è caduto. Si guarda cosa È SUCCESSO, non cosa è stato detto.
ROLLBACK=0
grep -qiE "rollback|torno indietro|ripristino" "$LOG" && ROLLBACK=1
GATE_KO=0
grep -q "collaudo: fallimento forzato" "$LOG" && GATE_KO=1

DOPO="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('current') or '')" "$STATO" 2>/dev/null)"
SU=$(timeout 60 docker compose -f "$REPO/compose.yaml" ps --format '{{.State}}' 2>/dev/null | grep -c running || true)

dice ""
dice "  ── osservato ──"
dice "    il gate ha rifiutato per l'aggancio : $([ "$GATE_KO" -eq 1 ] && echo sì || echo NO)"
dice "    il log nomina un rollback           : $([ "$ROLLBACK" -eq 1 ] && echo sì || echo NO)"
dice "    versione prima/dopo                 : v$CORRENTE → v${DOPO:-?}"
dice "    container running adesso            : ${SU:-0}"
dice ""

if [ -z "$DOPO" ]; then
  dice "⚪ NON MISURATO — dopo l'update lo stato ($STATO) non si legge: non so a che versione siamo."
  dice "   GUARDA SUBITO la macchina: «vps1777 status», poi il log in $LOG (cancellalo dopo)."
  exit 2
fi
if [ "$GATE_KO" -eq 1 ] && [ "$ROLLBACK" -eq 1 ] && [ "$DOPO" = "$CORRENTE" ] && [ "${SU:-0}" -gt 0 ]; then
  rm -f "$LOG"
  # 1 = «tornato indietro, sano». 2 = il prodotto crede che nemmeno il ritorno sia sano: con una
  # CLI precedente alla 0.98.7 è l'aggancio che falsa anche quel controllo; dopo, è un difetto.
  [ "$RC" -eq 1 ] || dice "  ⚠️ l'update è uscito $RC e non 1: il prodotto non ha visto sano il proprio rollback (vedi la testa di questo file)."
  dice "✅ PASS — il gate ha detto no, il rollback è partito, la versione è quella di prima"
  dice "   e i container sono su. **Il fail-closed non è più una riga mai eseguita.**"
  exit 0
fi
dice "🔴 FAIL — o non è andata come previsto, o le mie attese erano sbagliate."
dice "   Il rollback riuscito questo script l'ha visto (23/11/2026, e in CI): se qui fallisce,"
dice "   guarda prima il prodotto; se il prodotto ha fatto bene, il difetto è in queste attese."
dice "   Il log completo è in $LOG: leggilo prima di concludere qualcosa sul prodotto,"
dice "   e cancellalo quando hai finito (resta apposta, nessuno lo toglie da sé)."
[ "${SU:-0}" -eq 0 ] && dice "   🔴 E GUARDA SUBITO: nessun container running. Il servizio è giù."
exit 1
