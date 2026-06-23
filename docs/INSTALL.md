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
4. Lancia `docker compose --profile ingress.<scelta> up -d --build`

Se rilanci `setup.sh`, salta gli step già fatti.

## Post-install

1. **Login admin**: `<PUBLIC_BASE>/admin/login` → email + password admin
2. **Auth NotebookLM**: `<PUBLIC_BASE>/admin/nlm` → fai `nlm login` sul tuo PC → carichi `auth.json`. Il container `nb1777-mcp` riparte e detecta auth.
3. **Connector claude.ai**: Settings → Integrations → Add → incolla URL `<PUBLIC_BASE>/<SECRET>/archive/mcp` (e `/nb1777/mcp`)
4. **Bot Telegram**: `/start` al tuo bot

## Ops opzionali

Hardening di base (automatico: `unattended-upgrades` + `fail2ban`) e profili
opzionali — Portainer (cruscotto visuale), Watchtower (auto-update), backup —
sono documentati in [OPS.md](OPS.md).

## Aggiornamento

Vedi [BACKUP-RESTORE.md](BACKUP-RESTORE.md). Con Watchtower (profilo `ops.autoupdate`) è automatico.

## Disinstallazione

```bash
docker compose --profile ingress.tailscale down -v   # -v cancella i volumi
rm -rf secrets/                                       # cancella i secret
```
