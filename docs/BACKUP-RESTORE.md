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

## Chiave age

Crea/copia la tua chiave in `~/.config/age/keys.txt` (mode 600).

```bash
age-keygen -o ~/.config/age/keys.txt    # se nuova
```

Annota il recipient (la riga `# public key:`) — lo metti in `tools/age-recipients.txt` per cifrare i backup.

> **Importante**: tieni una **copia offline** della chiave age. Senza chiave, i backup sono inutili.

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
