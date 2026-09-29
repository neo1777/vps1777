# Backup & Restore — vps1777

Strategia: backup age-encrypted dei volumi + secrets, in `backups/`, su **due livelli**
separati per natura del dato — perché il 99,99% del peso è rigenerabile e lo 0,01% no.

## I due livelli (dal `0.43.13`)

| Livello | Cosa contiene | Quando | Ritenzione | Dove |
|---|---|---|---|---|
| **core** | tutti i volumi **tranne** l'archivio (`gateway-data`, `gateway-uploads`, `nlm-auth` — che da v0.44.0 porta anche gli strati locali della memoria 1777, `memoria-1777/{fatti,errata}.md` —, `nlm-artifacts`, …), `secrets/`, `.env` + compose + `ingress/`, e **le `description` dei DB dell'archivio** (`descrizioni/<db>.txt`) | **ogni notte** (03:00 UTC) e a ogni `vps1777 update` | 7 giorni distinti + 4 settimanali + ultime 3 versioni | `backups/vps1777-<ts>.tar.age` |
| **archivio** | i soli volumi dell'archivio (`archive-data`: i DB FTS), **compressi** prima di cifrare | **ogni 7 giorni** (dal cron notturno, quando è dovuto) | le ultime **2** copie — n e n-1 | `backups/archivio/vps1777-archivio-<ts>.tar.age` |

> **Perché due livelli** — misurato il 29/08/2026 sulla VPS: un backup pesava 9,7 GB, e
> 9,7 GB erano il solo `archive-data`. I DB dell'archivio sono **rigenerabili** dai
> bundle/export che l'owner conserva fuori dalla VPS (re-ingest ≈ 2h); tutto il resto —
> utenti, client OAuth, audit, profilo NotebookLM, secret — pesa 250 KB ed è
> **insostituibile**. Si pagavano 9,7 GB a notte per proteggere 250 KB (≈ 70 GB a regime
> su un disco da 118). L'unica parte dell'archivio che il re-ingest **non** rigenera sono
> le schede scritte a mano con `set_description`: per questo viaggiano ogni notte nel
> core. Decisione dell'owner: *«basta n, n-1 per paranoia… dobbiamo farci stare quel che
> serve»*. Fra un backup archivio e l'altro la rete è doppia: le fonti fuori dalla VPS +
> lo snapshot pre-update (`backups/pre-update/`, in chiaro, n e n-1).

> **«Tutti i volumi» dipende da DOVE gira `backup.sh`**, e i due contesti non salvano
> la stessa cosa:
>
> - **nel container `backup`** (il cron notturno) salva i volumi **montati** in
>   `compose.ops.backup.yaml`: `gateway-data`, `gateway-uploads`, `nlm-auth`,
>   `nlm-artifacts` (più `archive-data` per il livello archivio). `caddy-data` e
>   `caddy-config` **non ci sono**, di proposito: l'overlay vale per tutti gli ingress. Con
>   Caddy li salva il backup dall'host (sotto), e se mancano Caddy riottiene i certificati
>   da solo all'avvio. Non modificare a mano `compose.ops.backup.yaml`: è gestito, e il
>   primo update riscrive la modifica. È **solo qui** che si esportano le `descrizioni/<db>.txt`;
> - **sull'host** (`./tools/backup.sh` a mano, e il backup che fa `vps1777 update`)
>   chiede i volumi a `docker compose config --volumes` e, dal 29/09, anche a Docker per
>   etichetta di progetto: così segue davvero gli overlay attivi (prima leggeva solo
>   `compose.yaml`, e i volumi di Caddy e Portainer non entravano in nessun backup);
>   ma il volume dell'archivio non è leggibile da lì e le **`descrizioni/` non vengono
>   esportate** — lo dice nel log, e restano quelle dell'ultimo backup archivio.

Il nome resta `.tar.age` per entrambi anche se dentro c'è **zstd** (o gzip, se zstd
manca): il suffisso è un contratto letto da ritenzione, CLI, `restore.sh` e test. Il
formato reale sta nel sidecar `.meta` (`compressione: zstd`) e nei primi 4 byte del
decifrato — `restore.sh` lo riconosce da lì. A mano, con la tua chiave privata:
`age -d -i <chiave privata> f.tar.age | zstd -dc | tar -x`.

## Backup manuale

```bash
./tools/backup.sh                    # core + archivio SE dovuto (≥ 7 giorni dall'ultimo)
./tools/backup.sh --archivio         # core + archivio COMUNQUE
./tools/backup.sh --senza-archivio   # solo core (è ciò che fa `vps1777 update`)
./tools/backup.sh --prune-only       # SOLO la ritenzione: nessun backup nuovo
# → backups/vps1777-2026-08-29-030000.tar.age
#   backups/archivio/vps1777-archivio-2026-08-29-030000.tar.age
```

Un flag alla volta: con due flag, o con uno sconosciuto, stampa l'uso ed esce **2**.

Variabili (con i default): `BACKUP_DIR=backups/` (dove scrive e pota),
`VOLUMI_ARCHIVIO=archive-data` (nomi logici del livello archivio),
`ARCHIVIO_OGNI_GIORNI=7`, `KEEP_ARCHIVIO=2`, `KEEP_VERSIONI=3`.

Cosa NON includi: log container (sono in `/var/lib/docker/containers/*/`, gestiti dal driver json-file con rotation).

Il `MANIFEST.txt` dentro ogni archivio registra il livello (`tier:`), cosa contiene, la
compressione, la versione deployata (`VPS1777_TAG` dal `.env`) e il `VERSION` del bundle.

## Backup automatico (cron) — attivo di default

Il backup notturno è **attivo di default**: non devi fare nulla per averlo. L'installer
lo accende leggendo lo **stato dichiarato** delle feature — `VPS1777_FEATURES` nel `.env`
(default: `backup,autoupdate`). Il container `backup` esegue ogni notte (cron **03:00 UTC**)
il livello **core** — e il livello **archivio** quando è dovuto (ogni 7 giorni) — e tiene
**7 core giornalieri + 4 settimanali**, più **l'ultimo core di ciascuna delle ultime 3
versioni** (letta dal sidecar `.meta`), più **2 archivio**, tutti cifrati `age`.
`vps1777 check` (il timer giornaliero) avvisa se l'ultimo archivio ha più di 14 giorni;
finché non esiste nessun backup archivio, quell'avviso non parte.

> **Perché "dichiarato" e non "ricordato" — ed è il cuore del non-perdere-funzioni.**
> Prima (fino a v0.37.x) il backup era un profilo **opt-in**: un reinstall della VPS non lo
> ri-accendeva, e nessuno se ne accorgeva — la rete di sicurezza spariva in silenzio.
> Da **v0.38.0** la scelta vive in `VPS1777_FEATURES`: l'installer la legge, e install,
> update e rollback **riproducono sempre le stesse feature**. Un reinstall non "dimentica"
> il backup — lo **riproduce per costruzione**. E l'installer chiude col **referto**: un
> `OFF` non richiesto **si vede subito nel log**, non si scopre dopo mesi. La riga non è
> la stessa nelle tre vie: l'installer grafico scrive
> `✓ Feature attive: backup=ON · auto-update sicuro=ON · portainer=OFF`, `deploy.sh`
> chiude con `chiave age (backup): <stato>`, e `setup.sh` dice
> `Backup: recipient age presente` oppure `Backup DICHIARATO ma NON ARMATO`.

### Accendere o spegnere il backup

Non con un comando `docker compose` a mano (quello non sopravvive a un reinstall): si
cambia lo **stato dichiarato**. Nel `.env` della VPS:

```
VPS1777_FEATURES=backup,autoupdate    # il default: backup notturno + auto-update sicuro
# togli 'backup' per disattivarlo; l'installer/update applicheranno la scelta e la
# riprodurranno a ogni operazione. Il referto post-install ti confermerà backup=OFF.
```

> ⚠ **Serve la chiave `age`.** Il backup cifra con la sola chiave pubblica del recipient
> (la privata sta **fuori dalla VPS**, `v0.26.0`). Se `backup=ON` ma la chiave non è
> configurata, il referto te lo dice (nell'installer grafico
> `⚠ chiave age da configurare per i backup`, in `deploy.sh` uno stato `MANCANTE`, in
> `setup.sh` `Backup DICHIARATO ma NON ARMATO`). Vedi più sotto per generare la coppia e
> mettere la pubblica sul server.
>
> ⚠ **E dopo un format / una reinstallazione va RIMESSA** — il recipient vive sulla VPS
> (`tools/age-recipients.txt`) e il format lo porta via; la coppia sul PC sopravvive e
> resta quella giusta (i backup vecchi e nuovi si aprono con la stessa privata). Il punto
> in cui te ne accorgi è il **primo update**: `vps1777 update` pretende il backup, il
> backup pretende il recipient, e senza si ferma fail-safe («backup fallito — stack
> intatto, update annullato» — misurato al collaudo vergine, 27/08/2026). NON generare
> una coppia nuova sulla VPS: ricopia la pubblica del PC (`grep 'public key'` sul file
> della chiave: `~/.config/vps1777/age-key.txt` se l'ha generata l'installer,
> `~/.config/age/keys.txt` se l'hai generata tu come qui sotto).

> **Niente `docker.sock` (H13).** Il container di backup **non monta il Docker socket** e
> **non installa `docker-cli`**: i volumi dati gli sono montati **direttamente in sola
> lettura** (`/volumes/<nome>`) e `backup.sh` li archivia da lì. Montare il socket darebbe
> a un container di servizio il controllo root-equivalente dell'host.

## Restore

Un ripristino completo è **due restore, uno per livello** (l'ordine non conta: ognuno
tocca solo i propri volumi):

```bash
./tools/restore.sh backups/vps1777-2026-08-29-030000.tar.age                     # core
./tools/restore.sh backups/archivio/vps1777-archivio-2026-08-29-030000.tar.age   # archivio
```

> 🔑 **La chiave privata, `restore.sh` la cerca da sé**, in quest'ordine: la variabile
> `AGE_KEY` se la dai; `~/.config/vps1777/age-key.txt`, dove la generano `deploy.sh` e
> l'installer grafico; `~/.config/age/keys.txt`, il posto di `age-keygen` fatto a mano.
> `./tools/restore.sh --chiave` dice quale userebbe, senza toccare niente. Fino alla
> 0.62.2 cercava solo l'ultimo, e con la chiave degli installer il restore si fermava
> («chiave age non trovata», prima di toccare lo stack). Il restore gira sulla macchina
> che ha i volumi Docker, quindi la privata va portata lì per il tempo del restore — e
> poi tolta (`shred -u`). Uno snapshot pre-update in chiaro non chiede nessuna chiave.

Step:
1. `docker compose down --remove-orphans` — l'`--remove-orphans` serve: senza, il
   container dell'ingress non è nel modello (sta in un overlay) e **resta acceso**,
   servendo traffico sopra volumi che si stanno ripristinando. Si ferma anche il
   container `backup` (è in un overlay anche lui)
2. Decifra l'archivio con la tua chiave age e riconosce il formato dai byte
   (zstd / gzip / tar nudo — i backup precedenti al `0.43.13` sono tar nudo)
3. Ripristina volumi + secrets + **configurazione** (il core: sovrascrive anche `.env`,
   `compose*.yaml` e `ingress/` con quelli del backup) o i volumi dell'archivio
4. **Non riavvia lo stack**: stampa il comando da lanciare, con gli `-f` dell'ingress
   letti da `INGRESS_PROFILE` nel `.env` ripristinato e, dalla 0.62.3, quelli delle
   feature dichiarate in `VPS1777_FEATURES` (il backup notturno compreso: prima restava
   fuori, e il container `backup` restava spento fino al prossimo update).
   `./tools/restore.sh --comando-riavvio` lo stampa senza fare il restore. Col profilo e
   le feature di default:

   ```bash
   docker compose -f compose.yaml -f compose.ingress.tailscale.yaml -f compose.ops.backup.yaml \
     --profile ingress.tailscale --profile ops.backup up -d
   ```

Se l'archivio lo **rigeneri dalle fonti** invece di ripristinarlo (re-ingest dei bundle),
le `description` dei DB le ritrovi nel core in `descrizioni/<db>.txt` — si riapplicano con
`set_description` dal connector, o dal pannello.

Default: interattivo (chiede conferma). Flag:

- `--yes` — nessuna conferma (per script/automazioni)
- `--volumes-only vol1,vol2` — ripristina SOLO i volumi elencati (CSV, nomi corti o completi), saltando secrets/config
- come input accetta anche una **directory snapshot non cifrata** (`backups/pre-update/<dir>`), oltre al `.tar.age`
- `--chiave` — stampa la chiave privata che userebbe ed esce, senza toccare niente
- `--comando-riavvio` — stampa il comando per riavviare lo stack (ingress + feature) ed esce
- la variabile `AGE_KEY=<file>` indica la chiave privata (senza, `~/.config/vps1777/age-key.txt`, poi `~/.config/age/keys.txt`)

## Snapshot pre-update

`vps1777 update` crea in `backups/pre-update/` uno snapshot locale **non cifrato** dei volumi dati prima di ogni update — serve all'auto-rollback, che non può dipendere dalla age-key. Dentro ci sono `gateway-data` e `archive-data`; **`nlm-auth` è escluso di proposito**: contiene i cookie di sessione Google, e lo snapshot è in chiaro (il profilo NotebookLM si ricarica da `/admin/nlm`, e sta comunque nel backup age). Gli snapshot si potano a ogni update riuscito, a ogni auto-rollback e a ogni `vps1777 check` (il timer giornaliero): restano l'ultimo di n e n-1 (decisione owner del 29/08) più quello in uso come punto di ritorno. Vedi [UPDATE.md](UPDATE.md). Ripristino manuale:

```bash
./tools/restore.sh --yes --volumes-only gateway-data,archive-data backups/pre-update/<dir>
```

## Chiave age — dove sta cosa (importante)

Il backup si cifra con la chiave **pubblica** (il *recipient*); solo il **restore**
ha bisogno della chiave **privata**. Quindi:

- **La chiave PRIVATA vive sul TUO PC**, mai sulla VPS. Se installi con `deploy.sh` o con
  l'installer grafico, la coppia la genera lui sul PC, in
  `~/.config/vps1777/age-key.txt`, e manda alla VPS solo il recipient. A mano, generala
  lì:
  ```bash
  age-keygen -o ~/.config/age/keys.txt    # sul TUO computer, non sul server
  ```
- **Sulla VPS metti SOLO il recipient** (la riga `# public key:`, `age1…`) in
  `tools/age-recipients.txt`. Con quello la VPS cifra i backup senza mai vedere la
  privata:
  ```bash
  grep 'public key' ~/.config/age/keys.txt   # → age1…  da incollare in age-recipients.txt
  ```

> **Perché conta**: se la privata sta sulla VPS, sta sullo *stesso disco* dei
> backup — chi ruba o perde il disco ha (o perde) entrambi, e la cifratura non
> protegge da nulla. Tenendola sul PC, un dump del volume backup della VPS resta
> **indecifrabile** senza di te.

> **Copia offline**: la chiave privata è **irrecuperabile** se la perdi (e con
> essa tutti i backup). Tienine una copia offline sicura (password manager, chiave
> USB in cassetto).

**Dove metti i backup**: `tools/backup.sh` produce i `.tar.age` nella cartella
`backups/`. **Sei tu a scegliere dove portarli** (NAS, altro disco, cloud): vps1777 non
trasferisce nulla in automatico, ma il gesto è scritto — dal **tuo PC**:

```bash
bash tools/backup-pull.sh vps1777 /media/tu/HD/vps1777-backups
#   <host-ssh>  <cartella di destinazione>   (esce 2 se la cartella non c'è: HD non montato)
bash tools/backup-pull.sh vps1777 /media/tu/HD/vps1777-backups /srv/vps1777
#   terzo argomento facoltativo: il repo sulla VPS (default /home/vps1777/vps1777)
```

Tira i due livelli e i sidecar `.meta`, **senza** `pre-update/` (gli snapshot in chiaro
non lasciano la macchina) e **senza** `--delete`: la VPS pota per spazio, il tuo disco
tiene la storia. Un timer utente sul PC può lanciarlo ogni giorno: quando l'HD non è
montato esce 2 e lo dice, invece di copiare nel posto sbagliato.

> ⚠️ **Migrazione (installazioni esistenti)**: se hai una chiave privata in
> `~/.config/age/keys.txt` **sulla VPS** (le versioni fino alla 0.25.0 la
> generavano lì), **copiala sul tuo PC e poi rimuovila dalla VPS**:
> ```bash
> # dal tuo PC:
> scp OPERATOR@VPS:~/.config/age/keys.txt ~/.config/age/keys.txt   # salvala sul PC
> ssh OPERATOR@VPS 'shred -u ~/.config/age/keys.txt'               # toglila dal server
> ```
> Il recipient in `tools/age-recipients.txt` resta: i backup esistenti e futuri
> restano cifrabili, e ora decifrabili **solo** con la tua copia sul PC.

## Rotazione della chiave age (H37)

Ruotare la coppia age serve se sospetti che la **chiave privata** sia stata esposta,
o come igiene periodica. Regola d'oro: la privata **non deve mai toccare la VPS** —
si genera e si custodisce sul TUO PC; sulla VPS va solo il nuovo *recipient*.

```bash
# 1) sul TUO PC — genera la NUOVA coppia (non sovrascrivere subito la vecchia)
age-keygen -o ~/.config/age/keys-new.txt
grep 'public key' ~/.config/age/keys-new.txt        # → age1…  (il nuovo recipient)

# 2) sulla VPS — sostituisci il recipient in tools/age-recipients.txt col nuovo age1…
#    (una riga = un recipient; il commento '# created:'/altri sono ignorati)

# 3) verifica: il prossimo backup si cifra con la chiave nuova
./tools/backup.sh                                   # → un .tar.age nuovo
```

**Cosa succede ai backup VECCHI.** `age` cifra un archivio verso i *recipient*
elencati **al momento della cifratura**: i `.tar.age` già prodotti restano cifrati
con la **vecchia** chiave e si decifrano **solo con la vecchia privata**. Cambiare
il recipient **non** li ri-cifra. Quindi:

- **Conserva la vecchia privata** (offline) finché esistono backup cifrati con essa
  — cioè finché non sono usciti dalla rotazione o li hai cancellati/ri-cifrati tu. La
  rotazione non ha una durata fissa: 7 giornalieri + 4 settimanali sono circa un mese,
  ma l'ultimo backup di ciascuna delle ultime 3 versioni resta finché non escono tre
  versioni più nuove, e i 2 archivio restano fino ai due giri successivi. Prima di
  ritirarla, guarda cosa c'è ancora in `backups/` (e nelle copie sul tuo disco).
- Sul PC promuovi la nuova a chiave attiva quando sei pronto:
  ```bash
  mv ~/.config/age/keys.txt ~/.config/age/keys-old.txt   # tienila, non buttarla
  mv ~/.config/age/keys-new.txt ~/.config/age/keys.txt
  ```
- **Transizione morbida (opzionale)**: elenca **entrambi** i recipient (vecchio +
  nuovo) in `tools/age-recipients.txt` durante il periodo di overlap — così ogni
  nuovo backup è decifrabile con **una qualsiasi** delle due private. Rimuovi il
  vecchio recipient a fine transizione.
- **Ri-cifrare un backup vecchio sotto la chiave nuova** (se ne vuoi uno solo da
  custodire): `age -d -i keys-old.txt vecchio.tar.age | age -r age1NUOVO… -o vecchio.rekey.tar.age`.

> Gli **snapshot pre-update** (`backups/pre-update/`) **non** sono age-encrypted
> (sono snapshot locali in chiaro per l'auto-rollback): la rotazione della chiave
> age non li riguarda.

## Disaster recovery

Scenario: VPS morta, nuova macchina, vuoi ripristinare.

```bash
# Su nuova macchina
git clone https://github.com/neo1777/vps1777.git
cd vps1777
# La chiave privata dalla tua copia offline, dove restore.sh la cerca da sé
# (./tools/restore.sh --chiave per controllare)
mkdir -p ~/.config/vps1777 && cp /percorso/age-key.txt ~/.config/vps1777/age-key.txt
# backups/ non è nel repo (è ignorata da git): va creata, con la sottocartella dell'archivio
mkdir -p backups/archivio
# Copia l'ultimo backup di OGNI livello
scp tuo-backup-server:/percorso/vps1777-2026-08-29-030000.tar.age backups/
scp tuo-backup-server:/percorso/archivio/vps1777-archivio-2026-08-29-030000.tar.age backups/archivio/
# Restore, uno per livello (il core rimette anche .env, compose*.yaml, ingress/ e secrets/)
./tools/restore.sh backups/vps1777-2026-08-29-030000.tar.age
./tools/restore.sh backups/archivio/vps1777-archivio-2026-08-29-030000.tar.age
# restore.sh NON riavvia: lancia il comando che stampa (ingress + feature, vedi
# «Restore» sopra). Poi togli la chiave privata dalla macchina:
shred -u ~/.config/vps1777/age-key.txt
# Lo stack riparte uguale alla data dei backup (l'archivio: alla data del suo, ≤ 7 giorni
# prima; se hai i bundle sorgente, il re-ingest lo porta a oggi).
```
