#!/usr/bin/env bash
# collaudo-da-fuori.sh — l'installazione è riuscita? Chiesto DA FUORI, come l'utente.
#
# USO
#   ./tools/collaudo-da-fuori.sh https://tuo-url-pubblico     # dal TUO PC, non dalla VPS
#   PUBLIC_BASE=https://… ./tools/collaudo-da-fuori.sh
#   ./tools/collaudo-da-fuori.sh --help
#
# PERCHÉ ESISTE (voce `74b03e59`, collaudo del 02/08: format + reinstall):
#   `vps1777` promette «una persona sola, dal suo PC, senza shell sulla VPS». Ogni
#   verifica che richieda la shell prova un'altra cosa — e l'installer, che è il punto
#   ① della catena, NON HA TEST e la CI non lo tocca (zero occorrenze in `ci.yml`).
#
# 🔑 E LA RAGIONE PER CUI NON SI LEGGE L'OUTPUT DELL'INSTALLER: il 02/08 abbiamo curato
#   `_ts_funnel_ok()`, che dichiarava «✓ Funnel attivo» leggendo una STRINGA DI STATO
#   LOCALE — e su quel booleano metteva `production=True`, che chiude la porta 8080 di
#   fallback. Config a posto + tunnel rotto = utente senza HTTPS **e** senza fallback.
#   ⇒ un installer che dice «fatto» è una dichiarazione; questo script è una misura.
#
# 🔴 E PERCHÉ STA QUI DENTRO, che è la cura di un difetto suo (collaudo da fuori del
#   07/09/2026): fino a ieri questo file viveva in una cartella di lavoro FUORI dal
#   repo. Era sano, era stato scritto bene — e non lo lanciava nessuno. `git ls-files`
#   non lo conteneva, nessun documento lo nominava, la CI non poteva vederlo, e uno
#   sconosciuto che installa vps1777 non l'avrebbe incontrato mai.
#   ⭐ *Uno strumento fuori dal perimetro dell'oggetto che misura non viene agganciato:
#   non è pigrizia di chi non l'ha lanciato, è che non c'era il posto da cui lanciarlo.*
#   Da qui `setup.sh` e `deploy.sh` lo stampano come ultima riga — la fine
#   dell'installazione è il solo istante in cui qualcuno ha in mano l'URL.
#
# I TRE STATI, non due:
#   0  l'installazione risponde da Internet ed è ciò che dice di essere
#   1  NON risponde — e si dice QUALE passo è caduto, non «errore»
#   2  non eseguibile qui (manca l'URL, manca `curl`, il bersaglio è locale): «non ho
#      potuto guardare» non deve avere lo stesso colore di «non funziona»
#
# ⚠️ COSA NON PROVA, dichiarato: che i DATI siano tornati (archivio, notebook, profilo).
#   Prova che il servizio è in piedi e raggiungibile. Il ritorno dei dati si verifica
#   con una ricerca vera, e quella la può fare solo chi sa cosa cercare.
set -uo pipefail

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  sed -n '2,38p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 0
fi

URL="${1:-${PUBLIC_BASE:-}}"
if [ -z "$URL" ]; then
  echo "uso: collaudo-da-fuori.sh <https://url-pubblico>   (o PUBLIC_BASE nell'ambiente)" >&2
  echo "   non ho un bersaglio: NON so se l'installazione è viva, e non è la stessa" >&2
  echo "   cosa che sia morta." >&2
  exit 2
fi
command -v curl >/dev/null 2>&1 || { echo "⛔ curl non c'è: non eseguibile qui." >&2; exit 2; }
URL="${URL%/}"
host=$(printf '%s' "$URL" | sed -E 's#^https?://##; s#/.*##; s#:.*##')
porta=$(printf '%s' "$URL" | sed -E 's#^https?://##; s#/.*##; s#^[^:]*##; s#^:##')

# ── IL BERSAGLIO È LOCALE? Allora questa sonda non ha niente da misurare ──────────────
# 🔑 Terzo stato, applicato al BERSAGLIO e non solo all'esito (cura del 07/09): puntato
#   su `127.0.0.1` questo script rispondeva 🔴 due volte — «non è https» e «l'8080
#   risponde» — ed erano due verdetti VERI su una domanda che nessuno aveva fatto: chi
#   prova in locale (docs/PRIMI-15-MINUTI.md) non ha, e non vuole, un ingress pubblico.
#   ⚠️ Un rosso corretto sulla domanda sbagliata insegna a ignorare i rossi. E la cura
#   NON è far finta che il locale passi: è dire che qui la domanda non ha soggetto.
case "$host" in
  127.0.0.1|localhost|::1|0.0.0.0|[Ll]ocalhost.localdomain)
    echo "⚪ bersaglio LOCALE ($host): questa sonda misura la promessa PUBBLICA del" >&2
    echo "   README — «un solo URL HTTPS, raggiungibile da Internet». Da qui non la" >&2
    echo "   posso né confermare né smentire, e un verdetto lo darei su un'altra cosa." >&2
    echo "   · prova in locale  → la verifica è \`docker compose ps\` + il pannello:" >&2
    echo "                        docs/PRIMI-15-MINUTI.md" >&2
    echo "   · installazione vera → rilanciami con l'URL pubblico, dal TUO PC." >&2
    exit 2 ;;
esac

ok=0; ko=0
riga() { printf '  %s  %-34s %s\n' "$1" "$2" "$3"; }

# ── ① IL SERVIZIO RISPONDE DA INTERNET ───────────────────────────────────────────────
# Conta QUALUNQUE risposta HTTP, 401 compresa: si prova che il tunnel porta i byte, non
# che l'app dica sì. (È la stessa scelta di `_funnel_confermato_da_qui()` nell'installer:
# un 401 dimostra che c'è qualcuno dall'altra parte.)
# 🔴 NIENTE `|| echo "000"`: quando curl fallisce stampa GIÀ `000`, e il fallback ne
#   aggiungeva un secondo → `000000`, che non era uguale a «000» e faceva dire ✅ su un
#   dominio INESISTENTE. Cioè: il primo controllo di questo script aveva la classe che
#   lo script esiste per prevenire — un verde senza aver misurato. Trovato provandolo
#   su un bersaglio a risposta NOTA (`.invalid`), che è l'unico caso che la prende.
# ⇒ l'esito di curl si cattura a parte, e il codice si valida come TRE CIFRE.
codice=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 "$URL/" 2>/dev/null)
esito_curl=$?
[[ "$codice" =~ ^[0-9]{3}$ ]] || codice="000"
if [ "$esito_curl" -ne 0 ] || [ "$codice" = "000" ]; then
  riga "🔴" "risponde da Internet" "nessuna risposta da $URL"
  ko=$((ko+1))
else
  riga "✅" "risponde da Internet" "HTTP $codice (qualunque codice prova il transito)"
  ok=$((ok+1))
fi

# ── ② È HTTPS CON UN CERTIFICATO VALIDO ──────────────────────────────────────────────
# Separato dal ①: un servizio che risponde in HTTP semplice ha «funzionato» per l'utente
# e NON mantiene la promessa del README («un solo URL HTTPS pubblico»).
case "$URL" in
  https://*)
    if curl -sS -o /dev/null --max-time 15 "$URL/" 2>/dev/null; then
      riga "✅" "certificato TLS valido" "curl non ha dovuto forzare"
      ok=$((ok+1))
    else
      riga "🔴" "certificato TLS valido" "TLS rifiutato (cert non valido o non ancora emesso)"
      ko=$((ko+1))
    fi ;;
  *) riga "⚠️" "certificato TLS valido" "l'URL non è https: la promessa del README non è mantenuta"
     ko=$((ko+1)) ;;
esac

# ── ③ IL PANNELLO ADMIN ESISTE ───────────────────────────────────────────────────────
# Un 200 o un 302 verso il login vanno bene entrambi; un 404 dice che il gateway
# risponde ma non è vps1777 — il caso che «risponde da Internet» da solo non distingue.
adm=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 "$URL/admin/login" 2>/dev/null)
[[ "$adm" =~ ^[0-9]{3}$ ]] || adm="000"
case "$adm" in
  200|302|303|401|403) riga "✅" "pannello admin presente" "HTTP $adm su /admin/login"; ok=$((ok+1)) ;;
  404) riga "🔴" "pannello admin presente" "404: risponde qualcosa, ma non è vps1777"; ko=$((ko+1)) ;;
  *)   riga "🔴" "pannello admin presente" "HTTP $adm"; ko=$((ko+1)) ;;
esac

# ── ④ LA PORTA 8080 DI FALLBACK NON È RIMASTA APERTA ─────────────────────────────────
# 🔑 Questo è il controllo che nasce dal difetto vero: `production=True` la chiude, e la
#   cura del 02/08 riguarda proprio QUANDO viene messo. Se dopo un'installazione riuscita
#   l'8080 risponde ancora da Internet, il fallback è rimasto esposto.
# 🔴 E QUESTO CONTROLLO HA SENSO SOLO SE IL ① È PASSATO. Su un host che NON ESISTE,
#   «nessuna risposta sulla 8080» non prova che il fallback sia chiuso: prova che non
#   c'è niente. La prima stesura diceva ✅ su un dominio `.invalid` — cioè il controllo
#   dichiarava OK proprio quando la cosa da controllare era ASSENTE, che è la LENTE A
#   del round-14 dentro lo strumento scritto per applicarla.
#   ⇒ terzo stato: «non applicabile», che non è un verde e non è un rosso.
# 🔴 SECONDO CASO SENZA SOGGETTO, annotato dal collaudo del 07/09 e curato qui: se il
#   BERSAGLIO è già la 8080, questo controllo interroga se stesso. Dice il vero — «la
#   8080 risponde» — ma risponde a «hai puntato lì», non a «il fallback è rimasto
#   aperto», e il lettore lo legge come un allarme. *Due domande diverse non possono
#   avere la stessa riga di output.*
if [ "$esito_curl" -ne 0 ] || [ "$codice" = "000" ]; then
  riga "⚪" "fallback 8080 chiuso" "NON APPLICABILE: il servizio non risponde, quindi"
  printf '      %s\n' "questa domanda non ha un soggetto — non è un verde."
elif [ "$porta" = "8080" ]; then
  riga "⚪" "fallback 8080 chiuso" "NON APPLICABILE: il bersaglio È la 8080, quindi"
  printf '      %s\n' "chiederglielo vuol dire chiedere a se stessa — non è un verde."
else
  f=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 8 "http://$host:8080/" 2>/dev/null)
  esito_f=$?
  [[ "$f" =~ ^[0-9]{3}$ ]] || f="000"
  if [ "$esito_f" -ne 0 ] || [ "$f" = "000" ]; then
    riga "✅" "fallback 8080 chiuso" "nessuna risposta (atteso dopo un'installazione riuscita)"
    ok=$((ok+1))
  else
    riga "🔴" "fallback 8080 chiuso" "HTTP $f — la porta di fallback è ancora esposta"
    ko=$((ko+1))
  fi
fi

echo
echo "  ── $ok verificati · $ko caduti ─────────────────────────────────────────"
echo "  ⚠️  NON prova che i DATI siano tornati (archivio, notebook, profilo nlm):"
echo "      prova che il servizio è in piedi e raggiungibile. Il ritorno dei dati"
echo "      si verifica con una ricerca vera, e la fa chi sa cosa cercare."
[ "$ko" -eq 0 ] || exit 1
exit 0
