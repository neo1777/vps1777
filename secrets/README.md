# secrets/

Questa cartella è gitignored. Contiene i file plain-text dei secret montati come Docker secrets nei container.

**MAI committare niente qui** tranne questo README e `.gitkeep`.

Generati da `setup.sh` la prima volta. Vedi [docs/SECRETS.md](../docs/SECRETS.md) per dettagli + rotation.

File attesi (sempre `chmod 600`):
- `gateway_secret.txt`
- `oauth_signing_secret.txt`
- `admin_password_bcrypt.txt`
- `telegram_bot_token.txt`
- `ts_authkey.txt` (solo se ingress.tailscale + auth-key mode)
- `cloudflared_token.txt` (solo se ingress.cloudflared)
