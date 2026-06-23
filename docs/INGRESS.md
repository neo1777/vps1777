# Ingress — vps1777

3 modi per esporre il gateway su HTTPS pubblico. Scegli uno.

## 1. Tailscale Funnel (raccomandato)

**Quando**: vuoi un URL HTTPS gratis con cert auto-rinnovato, sub-dominio `*.ts.net`, no DNS proprio.

> **Perché serve più della auth-key.** Far entrare il nodo nel tailnet è facile;
> attivare il **Funnel** (l'esposizione HTTPS pubblica) richiede 3 cose a livello
> di **account**, che la sola auth-key non porta: **MagicDNS**, **HTTPS
> Certificates** e l'attributo **`funnel` nell'ACL**. Per questo l'installer usa
> un **OAuth client**: con quello automatizza la parte ACL + la generazione della
> key; i due toggle (MagicDNS/HTTPS) restano manuali perché Tailscale non espone
> API per abilitarli (è un consenso umano *by design*).

### Modalità A — OAuth client (raccomandato, via installer)

**4 passi una tantum nella admin console Tailscale:**

1. Crea l'account su [login.tailscale.com](https://login.tailscale.com)
2. In [admin → DNS](https://login.tailscale.com/admin/dns) abilita **MagicDNS** e **HTTPS Certificates**
3. In [admin → OAuth clients](https://login.tailscale.com/admin/settings/oauth) crea un **OAuth client** con scope **`policy_file`** (write) + **`auth_keys`**, e assegna il tag **`tag:vps1777`** (creandolo lì → viene aggiunto ai `tagOwners` dell'ACL)
4. Incolla **Client ID** e **Client Secret** nell'installer (sezione Ingress → Tailscale)

L'installer (engine, dal tuo PC) fa il resto **in automatico**:
- ottiene un token OAuth dal client
- scrive nell'ACL il `nodeAttr` `funnel` per `tag:vps1777` (merge idempotente)
- genera una **auth-key taggata single-use** e la scrive in `.env` come `TS_AUTHKEY`

> **Sicurezza**: il *Client Secret* non lascia il tuo PC. Sulla VPS finisce solo
> la auth-key usa-e-getta, che si consuma al primo login del nodo.

### Modalità B — Auth-key diretta (avanzata / manuale sulla VPS)

Se installi a mano sulla VPS (senza l'installer) o preferisci gestire l'account
da te:

1. Abilita comunque **MagicDNS** + **HTTPS Certificates** (vedi sopra) e aggiungi all'ACL `{"target":["tag:vps1777"],"attr":["funnel"]}` in `nodeAttrs`
2. Genera una **auth key** taggata `tag:vps1777` in [admin/settings/keys](https://login.tailscale.com/admin/settings/keys)
3. Mettila in `.env`: `TS_HOSTNAME=vps1777` + `TS_AUTHKEY=tskey-auth-...`
4. Lancia: `docker compose --profile ingress.tailscale up -d`

> `TS_AUTHKEY` vive in `.env` (letta dal sidecar via env), **non** è un Docker
> secret file. Senza i 3 prerequisiti account il Funnel non parte e si resta su
> HTTP — vedi [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

### Hostname del nodo

Tailscale assegna `<TS_HOSTNAME>.<tailnet>.ts.net`. L'installer ricava questa URL
da solo e imposta `PUBLIC_BASE`; in manuale annotala e mettila in `.env`.

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
