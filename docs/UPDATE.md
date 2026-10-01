# Aggiornamenti — vps1777

vps1777 si aggiorna **come un software qualunque**: versioni numerate
([SemVer](https://semver.org)), changelog, un comando (o un click) per
aggiornare, backup automatico prima, **rollback automatico** se la nuova
versione non torna in salute.

Modello: **registry-pull**. Le immagini vengono buildate e firmate dalla CI
a ogni release e pubblicate su GHCR; la tua VPS fa solo `docker compose pull`.
**Niente build in produzione** — su una VPS 4GB compilare le immagini durante un
update è il momento migliore per un OOM, quindi non succede mai.

## TL;DR

```bash
vps1777 status          # dove sono, c'è una versione nuova?
vps1777 update          # aggiorna (chiede conferma, mostra il changelog)
vps1777 rollback        # torna alla versione precedente
```

Oppure dal **pannello admin → tab Update**: stessa cosa, un click.
Quando esce una release il bot Telegram ti avvisa (una volta sola).
E se non fai niente, **fa da sola**: di default `vps1777-auto-update.timer`
applica l'update sicuro da sola: guarda ogni giorno e installa una release solo
quando ha **almeno 48 ore di vita** (feature `autoupdate`, attiva di default; come
spegnerla è in [OPS.md](OPS.md)).

## Cosa succede durante `vps1777 update`

```
lock → preflight → changelog+conferma → download bundle (sha256 + cosign)
  → backup age + snapshot locale volumi → pull immagini → verifica digest
  ── punto di non ritorno ──
  → sync file gestiti → stop → migrazioni → start → health-gate (180s)
  → ✅ esito su Telegram        (oppure: AUTO-ROLLBACK alla versione di prima)
```

Garanzie:

- **Prima di toccare qualunque cosa**: backup cifrato age del livello **core**
  (`tools/backup.sh --senza-archivio`: volumi piccoli, secret, config, description
  dei DB) + snapshot locale non cifrato di 2 volumi dati, `gateway-data` e
  `archive-data` (`backups/pre-update/`). Il terzo, `nlm-auth`, resta fuori di
  proposito (`H14`): sono i cookie di sessione Google, e uno snapshot in chiaro li
  copierebbe sul disco dell'host — stanno nel backup age, cifrati, e il profilo si
  ricarica da `/admin/nlm`.
  L'archivio cifrato ha il suo passo settimanale dal cron notturno — qui lo copre
  lo snapshot (vedi [BACKUP-RESTORE.md](BACKUP-RESTORE.md), «I due livelli»).
  Lo snapshot esiste perché l'auto-rollback **non può dipendere dalla age-key**
  (che spesso vive solo sul tuo PC); viene potato al successivo update riuscito.
- **Supply-chain**: il bundle di release porta `images.lock` con i digest
  immutabili delle immagini (una per servizio); dopo il pull, i digest locali DEVONO combaciare.
  Dal 01/10/2026 il lock contiene anche `caddy-dns01`, l'immagine **opzionale** della
  feature omonima ([INGRESS.md](INGRESS.md), DNS-01): la verifica riguarda le immagini che
  lo stack attivo usa davvero (lo chiede a `docker compose config --images`), e una voce
  del lock che non usa la scrive nel log come «non attivo — non verificato» invece di
  pretenderla. Prima si pretendevano tutte, e a feature spenta ogni update sarebbe fallito.
  Poi la CLI scrive quei digest nel `.env` (`VPS1777_DIGEST_GATEWAY`, `…_ARCHIVE_MCP`,
  `…_NB1777_MCP`, `…_NB1777_BOT`, `…_OCR`, `…_CADDY_DNS01`) insieme a `VPS1777_TAG`, in
  una sola scrittura, e `compose.yaml` (o l'overlay della feature) li usa:
  `…/vps1777-gateway:${VPS1777_TAG:-dev}${VPS1777_DIGEST_GATEWAY:+@${VPS1777_DIGEST_GATEWAY}}`
  — il `@digest` si aggiunge solo se la variabile c'è.
  Così anche un `docker compose pull` o `up` lanciato **a mano** nella cartella gira il
  digest verificato, non quello che il registro serve per il tag in quel momento (`H22`).
  Non modificarli a mano: li scrivono update, rollback e bootstrap. Vuoti = pin spento
  (resta il tag): succede su un'installazione nuova fino al primo update.
  La firma keyless del bundle è verificata con `cosign` **di default e in
  fail-closed**: se la verifica non passa — o se `cosign` manca e non è
  auto-installabile — l'update si ferma. `cosign` viene auto-installato se
  assente (versione pinnata). Via d'emergenza consapevole:
  `VPS1777_REQUIRE_COSIGN=0` in `.env` oppure `--no-require-cosign`.
- **I tag `v*` sono immutabili** (H24, v0.32.0): un ruleset GitHub vieta di
  spostarli o cancellarli. È il pezzo che rende *fidato* tutto il resto: se un
  tag potesse essere ripuntato, il bundle firmato a cui l'update si àncora
  potrebbe essere sostituito sotto i piedi, e la verifica del digest starebbe
  confrontando la cosa sbagliata con sé stessa. (La regola `non_fast_forward`
  da sola non bastava: spostare un tag *in avanti* è un fast-forward.)
- **Rollback automatico**: se dopo l'update lo stack non torna healthy entro
  180s (healthcheck compose + probe `/health?deep=1` del gateway), la VPS torna
  **da sola** alla versione precedente — le immagini vecchie sono ancora locali,
  nessun nuovo download. Se una migrazione ha toccato i dati, i volumi vengono
  ripristinati dallo snapshot (all-or-nothing, così registro e dati restano
  coerenti). Esito sempre su Telegram.

## Il pulsante nel pannello admin

Il gateway **non ha privilegi Docker** (per design — vedi
`docs/ARCHITECTURE.md`): il pulsante *Aggiorna* scrive solo un **intent file**
in `onboarding/`; una systemd path unit sull'host lo vede in <1s e lancia lo
stesso identico `vps1777 update`. L'intent è validato (schema, semver, TTL 10
minuti, nonce anti-replay, target = ultima release nota) e **cancellato prima
di agire**. Il progresso è mostrato nella card (la pagina tollera il riavvio
del gateway stesso a metà update); l'esito arriva comunque su Telegram.

## Notifiche e check

Sulla VPS girano **tre** timer systemd di serie, con cadenze diverse: due
**sorvegliano** cose che invecchiano a velocità diverse, il terzo **applica**. Un
quarto, facoltativo, non riguarda l'update e si accende a mano (sotto, al punto 4).

**1. Nuove release** — `vps1777-check-update.timer`, **una volta al giorno**. Fa
una GET **non autenticata** a `api.github.com/repos/neo1777/vps1777/releases/latest`
— **zero telemetria**: nessun dato lascia la tua VPS. Se c'è una versione
nuova: messaggio Telegram al owner (una sola volta per release) e badge nella
card admin. Se GitHub è irraggiungibile: nessun rumore, solo un badge
"check stantio".

**2. Scadenze dei secret** — `vps1777-secrets-check.timer`, **giornaliero**
(era settimanale: i secret invecchiano lentamente, ma fra le voci controllate c'è la
via d'emergenza cosign, che scade in **un giorno** — e la cadenza di un controllo non
può essere più lenta della sua soglia più stretta; nel caso normale non cambia il
rumore, perché notifica solo ciò che è oltre soglia. `RandomizedDelaySec` distribuisce
il carico, `Persistent=true` recupera i check persi a VPS spenta).
Lancia `vps1777 secrets-status --notify`: legge l'mtime dei file in `secrets/`,
scrive `onboarding/secrets_status.json` (che alimenta `/admin/secrets`) e
notifica su Telegram i secret oltre soglia. Le soglie e il *perché* di ognuna
stanno in [SECRETS.md](SECRETS.md). Puoi lanciarlo a mano quando vuoi:

```bash
vps1777 secrets-status          # a schermo
vps1777 secrets-status --notify # + notifica Telegram se qualcosa è oltre soglia
```

**3. Auto-update sicuro** — `vps1777-auto-update.timer`, **giornaliero, con quarantena di 48 ore**.
Questo non sorveglia: **applica** `vps1777 update --yes`, con l'intera rete di
sicurezza del canale gestito (backup, verifica digest, migrazioni, health-gate,
rollback). Il timer lo accende l'installazione se la feature `autoupdate` è dichiarata
in `VPS1777_FEATURES` (default sì), e update e rollback lo riallineano alla stessa riga:
togli `autoupdate` e il primo update o rollback lo spegne, rimettila e lo riaccende. È il
motivo per cui il check quotidiano può limitarsi ad avvisare: l'applicazione ha già un
suo canale sicuro. Dettagli e spegnimento: [OPS.md](OPS.md).

**La quarantena di 48 ore** (dal 27/09/2026). La unit lancia
`vps1777 update --yes --eta-minima 48`: se l'ultima release è stata pubblicata da meno
di 48 ore, il giro non fa niente e lo scrive nel journal («in quarantena… riprovo al
prossimo giro»). Serve a dare a un rilascio sbagliato il tempo di essere **ritirato**
prima che una macchina lo installi da sola: basta segnarlo come *prerelease* su GitHub,
perché l'update legge `/releases/latest`, che le prerelease le esclude. Vale **solo**
per il percorso automatico: `vps1777 update` a mano, `--version` e il pulsante admin
installano subito, e sono la via per una correzione urgente. Una data di pubblicazione
illeggibile vale come «troppo giovane»: in dubbio, da sola non installa.

**4. Indice notturno (facoltativo)** — `vps1777-indice-notturno.timer`, **ogni notte
alle 03:30** (con fino a 30 minuti di ritardo casuale). Non è acceso dall'installer: si
accende con `vps1777 indice-notturno --abilita` (e si spegne con `--disabilita`), perché
serve solo a chi ha già costruito l'indice della ricerca per senso. Aggiorna gli indici
**che esistono già**, e solo per i DB cambiati dopo la loro costruzione, nel servizio
compose `indice-notturno` (profilo `indice`: nessuna rete, una CPU, tetto di 1300 MB);
una prima costruzione non parte mai da sola. Vedi [RICERCA-IBRIDA.md](RICERCA-IBRIDA.md).

> Le unit non hanno utente né path hardcodati: la CLI sostituisce
> `@OPERATOR_USER@` / `@REPO@` coi valori reali a ogni update (H43). Era un bug
> vero: con un operatore diverso da `vps1777` il controllo delle scadenze
> smetteva di girare **in silenzio**.

## Rollback manuale

```bash
vps1777 rollback              # torna alla versione precedente (solo immagini+file)
vps1777 rollback --with-data  # anche i volumi dallo snapshot pre-update
```

Il default NON tocca i dati. `--with-data` ripristina dallo snapshot pre-update i 2
volumi che contiene (`gateway-data`, `archive-data`; il profilo NotebookLM non c'è, vedi
sopra): i dati scritti dopo quell'update vanno persi — è la scelta giusta
solo se l'update ha corrotto i dati.

## Migrazioni

Se una release cambia lo schema dei dati, porta con sé una migrazione
(`migrations/NNNN-slug/`) che l'update applica **una volta sola**, in un
container one-off senza rete, prima di riavviare lo stack. I salti
multi-versione (N → N+3) applicano in ordine tutto ciò che manca. Il contratto
completo: [`migrations/README.md`](../migrations/README.md). Non esistono
downgrade-script: tornare indietro = restore da snapshot/backup.

## Ho un'installazione vecchia (pre-canale update)

Un'installazione "legacy" (immagini buildate in locale, nessun comando
`vps1777`) si converte **una volta sola** con il bootstrap:

```bash
# dalla shell della VPS, utente vps1777, dentro ~/vps1777
VER=X.Y.Z   # ultima release: https://github.com/neo1777/vps1777/releases
curl -fsSLO "https://github.com/neo1777/vps1777/releases/download/v${VER}/vps1777-runtime-v${VER}.tar.gz"
curl -fsSLO "https://github.com/neo1777/vps1777/releases/download/v${VER}/SHA256SUMS"
sha256sum -c SHA256SUMS                    # verifica esplicita — mai curl|bash
mkdir -p /tmp/vps1777-bundle && tar xzf "vps1777-runtime-v${VER}.tar.gz" -C /tmp/vps1777-bundle
bash /tmp/vps1777-bundle/tools/bootstrap.sh
```

Il bootstrap: backup completo → installa CLI + timer → converte i compose al
modello pull → pull + verifica digest → riavvia dai container ghcr → health-gate.
I volumi named **non vengono mai toccati** (`up` non li ricrea; nessun percorso
esegue mai `down -v`): zero perdita dati. Se qualcosa va storto, ripristina da
solo lo stack precedente (le vecchie immagini restano come paracadute fino al
primo `vps1777 update` riuscito). È idempotente: rieseguito, dice "già a regime".

## Canali

- **stable** (default): solo release stabili — `releases/latest` esclude le
  prerelease, quindi le `-rc.*` di test non ti raggiungono mai.
- **prerelease** (solo per test): `VPS1777_RELEASE_CHANNEL=prerelease` in
  `.env`, oppure update esplicito con `vps1777 update --version vX.Y.Z-rc.1`.

## E Watchtower?

**Rimosso nella 0.67.0.** Il profilo `ops.autoupdate` (Watchtower) bypassava backup,
migrazioni, health-gate, changelog e rollback, e la sua immagine è archiviata a monte.
L'update alla 0.67.0 ferma e rimuove il container `vps1777-watchtower` se lo trova
(step 11, con una riga nel log). Se `VPS1777_FEATURES` nomina ancora `watchtower`, la
CLI lo dice a ogni comando e la ignora: toglila dal `.env`. L'aggiornamento automatico
è la feature `autoupdate` (il timer, con quarantena e rete di sicurezza).

## File e stato (dove vive cosa)

| Cosa | Dove |
|---|---|
| Versione deployata | `.env` → `VPS1777_TAG` (scritta SOLO da update/rollback/bootstrap/installer) |
| Stato del canale (previous, history, nonce…) | `var/state.json` (chmod 700) |
| Release staged (bundle + rollback-files) | `releases/vX.Y.Z/` (tenute: corrente + precedente) |
| Snapshot pre-update | `backups/pre-update/` (tenuti: l'ultimo delle ultime **2 versioni** — n e n-1; il resto si pota subito. Decisione owner del 29/08: la vecchia regola 72h+3-versioni non guardava il PESO, e 7 release in 36h × volumi da 10 GB hanno riempito il disco) |
| Stato check / intent / progress (per la card admin) | `onboarding/update_{status,pending_update,progress}.json` |
| Storia degli step (una riga per step, anche degli update riusciti e di quelli notturni; ultime 2.000 righe) | `onboarding/update_journal.ndjson` — `tail -n 20 onboarding/update_journal.ndjson` |
| Registro migrazioni | volume `gateway-data` → `state/migrations.json` |
| Log dell'updater | `journalctl -u vps1777-auto-update -u vps1777-update -u vps1777-check-update` (il giro automatico del timer scrive nella prima) |

## Troubleshooting rapido

- **"update già in corso"** — c'è un lock (`var/update.lock`): un altro update,
  rollback o bootstrap sta lavorando. La CLI esce con **75** (`EX_TEMPFAIL`, «riprova
  più tardi»), che le unit di update contano come successo (`SuccessExitStatus=75`):
  un giro del timer che incontra un update in corso non manda un falso «fallito» su
  Telegram. Se è un residuo di un crash: `vps1777 status` mostra `update_in_progress`;
  nessun processo attivo → riprova, il lock è per-processo.
- **Digest mismatch al pull** — qualcosa non torna tra registry e release
  (attacco o release corrotta): l'update abortisce PRIMA di toccare lo stack.
  Controlla la release su GitHub e riprova.
- **Rollback non healthy (exit 2)** — la CLI si ferma senza thrashing e ti
  scrive su Telegram. Hai: lo snapshot in `backups/pre-update/`, il backup age
  core in `backups/` (e l'archivio in `backups/archivio/`), e
  `docs/BACKUP-RESTORE.md` per il disaster recovery.
