# Il metodo del non-dimenticare — perché e come funziona il ledger delle feature

> **A chi legge:** questo file spiega il *perché* e il *come* del ledger (`features.yaml`).
> Non è il ledger — è la sua ragione d'essere e la disciplina che lo tiene vero.
> Scritto dopo aver perso una feature vera (l'auto-update) per un mese senza che nessuno se ne
> accorgesse. Non è teoria: ogni riga qui è un errore già pagato.

## Il problema, in una frase

**Una feature si perde quando ciò che è DICHIARATO diverge da ciò che è REALE, e nessuna macchina
cattura il divario.** Non si perde per cattiveria né per pigrizia: si perde perché la memoria umana
(e quella di una sessione LLM) muore, e il divario resta invisibile finché qualcuno non inciampa.

Il caso che ha fatto nascere tutto questo — **l'auto-update**:

1. Il 10/06 fu deciso di **declassare Watchtower** (l'auto-update d'allora) a «opt-in, non supportato».
   Decisione **giusta e documentata**.
2. Il rimpiazzo — un timer sicuro — doveva sostituirlo. **All'epoca non fu mai costruito**
   *(oggi sì: vedi «L'epilogo — il cerchio si è chiuso» in fondo).*
3. Nessun documento mentiva: Watchtower *era* opt-in, come scritto. Ma **l'auto-update, come
   capacità, era svanito** — caduto nel buco fra «Watchtower via» e «timer mai fatto».
4. Un reformat della VPS (~luglio) non ri-accese i profili opt-in. Nessuno se ne accorse per un mese.

**Una decisione tracciata + un lavoro non tracciato = una feature che sparisce senza che un documento
menta.** È il buco più insidioso, perché non c'è nulla di *sbagliato* da trovare: c'è solo qualcosa
che *manca*, e ciò che manca non grida.

## La regola di cattura — il cuore

> **Il ledger è la DEFINIZIONE-DI-FATTO di una decisione sulle feature.**
> *«Abbiamo declassato X»* non è vero finché il ledger non ha:
> `X · stato: rinviata · decisione: <perché + data> · follow-up: <cosa la sostituisce>`.
> **Una decisione senza la sua voce non è presa: è chiacchiera.**

Non è una regola nuova — è un pattern già validato altrove, voltato sulle feature:

- **Come un registro degli aperti**: una cosa aperta *non esiste* finché non è appesa. Il ledger:
  una decisione-su-feature non esiste finché non è scritta.
- **Come «"fatto" si dice con l'output della verifica»**: *«declassato»* si dice con la voce **e** il
  follow-up, non a parole.

Riscritto sotto questa regola, l'auto-update non si sarebbe perso: il 10/06 la voce sarebbe stata
`Watchtower · rinviata · follow-up: timer sicuro`, con il follow-up **vuoto** — e (vedi sotto) la CI
sarebbe stata **rossa dal 10/06** finché il timer non fosse esistito. Il divario avrebbe gridato per
un mese, invece di tacere.

## L'enforcement — perché la regola regge (non è solo buona volontà)

Una regola che dipende dal ricordarsela muore col cambio di sessione o di LLM. Perciò **una macchina
la fa rispettare** — è il verificatore (`verify-features.py`, in CI, non un processo in produzione).
Il verificatore è **bidirezionale**:

| verso | cosa cattura |
|---|---|
| **ledger → realtà** | ogni feature `attiva` deve avere il suo `verify` che passa. Feature dichiarata ma **sparita** → CI rossa. *Cattura la PERDITA.* |
| **realtà → ledger** | ogni tool MCP / endpoint / systemd-unit **reale** deve avere una voce. Feature reale **non dichiarata** → CI rossa. *Cattura ciò che poi si DIMENTICA.* |

Una feature **non può sparire in silenzio** (il suo verify fallirebbe) **né entrare senza traccia**
(il check inverso la pretende nel ledger). Servono entrambi i versi: uno solo lascia metà del buco.

## I due tipi di follow-up — o il verificatore diventa rumore

Un follow-up dev'essere una **condizione**, non prosa — o la CI non sa quando smettere di essere
rossa. Ce ne sono due specie, e vanno trattate all'opposto:

1. **Verificabile** — es. *«esiste `systemd/vps1777-auto-update.timer`»*. La CI lo controlla da sé:
   **rossa finché è falso, verde quando è vero. Auto-chiude.** (L'auto-update era di questa specie:
   la CI avrebbe controllato «esiste il timer?» ogni giorno.)
2. **A giudizio umano** — es. *«quando il ritmo dei rilasci sarà regolare»* (H24). La CI **non può
   deciderlo**, quindi non lo chiude — ma **lo sorveglia**: lo rimette davanti a intervalli
   (*«3 rinviati-a-giudizio da rivedere»*). Non grida (non è un bug), ma **non sparisce**.

> **Perché la distinzione salva il sistema:** senza, o i follow-up-a-giudizio tengono la CI rossa
> per sempre (rumore → si ignora → il verificatore muore), o i verificabili restano prosa e nessuno
> sa quando sono fatti. La distinzione tiene il verificatore *utile*, e uno strumento utile è uno
> strumento che non viene ignorato.

## `rivedi_dopo` — la freschezza applicata ai rinvii

Un rinvio-a-giudizio senza scadenza è un fatto stale che nessuno ri-guarda. Perciò ogni rinviata-a-
giudizio porta la **sua** `rivedi_dopo`, stimata *quando* fu rinviata — non un timer globale uguale
per tutte. Chi rinvia sa quanto lontano sta rinviando meglio di un «N giorni» generico; **una stima
grezza vale più di nessuna**. La CI non chiede «rivedi tutte ogni N giorni», chiede «questa doveva
essere rivista entro *il suo* X, e siamo oltre».

## Il confine architetturale (non violarlo)

- Il ledger è **parte del prodotto vps1777** — protegge le feature *di* vps1777. Vive **nel repo**
  (`features.yaml` è il ledger, `docs/FEATURES-METODO.md` è questo metodo); il verificatore gira
  **in CI** (o sulla VPS).
- **Non è un servizio in esecuzione**, e **non gira sul PC di chi installa vps1777** — lì gira solo
  l'installer, temporaneo. Il ledger è **documentazione + un check**, nient'altro.

## L'epilogo — il cerchio si è chiuso (e ora una macchina lo sorveglia)

Questo doc è nato da una perdita. Oggi quella perdita è **chiusa e sorvegliata** — ed è la prova
migliore che il metodo tiene, non una postilla di comodo:

- Il **rimpiazzo sicuro esiste**: `systemd/vps1777-auto-update.timer` + `.service` lanciano
  `vps1777 update --yes` (backup + firma + migrazioni + health-gate + rollback) — tutto ciò che
  Watchtower bypassava. Rilasciato in **v0.38.0**.
- **È nel ledger, non a voce**: `update.auto-timer · status: active-default · since 0.38.0`,
  dichiarato *«il RIMPIAZZO sicuro di Watchtower»*. Il vecchio meccanismo non è cancellato ma
  **tenuto visibile col suo divieto**: `ops.autoupdate · opt-in legacy NON supportato`, così
  l'avvertimento «non riaccenderlo» viaggia col profilo invece di sparire.
- **Il verificatore ora sorveglia entrambe**: se domani il timer sparisse dal repo la CI
  diventerebbe rossa (ledger→realtà); se Watchtower rientrasse senza voce la CI lo pretenderebbe
  nel ledger (realtà→ledger). Il buco da cui questo doc è nato **non può più riaprirsi in silenzio.**

Il buco durò un mese perché nessuna macchina guardava. Ora una macchina guarda. E questa sezione è
essa stessa un pezzo del metodo: **un doc che descrive un problema risolto deve dire che è risolto**,
o invecchia in una bugia — la stessa freschezza (separa *origine* da *impatto*) che il ledger impone
alle feature, applicata al doc che lo spiega.

## In una riga, per un LLM che arriva domani senza memoria di tutto questo

**Non devi *ricordare* le feature di vps1777: lancia il verificatore e le *scopri* — e scopri se la
realtà combacia col dichiarato.** Il ledger è la memoria che sopravvive a te.
