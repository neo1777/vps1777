# Ingress — vps1777

3 modi per esporre il gateway su HTTPS pubblico. Scegli uno.

## 1. Tailscale Funnel (raccomandato)

**Quando**: vuoi un URL HTTPS gratis con cert auto-rinnovato, sub-dominio `*.ts.net`, no DNS proprio.

> **Tailscale gira SULL'HOST, non in container.** L'installer installa Tailscale
> sull'host (servizio systemd) e fa `up` + `serve` + `funnel` verso il gateway su
> `127.0.0.1:8080`. Questo evita i bug del container sidecar (crash containerboot,
> netns fragile) ed è robusto ai reboot. Il gateway resta in Docker.
>
> **Prerequisiti di account** (la sola auth-key non li porta — restano comunque
> necessari): **MagicDNS**, **HTTPS Certificates** e l'attributo **`funnel` nell'ACL**.
> I due toggle MagicDNS/HTTPS sono manuali (Tailscale non espone API: è un consenso
> umano *by design*).

Comune a entrambe le modalità: in [admin → DNS](https://login.tailscale.com/admin/dns)
abilita **MagicDNS** e **HTTPS Certificates** (una tantum).

### Modalità A — Auth-key (semplice, consigliata per iniziare)

1. Vai su [admin → Machines → Add device → Linux server](https://login.tailscale.com/admin/machines/new-linux) (o [Settings → Keys](https://login.tailscale.com/admin/settings/keys)) e **Generate** una auth-key. Se la tagghi `tag:vps1777`, assicurati che l'ACL conceda il funnel a quel tag; se la lasci **senza tag**, il nodo è tuo (autogroup:member) e serve `{"target":["autogroup:member"],"attr":["funnel"]}` nell'ACL.
2. Incolla la stringa `tskey-auth-...` nell'installer (Ingress → Tailscale → campo auth-key).

L'installer la usa per `tailscale up` sull'host. **Non scrive l'ACL** in questa modalità: il `nodeAttr funnel` deve già esserci (vedi sotto).

### Modalità B — OAuth client (automatizza anche l'ACL)

1. In [admin → OAuth clients](https://login.tailscale.com/admin/settings/oauth) crea un **OAuth client** con scope **`policy_file`** (write) + **`auth_keys`**. **⚠ Punto critico**: nello scope `auth_keys`, sezione **Tags**, **assegna `tag:vps1777`** (selezionalo). Se il client non possiede quel tag, la key fallisce con `requested tags [tag:vps1777] are invalid or not permitted`.
2. Incolla **Client ID** e **Client Secret** nell'installer.

L'installer, dal tuo PC: ottiene il token, **scrive nell'ACL il `nodeAttr funnel`** per `tag:vps1777` (merge idempotente), e genera una **auth-key taggata single-use**. Il *Client Secret* non lascia il PC.

### nodeAttr funnel nell'ACL (modalità A, manuale)

In [admin → Access Controls](https://login.tailscale.com/admin/acls), in `nodeAttrs`:
```hujson
"nodeAttrs": [ { "target": ["autogroup:member"], "attr": ["funnel"] } ]
```
(o per `tag:vps1777` se usi una key taggata). La modalità B lo scrive da sé.

### Hostname del nodo

Tailscale assegna `<TS_HOSTNAME>.<tailnet>.ts.net`. L'installer ricava questa URL
da solo (`tailscale status`) e imposta `PUBLIC_BASE`.

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

## Nota — IP client dietro il proxy (`forwarded_allow_ips`)

Dal **v0.28.0** il gateway si fida dell'header `X-Forwarded-For` **solo** dai
peer nei range privati + loopback (uvicorn `forwarded_allow_ips`), mai da un IP
pubblico → l'IP del client non è spoofabile (rate-limit, lockout e audit
restano affidabili). Il default è
`127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16`.

Per gli ingress **in container** (Caddy, Cloudflared) il proxy arriva da una
bridge Docker privata (es. `172.x.0.1`): il default **la copre già**, quindi di
norma **non serve configurare nulla**. Solo topologie esotiche (proxy su un
altro host, subnet fuori dai blocchi privati) richiedono un override via env
**`GATEWAY_FORWARDED_ALLOW_IPS`** (uvicorn 0.51 accetta anche la notazione CIDR).

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
