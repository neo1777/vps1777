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
| Linux x86_64/arm64 | qualsiasi recente | Debian 13 / Ubuntu 24+ / Fedora / Arch testati |
| Docker Engine | 24+ | con `docker compose` plugin v2 |
| python3 | 3.10+ | solo per setup.sh (calcola bcrypt) |
| Account Tailscale **o** Caddy+dominio **o** Cloudflare | uno dei tre | scelta al setup |
| Bot Telegram + OWNER_ID | da [@BotFather](https://t.me/BotFather) + [@userinfobot](https://t.me/userinfobot) | opzionale per dev, obbligatorio per prod |
| Account Google con NotebookLM | gratis | il login si fa **dopo l'install** via `/admin/nlm` |

## 4 step

```bash
git clone https://github.com/<owner>/vps1777.git
cd vps1777
./setup.sh                                      # wizard interattivo
docker compose --profile ingress.tailscale up -d  # o caddy / cloudflared
```

Lo stage finale ti stampa gli URL.

## Cosa fa `setup.sh`

1. Verifica Docker + Compose v2 + python3
2. Crea `.env` (chiede: email admin, TG_OWNER_ID, ingress)
3. Genera `secrets/*.txt`:
   - `gateway_secret.txt` (32 byte url-safe)
   - `oauth_signing_secret.txt` (64 byte url-safe)
   - `admin_password_bcrypt.txt` (bcrypt rounds=12 della password che scegli/che genera)
   - `telegram_bot_token.txt` (incolli il token)
4. Lancia `docker compose --profile ingress.<scelta> up -d` — le immagini
   vengono **pullate da GHCR** (`compose.yaml` è pull-only: sulla VPS non si
   builda mai; il build locale è solo dev, con l'overlay `compose.build.yaml`)

Se rilanci `setup.sh`, salta gli step già fatti.

## Post-install

1. **Login admin**: `<PUBLIC_BASE>/admin/login` → email + password admin
2. **Auth NotebookLM**: sul TUO PC installa il CLI `nlm`, fai login, poi carica il **profilo** (tar.gz) su `<PUBLIC_BASE>/admin/nlm`. La CLI `nlm` 0.7.x salva l'auth come cartella `profiles/default/` (non più un singolo `auth.json`):
   ```bash
   uv tool install notebooklm-mcp-cli --python 3.12      # serve uv (astral.sh)
   nlm login                                             # apre il browser → login NotebookLM
   cd ~/.notebooklm-mcp-cli && tar czf nlm-profile.tgz profiles/default
   ```
   Carica `nlm-profile.tgz` su `<PUBLIC_BASE>/admin/nlm` (login admin). Il gateway lo estrae sul volume; `nb1777-mcp` lo rileva alla prossima call.
   Se `nlm` risulta "not found": `uv tool update-shell` (mette `~/.local/bin` nel PATH) e riapri il terminale.
3. **Connector claude.ai**: Settings → Integrations → Add → incolla URL `<PUBLIC_BASE>/<SECRET>/archive/mcp` (e `/nb1777/mcp`). Autorizza → login admin. `archive` espone i tool di ricerca sull'archivio (elenco e dettaglio in [ARCHIVE.md](ARCHIVE.md)), `nb1777` ne espone **37** ([NB1777.md](NB1777.md)). I connector **persistono** ai restart del gateway (DCR salvata su disco).
4. **Bot Telegram**: `/start` al tuo bot
5. **Mini App**: nel bot, bottone **Pannello** accanto al campo di testo (o
   `/pannello`) → la plancia mobile: notebook, archivio, secret, update.
   Richiede `PUBLIC_BASE` https. Vedi [MINIAPP.md](MINIAPP.md).

## Ops opzionali

Hardening di base (automatico: `unattended-upgrades` + `fail2ban`) e profili
opzionali — Portainer (cruscotto visuale), Watchtower (declassato), backup —
sono documentati in [OPS.md](OPS.md).

## Aggiornamento

Canale primario: la CLI host **`vps1777 update`** (installata da `deploy.sh`,
nella radice del repo) o il pulsante nel **pannello admin → tab Update** —
backup automatico prima, pull con verifica digest, migrazioni, health-gate,
rollback automatico se la nuova versione non torna in salute. Manuale
completo: [UPDATE.md](UPDATE.md).

Watchtower (profilo `ops.autoupdate`) è **declassato**: resta opt-in ma non è
supportato in concomitanza col canale gestito (bypassa backup, migrazioni,
health-gate e rollback) — vedi [OPS.md](OPS.md).

## Disinstallazione

```bash
docker compose --profile ingress.tailscale down -v   # -v cancella i volumi
rm -rf secrets/                                       # cancella i secret
```
