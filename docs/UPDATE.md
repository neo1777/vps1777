# Aggiornamenti — vps1777

vps1777 si aggiorna **come un software qualunque**: versioni numerate
([SemVer](https://semver.org)), changelog, un comando (o un click) per
aggiornare, backup automatico prima, **rollback automatico** se la nuova
versione non torna in salute.

Modello: **registry-pull**. Le immagini vengono buildate e firmate dalla CI
a ogni release e pubblicate su GHCR; la tua VPS fa solo `docker compose pull`.
**Niente build in produzione** — su una VPS 4GB compilare Chromium durante un
update è il momento migliore per un OOM, quindi non succede mai.

## TL;DR

```bash
vps1777 status          # dove sono, c'è una versione nuova?
vps1777 update          # aggiorna (chiede conferma, mostra il changelog)
vps1777 rollback        # torna alla versione precedente
```

Oppure dal **pannello admin → tab Update**: stessa cosa, un click.
Quando esce una release il bot Telegram ti avvisa (una volta sola).

## Cosa succede durante `vps1777 update`

```
lock → preflight → changelog+conferma → download bundle (sha256 + cosign)
  → backup age + snapshot locale volumi → pull immagini → verifica digest
  ── punto di non ritorno ──
  → sync file gestiti → stop → migrazioni → start → health-gate (180s)
  → ✅ esito su Telegram        (oppure: AUTO-ROLLBACK alla versione di prima)
```

Garanzie:

- **Prima di toccare qualunque cosa**: backup cifrato age (`tools/backup.sh`)
  + snapshot locale non cifrato dei 3 volumi dati (`backups/pre-update/`).
  Lo snapshot esiste perché l'auto-rollback **non può dipendere dalla age-key**
  (che spesso vive solo sul tuo PC); viene potato al successivo update riuscito.
- **Supply-chain**: il bundle di release porta `images.lock` con i digest
  immutabili delle 4 immagini; dopo il pull, i digest locali DEVONO combaciare.
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

Sulla VPS girano **due** timer systemd, con cadenze diverse perché sorvegliano
cose che invecchiano a velocità diverse.

**1. Nuove release** — `vps1777-check-update.timer`, **una volta al giorno**. Fa
una GET **non autenticata** a `api.github.com/repos/neo1777/vps1777/releases/latest`
— **zero telemetria**: nessun dato lascia la tua VPS. Se c'è una versione
nuova: messaggio Telegram al owner (una sola volta per release) e badge nella
card admin. Se GitHub è irraggiungibile: nessun rumore, solo un badge
"check stantio".

**2. Scadenze dei secret** — `vps1777-secrets-check.timer`, **settimanale**
(i secret invecchiano lentamente: una nudge a settimana basta; `RandomizedDelaySec`
distribuisce il carico, `Persistent=true` recupera i check persi a VPS spenta).
Lancia `vps1777 secrets-status --notify`: legge l'mtime dei file in `secrets/`,
scrive `onboarding/secrets_status.json` (che alimenta `/admin/secrets`) e
notifica su Telegram i secret oltre soglia. Le soglie e il *perché* di ognuna
stanno in [SECRETS.md](SECRETS.md). Puoi lanciarlo a mano quando vuoi:

```bash
vps1777 secrets-status          # a schermo
vps1777 secrets-status --notify # + notifica Telegram se qualcosa è oltre soglia
```

> Entrambe le unit non hanno utente né path hardcodati: la CLI sostituisce
> `@OPERATOR_USER@` / `@REPO@` coi valori reali a ogni update (H43). Era un bug
> vero: con un operatore diverso da `vps1777` il controllo delle scadenze
> smetteva di girare **in silenzio**.

## Rollback manuale

```bash
vps1777 rollback              # torna alla versione precedente (solo immagini+file)
vps1777 rollback --with-data  # anche i volumi dallo snapshot pre-update
```

Il default NON tocca i dati. `--with-data` ripristina i 3 volumi dallo snapshot
pre-update: i dati scritti dopo quell'update vanno persi — è la scelta giusta
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

Il profilo `ops.autoupdate` (Watchtower) esiste ancora ma è **declassato e non
supportato in concomitanza** col canale gestito: bypassa backup, migrazioni,
health-gate, changelog e rollback. Con i tag SemVer pinnati è comunque quasi
inerte. `vps1777 update` ti avvisa se lo trova attivo. Usa il canale gestito.

## File e stato (dove vive cosa)

| Cosa | Dove |
|---|---|
| Versione deployata | `.env` → `VPS1777_TAG` (scritta SOLO da update/rollback/bootstrap/installer) |
| Stato del canale (previous, history, nonce…) | `var/state.json` (chmod 700) |
| Release staged (bundle + rollback-files) | `releases/vX.Y.Z/` (tenute: corrente + precedente) |
| Snapshot pre-update | `backups/pre-update/` (tenuto: l'ultimo) |
| Stato check / intent / progress (per la card admin) | `onboarding/update_{status,pending_update,progress}.json` |
| Registro migrazioni | volume `gateway-data` → `state/migrations.json` |
| Log dell'updater | `journalctl -u vps1777-update -u vps1777-check-update` |

## Troubleshooting rapido

- **"update già in corso"** — c'è un lock (`var/update.lock`). Se è un residuo
  di un crash: `vps1777 status` mostra `update_in_progress`; nessun processo
  attivo → riprova, il lock è per-processo.
- **Digest mismatch al pull** — qualcosa non torna tra registry e release
  (attacco o release corrotta): l'update abortisce PRIMA di toccare lo stack.
  Controlla la release su GitHub e riprova.
- **Rollback non healthy (exit 2)** — la CLI si ferma senza thrashing e ti
  scrive su Telegram. Hai: lo snapshot in `backups/pre-update/`, il backup age
  in `backups/`, e `docs/BACKUP-RESTORE.md` per il disaster recovery.
