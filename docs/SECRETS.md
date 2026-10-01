# Secrets — vps1777

Tutti i secret stanno in `secrets/*.txt` (gitignored) e vengono montati nei container in `/run/secrets/<name>`, in sola lettura. Con Docker Compose fuori da Swarm un secret `file:` è un **bind mount del file dell'host**: dentro il container ha gli stessi permessi e lo stesso proprietario che ha fuori (gli installer lo lasciano `600`, dell'utente che l'ha generato — per questo quell'utente deve essere l'UID 1000 dei container, vedi [TROUBLESHOOTING.md](TROUBLESHOOTING.md)).

## Inventario

| Secret | File | Cosa contiene | Chi lo legge |
|---|---|---|---|
| `gateway_secret` | `secrets/gateway_secret.txt` | namespace nelle URL `/<SECRET>/<service>/mcp` (24-32 char) **e** segreto del canale interno verso nb1777-mcp (v0.30.0) | gateway, nb1777-mcp, nb1777-bot |
| `oauth_signing_secret` | `secrets/oauth_signing_secret.txt` | firma JWT HS256 (≥32 byte) | gateway |
| `admin_password_bcrypt` | `secrets/admin_password_bcrypt.txt` | hash bcrypt della password admin (rounds=12) | gateway |
| `archive_desc_secret` | `secrets/archive_desc_secret.txt` | segreto del canale interno con cui archive-mcp inoltra al gateway le `set_description` (separato da `gateway_secret` di proposito) | gateway, archive-mcp |
| `telegram_bot_token` | `secrets/telegram_bot_token.txt` | TOKEN bot da BotFather | nb1777-bot (e la CLI sull'host, per le notifiche) |
| `telegram_webapp_secret` | `secrets/telegram_webapp_secret.txt` | chiave **derivata** dal token (HMAC_SHA256 con chiave «WebAppData», 64 hex) con cui si verifica l'`initData` della Mini App — non risale al token. La scrive l'installer; la riallineano al token `rotate-secret.sh`, `vps1777 update` e `vps1777 rollback` | gateway |
| `cloudflared_token` | `secrets/cloudflared_token.txt` | (opz) CF Tunnel token | cloudflared sidecar |

> Il gateway **non** monta il token del bot: gli basta la chiave derivata. Chi buca il
> gateway può al massimo forgiare un `initData` per la Mini App di quel gateway, non
> parlare come il bot. La chiave la scrivono gli installer; `vps1777 update` la ricalcola
> dal token a ogni avvio dello stack che fa (vedi la rotazione del token, sotto).

> **Tailscale**: `TS_AUTHKEY` **non** è un Docker secret — passa da `.env` solo il
> tempo del provisioning. Tailscale gira **sull'host** (non più in un sidecar), e la
> authkey è **monouso**: dopo un `tailscale up` riuscito l'installer la **azzera da
> `.env`** (che è a `chmod 600`) — così non resta sul disco una credenziale già
> spesa (H15). Con l'installer è generata da un OAuth client (il cui *secret* resta
> sul tuo PC). Vedi [INGRESS.md](INGRESS.md).

## Generazione iniziale

`setup.sh` li genera tutti la prima volta. Per rigenerarne uno singolo: cancellalo (`rm secrets/<file>`) e rilancia `./setup.sh`.

## Rotation senza downtime

### Rota `gateway_secret`

```bash
NEW=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')
echo -n "$NEW" > secrets/gateway_secret.txt
# Riavvia TUTTI i consumatori, non solo il gateway (vedi sotto)
docker compose restart gateway nb1777-mcp nb1777-bot   # < 2s downtime
# I tuoi URL connector cambiano: rigenerali da claude.ai
```

Più semplice: `./tools/rotate-secret.sh gateway_secret` fa tutto questo. Davanti a un
terminale stampa il segreto nuovo e le due URL dei connettori; se l'output va altrove (un
agente, una pipe, un log) li scrive in `~/.config/vps1777/gateway-secret-<data>.txt` (600) e
stampa solo il percorso (H77): copiali su claude.ai, poi cancella il file. `deploy.sh` fa lo
stesso a fine installazione (`RESULT_SECRET_FILE=` invece di `RESULT_SECRET=`).

> **Perché tre servizi e non solo il gateway.** Dalla v0.30.0 il `gateway_secret`
> non è più solo il namespace dell'URL: è **anche** il segreto con cui gateway e
> bot si autenticano verso gli endpoint interni di `nb1777-mcp` (il profilo
> NotebookLM — vedi [SECURITY.md](../SECURITY.md)). Riavviare il solo gateway lo
> lascerebbe col segreto nuovo mentre gli altri due hanno ancora il vecchio: il
> canale interno risponderebbe **403**, `/admin/nlm` direbbe "nb1777-mcp non
> raggiungibile" e il bot crederebbe l'auth NotebookLM mancante.
> `tools/rotate-secret.sh` lo fa già correttamente.

### Rota `oauth_signing_secret`

```bash
NEW=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')
echo -n "$NEW" > secrets/oauth_signing_secret.txt
docker compose restart gateway
# ATTENZIONE: invalida TUTTI i token attivi (access, refresh, admin, miniapp).
# I client OAuth (claude.ai) richiedono nuovo login via refresh_token automatico,
# se il refresh era ancora valido. Altrimenti devi rifare il connector.
```

### Rota `telegram_bot_token` (e la chiave derivata)

```bash
./tools/rotate-secret.sh telegram_bot_token   # revoca su @BotFather, incolla il nuovo:
                                              # scrive il token, RIDERIVA la chiave, riavvia bot e gateway
```

Dalla 0.62.3 `rotate-secret.sh` rideriva da sé la chiave della Mini App; prima scriveva
solo il token, e il secondo passo andava fatto a mano.

> ⚠️ **Perché conta.** La chiave derivata è una funzione del token: col token nuovo e la
> chiave vecchia il bot risponde e la Mini App **rifiuta tutti**, senza un errore che
> nomini la chiave. Si ricalcola da sola con `rotate-secret.sh`, con un `vps1777 update`
> che installa davvero una versione, con `vps1777 rollback` e nell'auto-rollback — non
> con un `docker compose restart`. Se hai riscritto il token a mano nel file, rilancia
> `rotate-secret.sh telegram_bot_token` (o vedi [TROUBLESHOOTING.md](TROUBLESHOOTING.md)).

### Rota `admin_password_bcrypt`

```bash
ADMIN_PWD_RAW="<nuova_password>" python3 -c '
import os, bcrypt
print(bcrypt.hashpw(os.environ["ADMIN_PWD_RAW"].encode(), bcrypt.gensalt(12)).decode())
' > secrets/admin_password_bcrypt.txt
docker compose restart gateway
```

Oppure `./tools/rotate-secret.sh admin_password`: con Invio vuoto la genera lui (24
caratteri) e la mostra solo se l'output va a un terminale; altrimenti la scrive in
`~/.config/vps1777/admin-password-<data>.txt` (600) e stampa il percorso (H75: una
password stampata davanti a un agente finisce nel suo transcript, e da lì nell'archivio).

Il pannello `/admin/secrets` documenta la procedura ma non la esegue: il
gateway non ha privilegi per riscrivere i secret host né per riavviarsi
(stesso design del canale update, vedi [ARCHITECTURE.md](ARCHITECTURE.md)) —
la rotation si fa da CLI come sopra. Un `docker compose restart` non tocca le
immagini: nessuna build, nessun pull.

## Scadenze e monitoraggio

Un check host — `vps1777 secrets-status` (timer systemd **giornaliero**
`vps1777-secrets-check.timer`, `OnCalendar=daily`: era settimanale, ma la soglia più
stretta qui dentro è di un giorno) — calcola l'**età** di ogni secret (dall'mtime del
file, riscritto a ogni rotazione) e la confronta con una soglia:

| Secret | Fascia | Soglia consigliata | Rotazione |
|---|---|---|---|
| `telegram_bot_token` | **massima** (radice di fiducia Mini App) | **90 giorni** | manuale (revoca e rigenera su @BotFather) |
| `oauth_signing_secret` | alta | 90 giorni | manuale (invalida i token) |
| `admin_password_bcrypt` | alta | 90 giorni | manuale |
| `telegram_webapp_secret` | segue il token | 90 giorni | non si ruota a parte: si ricalcola dal token (sopra) |
| `gateway_secret` | media | 180 giorni | manuale (cambia le URL MCP) |
| `archive_desc_secret` | media | 180 giorni | manuale: rigenera il file e ricrea il gateway (e archive-mcp) — `rotate-secret.sh` non lo copre |
| `cloudflared_token` | bassa | 365 giorni | manuale (se usi l'ingress Cloudflare) |
| cookie NotebookLM | — | 14 giorni | ricarica da `/admin/nlm` — scadono da soli |
| via d'emergenza cosign aperta | — | **1 giorno** | togli `VPS1777_REQUIRE_COSIGN=0` dal `.env` (compare solo mentre è aperta) |

> **Perché `telegram_bot_token` è fascia massima (H29).** Non è un segreto
> "ordinario": è la **radice di fiducia della Mini App**. L'autenticazione della
> Mini App valida l'`initData` firmandolo con il token del bot — quindi **chi ha il
> token può forgiare un `initData` valido per QUALUNQUE user id**, compreso quello
> dell'owner, e passare per chiunque. Vale quanto una chiave di firma di sessione,
> non quanto un'API key qualsiasi: per questo la soglia consigliata scende a
> **90 giorni** (allineata a `oauth_signing_secret`), non 365. La revoca è
> immediata da @BotFather (rigenera il token → il vecchio smette di firmare).
> La soglia è **90 anche nel codice** (`tools/vps1777.py`, `_SECRET_POLICY`) dalla
> v0.33.0 (H29): il promemoria automatico e questa pagina dicono la stessa cosa.

Se un secret supera la soglia, il check **notifica il owner su Telegram** (`--notify`)
e lo segna nella pagina admin **`/admin/secrets`**, che mostra età, ultima rotazione
e stato di ogni secret + le istruzioni di rotazione. Scrive `onboarding/secrets_status.json`
(letto dal gateway). Manuale: `vps1777 secrets-status` in qualunque momento.

Cosa notifica e cosa no:

- **scaduti** → una notifica con l'elenco (niente scaduto, niente messaggio: la cadenza
  giornaliera non aggiunge rumore);
- **secret attesi e non trovati** in `secrets/` → solo nel log e nel campo `mancanti` del
  JSON, **nessuna notifica**. L'elenco è quello della tabella; `cloudflared_token` è
  atteso solo col profilo Cloudflare (fino alla 0.62.2 compariva sempre fra i mancanti);
- **nessun secret trovato** → esce **2** (la unit risulta fallita) e, con `--notify`,
  lo dice su Telegram: non è «tutto a posto», è «non ho potuto guardare» (percorso o
  permessi sbagliati).

> Perché quasi tutto è **manuale**: ruotare `oauth_signing_secret`/`gateway_secret`
> in automatico romperebbe i connettori attivi (token/URL). L'auto-rotazione
> trasparente richiede un *key-ring con grazia* (roadmap). Il **refresh token
> OAuth**, invece, **ruota già da solo** a ogni uso, con revoca durevole e
> rilevamento del riuso (difesa dal furto token) — il ramo vive in
> `services/gateway/app/oauth.py`, eventi `oauth_refresh_rotated` e
> `oauth_refresh_reuse` nell'audit.

## Backup

Vedi [BACKUP-RESTORE.md](BACKUP-RESTORE.md). I secret vanno backuppati age-encrypted
insieme ai volumi. Dalla v0.26.0 il backup cifra con la sola chiave **pubblica**
(recipient in `tools/age-recipients.txt`); la chiave **privata** vive sul PC
dell'owner, **fuori dalla VPS**, e serve solo al restore — `backup.sh` non genera
più la coppia sulla VPS. Per **ruotare** la coppia age (e cosa ne è dei backup
vecchi) vedi [BACKUP-RESTORE.md](BACKUP-RESTORE.md#rotazione-della-chiave-age-h37).

## Threat model

- `secrets/`, `backups/`, `onboarding/` a mode 700 + file 600 (impostato dagli installer, H38)
- Container vede solo i propri `/run/secrets/<name>`, montati in sola lettura con i
  permessi e il proprietario del file sull'host (`600`, UID 1000)
- **Log redatti** (v0.24.0): un filtro di logging (`app/logredact.py`) sostituisce
  ogni secret con `***` in ogni riga *prima* che venga scritta. In particolare il
  `gateway_secret` vive nel PATH del proxy MCP (`/<SECRET>/<service>/mcp`) e
  finirebbe nella request-line dell'access-log di uvicorn: ora compare come
  `/***/<service>/mcp` (redatto anche a valle, in Caddy/Cloudflare). È una difesa
  a valle, non sostituisce la rotazione: smette solo di produrre nuovi leak.
- **Segreti fuori dall'argv** (v0.29.0): `deploy.sh` passa i segreti via STDIN,
  non nell'argv → non compaiono in `ps`/`/proc/<pid>/cmdline` sull'host remoto.
- L'audit log NON contiene mai i valori, solo il nome del secret rotato — lo
  impone l'allowlist `_CHIAVI_NOTE` di `services/gateway/app/audit.py`: una
  chiave non dichiarata non entra nel log, qualunque cosa contenga
