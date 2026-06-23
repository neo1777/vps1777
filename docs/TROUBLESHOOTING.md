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

## Bot Telegram non risponde a `/start`

Diagnosi:
```bash
docker compose logs nb1777-bot --tail 30
```

Casi:
- `TELEGRAM_BOT_TOKEN` vuoto → riempi `secrets/telegram_bot_token.txt` + `docker compose restart nb1777-bot`
- `TELEGRAM_OWNER_ID` sbagliato → controlla `.env`, deve essere il TUO numero (non `0`)
- TOKEN revocato su BotFather → genera uno nuovo, aggiorna `secrets/telegram_bot_token.txt`

## Bot risponde "Auth NotebookLM mancante"

È atteso al primo avvio. Carica `auth.json` da `<PUBLIC_BASE>/admin/nlm`.

## `/admin/nlm` upload — "non è JSON valido"

Causa: hai caricato il file sbagliato.

`auth.json` corretto è quello che `nlm login` crea in `~/.notebooklm-mcp-cli/auth.json`. Deve avere chiave `profiles.default`.

Verifica sul tuo PC:
```bash
python3 -c "import json; d = json.load(open('~/.notebooklm-mcp-cli/auth.json')); print(list(d.keys()))"
# → ['profiles']
```

## Tailscale Funnel non si attiva (URL resta HTTP su :8080)

È il caso più comune al primo deploy. Il nodo entra nel tailnet ma il **Funnel
HTTPS non parte** → l'installer lascia il fallback `http://<IP>:8080`.

Causa quasi sempre: mancano i **prerequisiti a livello di account** (la auth-key
NON li porta). Servono tutti e tre:

1. **MagicDNS** abilitato — [admin → DNS](https://login.tailscale.com/admin/dns)
2. **HTTPS Certificates** abilitato — stessa pagina DNS
3. Attributo **`funnel` nell'ACL** per `tag:vps1777` (l'installer lo scrive da sé se gli dai un **OAuth client** con scope `policy_file`; vedi [INGRESS.md](INGRESS.md))

Diagnosi sulla VPS:
```bash
docker exec vps1777-tailscale tailscale funnel status     # cosa è attivo
docker logs vps1777-tailscale --tail 40                   # errore esatto
```
- `Funnel not available; "funnel" node attribute not set` → manca il nodeAttr (punto 3). Con OAuth client: verifica lo scope `policy_file` (write). A mano: aggiungi `{"target":["tag:vps1777"],"attr":["funnel"]}` ai `nodeAttrs` dell'ACL.
- errori su `cert`/`HTTPS` → manca il toggle HTTPS Certificates (punto 2).
- `tailscale status` non mostra il device → key non valida/consumata o login fallito.

> L'installer mostra già questa diagnosi in chiaro nella console di deploy:
> se vedi l'avviso, segui il link che indica.

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

## Tailscale: container parte ma non si logga

Causa: `TS_AUTHKEY` vuoto al deploy. Il sidecar gira ma il nodo non è autenticato.

Fix:
```bash
ssh <user>@<vps>
sudo docker exec -it vps1777-tailscale tailscale up --authkey=tskey-auth-...
# Genera la key su https://login.tailscale.com/admin/settings/keys
```

## Reset completo (perdi dati)

```bash
docker compose down -v       # -v cancella volumi
rm -rf secrets/ .env backups/
./setup.sh                   # ricominci da capo
```
