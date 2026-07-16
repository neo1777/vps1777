# Architettura — vps1777

## Tre cuori

```
┌────────── INGRESS (1 a scelta) ──────────┐
│  Tailscale Funnel | Caddy | Cloudflared  │
└─────────────────┬────────────────────────┘
                  ▼  (HTTPS pubblico → :8080 nel container)
┌──────────────── GATEWAY (core stabile) ──────────────┐
│  - OAuth 2.1 + DCR + PKCE                            │
│  - /admin/*: login, logout, setup, secrets, nlm,     │
│              audit, archive, update                  │
│  - /app/* (Mini App Telegram)                        │
│  - Reverse proxy: /<SECRET>/<name>/<path>            │
│  - Plugin registry: legge GATEWAY_UPSTREAMS da env   │
└─────────────────┬────────────────────────────────────┘
                  ▼  (rete backend, internal: true)
┌─── archive-mcp ──┬── nb1777-mcp ──┬── nb1777-bot ──┬─── PLUGIN ───┐
│  FTS5 multi-DB   │ nlm + Chromium │ Telegram poll  │  your MCP    │
│  :8002 /mcp      │ :8003 /mcp     │ no porta       │  your bot    │
└──────────────────┴────────────────┴────────────────┴──────────────┘
```

## Rete

| Rete | Driver | `internal` | Servizi connessi |
|---|---|---|---|
| `backend` | bridge | ✅ true | tutti i servizi (comunicazione interna) |
| `ingress` | bridge | ❌ false | **solo** gateway + proxy d'ingresso (caddy/cloudflared) |
| `egress` | bridge | ❌ false | nb1777-mcp, bot — escono su Internet, **fuori** da `ingress` |

Tre reti, tre ruoli distinti (H25):
- **`backend`** è `internal: true` → world-isolated: chi sta solo qui (`archive-mcp`) non può esfiltrare nulla.
- **`ingress`** ospita **solo** il servizio esposto (gateway) e il proxy che lo pubblica. Nient'altro.
- **`egress`** dà l'uscita a Internet ai backend che ne hanno bisogno (`nb1777-mcp` → NotebookLM, `bot` → Telegram) **separandoli** dalla rete d'ingresso: un proxy d'ingresso compromesso non si trova sulla stessa rete di questi servizi. È un bridge senza porte pubblicate → consente l'uscita (NAT), non l'ingresso.

## Volumi persistenti

| Volume | Path container | Contenuto |
|---|---|---|
| `gateway-data` | `/var/lib/gateway` | audit log, audit.jsonl |
| `archive-data` | `/var/lib/archive` | `data/` (sources) + `db/` (SQLite FTS5) |
| `nlm-auth` | `/var/lib/nlm` | profilo NotebookLM `profiles/default/` + `AUTH_PENDING.flag` |
| Tailscale (host) | `/var/lib/tailscale` sull'**host** | stato del nodo (non in container; vedi INGRESS.md) |
| `caddy-data` (se Caddy) | `/data` | certificati ACME |
| `cf-data` (se CF) | (nessuno) | token cred ephemeral |

## Secrets

Vedi [SECRETS.md](SECRETS.md). Tutti file-mounted in `/run/secrets/<name>` (tmpfs RO). Niente env var per cose sensibili.

## Contratti tra servizi

| Caller → Callee | Protocollo | Path |
|---|---|---|
| Internet → gateway | HTTPS (ingress) | `/<SECRET>/<name>/mcp` |
| gateway → MCP servers | HTTP loopback container | `http://<service>:<port>/mcp` |
| gateway → nb1777-mcp (profilo nlm) | HTTP interno + segreto condiviso | `/internal/nlm/{status,profile}` |
| bot → nb1777-mcp (notifiche #30) | HTTP interno + segreto condiviso | `/internal/{notifications,canonico/ack}` |
| nb1777-bot → nb1777-mcp | MCP client HTTP | `http://nb1777-mcp:8003/mcp` |
| Telegram cloud → bot | long-poll outbound HTTPS | `api.telegram.org` |
| claude.ai → gateway | OAuth 2.1 + MCP streamable-http | `/<SECRET>/<name>/mcp` |

## Plugin pattern

Vedi [PLUGINS.md](PLUGINS.md). In sintesi:

1. Crei `plugins/<nome>/` con `Dockerfile` + `compose.<nome>.yaml`
2. Esponi un endpoint MCP su porta interna (es. `8004`)
3. Aggiungi a `.env`: `GATEWAY_UPSTREAMS=archive=archive-mcp:8002,nb1777=nb1777-mcp:8003,<nome>=<container>:8004`
4. Restart gateway: `docker compose restart gateway`
5. URL del tuo plugin: `<PUBLIC_BASE>/<SECRET>/<nome>/mcp`

## Canale di aggiornamento

Il motore degli update vive **sull'host**, non nei container: la CLI
`/usr/local/bin/vps1777` (installata da `deploy.sh`, nella radice del repo) è l'unico punto
che tocca immagini e stack. Il gateway resta **senza privilegi**: il pulsante
*Aggiorna* del pannello admin scrive solo un **intent file** in `onboarding/`
(validato: schema, semver, TTL, nonce anti-replay); una systemd **path unit**
(`vps1777-update.path` → `vps1777-update.service`) lo vede e lancia lo stesso
`vps1777 update`. Un timer giornaliero (`vps1777-check-update.timer`) fa il
check release + notifica Telegram al owner.

```
admin UI ──intent──► onboarding/update_pending_update.json
                        │  (systemd path unit, host)
                        ▼
   vps1777 update ──► backup age + snapshot locale
                  ──► pull + verifica digest (images.lock dal
                      bundle firmato cosign della GitHub Release)
                  ──► migrazioni ──► health-gate 180s
                  ──► ✅ ok  │  AUTO-ROLLBACK
```

La verifica della firma **cosign** del bundle è **obbligatoria (fail-closed) di
default** dalla v0.23.0: se cosign manca e non è installabile, l'update si ferma
invece di procedere — la sola via d'emergenza *consapevole* è impostare
`VPS1777_REQUIRE_COSIGN=0` nel `.env`.

Le immagini arrivano **solo da GHCR** (`compose.yaml` è pull-only; il build
locale esiste solo nell'overlay `compose.build.yaml`, dev/CI). Manuale utente
completo: [UPDATE.md](UPDATE.md).

## Healthcheck

Ogni servizio ha un healthcheck compose (usati anche dal health-gate dell'update):

| Servizio | Probe |
|---|---|
| gateway | `/health` → body pubblico minimo `{"ok":true}`. Con `?deep=1` proba TCP gli upstream MCP (503 se giù), ma è **riservato ai chiamanti interni**: da fuori risponde 403 (H33). L'updater lo chiama via `compose exec` *dentro* il gateway, quindi da loopback. |
| archive-mcp / nb1777-mcp | TCP sulla porta MCP |
| nb1777-bot | long-poll, nessuna porta: file heartbeat `/tmp/nb1777-bot.heartbeat` (unhealthy se mtime > 90s) |

## OAuth flow

```
claude.ai                     gateway                    user browser
   │                            │                            │
   │ POST /register             │                            │
   │ (Dynamic Client Reg)       │                            │
   │ ◄──────────── client_id ───┤                            │
   │ POST /authorize ───────────┼──── 302 → /admin/login ───►│
   │                            │ ◄────── email+pwd ─────────│
   │                            │  bcrypt verify ↓           │
   │                            │  set admin_cookie          │
   │                            ├──── 302 → consent page ───►│
   │                            │ ◄────── approve ───────────│
   │                            │  emit access+refresh JWT   │
   │ ◄─── 302 + code ───────────┤                            │
   │ POST /token                │                            │
   │ ◄─── access + refresh ─────│                            │
   │ GET /<SECRET>/archive/mcp  │                            │
   │       Bearer <access> ─────►│                            │
   │       verify JWT typ=access │                            │
   │       proxy → archive-mcp:8002                          │
```

JWT typ è la chiave: `access_token` non funziona dove serve `admin_cookie` e viceversa. Vedi [SECURITY.md](../SECURITY.md).

## Modello di sicurezza

La postura è **fail-closed**: in assenza di configurazione il gateway nega, non
apre. Segue la sintesi degli hardening della review difensiva (luglio 2026,
`v0.19.1 → v0.33.0`, dossier chiuso: **35 chiusi · 7 parziali · 1 accettato · 0
aperti**); il dettaglio operativo sta in [SECURITY.md](../SECURITY.md), che è la
fonte di verità — qui c'è la sintesi, là il registro che la CI verifica.

### Baseline (dall'inizio)

- Backend su rete `internal: true` — world-isolated. *(Vero per tutti all'inizio;
  dalla v0.33.0 `nb1777-mcp` e il bot hanno un'uscita dedicata sulla rete `egress`
  — vedi **Rete** sopra. Chi resta solo su `backend`, come `archive-mcp`, non può
  esfiltrare nulla: è quello il punto, e per lui vale ancora alla lettera.)*
- OAuth 2.1 + DCR + PKCE; JWT con `typ` separati (`access` ≠ `admin_cookie` ≠ miniapp).
- `GATEWAY_SECRET` come path-namespace del proxy MCP.
- Container non-root, `cap_drop: ALL`, `no-new-privileges`.
- Gateway **senza** `docker.sock` né secret dell'host; immagini pinnate a digest (`images.lock`).

### Hardening (v0.22.0 → v0.33.0)

| Versione | Hardening |
|---|---|
| v0.22.0 | **Owner-gating fail-closed**: senza `TELEGRAM_OWNER_ID` la Mini App e il bot negano TUTTI (`/app/auth` → 503, `is_owner` → False). |
| v0.23.0 | **cosign REQUIRED di default** sul self-update (vedi *Canale di aggiornamento*); escape consapevole `VPS1777_REQUIRE_COSIGN=0`. |
| v0.24.0 | `GATEWAY_SECRET` redatto dagli access-log (redazione installata prima di servire la prima richiesta). |
| v0.25.0 | **Rate-limit per-IP** sugli endpoint auth: `/register` 10/5min, `/token` 60/min, `/app/auth` 20/5min. Il proxy MCP verifica l'**audience**: il `sub` dell'access token deve essere in `OAUTH_ALLOWED_EMAILS`, altrimenti rifiuta (401 `subject_not_allowed`). |
| v0.26.0 | **La chiave di backup fuori dalla VPS** (`age`): niente auto-keygen sul server — la privata nasce e resta sul PC, il container di backup cifra con la sola pubblica. Una chiave privata sullo stesso disco dei backup non protegge da nulla. |
| v0.27.0 | **Supply-chain della CI**: GitHub Action pinnate a **SHA pieno** (non più tag mobili — `trivy-action@master` era il caso peggiore), Dependabot perché il pin non invecchi, permessi least-privilege per-job, immagini di terzi pinnate a digest. |
| v0.28.0 | **`forwarded_allow_ips` ristretto** — vedi sotto. |
| v0.29.0 | Container di **backup senza `docker.sock`**: volumi montati diretti `:ro`. Segreti fuori dall'argv nel deploy. |
| v0.30.0 | **Il gateway non tocca i cookie Google**: `nlm-auth` lo monta solo nb1777-mcp; gateway e bot ad accesso-zero, via canale interno. Il proxy rifiuta i sotto-path `internal/`. |
| v0.31.0 | **Il registro dei rilievi**: `security/findings.yml` (43 rilievi, ognuno con evidenza ancorata al *contenuto* e non al numero di riga) + `security/check_findings.py` in CI. «Dichiarato fatto ma assente» diventa una build rossa: un claim di sicurezza senza coordinate non può marcire rumorosamente. |
| v0.32.0 | Revoca **reale** della sessione admin (`jti` + revoke-list: prima il logout cancellava solo il cookie, H20); cookie Google fuori dallo snapshot pre-update (H14); tetti sul **decompresso** (H39); **open-redirect** H30 dato per chiuso e invece bypassabile (`startswith` è un match di *prefisso*, non di *origine*) → chiuso davvero con 12 test d'attacco; **tag `v*` immutabili** (H24). |
| v0.33.0 | **Pagina di consenso OAuth** vera (H8); **rete `egress` separata** (H25); CORS scoped ai soli OAuth+`/app`, `/health` con body minimo e `?deep` interno-only, CSP globale `default-src 'none'` (H31/H33/H34/H36); PKCE constant-time (H32); rootfs `read_only` su gateway/archive-mcp/bot (H43). Dossier chiuso: **0 rilievi aperti**. |

> Le versioni successive (v0.34.0 → v0.36.0) non sono hardening: sono le funzioni
> nb1777 (fix studio, canonico, `memoria_check`) — vedi [NB1777.md](NB1777.md).
> Lo stato `accepted` nel registro (v0.33.0) è la terza casella accanto a
> `closed`/`open`: un rischio **deciso di non chiudere** non è né fatto né
> dimenticato, e il gate pretende che porti la sua motivazione. Il primo è il
> no-2FA (H28).

### IP client e header proxy (v0.28.0)

uvicorn gira con `proxy_headers=True` ma `forwarded_allow_ips` **ristretto** a
`GATEWAY_FORWARDED_ALLOW_IPS` (default
`127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16`), non più `*`.
L'`X-Forwarded-For` è fidato SOLO dai range privati + loopback: il reverse-proxy
(Tailscale/Caddy/Cloudflared) arriva sempre da una bridge Docker privata
(es. `172.21.0.1`), MAI da un IP pubblico. uvicorn cammina l'XFF da **destra** e
prende il primo host non fidato, quindi un `X-Forwarded-For` iniettato da un
client pubblico viene scartato. Conseguenza: l'IP client non è più spoofabile e
rate-limit, lockout e audit non sono più evadibili.

### Il profilo NotebookLM e il canale interno (v0.30.0)

I cookie di sessione Google (volume `nlm-auth`) li monta **solo `nb1777-mcp`** —
il servizio che li usa. Il gateway (l'unico esposto su Internet) e il bot hanno
**accesso zero**: chiedono a lui.

```
gateway (esposto) ──┐
                    ├─ HTTP interno + segreto condiviso ─► nb1777-mcp ─► [ nlm-auth ]
bot               ──┘   X-Vps1777-Internal (constant-time)   (unico mount)
```

| Endpoint (solo rete `backend`) | Chi chiama | Cosa fa |
|---|---|---|
| `GET /internal/nlm/status` | gateway | dice **se** c'è un profilo valido (`{ok, has_cookies, pending}`) — mai il contenuto |
| `POST /internal/nlm/profile` | gateway | riceve il tar.gz, **valida**, installa (staging → swap con rollback) |
| `GET /internal/notifications` | bot | preleva la coda notifiche (drift memoria + promemoria canonico, v0.36.0) |
| `POST /internal/canonico/ack` | bot | registra l'ack del bottone «✓ Fatto» (v0.36.0) |

Senza `gateway_secret` configurato → **403**: fail-closed anche qui. Il dettaglio
dei due endpoint memoria e del perché esistono sta in [NB1777.md](NB1777.md) §6-§7.

Due proprietà da non perdere di vista se tocchi questa zona:

- **`internal/` non si attraversa.** Il reverse proxy MCP è un catch-all su
  `{path:path}`: senza un blocco esplicito, quegli endpoint sarebbero raggiungibili
  da Internet via `/<SECRET>/<service>/internal/…`. `proxy.py` rifiuta ogni
  sotto-path `internal/` con 404 **prima di ogni altro controllo** (secret, bearer),
  per **tutti** gli upstream. È un **prefisso riservato**: un plugin può usarlo per
  i propri endpoint privati sapendo che il proxy non li espone. Vedi [PLUGINS.md](PLUGINS.md).
- **L'upload è non distruttivo.** Il tar si estrae in staging, si valida, e solo
  allora sostituisce il profilo buono: un file sbagliato non ti scollega da
  NotebookLM.
