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
# 🔴 DICHIARAZIONE ONESTA, e va letta prima di lanciare: **questo script non è mai
#    stato eseguito.** È stato scritto sulla lettura del codice, non sull'osservazione
#    della macchina. Le sue attese possono essere sbagliate; se lo sono, il primo giro
#    lo dirà, e la correzione va scritta qui dentro. *Uno script mai eseguito non è
#    una prova: è una proposta di prova.*
#
# Uso:
#   bash prova-9-il-fail-closed-torna-indietro-davvero.sh            # dice cosa farebbe, exit 2
#   bash prova-9-il-fail-closed-torna-indietro-davvero.sh --esegui   # lo fa davvero
#
# Exit: 0 PASS · 1 FAIL · 2 NON MISURATO (comprese le precondizioni mancanti)
set -uo pipefail

REPO="${VPS1777_REPO:-$HOME/vps1777}"
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

dice "  ✅ precondizioni: versione corrente v$CORRENTE · $N_SNAP snapshot disponibili"
dice ""

# ── 2. cosa farà, detto PRIMA ─────────────────────────────────────────────────
dice "  COSA FA, e cosa costa:"
dice "    · rilancia l'update sulla versione GIÀ IN ESECUZIONE (v$CORRENTE)"
dice "      ⇒ non si cambia versione: si esercita solo gate + rollback"
dice "    · con VPS1777_COLLAUDO_HEALTH_KO=1 il gate rifiuta"
dice "    · attesa: parte _rollback_routine, i container SI RIAVVIANO"
dice "    · costo reale: il servizio è indisponibile per la durata del rollback"
dice ""
if [ "$ESEGUI" -eq 0 ]; then
  dice "  ⚪ giro a secco: NON ho toccato niente."
  dice "     Per farlo davvero:  bash $(basename "$0") --esegui"
  dice "     ⚠️ e prima dillo a chi usa la macchina: questa fa cadere il servizio."
  exit 2
fi

# ── 3. l'esecuzione ───────────────────────────────────────────────────────────
LOG="$(mktemp)"
dice "  ▶ eseguo… (log in $LOG)"
set +e
VPS1777_COLLAUDO_HEALTH_KO=1 python3 "$CLI" update --version "$CORRENTE" --yes >"$LOG" 2>&1
RC=$?
set -e
dice "  ▶ exit dell'update: $RC"

# ── 4. il verdetto, su OSSERVABILI e non sull'exit ────────────────────────────
# L'exit dell'update non basta: un rollback riuscito può uscire con codici diversi
# a seconda di dove è caduto. Si guarda cosa È SUCCESSO, non cosa è stato detto.
ROLLBACK=0
grep -qiE "rollback|torno indietro|ripristino" "$LOG" && ROLLBACK=1
GATE_KO=0
grep -q "collaudo: fallimento forzato" "$LOG" && GATE_KO=1

DOPO="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('current') or '')" "$STATO" 2>/dev/null)"
SU=$(docker compose -f "$REPO/compose.yaml" ps --format '{{.State}}' 2>/dev/null | grep -c running || true)

dice ""
dice "  ── osservato ──"
dice "    il gate ha rifiutato per l'aggancio : $([ "$GATE_KO" -eq 1 ] && echo sì || echo NO)"
dice "    il log nomina un rollback           : $([ "$ROLLBACK" -eq 1 ] && echo sì || echo NO)"
dice "    versione prima/dopo                 : v$CORRENTE → v${DOPO:-?}"
dice "    container running adesso            : ${SU:-0}"
dice ""

if [ "$GATE_KO" -eq 1 ] && [ "$ROLLBACK" -eq 1 ] && [ "$DOPO" = "$CORRENTE" ] && [ "${SU:-0}" -gt 0 ]; then
  dice "✅ PASS — il gate ha detto no, il rollback è partito, la versione è quella di prima"
  dice "   e i container sono su. **Il fail-closed non è più una riga mai eseguita.**"
  exit 0
fi
dice "🔴 FAIL — o non è andata come previsto, o le mie attese erano sbagliate."
dice "   ⚠️ Questo script non era mai stato eseguito prima: il primo giro può fallire"
dice "      perché il codice si comporta diversamente da come l'ho letto. In quel caso"
dice "      il difetto è QUI, non nel prodotto — e va corretto qui dentro."
dice "   Il log completo è in $LOG: leggilo prima di concludere qualcosa sul prodotto."
[ "${SU:-0}" -eq 0 ] && dice "   🔴 E GUARDA SUBITO: nessun container running. Il servizio è giù."
exit 1
