# Secrets — vps1777

Tutti i secret stanno in `secrets/*.txt` (gitignored) e vengono montati nei container in `/run/secrets/<name>` (tmpfs read-only).

## Inventario

| Secret | File | Cosa contiene | Chi lo legge |
|---|---|---|---|
| `gateway_secret` | `secrets/gateway_secret.txt` | namespace nelle URL `/<SECRET>/<service>/mcp` (24-32 char) | gateway |
| `oauth_signing_secret` | `secrets/oauth_signing_secret.txt` | firma JWT HS256 (≥32 byte) | gateway |
| `admin_password_bcrypt` | `secrets/admin_password_bcrypt.txt` | hash bcrypt della password admin (rounds=12) | gateway |
| `telegram_bot_token` | `secrets/telegram_bot_token.txt` | TOKEN bot da BotFather | gateway, nb1777-bot |
| `cloudflared_token` | `secrets/cloudflared_token.txt` | (opz) CF Tunnel token | cloudflared sidecar |

> **Tailscale**: `TS_AUTHKEY` **non** è un Docker secret — vive in `.env` (la legge
> il sidecar via env). Con l'installer è una key usa-e-getta generata da un OAuth
> client (il cui *secret* resta sul tuo PC). Vedi [INGRESS.md](INGRESS.md).

## Generazione iniziale

`setup.sh` li genera tutti la prima volta. Per rigenerarne uno singolo: cancellalo (`rm secrets/<file>`) e rilancia `./setup.sh`.

## Rotation senza downtime

### Rota `gateway_secret`

```bash
NEW=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')
echo -n "$NEW" > secrets/gateway_secret.txt
docker compose restart gateway   # < 2s downtime
# I tuoi URL connector cambiano: rigenerali da claude.ai
```

### Rota `oauth_signing_secret`

```bash
NEW=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')
echo -n "$NEW" > secrets/oauth_signing_secret.txt
docker compose restart gateway
# ATTENZIONE: invalida TUTTI i token attivi (access, refresh, admin, miniapp).
# I client OAuth (claude.ai) richiedono nuovo login via refresh_token automatico,
# se il refresh era ancora valido. Altrimenti devi rifare il connector.
```

### Rota `admin_password_bcrypt`

```bash
ADMIN_PWD_RAW="<nuova_password>" python3 -c '
import os, bcrypt
print(bcrypt.hashpw(os.environ["ADMIN_PWD_RAW"].encode(), bcrypt.gensalt(12)).decode())
' > secrets/admin_password_bcrypt.txt
docker compose restart gateway
```

Il pannello `/admin/secrets` documenta la procedura ma non la esegue: il
gateway non ha privilegi per riscrivere i secret host né per riavviarsi
(stesso design del canale update, vedi [ARCHITECTURE.md](ARCHITECTURE.md)) —
la rotation si fa da CLI come sopra. Un `docker compose restart` non tocca le
immagini: nessuna build, nessun pull.

## Backup

Vedi [BACKUP-RESTORE.md](BACKUP-RESTORE.md). I secret vanno backuppati age-encrypted insieme ai volumi.

## Threat model

- `secrets/` ha mode 700 + file 600 (impostato da setup.sh)
- Container vede solo `/run/secrets/<name>` con mode 400, owner root
- Mai loggare i secret a video (gateway sanitizza i log)
- L'audit log NON contiene mai i valori, solo il nome del secret rotato
