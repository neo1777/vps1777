# Installazione — vps1777

> **La via più semplice è l'installer grafico** (cross-OS, zero comandi): doppio-click
> su `installer/launch.bat` (Windows) o `installer/launch.sh` (Linux/Mac/WSL), compili
> un form e clicchi **Installa**. Vedi [installer/README.md](../installer/README.md).
> Questo documento descrive il percorso **manuale/avanzato**, per chi vuole installare
> a mano sulla VPS o capire ogni passo.

Sequenza passo-passo dall'host vuoto a stack su.

## Prerequisiti

| Cosa | Versione | Note |
|---|---|---|
| Linux x86_64 (amd64) | qualsiasi recente | Le immagini di release sono pubblicate **solo per amd64**: su arm64 (Raspberry, VPS Ampere) il pull non trova un'immagine per l'architettura. Debian 12 consigliata (collaudo completo su macchina vergine, 27/08/2026 — su Debian 13 con volumi cifrati la VPS era instabile, voce `H56`) / Ubuntu 24+ / Fedora / Arch |
| Docker Engine | 24+ | con `docker compose` plugin v2 |
| python3 **+ bcrypt** | 3.10+ | solo per `setup.sh` (calcola l'hash della password admin). Su Debian/Ubuntu `python3` è un pacchetto a sé: `sudo apt install python3 python3-bcrypt`. ⚠️ **`python3-pip` NON basta su Debian 12+ / Ubuntu 23.04+** — cioè proprio sulla distro consigliata: lì pip c'è già ed è l'*installazione* a essere vietata (PEP 668), quindi `pip install bcrypt` fallisce. Il pacchetto giusto è `python3-bcrypt` (Fedora: `sudo dnf install python3-bcrypt`). Se `bcrypt` c'è già, non serve altro — il preflight verifica la capacità, non il nome |
| RAM / disco | 4 GB / ~2 GB liberi | il progetto è tarato su una VPS da 4 GB; le immagini occupano ~2 GB |
| `curl`, `sudo` | — | `setup.sh` chiede a GitHub l'ultima release con `curl`; va lanciato da un utente normale con `sudo`, non da root (vedi il passo 5 qui sotto) |
| Account Tailscale **o** Caddy+dominio **o** Cloudflare | uno dei tre | scelta al setup. Con **Caddy** servono le porte 80 e 443 aperte in ingresso. Con **Cloudflare**, **prima** di `./setup.sh` crea il tunnel sul dashboard (one.dash.cloudflare.com → Networks → Tunnels): `setup.sh` chiede l'hostname pubblico e il token (senza mostrarlo, lo salva in `secrets/cloudflared_token.txt` con permessi 600). Se lasci il token vuoto lo stack parte senza tunnel, e `setup.sh` dice alla fine come aggiungerlo. Con **Tailscale** vedi [più sotto](#se-hai-scelto-tailscale-il-funnel-lo-accendi-tu) |
| Bot Telegram + OWNER_ID | da [@BotFather](https://t.me/BotFather) + [@userinfobot](https://t.me/userinfobot) | opzionale per dev, obbligatorio per prod |
| Account Google con NotebookLM | gratis | il login si fa **dopo l'install** via `/admin/nlm` |

## 4 step

```bash
git clone https://github.com/neo1777/vps1777.git
cd vps1777
./setup.sh                                      # wizard interattivo
# solo se hai risposto «no» a «Procedo ora?»: lancia il comando che setup.sh ti ha
# stampato (contiene anche l'overlay delle feature). Con Tailscale e le feature di default:
docker compose -f compose.yaml -f compose.ingress.tailscale.yaml -f compose.ops.backup.yaml \
  --profile ingress.tailscale --profile ops.backup pull
docker compose -f compose.yaml -f compose.ingress.tailscale.yaml -f compose.ops.backup.yaml \
  --profile ingress.tailscale --profile ops.backup up -d      # o caddy / cloudflared
```

Lo stage finale ti stampa gli URL. Con Tailscale, finché non accendi il Funnel, al
posto dell'URL trovi il segnaposto `<PUBLIC_BASE>`: vedi
[più sotto](#se-hai-scelto-tailscale-il-funnel-lo-accendi-tu).

Rispondendo «no» a «Procedo ora?», `setup.sh` salta anche il passo 5 qui sotto (CLI
`vps1777`, unit systemd, hardening): avviare lo stack a mano non li recupera. Per
averli, rilancia `./setup.sh` e rispondi «sì»: gli step già fatti vengono saltati.

## Cosa fa `setup.sh`

1. Verifica Docker + Compose v2 + python3
2. Crea `.env` (chiede: email admin, TG_OWNER_ID, ingress; con Caddy il dominio, con
   Cloudflare l'hostname pubblico del tunnel)
3. Genera `secrets/*.txt`:
   - `gateway_secret.txt` (32 caratteri url-safe = 24 byte di entropia)
   - `archive_desc_secret.txt` (32 caratteri url-safe = 24 byte di entropia)
   - `oauth_signing_secret.txt` (64 caratteri url-safe = 48 byte di entropia)
   - `admin_password_bcrypt.txt` (bcrypt rounds=12 della password che scegli/che genera)
   - `telegram_bot_token.txt` (incolli il token, che non viene mostrato; vuoto = bot in
     standby, da attivare poi con `./tools/rotate-secret.sh telegram_bot_token`)
   - `cloudflared_token.txt`, solo con Cloudflare (incolli il token del tunnel, che non
     viene mostrato; vuoto = lo stack parte senza tunnel, e rilanciando `./setup.sh` te lo
     richiede)
   - `telegram_webapp_secret.txt` — la chiave **derivata** dal token
     (HMAC-SHA256 con chiave `WebAppData`), l'unica che il gateway monta: la
     rigenera a ogni lancio, così segue il token se cambia (vuota se il token è vuoto)
4. Lancia `docker compose -f compose.yaml -f compose.ingress.<scelta>.yaml --profile
   ingress.<scelta> up -d`, più l'overlay e il profilo di ogni feature dichiarata in
   `VPS1777_FEATURES` (di default `backup`: `-f compose.ops.backup.yaml --profile ops.backup`;
   `portainer` allo stesso modo; `caddy-dns01` aggiunge solo l'overlay
   `compose.ops.caddy-dns01.yaml`, e solo con l'ingress Caddy e
   `secrets/cf_api_token.txt` non vuoto, altrimenti avvisa e Caddy parte in HTTP-01;
   vedi [OPS.md](OPS.md)) — gli `-f` non sono decorativi: senza, l'overlay ingress non
   viene montato (il `gateway` resta senza `ports:` e manca la rete `funnel`) — le immagini
   vengono **pullate da GHCR** (`compose.yaml` è pull-only: sulla VPS non si
   builda mai; il build locale è solo dev, con l'overlay `compose.build.yaml`)
5. Se hai risposto «sì» a «Procedo ora?», **con `sudo`** (ti chiede la password):
   installa la CLI `vps1777` in `/usr/local/bin`; installa **tutte** le unit
   `systemd/vps1777-*` in `/etc/systemd/system` e ne **abilita** quattro —
   `vps1777-check-update.timer`, `vps1777-update.path`, `vps1777-secrets-check.timer`,
   `vps1777-ingest.path` (la coda d'indicizzazione della pagina Archive)
   — più `vps1777-auto-update.timer` se `autoupdate` è in `VPS1777_FEATURES` (lo è di
   default); applica l'**hardening dell'host**: `apt-get install` di
   `unattended-upgrades` e `fail2ban`, con `/etc/apt/apt.conf.d/20auto-upgrades` e una
   jail `sshd` in `/etc/fail2ban/jail.local` (se quei file ci sono già con un contenuto
   diverso non li tocca, e lo dice; senza `apt-get` avvisa e salta). Le unit girano
   come l'utente che lancia lo script: se è `root` (`sudo ./setup.sh`) qui si ferma,
   perché l'updater automatico avrebbe i privilegi pieni della macchina (`H55`) — lancialo
   come l'operatore, oppure digli chi è con `OPERATOR_USER=<utente>`
6. Stampa come ultima riga il comando per verificare l'installazione **da fuori**,
   dal tuo PC: `./tools/collaudo-da-fuori.sh <url-pubblico>`

Se rilanci `setup.sh`, salta gli step già fatti.

## Se hai scelto Tailscale: il Funnel lo accendi tu

`setup.sh` non installa Tailscale e non attiva il Funnel: lo fanno solo l'installer
grafico e `deploy.sh`. Senza questo passo il pannello risponde solo su `127.0.0.1:8080`
della VPS e `<PUBLIC_BASE>` resta un segnaposto. Alla fine `setup.sh` stampa questi
stessi comandi, col tuo comando compose.

Prima prepara l'account come in [INGRESS.md](INGRESS.md) §1 (MagicDNS, HTTPS
Certificates, `nodeAttr funnel` nell'ACL), poi sulla VPS:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --hostname=vps1777 --accept-dns=false   # o --authkey=file:<file con la tskey-auth-…>
sudo tailscale serve reset && sudo tailscale funnel --bg --https=443 http://127.0.0.1:8080
tailscale status --json | python3 -c 'import sys,json;print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))'
```

Il Funnel si accende in un comando solo: `tailscale serve --https=443 …` seguito da
`tailscale funnel 443` fa rispondere 502.

Scrivi l'URL ottenuto in `.env` (`PUBLIC_BASE=https://<nome>.<tailnet>.ts.net`) e
ricrea i servizi che lo leggono (gateway, `nb1777-mcp` e `nb1777-bot`) con gli stessi
`-f` e `--profile` che `setup.sh` ha stampato, per esempio con le feature di default:

```bash
docker compose -f compose.yaml -f compose.ingress.tailscale.yaml -f compose.ops.backup.yaml \
  --profile ingress.tailscale --profile ops.backup up -d gateway nb1777-mcp nb1777-bot
```

## Post-install

1. **Login admin**: `<PUBLIC_BASE>/admin/login` → email + password admin
2. **Auth NotebookLM**: sul TUO PC installa il CLI `nlm`, fai login, poi carica il **profilo** (tar.gz) su `<PUBLIC_BASE>/admin/nlm`. La CLI `nlm` (dalla 0.7) salva l'auth come cartella `profiles/default/` (non più un singolo `auth.json`):
   ```bash
   uv tool install notebooklm-mcp-cli==0.15.4 --python 3.12   # serve uv (astral.sh)
   nlm login                                             # apre il browser → login NotebookLM
   # se chiede «Protected or plain file?» scegli il FILE: la VPS non apre il login cifrato
   cd ~/.notebooklm-mcp-cli && tar czf nlm-profile.tgz profiles/default
   ```
   La versione è quella con cui gira il server (`services/nb1777-mcp/pyproject.toml`): una CLI diversa può salvare il profilo in un'altra forma. Carica `nlm-profile.tgz` su `<PUBLIC_BASE>/admin/nlm` (login admin). Il gateway lo inoltra a `nb1777-mcp` sul canale interno (il gateway non monta i cookie), che lo estrae sul suo volume e lo usa dalla call successiva.
   Se `nlm` risulta "not found": `uv tool update-shell` (mette `~/.local/bin` nel PATH) e riapri il terminale.
3. **Connector claude.ai**: Settings → Connectors → Add custom connector → incolla URL `<PUBLIC_BASE>/<SECRET>/archive/mcp` (e `/nb1777/mcp`); `<SECRET>` è il contenuto di `secrets/gateway_secret.txt` (`cat secrets/gateway_secret.txt`). Autorizza → login admin. `archive` espone i tool di ricerca sull'archivio (elenco e dettaglio in [ARCHIVE.md](ARCHIVE.md)), `nb1777` ne espone **55** ([NB1777.md](NB1777.md)). I connector **persistono** ai restart del gateway (DCR salvata su disco).
4. **Bot Telegram**: `/start` al tuo bot
5. **Mini App**: nel bot, bottone **Pannello** accanto al campo di testo (o
   `/start`) → la plancia mobile: notebook, archivio, secret, update.
   Richiede `PUBLIC_BASE` https. Vedi [MINIAPP.md](MINIAPP.md).
6. **Ricerca per senso** (facoltativa): `search_ibrida` trova ciò di cui ricordi il
   senso e non la parola. Servono il modello (`vps1777 indice-modello`, scarica e
   verifica da solo) e un indice per ogni DB, costruito sul PC: ~7 ore ogni 100.000
   vettori su un PC a 4 core. Finché mancano, `search` funziona come prima e
   `search_ibrida` dice cosa manca. Passi: [RICERCA-IBRIDA.md](RICERCA-IBRIDA.md),
   «Attivare la ricerca per senso».

## Ops opzionali

Hardening di base (automatico: `unattended-upgrades` + `fail2ban`) e profili
opzionali — Portainer (cruscotto visuale), backup — sono documentati in
[OPS.md](OPS.md).

## Aggiornamento

Canale primario: la CLI host **`vps1777 update`** (la installano `setup.sh`,
`deploy.sh` e l'installer grafico) o il pulsante nel **pannello admin → tab Update** —
backup automatico prima, pull con verifica digest, migrazioni, health-gate,
rollback automatico se la nuova versione non torna in salute. Manuale
completo: [UPDATE.md](UPDATE.md).

Watchtower (profilo `ops.autoupdate`) è stato **rimosso nella 0.67.0**: bypassava
backup, migrazioni, health-gate e rollback, e la sua immagine è archiviata a monte.
L'aggiornamento automatico è la feature `autoupdate`, accesa di default. Se l'avevi
attivo, `vps1777 update` ne rimuove il container — vedi [OPS.md](OPS.md).

## Disinstallazione

Prima spegni le unit systemd e togli la CLI che `setup.sh` ha installato, altrimenti
l'auto-update e gli altri timer continuano a girare su un'installazione smontata:

```bash
for u in /etc/systemd/system/vps1777-*; do sudo systemctl disable --now "$(basename "$u")"; done
sudo rm -f /etc/systemd/system/vps1777-* /usr/local/bin/vps1777 && sudo systemctl daemon-reload
```

(`fail2ban` e `unattended-upgrades` restano: si tolgono come qualunque pacchetto.) Poi:

```bash
# `--remove-orphans` non è opzionale: il container dell'ingress sta in un overlay, non
# è nel modello che `down` costruisce da solo, e senza RESTA ACCESO. Si usa questo e non
# gli `-f` perché qui non sappiamo quale ingress hai scelto — e una riga che deve
# indovinarlo è sbagliata per chi ha scelto l'altro.
docker compose down -v --remove-orphans               # -v cancella i volumi
rm -rf secrets/                                       # cancella i secret
```
