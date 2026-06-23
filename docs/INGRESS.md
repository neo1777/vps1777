# Ingress — vps1777

3 modi per esporre il gateway su HTTPS pubblico. Scegli uno.

## 1. Tailscale Funnel (raccomandato)

**Quando**: vuoi un URL HTTPS gratis con cert auto-rinnovato, sub-dominio `*.ts.net`, no DNS proprio.

**Setup**:

### Modalità A — OAuth client (raccomandato 2026)

1. Vai su [admin.tailscale.com → Settings → OAuth clients](https://login.tailscale.com/admin/settings/oauth)
2. **Generate OAuth client** con scope `devices:read,devices:write`, tag `tag:vps1777`
3. Salva `client_id` e `client_secret` in `secrets/ts_oauth.txt` (formato: `<client_id>:<client_secret>`)
4. Aggiungi a `.env`: `TS_HOSTNAME=vps1777`
5. Lancia: `docker compose --profile ingress.tailscale up -d`

### Modalità B — Auth-key (fallback)

1. Vai su [admin/settings/keys](https://login.tailscale.com/admin/settings/keys)
2. **Generate auth key** (tag `tag:vps1777`, expiry 90gg)
3. Salva la stringa `tskey-auth-...` in `secrets/ts_authkey.txt`
4. Aggiungi a `.env`: `TS_HOSTNAME=vps1777` + `TS_AUTHKEY=` (lascia vuoto, lo legge dal file)
5. Lancia: `docker compose --profile ingress.tailscale up -d`

### Hostname del nodo

Tailscale assegna `<TS_HOSTNAME>.<tailnet>.ts.net`. Annota questa URL nel pannello — la userai come `PUBLIC_BASE` dopo il primo avvio.

## 2. Caddy + Let's Encrypt

**Quando**: hai un dominio tuo, vuoi controllo totale, no Tailscale dependency.

**Setup base (HTTP-01)**:

1. Punta DNS `A`/`AAAA` di `<dominio>` all'IP VPS
2. Apri porte 80 e 443 in ufw/firewall
3. Aggiungi a `.env`:
   - `CADDY_DOMAIN=vps.tuosito.com`
   - `CADDY_EMAIL=tu@gmail.com`
4. Lancia: `docker compose --profile ingress.caddy up -d`

Caddy fa cert ACME via HTTP-01 al primo avvio.

**Setup DNS-01 (senza porta 80)**:

Richiede immagine Caddy custom con plugin DNS provider. Esempio Cloudflare:

```Dockerfile
FROM caddy:2.8-builder AS builder
RUN xcaddy build --with github.com/caddy-dns/cloudflare

FROM caddy:2.8-alpine
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
```

Aggiungi `secrets/cf_api_token.txt` + modifica `ingress/Caddyfile` con `tls.dns cloudflare`.

## 3. Cloudflare Tunnel

**Quando**: vuoi anti-DDoS CF gratis, no porte aperte sul VPS.

**Setup**:

1. Su [one.dash.cloudflare.com → Networks → Tunnels](https://one.dash.cloudflare.com/) → Create Tunnel
2. Configura **Public Hostname** che punta a `http://gateway:8080`
3. Copia il **tunnel token** (lungo, base64) in `secrets/cloudflared_token.txt`
4. Lancia: `docker compose --profile ingress.cloudflared up -d`

CF gestisce HTTPS + DNS automaticamente.

## Confronto rapido

| Aspetto | Tailscale | Caddy | Cloudflared |
|---|---|---|---|
| Costo | gratis (free tier) | gratis | gratis |
| Dominio tuo | no (*.ts.net) | sì obbligatorio | sì o sub-dominio |
| Porte aperte | nessuna | 80 + 443 | nessuna |
| Cert auto | sì | sì (LE) | sì (CF) |
| Anti-DDoS | no | no | sì |
| Setup minuti | ~5 | ~10 | ~10 |
| Vincoli | account Tailscale | account ACME | account Cloudflare |
