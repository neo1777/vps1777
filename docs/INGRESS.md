# Ingress — vps1777

3 modi per esporre il gateway su HTTPS pubblico. Scegli uno.

> **Il profilo scelto sta nel `.env`: `INGRESS_PROFILE=ingress.<nome>`** (`tailscale`,
> `caddy` o `cloudflared`). Lo scrivono gli installer, ed è da lì che `vps1777 update` e
> `vps1777 rollback` (e le unit che li lanciano) ricavano quale overlay montare. **Se manca, vale
> `ingress.tailscale`.** Quindi un cambio d'ingress fatto a mano solo con gli `-f` di
> `docker compose` dura fino al primo update: se nel `.env` non cambi anche
> `INGRESS_PROFILE`, l'update riporta su Tailscale.

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
   - `INGRESS_PROFILE=ingress.caddy` (vedi in cima: senza, il primo update torna a Tailscale)
4. Lancia: `docker compose -f compose.yaml -f compose.ingress.caddy.yaml --profile ingress.caddy up -d`
   (senza gli `-f` l'overlay non viene montato e Caddy non entra nel progetto)

Caddy fa cert ACME via HTTP-01 al primo avvio.

**Setup DNS-01 (senza porta 80) — oggi NON è predisposto.**

Il repo ne ha solo gli accenni, e nessuno dei pezzi è collegato:

- `ingress/Caddyfile` porta la riga `acme_dns cloudflare {env.CF_API_TOKEN}`, **commentata**;
- `compose.ingress.caddy.yaml` usa l'immagine `caddy:2.8-alpine` di serie (senza plugin
  DNS) e al container passa **solo** `CADDY_DOMAIN` e `CADDY_EMAIL`: `CF_API_TOKEN` **non
  arriva** a Caddy, e nessun file lo legge da `secrets/`;
- l'override «compose.ingress.caddy-dns01.yaml» che il commento in testa a quel file
  nomina **non esiste**.

Per farlo a mano servono tre cose: un'immagine Caddy con il plugin del provider (esempio
Cloudflare sotto), un override compose che la usi e passi `CF_API_TOKEN` nell'ambiente
del servizio `caddy`, e la riga `acme_dns` scommentata nel `Caddyfile`.

```Dockerfile
FROM caddy:2.8-builder AS builder
RUN xcaddy build --with github.com/caddy-dns/cloudflare

FROM caddy:2.8-alpine
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
```

⚠️ **E non sopravvive al canale di aggiornamento**: `ingress/Caddyfile` e
`compose*.yaml` sono file gestiti, che ogni `vps1777 update` riscrive dal bundle, e il
comando compose della CLI monta solo `compose.yaml`, l'overlay di `INGRESS_PROFILE` e
quelli delle feature — non un override tuo. Oggi DNS-01 regge solo su una macchina che
non usa `vps1777 update`.

## 3. Cloudflare Tunnel

**Quando**: vuoi anti-DDoS CF gratis, no porte aperte sul VPS.

**Setup**:

1. Su [one.dash.cloudflare.com → Networks → Tunnels](https://one.dash.cloudflare.com/) → Create Tunnel
2. Configura **Public Hostname** che punta a `http://gateway:8080`
3. Copia il **tunnel token** (lungo, base64) in `secrets/cloudflared_token.txt`, e metti
   `INGRESS_PROFILE=ingress.cloudflared` nel `.env` (vedi in cima)
4. Lancia: `docker compose -f compose.yaml -f compose.ingress.cloudflared.yaml --profile ingress.cloudflared up -d`
   (senza gli `-f` l'overlay non viene montato e il tunnel non entra nel progetto)

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
**`GATEWAY_FORWARDED_ALLOW_IPS`** (uvicorn — il gateway chiede `>=0.52.3` — accetta anche
la notazione CIDR).

## Confronto rapido

| Aspetto | Tailscale | Caddy | Cloudflared |
|---|---|---|---|
| **Chi può raggiungere il servizio** | **chiunque su Internet** (il profilo attiva il Funnel) | **chiunque su Internet** | **chiunque su Internet** |
| Costo | gratis (free tier) | gratis | gratis |
| Dominio tuo | no (*.ts.net) | sì obbligatorio | sì o sub-dominio |
| Porte aperte | nessuna | 80 + 443 | nessuna |
| Cert auto | sì | sì (LE) | sì (CF) |
| Anti-DDoS | no | no | sì |
| Setup minuti | ~5 | ~10 | ~10 |
| Vincoli | account Tailscale | account ACME | account Cloudflare |

> ⚠️ **La prima riga è la prima apposta** (issue #63). Le altre pesano costo e minuti di
> setup; questa dice **chi arriva alla porta** — ed è l'unica in cui i tre profili **non
> si distinguono: sono pubblici tutti e tre.** [`SECURITY.md`](../SECURITY.md#security-model)
> lo dichiara già in una riga («espone su Internet **solo** il gateway, porta 443 via
> Tailscale Funnel / Caddy / Cloudflared»), ma non stava *qui*, dove l'ingress si sceglie.
>
> Il punto è **`tailscale`**, perché il nome evoca una rete privata e il profilo non lo è:
> `setup.sh` propone «1) Tailscale Funnel (consigliato)» **ed è il default**, e `deploy.sh`
> esegue `tailscale serve reset` seguito da `tailscale funnel --bg --https=443
> http://127.0.0.1:8080`. **Scegliere `tailscale` attiva il Funnel**, e il servizio esce su
> `*.ts.net` per chiunque. Un tailnet-only — `serve` senza `funnel` — questo repo non lo
> installa: sulla VPS il gateway resta sul loopback (`GATEWAY_BIND=127.0.0.1`) e l'unica
> via d'ingresso è il Funnel.
>
> ⇒ **È la condizione che rende possibile la promessa del `README`** (collegare i propri
> MCP a claude.ai, Claude Code e all'app desktop): un client di terzi arriva solo su un
> ingress pubblico. E **raggiungere non è entrare** — chi arriva alla porta trova
> l'autenticazione, che è l'altra metà della domanda:
> [`SECURITY.md` § Security model](../SECURITY.md#security-model).

