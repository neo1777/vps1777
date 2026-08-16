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

# ── 🎯 --fase <nome>: TRE FOTOGRAFIE CONFRONTABILI, non tre volte la stessa ────
# 🔴 PERCHÉ (abdd732a, 16/08, voce 4a5815c3): il collaudo del FORMAT chiede di
#   lanciare queste prove TRE volte — (a) baseline prima del format, (b) a macchina
#   formattata PRIMA dell'installer, (c) a installazione finita. Con un solo file di
#   uscita **la (b) cancella la (a) e la (c) cancella la (b)**: alla fine resti con
#   l'ultima foto e nessun confronto, cioè esattamente il dato che il collaudo cerca.
# ⭐ E il caso (b) è quello che vale di più: a macchina nuda devono uscire TUTTE «2 =
#   non eseguibile». **Se una desse 0 avremmo trovato un falso PASS nel momento esatto
#   in cui serve** — ma solo se quella foto sopravvive alla successiva.
# 🛡️ Non è una regola nuova: è la STESSA che c'è già per `--solo`, che scrive su
#   `-parziale.json` per non contaminare il quadro completo. *Qui il quadro non è
#   parziale, è di un ALTRO momento — e due momenti diversi non si sovrascrivono
#   per la stessa ragione per cui non lo fanno due popolazioni diverse.*
FASE=""
if [ "${1:-}" = "--fase" ]; then
  FASE="${2:-}"; SOLO="${3:-}"
  [ "${3:-}" = "--solo" ] && SOLO="${4:-}" || SOLO=""
  [ -n "$FASE" ] || { echo "uso: lancia-tutte.sh --fase <nome> [--solo prova-N]" >&2; exit 2; }
  case "$FASE" in
    *[!a-zA-Z0-9_-]*) echo "⛔ nome fase non valido: «$FASE» (lettere, cifre, - e _)" >&2; exit 2 ;;
  esac
  FUORI="${FUORI%.json}-$FASE.json"
fi

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
#
# 🔴 DIFETTO CURATO IL 02/08 (b82df434, voce `e12aa7ec` aperta da 71d540e6 su
#   segnalazione di un agente — difetto verificato riga per riga da entrambe).
#   `--solo prova-3` eseguiva UNA prova e scriveva il record **sullo stesso file**:
#   `totale:1 ok:1 rosse:0 non_eseguite:0`, cancellando il referto delle nove. Al
#   giro dopo l'intestazione stampava «N ore fa · 1/1 verdi» — **che è esattamente
#   la frase che questo script esiste per rendere impossibile.**
# ⭐ E la seconda faccia, più silenziosa: `tot` contava ciò che IL GLOB aveva
#   trovato. Se il glob trovasse meno file dei tracciati (un bundle di release
#   incompleto), le mancanti non sarebbero «non eseguite»: **semplicemente non
#   contate.** ⇒ serve un ATTESO che non venga dallo stesso glob che sto contando.
#
# LA CURA, in due pezzi e nessuno dei due copiato:
#  ① l'atteso viene da `git ls-files`, non dal glob — stesso criterio della CI
#    (`ci.yml:79`, «un elenco scritto a mano invecchia in silenzio»). Se git non
#    risponde NON si inventa un numero: si scrive `null` e si dichiara.
#  ② una corsa PARZIALE non tocca il referto completo. Va su un file suo, e lo
#    dice. *Marcare il record «parziale» non basterebbe: il referto completo
#    sarebbe comunque distrutto, e un dato marcato bene ma perso è perso.*
atteso="$(git -C "$REPO" ls-files 'tools/prove-empiriche/prova-*.sh' 2>/dev/null | wc -l)"
[ "${atteso:-0}" -gt 0 ] || atteso=""      # git assente ⇒ «non lo so», non uno zero
_atteso_json="${atteso:-null}"

if [ -n "$SOLO" ]; then
  FUORI="${FUORI%.json}-parziale.json"
  printf '  ⚠️  corsa PARZIALE (--solo «%s»): il referto completo NON è stato toccato.\n' "$SOLO"
  printf '     Questo esito va in %s — una corsa su %s prove non può\n' "${FUORI##*/}" "$tot"
  printf '     sostituire il quadro di %s.\n' "${atteso:-tutte le}"
fi

printf '{"quando":"%s","dove":"%s","parziale":%s,"filtro":"%s","atteso":%s,"totale":%d,"ok":%d,"rosse":%d,"non_eseguite":%d,"prove":[%s]}\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(hostname)" \
  "$([ -n "$SOLO" ] && echo true || echo false)" "$SOLO" "$_atteso_json" \
  "$tot" "$ok" "$ko" "$salt" \
  "$(IFS=,; echo "${righe[*]:-}")" > "$FUORI"

# 🛡️ E il caso che nessuno dei due pezzi copre: corsa COMPLETA che vede meno
#   prove di quante ne siano tracciate. Non è «non eseguite»: è che non le ha
#   nemmeno viste. Va detto qui, o resta un verde su un insieme rimpicciolito.
if [ -z "$SOLO" ] && [ -n "$atteso" ] && [ "$tot" -lt "$atteso" ]; then
  printf '  🔴 ho eseguito %d prove ma ne risultano %d tracciate: %d NON sono state\n' \
    "$tot" "$atteso" "$((atteso - tot))"
  printf '     nemmeno viste dal glob. Non sono «non eseguite» — sono assenti.\n'
fi

printf '\n  %d verdi · %d rosse · %d non eseguite   →  %s\n' "$ok" "$ko" "$salt" "${FUORI#"$REPO"/}"
[ -n "$FASE" ] && printf '  📸 fase «%s»: questa foto NON sovrascrive le altre fasi.\n' "$FASE"
[ $salt -gt 0 ] && printf '  ⚪ le NON ESEGUITE non sono passate: mancava un prerequisito (di solito docker).\n     Sono contate a parte apposta — un verde che include ciò che non hai guardato\n     è esattamente il difetto che queste prove esistono per non commettere.\n'
# ─── il verdetto ──────────────────────────────────────────────────────────────
# 🔴 DIFETTO CURATO IL 02/08 (abdd732a, da un rilievo di un agente, verificato sul
#   vivo: lanciato su un PC senza docker stampava «0 verdi · 0 rosse · 9 non
#   eseguite» e usciva **0**).
# ⭐ Il TESTO era onesto e il CODICE DI RITORNO no — e il codice di ritorno è ciò
#   che legge chi appende questo a un timer, a un hook o a un altro script. Tre
#   righe più su questo file dice: «un verde che include ciò che non hai guardato
#   è esattamente il difetto che queste prove esistono per non commettere».
#   Lo diceva a parole, e usciva 0.
# 🔑 Il contratto della famiglia — 0=PASS · 1=FAIL · 2=non eseguibile, dichiarato
#   in `prova-8` e già applicato qui alle singole prove (:76) — non era applicato
#   al lanciatore stesso. *Lo strumento che aggrega non rispettava il contratto
#   che fa rispettare.*
# ⚠️ COSTO DICHIARATO: da adesso, se anche UNA sola prova non è eseguibile, il
#   lanciatore NON esce 0. Su una macchina che ha lo stack devono girare tutte e
#   nove; se una resta strutturalmente non eseguibile, il 2 è il promemoria che
#   manca una misura — e va tolto curando la prova, non allargando questa soglia.
if [ $ko -gt 0 ]; then
  exit 1
fi
if [ $ok -eq 0 ]; then
  echo "⚪ NESSUNA prova eseguita ($salt su $tot non eseguibili): non è un verde, è un'assenza di dato."
  exit 2
fi
if [ $salt -gt 0 ]; then
  echo "⚪ PARZIALE: $ok eseguite e verdi, $salt su $tot NON eseguite — non è un PASS pieno."
  exit 2
fi
exit 0
