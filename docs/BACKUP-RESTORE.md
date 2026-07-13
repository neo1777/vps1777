# Backup & Restore — vps1777

Strategia: backup age-encrypted dei volumi + secrets, una directory locale `backups/<timestamp>/`.

## Backup manuale

```bash
./tools/backup.sh
# → backups/vps1777-2026-06-23-080000.tar.age
```

Cosa includi: `gateway-data`, `archive-data`, `nlm-auth`, `secrets/*`, `.env`, `compose.*.yaml`.

Cosa NON includi: log container (sono in `/var/lib/docker/containers/*/`, gestiti dal driver json-file con rotation).

Il `MANIFEST.txt` dentro l'archivio registra anche la versione deployata (`VPS1777_TAG` dal `.env`) e il `VERSION` del bundle.

## Backup automatico (cron)

Aggiungi profilo `ops.backup`:

```bash
docker compose --profile ops.backup up -d
```

Container `backup` esegue ogni notte (cron 03:00). Rotation: mantiene **7 backup giornalieri + 4 settimanali** (uno per settimana).

> **Niente `docker.sock` (H13).** Il container di backup **non monta il Docker
> socket** e **non installa `docker-cli`**: i volumi dati gli sono montati
> **direttamente in sola lettura** (`/volumes/<nome>`) e `backup.sh` li archivia da
> lì (variabile `BACKUP_VOLUMES_DIR`) — così un container di servizio non ha mai il
> controllo root-equivalente dell'host. Lo stesso `backup.sh` resta *dual-context*:
> lanciato sull'host dumpa via `docker run` come prima, dentro il container usa i
> mount diretti. Col profilo `ingress.caddy` decommenta `caddy-data`/`caddy-config`
> nel compose per includerli.

## Restore

```bash
./tools/restore.sh backups/vps1777-2026-06-23-080000.tar.age
```

Step:
1. `docker compose down`
2. Decifra archivio con la tua chiave age
3. Ripristina volumi + secrets
4. `docker compose up -d`

Default: interattivo (chiede conferma). Flag:

- `--yes` — nessuna conferma (per script/automazioni)
- `--volumes-only vol1,vol2` — ripristina SOLO i volumi elencati (CSV, nomi corti o completi), saltando secrets/config
- come input accetta anche una **directory snapshot non cifrata** (`backups/pre-update/<dir>`), oltre al `.tar.age`

## Snapshot pre-update

`vps1777 update` crea in `backups/pre-update/` uno snapshot locale **non cifrato** dei volumi dati prima di ogni update — serve all'auto-rollback, che non può dipendere dalla age-key — e lo pota al successivo update riuscito (tenuto: l'ultimo). Vedi [UPDATE.md](UPDATE.md). Ripristino manuale:

```bash
./tools/restore.sh --yes --volumes-only gateway-data,archive-data,nlm-auth backups/pre-update/<dir>
```

## Chiave age — dove sta cosa (importante)

Il backup si cifra con la chiave **pubblica** (il *recipient*); solo il **restore**
ha bisogno della chiave **privata**. Quindi:

- **La chiave PRIVATA vive sul TUO PC**, mai sulla VPS. Genera la coppia lì:
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
`backups/`. **Sei tu a scegliere dove portarli** (NAS, altro disco, cloud): copia
quella cartella dove preferisci — vps1777 non trasferisce nulla in automatico.

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

## Disaster recovery

Scenario: VPS morta, nuova macchina, vuoi ripristinare.

```bash
# Su nuova macchina
git clone https://github.com/<owner>/vps1777.git
cd vps1777
# Copia ~/.config/age/keys.txt dalla tua copia offline
mkdir -p ~/.config/age && cp /percorso/keys.txt ~/.config/age/
# Copia l'ultimo backup
scp tuo-backup-server:/percorso/vps1777-*.tar.age backups/
# Restore
./tools/restore.sh backups/vps1777-*.tar.age
# Lo stack riparte uguale alla data del backup.
```
