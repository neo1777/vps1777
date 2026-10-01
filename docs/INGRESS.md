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

**Setup DNS-01 (certificato senza porta 80, o wildcard) — feature `caddy-dns01`**

Con HTTP-01 Let's Encrypt chiama la tua porta 80. Con DNS-01 Caddy dimostra il possesso del
dominio scrivendo un record TXT nella zona, via API del provider DNS: la porta 80 non serve
più al certificato (e diventa possibile un certificato wildcard). Il provider supportato è
**Cloudflare**: il DNS della zona deve stare lì.

È una feature dichiarata, spenta di default, e vale **solo con `INGRESS_PROFILE=ingress.caddy`**:
non è un quarto ingresso, è un altro modo di ottenere il certificato per lo stesso Caddy.

1. Fai il setup base qui sopra (record DNS, `CADDY_DOMAIN`, `CADDY_EMAIL`,
   `INGRESS_PROFILE=ingress.caddy`).
2. Crea un **token API** Cloudflare (dash.cloudflare.com → My Profile → API Tokens →
   Create Token) con i permessi **Zone · Zone · Read** e **Zone · DNS · Edit**, ristretto
   alla zona del tuo dominio (*Zone Resources → Include → Specific zone*). I due permessi li
   chiede il plugin (README di `caddy-dns/cloudflare` v0.2.4): `Read` per trovare la zona,
   `Edit` per scrivere il TXT. Puoi dargli una scadenza (*TTL*) dalla stessa pagina.
3. Sulla VPS, nella cartella del repo:
   ```bash
   install -m 600 /dev/null secrets/cf_api_token.txt   # file vuoto, già 600
   nano secrets/cf_api_token.txt                       # incolla il token, una riga
   ```
   Il file è dell'utente che fa girare lo stack (UID 1000, come gli altri segreti: vedi
   [SECRETS.md](SECRETS.md)).
4. Aggiungi `caddy-dns01` a `VPS1777_FEATURES` nel `.env`, tenendo le feature che hai già:
   ```
   VPS1777_FEATURES=backup,autoupdate,caddy-dns01
   ```
5. Applica subito (come per gli altri overlay, [OPS.md](OPS.md): nessun comando lo fa al
   posto tuo, e `vps1777 update` a versione già corrente non tocca lo stack):
   ```bash
   docker compose -f compose.yaml -f compose.ingress.caddy.yaml -f compose.ops.backup.yaml \
     -f compose.ops.caddy-dns01.yaml --profile ingress.caddy --profile ops.backup \
     up -d --force-recreate caddy
   ```
   Da lì in poi update e rollback montano l'overlay da soli, leggendo la riga del `.env`.
   L'immagine `vps1777-caddy-dns01` esce dalla release come le altre (firmata, nel lock):
   serve una versione di vps1777 che la contenga.

**Cosa fa.** L'overlay `compose.ops.caddy-dns01.yaml` ridefinisce il servizio `caddy`: usa
l'immagine `vps1777-caddy-dns01` (Caddy 2.11 + plugin Cloudflare, `services/caddy-dns01/`),
monta `ingress/Caddyfile.dns01` al posto di `ingress/Caddyfile` — la stessa configurazione
più `acme_dns cloudflare {file./run/secrets/cf_api_token}` — e il token come secret. Caddy
lo legge **dal file**: non passa mai da una variabile d'ambiente, che `docker inspect`
mostrerebbe. Porte, rete e volume dei certificati restano quelli dell'ingresso Caddy.

**La prova.**
```bash
docker logs vps1777-caddy 2>&1 | grep -iE 'dns|certificate obtained|error'
```
Al primo avvio cerca `certificate obtained successfully` per il tuo dominio. Se il token
manca o non è leggibile, Caddy **non parte**: nei log trovi `placeholder: failed to read
file` seguito da `API token '' appears invalid` — un rosso esplicito, non un Caddy acceso
senza certificato.

**Con un altro ingresso la CLI rifiuta.** Se `VPS1777_FEATURES` contiene `caddy-dns01` e
`INGRESS_PROFILE` non è `ingress.caddy`, ogni comando di `vps1777` che costruisce il compose
(update, rollback, status…) si ferma e dice perché: una riga del `.env` che dichiara un
certificato via DNS-01 che non esiste è il difetto che le feature dichiarate esistono per
impedire. Gli installer, che lavorano su uno stack che sta nascendo, invece **avvisano** e
proseguono senza l'overlay; e se il token sulla VPS non c'è ancora, avviano Caddy in HTTP-01
e lo dicono.

**Per tornare a HTTP-01**: togli `caddy-dns01` dal `.env` e ricrea caddy col comando del
setup base più `--force-recreate caddy`. I certificati già emessi restano nel volume e Caddy
li rinnova con la sfida HTTP-01 (che vuole la porta 80 aperta).

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
| Porte aperte | nessuna | 80 + 443 (con `caddy-dns01` il certificato non ha bisogno della 80) | nessuna |
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

