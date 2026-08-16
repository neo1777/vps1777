#!/usr/bin/env bash
# `setup.sh` si LASCIA ESEGUIRE senza una persona che digita? — e sa ancora dire di no?
#
# 🔴 PERCHÉ ESISTE (abdd732a, 16/08): fino a oggi `setup.sh` non era mai stato ESEGUITO
#   da nessun test. Sette test lo nominano e tutti e sette lo LEGGONO come sorgente;
#   la CI lo citava solo nei commenti. ⇒ l'installazione non era «non testata»: era
#   **non testabile**, e il punto in cui si fermava era l'INIZIO, non la fine.
#
# ⭐ I DUE VERSI, e il secondo è quello che rende il primo una prova:
#   ① CON le variabili e stdin CHIUSO  → arriva in fondo, exit 0
#   ② SENZA le variabili e stdin CHIUSO → NON deve arrivare in fondo
#      *Senza il ②, un `setup.sh` che ignorasse del tutto l'input darebbe verde al ①
#      e il test direbbe «non-interattivo» di uno strumento rotto in un altro modo.*
#
# 🛡️ NON lancia container: l'ultima conferma («Procedo ora?») riceve `n` via SETUP_YES.
#   Gira in una directory TEMPORANEA con una copia del repo (`git worktree`): `setup.sh`
#   scrive `.env` e `secrets/`, e un test che sporca l'albero vero è un test che si fa
#   odiare. La dir viene rimossa anche se il test fallisce (trap).
#
# 📐 Esito a TRE valori, come gli altri presìdi del repo:
#     0 = provato e passa · 1 = provato e FALLISCE · 2 = NON eseguibile (manca docker)
#   «non ho potuto misurare» non è «ok»: senza docker `setup.sh` muore ai prerequisiti,
#   e chiamarlo verde sarebbe il falso PASS che questo repo ha già pagato altrove.
#
# Uso:  bash tools/tests/test-setup-non-interattivo.sh
set -uo pipefail

RADICE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FALLITI=0

# — prerequisito: senza docker `setup.sh` esce ai controlli e non prova niente —
if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  echo "⚪ NON MISURATO — manca docker/compose v2: setup.sh esce ai prerequisiti"
  echo "   (esito 2: «non ho potuto misurare» ≠ «ok»)"
  exit 2
fi

BANCO="$(mktemp -d)"
trap 'git -C "$RADICE" worktree remove --force "$BANCO/repo" >/dev/null 2>&1 || true; rm -rf "$BANCO"' EXIT
git -C "$RADICE" worktree add --detach "$BANCO/repo" HEAD >/dev/null 2>&1 || {
  echo "⚪ NON MISURATO — non riesco a creare il worktree di prova"; exit 2; }
# il setup.sh da provare è quello dell'albero di lavoro, non quello di HEAD:
# altrimenti una modifica non committata non verrebbe mai messa alla prova.
cp "$RADICE/setup.sh" "$BANCO/repo/setup.sh"

PWD_FORTE='Xk9%mQ2vL7pR4tN8wZ'   # 18 char, 4 classi: passa pw_weak_reason (H16)
#   (simbolo % e non $: dentro apici singoli il $ sarebbe letterale e corretto, ma
#    l'analisi statica lo segnala come SC2016 — meglio cambiare il carattere che
#    zittire il presidio con una direttiva di esclusione.
#    ⚠️ e questo commento NON nomina lo strumento a inizio riga apposta: un commento
#    che comincia col suo nome viene letto COME UNA DIRETTIVA (SC1073) e rompe il
#    parsing di tutto ciò che segue — mi è appena successo scrivendo questa nota.)

# ── ① CON le variabili: deve arrivare in fondo senza chiedere niente ────────────
uscita="$(cd "$BANCO/repo" && \
  SETUP_ADMIN_EMAIL="test@example.com" \
  SETUP_TG_OWNER_ID="123456789" \
  SETUP_INGRESS_NUM="1" \
  SETUP_TG_TOKEN="" \
  SETUP_ADMIN_PWD="$PWD_FORTE" \
  SETUP_YES=n \
  timeout 180 bash setup.sh < /dev/null 2>&1)"
rc=$?

if [ "$rc" -ne 0 ]; then
  echo "🔴 ① setup.sh NON arriva in fondo senza una persona (exit $rc)"
  printf '%s\n' "$uscita" | tail -5 | sed 's/^/     /'
  FALLITI=$((FALLITI+1))
else
  # non basta l'exit 0: i valori devono essere ARRIVATI dove servono
  env_ok=0
  grep -q '^ADMIN_EMAIL=test@example.com$'   "$BANCO/repo/.env" && env_ok=$((env_ok+1))
  grep -q '^TELEGRAM_OWNER_ID=123456789$'    "$BANCO/repo/.env" && env_ok=$((env_ok+1))
  grep -q '^INGRESS_PROFILE=ingress.tailscale$' "$BANCO/repo/.env" && env_ok=$((env_ok+1))
  if [ "$env_ok" -eq 3 ]; then
    echo "✅ ① eseguito senza una persona, e le 3 risposte sono nel .env"
  else
    echo "🔴 ① exit 0 ma solo $env_ok/3 risposte sono finite nel .env"
    FALLITI=$((FALLITI+1))
  fi
  # i secret: sono CINQUE (INSTALL.md ne elencava 4 — reperto del 16/08)
  n_secret="$(find "$BANCO/repo/secrets" -maxdepth 1 -name '*.txt' 2>/dev/null | wc -l)"
  if [ "$n_secret" -eq 5 ]; then
    echo "✅ ① i 5 secret sono stati generati"
  else
    echo "🔴 ① secret generati: $n_secret (attesi 5)"
    FALLITI=$((FALLITI+1))
  fi
  # e NON deve aver avviato niente: la conferma finale ha ricevuto «n»
  if printf '%s' "$uscita" | grep -q "OK, avvialo a mano quando vuoi"; then
    echo "✅ ① nessun container avviato (SETUP_YES=n rispettato)"
  else
    echo "🔴 ① la conferma finale non ha rispettato SETUP_YES=n"
    FALLITI=$((FALLITI+1))
  fi
fi

# ── ② SENZA le variabili: NON deve arrivare in fondo ────────────────────────────
#    È il gruppo di controllo: prova che il ① misura le variabili e non un
#    `setup.sh` che ignora l'input. Banco pulito, o `.env` e `secrets/` del ①
#    farebbero saltare le domande e il ② passerebbe per la ragione sbagliata.
rm -rf "$BANCO/repo/.env" "$BANCO/repo/secrets"
# l'uscita del ② non serve: interessa solo SE completa, non cosa stampa
(cd "$BANCO/repo" && timeout 120 bash setup.sh < /dev/null >/dev/null 2>&1); rc2=$?
if [ "$rc2" -eq 0 ] && [ -f "$BANCO/repo/.env" ] && \
   grep -q '^ADMIN_EMAIL=test@example.com$' "$BANCO/repo/.env" 2>/dev/null; then
  echo "🔴 ② SENZA variabili arriva in fondo CON I VALORI DI PRIMA: il ① non prova niente"
  FALLITI=$((FALLITI+1))
else
  echo "✅ ② senza le variabili non completa: il ① misura davvero le variabili"
fi

if [ "$FALLITI" -eq 0 ]; then
  echo "── setup.sh è eseguibile senza una persona, e sa ancora dire di no."
  exit 0
fi
echo "── 🔴 $FALLITI controllo/i fallito/i: il contratto non-interattivo NON regge."
exit 1
