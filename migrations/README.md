# migrations/ — migrazioni di dato tra versioni

Ogni update `vps1777 update` esegue, **in ordine**, le migrazioni non ancora
applicate prima di riavviare lo stack. Questa cartella viaggia nel runtime
bundle di ogni release ed è **cumulativa**: il bundle della versione target
contiene tutte le migrazioni della storia, così un salto multi-versione
(N → N+3) applica naturalmente tutto ciò che sta in mezzo.

## Layout

```
migrations/
  README.md                # questo contratto
  0001-<slug>/
    migration.json         # metadati (vedi sotto)
    run.py                 # lo script — eseguito DENTRO un container one-off
                           # del `service` dichiarato, sulla NUOVA immagine
```

`migration.json`:

```json
{
  "id": "0001-<slug>",
  "description": "cosa fa, una frase",
  "service": "archive-mcp",
  "volumes": ["archive-data"],
  "data_mutating": true,
  "reversible": "restore-only",
  "introduced_in": "vX.Y.Z"
}
```

- `service` — il servizio della cui immagine (nuova) viene creato il container
  one-off che esegue `run.py`. Ha già le librerie giuste e l'utente giusto.
- `volumes` — i soli volumi montati nel container one-off. Niente altro.
- `data_mutating` — `true` se tocca i dati nei volumi. **Dichiaralo onestamente**:
  pilota il restore-da-snapshot nell'auto-rollback (all-or-nothing sui 3 volumi
  dati, così registro e dati restano coerenti per costruzione).
- `reversible` — `true` | `false` | `"restore-only"`. `false`/`restore-only` è
  lecito ma va dichiarato: il rollback di quell'update passa dallo snapshot.

## Il contratto (regole ferree)

1. **Idempotente internamente.** Rieseguibile senza danno anche se il registro
   fosse perso: `CREATE TABLE IF NOT EXISTS`, `ALTER` guardati da introspezione,
   scritture condizionali. Il runner protegge dal replay, lo script non ci conta.
2. **Niente rete, niente secret.** Il container one-off gira senza rete e monta
   solo i volumi dichiarati, come l'utente del servizio (uid 1000).
3. **Immutabile una volta pubblicata.** Un `run.py`/`migration.json` con id già
   su `main` non si modifica mai (la CI lo blocca: job "Migrations immutability").
   Serve un fix? Nuova migrazione con id successivo.
4. **Ordine lessicografico** degli id `NNNN-slug`. Il runner applica in ordine
   stretto, registra dopo ogni successo, e al primo fallimento abortisce
   (→ auto-rollback dell'update).
5. **Mai downgrade-script.** Il runner non "esegue al contrario": tornare
   indietro = restore da snapshot/backup, per definizione (vedi docs/UPDATE.md).

## Registro

`gateway-data:/var/lib/gateway/state/migrations.json` — nel volume perché:
esiste sempre, è nel set di backup, e il restore all-or-nothing dello snapshot
lo mantiene automaticamente coerente coi dati. Entry:
`{id, version, applied_at, checksum}` dove `checksum` è lo sha256 di `run.py`
al momento dell'applicazione.

Il runner è `vps1777 migrate` (vedi `tools/vps1777.py`):
- `vps1777 migrate --pending` — elenca le migrazioni non applicate
- `vps1777 migrate --run` — le applica (normalmente lo fa `update` da solo)
