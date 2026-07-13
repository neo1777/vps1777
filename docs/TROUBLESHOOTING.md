# Troubleshooting — vps1777

Casi reali, diagnosi, fix.

## `docker compose up` fallisce con "permission denied" sui secret

Causa: i file `secrets/*.txt` hanno owner sbagliato.

Fix:
```bash
chmod 600 secrets/*.txt
chown $(id -u):$(id -g) secrets/*.txt
```

## Gateway non risponde su `/health`

Diagnosi:
```bash
docker compose ps gateway
docker compose logs gateway --tail 50
```

Casi comuni:
- `bcrypt` hash malformato in `admin_password_bcrypt.txt` → rigenera con `./tools/rotate-secret.sh admin_password`
- `gateway_secret.txt` vuoto → `./setup.sh` lo rigenera
- Porta 8080 occupata sul host (dev) → `lsof -iTCP:8080` e killa il processo

## Login admin: password corretta, nessun errore, ma resta sulla pagina

Causa: il cookie di sessione admin è `Secure` e il browser **non lo salva su HTTP**
(lo accetta solo su HTTPS). Su un accesso via `http://<IP>:8080` il login validava
ma il cookie spariva → redirect di nuovo a `/admin/login`.

Fix: il gateway ora imposta `Secure` **solo se `PUBLIC_BASE` è https** → su HTTP
(setup locale) il login funziona, su HTTPS (produzione) il cookie resta sicuro.
Se ti ricapita, verifica che `PUBLIC_BASE` nel `.env` combaci con lo schema con cui
accedi davvero (http vs https) e riavvia il gateway.

## Bot Telegram non risponde a `/start`

Diagnosi:
```bash
docker compose logs nb1777-bot --tail 30
```

Casi:
- `TELEGRAM_BOT_TOKEN` vuoto → riempi `secrets/telegram_bot_token.txt` + `docker compose restart nb1777-bot`
- `TELEGRAM_OWNER_ID` sbagliato → controlla `.env`, deve essere il TUO numero (non `0`)
- TOKEN revocato su BotFather → genera uno nuovo, aggiorna `secrets/telegram_bot_token.txt`

## `nlm: command not found` (sul tuo PC)

`nlm` è il pacchetto PyPI **`notebooklm-mcp-cli`**, non un pacchetto apt/snap.
Installalo con [uv](https://astral.sh):
```bash
uv tool install notebooklm-mcp-cli --python 3.12
nlm login
```
Se dopo l'install resta "not found": `uv` mette i binari in `~/.local/bin` →
`uv tool update-shell` e riapri il terminale (o aggiungi `~/.local/bin` al PATH).

## Bot risponde "Auth NotebookLM mancante"

È atteso al primo avvio. Carica il **profilo nlm** (tar.gz) da `<PUBLIC_BASE>/admin/nlm` (vedi sotto).

## `/admin/nlm` — "il tar non contiene profiles/default/cookies.json"

Causa: hai caricato l'archivio sbagliato. La CLI `nlm` 0.7.x salva l'auth come
**cartella** `~/.notebooklm-mcp-cli/profiles/default/` (con `cookies.json` +
`metadata.json`), non come `auth.json`. Crea il tar.gz dalla dir giusta:
```bash
cd ~/.notebooklm-mcp-cli
tar czf nlm-profile.tgz profiles/default     # NON da dentro profiles/default
```
Carica `nlm-profile.tgz` su `<PUBLIC_BASE>/admin/nlm`.

Verifica sul tuo PC che il profilo esista prima di taggarlo:
```bash
ls ~/.notebooklm-mcp-cli/profiles/default/   # → cookies.json  metadata.json
```

## Tailscale Funnel non si attiva (URL resta HTTP su :8080)

È il caso più comune al primo deploy. Il nodo entra nel tailnet ma il **Funnel
HTTPS non parte** → l'installer lascia il fallback `http://<IP>:8080`.

Causa quasi sempre: mancano i **prerequisiti a livello di account** (la auth-key
NON li porta). Servono tutti e tre:

1. **MagicDNS** abilitato — [admin → DNS](https://login.tailscale.com/admin/dns)
2. **HTTPS Certificates** abilitato — stessa pagina DNS
3. Attributo **`funnel` nell'ACL** per `tag:vps1777` (l'installer lo scrive da sé se gli dai un **OAuth client** con scope `policy_file`; vedi [INGRESS.md](INGRESS.md))

> **Nota architettura**: Tailscale gira **sull'host** (servizio systemd), non in un
> container. (Storicamente era un sidecar Docker, abbandonato per i bug di
> containerboot e del netns condiviso.) Quindi i comandi qui sotto sono `tailscale ...`
> diretti sull'host, non `docker exec`.

Diagnosi (l'installer fallisce **subito**, allo STEP 3, se la provisioning OAuth non va):

- **`l'OAuth client NON è autorizzato al tag tag:vps1777`** / `requested tags [tag:vps1777] are invalid or not permitted` → l'OAuth client non ha quel tag assegnato. **FIX**: ricrea l'OAuth client e nello scope `auth_keys` **seleziona `tag:vps1777`** nei Tags (vedi [INGRESS.md](INGRESS.md)). È l'errore più comune.
- `token fallito` → Client ID/Secret errati.
- `ACL non aggiornata … policy_file` → all'OAuth client manca lo scope `policy_file` (write).

Se invece il nodo entra ma il Funnel non parte, sulla VPS (host):
```bash
tailscale funnel status     # cosa è pubblicato
tailscale serve status      # mapping serve → 127.0.0.1:8080
tailscale status            # login / DNSName del nodo
sudo journalctl -u tailscaled --no-pager | tail -40   # errori cert/funnel
```
Se serve, riattiva a mano: `tailscale serve --bg --https=443 http://127.0.0.1:8080 && tailscale funnel --bg 443`.
- `Funnel not available; "funnel" node attribute not set` → manca il nodeAttr nell'ACL.
- errori su `cert`/`HTTPS` → manca il toggle **HTTPS Certificates** (admin → DNS).
- `Logged out` + `nessuna TS_AUTHKEY` nei log → la key non è arrivata in `.env` (provisioning fallita allo STEP 3).

## Archive MCP non trova niente (`search` ritorna vuoto)

Causa: i DB sono vuoti (degraded mode).

Soluzione: popola i dati:
```bash
docker compose exec archive-mcp ls /var/lib/archive/data/
# Devono esistere claude-web/, claude-cli/, claude-cli-dash/ con file di export
```

Vedi [docs/ARCHITECTURE.md](ARCHITECTURE.md) §archive-mcp per i formati attesi.

## Connector claude.ai non si autentica (Tailscale)

Causa: `PUBLIC_BASE` è vuoto nel `.env` perché l'URL `*.ts.net` si conosce solo dopo il login Tailscale. L'issuer OAuth punta a loopback e claude.ai non completa il flow.

Fix (dopo che Tailscale è loggato e hai l'URL):
```bash
ssh <user>@<vps>
sudo -u vps1777 -i
cd vps1777
# Sostituisci con il tuo URL .ts.net reale
sed -i 's|^PUBLIC_BASE=.*|PUBLIC_BASE=https://vps1777.<tuo-tailnet>.ts.net|' .env
docker compose -f compose.yaml -f compose.ingress.tailscale.yaml --profile ingress.tailscale up -d
```

## Tailscale: il nodo non è autenticato

Causa: `tailscale up` non è stato eseguito o la key era vuota/non valida.

Fix (sull'host):
```bash
ssh <user>@<vps>
sudo tailscale up --authkey=tskey-auth-... --hostname=vps1777
# Genera la key su https://login.tailscale.com/admin/machines/new-linux
# Poi: sudo tailscale serve --bg --https=443 http://127.0.0.1:8080 && sudo tailscale funnel --bg 443
```

## Update: "update già in corso"

Causa: c'è un lock (`var/update.lock`) — un altro update sta girando, oppure è
il residuo di un crash.

Diagnosi:
```bash
vps1777 status                                      # mostra update_in_progress
journalctl -u vps1777-update --no-pager | tail -30  # log dell'ultimo run
```
Se nessun processo è attivo, riprova: il lock è per-processo. Dettagli in
[UPDATE.md](UPDATE.md).

## Update: digest mismatch al pull

Causa: i digest delle immagini pullate non combaciano con `images.lock` del
bundle di release (release corrotta o manomissione registry).

L'update abortisce **prima** di toccare lo stack — non è un guasto, è la
verifica supply-chain che fa il suo lavoro. Controlla la release su GitHub e
riprova. Vedi [UPDATE.md](UPDATE.md).

## Update: verifica firma cosign fallita ("firma richiesta ma cosign assente")

Da **v0.23.0** la verifica **cosign** della firma di release è **obbligatoria
di default** (fail-closed): le release sono sempre firmate e la CLI prova a
installare cosign da sé se manca. L'update abortisce **prima** di toccare lo
stack se la firma non verifica o se cosign è assente e non installabile.

Cause:
- cosign mancante e non installabile (rete/permessi) → `verifica firma richiesta ma cosign è assente e non installabile`
- firma `.sig`/`.pem` assente o non valida nel bundle → `cosign verify-blob fallita`

Fix: risolvi la causa (installa cosign da [github.com/sigstore/cosign](https://github.com/sigstore/cosign), o verifica la release su GitHub). Via d'emergenza **consapevole** — accetti una release non verificata, usala solo se sai cosa fai:
```bash
vps1777 update --no-require-cosign          # una tantum
# oppure, persistente, nel .env:  VPS1777_REQUIRE_COSIGN=0
```
Dettagli in [UPDATE.md](UPDATE.md).

## Update: rollback non healthy (exit 2)

Il caso peggiore: nemmeno il rollback torna in salute. La CLI si ferma senza
thrashing e ti avvisa su Telegram. Hai tre paracadute:

1. snapshot locale in `backups/pre-update/` (non cifrato)
2. backup age in `backups/`
3. [BACKUP-RESTORE.md](BACKUP-RESTORE.md) per il disaster recovery

## Card admin Update: "check stantio"

Causa: il timer giornaliero (`vps1777-check-update.timer`) non gira o GitHub
era irraggiungibile all'ultimo check (nessun rumore by design: solo il badge).

Diagnosi:
```bash
systemctl list-timers vps1777-check-update.timer
journalctl -u vps1777-check-update --no-pager | tail -20
vps1777 check     # forza il check subito
```

## Mini App: il bottone apre un URL vecchio ("Name or service not known")

Il client Telegram può avere in cache un **menu button legacy** o una **Main
Mini App** configurata a mano in BotFather con un host che non esiste più.
Il menu button corretto lo imposta il bot a ogni avvio (`set_chat_menu_button`
→ "Pannello" → `PUBLIC_BASE/app`).

1. Riavvia il client Telegram (o prova dal telefono): il bottone diventa
   "Pannello".
2. Se persiste: @BotFather → `/mybots` → il tuo bot → **Bot Settings →
   Configure Mini App** → correggi o **disabilita** la Main App legacy.
3. Verifica cosa c'è lato server:
   ```bash
   TOK=$(sudo cat /home/vps1777/vps1777/secrets/telegram_bot_token.txt)
   curl -s "https://api.telegram.org/bot$TOK/getChatMenuButton"
   ```

## Mini App: "Questo account Telegram non è l'owner del gateway"

`/app/auth` limita l'accesso a `TELEGRAM_OWNER_ID` (in `.env`) — verificato
**server-side**, non basta che il bot ti risponda. Controlla che l'id sia il
tuo (`@userinfobot`) e che il gateway lo veda:
```bash
docker exec vps1777-gateway-1 printenv TELEGRAM_OWNER_ID
```
Se è vuoto, aggiorna `.env` e ricrea il gateway (`docker compose up -d gateway`).

## Mini App: risponde `503 owner_not_configured`

Causa: manca `TELEGRAM_OWNER_ID` nel `.env`. Da **v0.22.0** gli endpoint
owner-only sono **fail-closed**: finché l'owner non è impostato la Mini App
nega TUTTI (503) e il bot owner-only non risponde a nessuno. Lasciarlo vuoto
**non** è senza conseguenze.

Fix:
```bash
docker exec vps1777-gateway-1 printenv TELEGRAM_OWNER_ID   # vuoto = non configurato
# prendi il tuo id da @userinfobot, mettilo in .env, poi ricrea il gateway:
docker compose up -d gateway
```

## `429` / `rate_limited` su connector o Mini App

Causa: da **v0.25.0** gli endpoint di auth pubblici hanno un **rate-limit
per-IP** (difesa anti-raffica). Le soglie:
- `/register` (DCR del connector): 10 ogni 5 min
- `/token` (OAuth del connector): 60 al minuto
- `/app/auth` (Mini App): 20 ogni 5 min

Non è un guasto: hai superato la soglia (retry a raffica, script, o più client
dietro lo stesso IP). Il contatore è **in-memory** e si azzera al **restart del
gateway**. Aspetta la finestra o riavvia:
```bash
docker compose restart gateway
```

## Nei log/audit l'IP client è sempre lo stesso (es. l'IP della bridge Docker)

Causa: da **v0.28.0** il gateway si fida degli header `X-Forwarded-*` solo dai
peer in `GATEWAY_FORWARDED_ALLOW_IPS` (default
`127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16` — loopback + bridge Docker
private). Dietro un ingress **custom** il cui IP non rientra in quei range l'XFF
viene ignorato, e in audit/rate-limit compare sempre l'IP del proxy invece di
quello reale del client.

Fix: aggiungi l'IP/subnet del tuo ingress a `GATEWAY_FORWARDED_ALLOW_IPS` nel
`.env` e ricrea il gateway (`docker compose up -d gateway`). **NON** impostarlo a
`*`: riaprirebbe lo spoofing degli header (rate-limit/lockout/audit
falsificabili da un client pubblico).

## Reset completo (perdi dati)

```bash
docker compose down -v       # -v cancella volumi
rm -rf secrets/ .env backups/
./setup.sh                   # ricominci da capo
```
