#!/usr/bin/env bash
# lancia-tutte.sh — esegue TUTTE le prove empiriche e DATA l'esito.
#
# PERCHÉ ESISTE, ed è un rilievo dell'audit del round-11 (01/08) portato alla
# sua coordinata invece che alla sua frase.
#   L'audio diceva «il sistema predica l'osservazione scientifica ma pratica la
#   ricerca testuale». Contato: dei 105 test della suite, 85 importano e chiamano
#   davvero il codice — quindi «controlli fittizi» era gonfiato. **Ma sotto c'era
#   un fatto vero che nessuno aveva detto**: queste nove prove sono l'unico strato
#   che tocca il sistema reale, e sono l'unico che nessuno esegue in automatico.
#   In CI ci passa `shellcheck` sopra — le CONTROLLA, non le ESEGUE. In release
#   vengono copiate nel bundle. A lanciarle è una persona, quando se ne ricorda.
#
# 🔑 E non è pigrizia: servono docker, la rete e systemd VERI. In una CI non
#    possono girare per costruzione — quindi il difetto non è «non sono in CI».
# ⭐ Il difetto è che **«abbiamo le prove empiriche» può diventare in silenzio
#    «le avevamo»**, e nessuno se ne accorge: l'assenza di una data non fa rumore.
#    Perciò questo script non le automatizza — le DATA. È la stessa forma del
#    badge «check stantio» che il progetto ha già per le release: non promette che
#    sia fresco, dichiara quanto è vecchio.
#
# COSA SCRIVE: onboarding/prove-empiriche.json (runtime, gitignored) con, per
# ogni prova, l'esito e QUANDO. E all'avvio stampa l'età dell'esecuzione
# precedente, così la domanda «da quanto non le lanciamo?» ha una risposta prima
# ancora che tu lanci.
#
# Uso:  bash tools/prove-empiriche/lancia-tutte.sh [--solo prova-3]
set -uo pipefail          # NON -e: una prova che fallisce non deve fermare le altre

QUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$QUI/../.." && pwd)"
FUORI="$REPO/onboarding/prove-empiriche.json"
SOLO="${2:-}"
[ "${1:-}" = "--solo" ] || SOLO=""

mkdir -p "$(dirname "$FUORI")"

# ── L'ETÀ DEL DATO PRECEDENTE, prima di qualunque cosa ────────────────────────
# Se non lo stampiamo QUI, chi lancia lo script vede solo il risultato di adesso
# e non saprà mai che il precedente aveva sei settimane.
if [ -f "$FUORI" ]; then
  _prima=$(python3 - "$FUORI" <<'PY' 2>/dev/null || true
import json, sys, datetime
d = json.load(open(sys.argv[1]))
t = datetime.datetime.fromisoformat(d["quando"].replace("Z", "+00:00"))
ore = (datetime.datetime.now(datetime.timezone.utc) - t).total_seconds() / 3600
print(f'{d["quando"][:16]}Z · {ore:.0f} ore fa · {d["ok"]}/{d["totale"]} verdi')
PY
)
  printf '  ultima esecuzione: %s\n\n' "${_prima:-illeggibile}"
else
  printf '  ⚪ NON risulta nessuna esecuzione precedente su questa macchina.\n'
  printf '     Non vuol dire che non siano mai state lanciate: vuol dire che non\n'
  printf '     lo sappiamo — ed è la ragione per cui questo file esiste.\n\n'
fi

# ── L'esecuzione ──────────────────────────────────────────────────────────────
righe=(); ok=0; ko=0; salt=0; tot=0
for p in "$QUI"/prova-*.sh; do
  nome="$(basename "$p" .sh)"
  [ -n "$SOLO" ] && [[ "$nome" != *"$SOLO"* ]] && continue
  tot=$((tot+1))
  t0=$(date +%s)
  out="$(bash "$p" 2>&1)"; rc=$?
  dt=$(( $(date +%s) - t0 ))

  # 🔴 «non ho potuto guardare» ≠ «non c'è niente»: exit 127 (comando assente) e
  #    un output che dichiara un prerequisito mancante NON sono un fallimento.
  #    Confonderli è il difetto che questo progetto insegue da giorni su altri
  #    oggetti: un verde per assenza di misura, o un rosso per assenza di docker.
  # 🔑 exit 2 È IL CONTRATTO, e non l'avevo letto: `prova-8` lo dichiara in testa —
  #    «0 = PASS · 1 = FAIL · 2 = non eseguibile» — ed è l'unica delle nove che
  #    distingue i tre stati. La mia prima versione trattava 2 come un FAIL, cioè
  #    trasformava l'unico attrezzo onesto nel più rumoroso. Trovato da 71d540e6,
  #    che è andata a leggere una prova invece di riprogettare la cura.
  if [ $rc -eq 2 ] || [ $rc -eq 127 ] || printf '%s' "$out" | grep -qiE "docker: (command )?not found|impossibile connettersi al demone|cannot connect to the docker daemon|prova non eseguibile"; then
    esito="NON-ESEGUITA"; salt=$((salt+1)); segno="⚪"
  elif [ $rc -eq 0 ]; then
    esito="verde"; ok=$((ok+1)); segno="✅"
  else
    esito="ROSSA"; ko=$((ko+1)); segno="🔴"
  fi
  printf '  %s %-52s %s (%ss)\n' "$segno" "$nome" "$esito" "$dt"
  righe+=("$(printf '{"prova":"%s","esito":"%s","rc":%d,"secondi":%d}' "$nome" "$esito" "$rc" "$dt")")
done

# ── Il record, con DOVE oltre che QUANDO ──────────────────────────────────────
# La macchina fa parte del dato: una prova verde sul portatile non dice niente
# della VPS, e senza `dove` fra un mese non si potrà più distinguere.
printf '{"quando":"%s","dove":"%s","totale":%d,"ok":%d,"rosse":%d,"non_eseguite":%d,"prove":[%s]}\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(hostname)" "$tot" "$ok" "$ko" "$salt" \
  "$(IFS=,; echo "${righe[*]:-}")" > "$FUORI"

printf '\n  %d verdi · %d rosse · %d non eseguite   →  %s\n' "$ok" "$ko" "$salt" "${FUORI#"$REPO"/}"
[ $salt -gt 0 ] && printf '  ⚪ le NON ESEGUITE non sono passate: mancava un prerequisito (di solito docker).\n     Sono contate a parte apposta — un verde che include ciò che non hai guardato\n     è esattamente il difetto che queste prove esistono per non commettere.\n'
[ $ko -gt 0 ] && exit 1
exit 0
