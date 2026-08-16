#!/usr/bin/env bash
# onesta-a-macchina-nuda.sh — l'unica cosa delle nove prove che una CI PUÒ verificare.
#
# PERCHÉ ESISTE.
#   In testa a `lancia-tutte.sh` c'è scritto da settimane: queste nove prove sono
#   l'unico strato che tocca il sistema reale, e l'unico che nessuno esegue in
#   automatico — «in CI ci passa shellcheck sopra: le CONTROLLA, non le ESEGUE».
#   Vero, e per costruzione: servono docker, la rete e systemd VERI.
# ⭐ Ma c'è una proprietà che NON ha bisogno del sistema per essere verificata, ed è
#   quella su cui poggia tutto il resto: **a macchina nuda nessuna delle nove deve
#   dichiarare un PASS.** Lo dice `lancia-tutte.sh` stesso, righe 42-44, a proposito
#   della fase (b) del collaudo del FORMAT: «a macchina nuda devono uscire TUTTE
#   2 = non eseguibile. Se una desse 0 avremmo trovato un falso PASS nel momento
#   esatto in cui serve».
# 🔑 Un runner di GitHub Actions È una macchina nuda: il prodotto non ci gira.
#   Quindi la fase (b) si può eseguire ad ogni PR, gratis, e senza fingere che
#   stiamo misurando il sistema — misuriamo l'ONESTÀ degli strumenti che lo
#   misureranno. *Un attrezzo che dice «tutto bene» quando non ha guardato non è
#   uno strumento rotto: è peggio di non averlo.*
#
# 🔴 QUANDO QUESTO GATE ANDRÀ CAMBIATO, e va detto adesso perché il prossimo non
#   lo scopra da un rosso: il giorno in cui la CI avviasse davvero lo stack, un
#   verde diventerebbe legittimo e questo script sbaglierebbe. Il criterio non è
#   «nessuna verde» in assoluto — è «nessuna verde SENZA il sistema sotto».
#
# Esce 0 se tutte e nove sono NON-ESEGUITE · 1 se una qualunque è verde o rossa.
set -uo pipefail

QUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$QUI/../.." && pwd)"
FASE="ci-macchina-nuda"
REFERTO="$REPO/onboarding/prove-empiriche-$FASE.json"

printf '🧪 le nove prove su una macchina dove il prodotto NON gira: nessuna deve dire PASS.\n\n'

# L'exit 2 di «nessuna prova eseguita» è l'esito ATTESO qui, non un errore:
# per questo non lo propaghiamo. È il contenuto del referto a dare il verdetto.
bash "$QUI/lancia-tutte.sh" --fase "$FASE" || true

[ -f "$REFERTO" ] || { printf '\n⛔ il referto «%s» non è stato scritto: il gate NON ha un verdetto, e NON è un verde.\n' "$REFERTO" >&2; exit 1; }

python3 - "$REFERTO" <<'PY'
import json, sys

d = json.load(open(sys.argv[1]))
prove = d.get("prove", [])
if not prove:
    print("\n⛔ referto senza nessuna prova dentro: assenza di dato, non un verde.", file=sys.stderr)
    sys.exit(1)

# 🔎 Il verdetto si legge dagli ESITI, uno per uno — non dai contatori aggregati:
#    un totale che torna può nascondere due errori che si compensano, ed è il
#    difetto che questo repo ha già incontrato altrove (il conteggio distingue il
#    frequente dal raro, non il vero dal finto).
bugiarde = [p for p in prove if p.get("esito") == "verde"]
rumorose = [p for p in prove if p.get("esito") == "ROSSA"]
oneste   = [p for p in prove if p.get("esito") == "NON-ESEGUITA"]

for p in oneste:
    print(f'  ⚪ {p["prova"]:<52} {p.get("motivo","(nessun motivo dichiarato)")[:70]}')

if bugiarde:
    print(f'\n⛔ {len(bugiarde)} prova/e dichiarano un PASS senza il sistema sotto — è un FALSO VERDE:', file=sys.stderr)
    for p in bugiarde:
        print(f'   🔴 {p["prova"]} (rc={p.get("rc")})', file=sys.stderr)
    print('   Una prova che non ha potuto guardare deve uscire 2, non 0.', file=sys.stderr)

if rumorose:
    print(f'\n⛔ {len(rumorose)} prova/e dichiarano un FALLIMENTO del sistema che non hanno guardato:', file=sys.stderr)
    for p in rumorose:
        print(f'   🔴 {p["prova"]} (rc={p.get("rc")}) — {p.get("motivo","")[:70]}', file=sys.stderr)
    print('   «non ho potuto guardare» ≠ «ho guardato e non va»: il contratto è 0/1/2.', file=sys.stderr)

if bugiarde or rumorose:
    sys.exit(1)

print(f'\n✅ {len(oneste)} su {len(prove)}: nessuna prova dichiara un esito che non poteva misurare.')
print('   Non è un collaudo del sistema — è la garanzia che il collaudo, quando')
print('   lo faremo sulla macchina vera, non potrà mentire per assenza.')
PY
