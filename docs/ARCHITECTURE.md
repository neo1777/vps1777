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
┌─ archive-mcp ─┬─ nb1777-mcp ──┬─ nb1777-bot ──┬─ ocr ────────┬─ PLUGIN ──┐
│ FTS5 multi-DB │ nlm (CLI)     │ Telegram poll │ immagini →   │ il tuo MCP│
│ + vettori     │ senza browser │ nessuna porta │ testo        │ o bot     │
│ :8002 /mcp    │ :8003 /mcp    │               │ :8004 /ocr   │ :8010…    │
└───────────────┴───────────────┴───────────────┴──────────────┴───────────┘
```

## Rete

| Rete | Driver | `internal` | Servizi connessi |
|---|---|---|---|
| `backend` | bridge | ✅ true | tutti i servizi (comunicazione interna), tranne il job `indice-notturno`, che non ha rete |
| `ingress` | bridge | ❌ false | **solo** il proxy d'ingresso (caddy/cloudflared) e, col suo profilo, il gateway |
| `egress` | bridge | ❌ false | nb1777-mcp, bot — escono su Internet, **fuori** da `ingress` |
| `funnel` | bridge senza masquerade | ❌ false | solo col profilo Tailscale: il gateway. Ingresso sì, uscita no (H50) |

In `compose.yaml` il gateway sta **solo** su `backend` (H50): dichiarargli `ingress` gli
dava un'uscita NAT verso qualunque host, misurata sul vivo il 26/07. La rete d'ingresso
gliela ridà l'overlay del profilo scelto (`compose.ingress.caddy.yaml`,
`compose.ingress.cloudflared.yaml`); col profilo Tailscale il gateway pubblica una porta
sul loopback dell'host e sta sulla rete `funnel`, che accetta connessioni in entrata e non
fa uscire niente.

Tre reti base, tre ruoli distinti (H25):
- **`backend`** è `internal: true` → world-isolated: chi sta solo qui (`archive-mcp`) non può esfiltrare nulla.
- **`ingress`** ospita **solo** il proxy che pubblica il gateway e, col profilo caddy o cloudflared, il gateway stesso. Nient'altro.
- **`egress`** dà l'uscita a Internet ai backend che ne hanno bisogno (`nb1777-mcp` → NotebookLM, `bot` → Telegram) **separandoli** dalla rete d'ingresso: un proxy d'ingresso compromesso non si trova sulla stessa rete di questi servizi. È un bridge senza porte pubblicate → consente l'uscita (NAT), non l'ingresso.

## Volumi persistenti

| Volume | Path container | Contenuto |
|---|---|---|
| `gateway-data` | `/var/lib/gateway` | audit log, audit.jsonl |
| `archive-data` | `/var/lib/archive` | `data/` (sources) + `db/` (SQLite FTS5: i messaggi e, dai bundle di Recupero Sessioni, le tabelle `sessioni`/`archi`/`memorie` — vedi [ARCHIVE.md](ARCHIVE.md)) + `models/` e gli indici `<db>.vec.db` della ricerca per senso ([RICERCA-IBRIDA.md](RICERCA-IBRIDA.md)). Lo scrivono il gateway (ingest) e il job `indice-notturno` (gli indici); `archive-mcp` lo monta in sola lettura |
| `nlm-auth` | `/var/lib/nlm` | profilo NotebookLM `profiles/default/` + `AUTH_PENDING.flag` |
| `nlm-artifacts` | `/var/lib/nlm-artifacts` | gli artefatti Studio scaricati da nb1777-mcp e i file in transito di `archive-ingest`. Niente segreti |
| `gateway-uploads` | `/var/lib/uploads` | lo spool degli upload del gateway (`TMPDIR`): su disco e non nella tmpfs `/tmp`, che un bundle da 2,6 GB saturava |
| Tailscale (host) | `/var/lib/tailscale` sull'**host** | stato del nodo (non in container; vedi INGRESS.md) |
| `caddy-data`, `caddy-config` (se Caddy) | `/data`, `/config` | certificati ACME e configurazione di Caddy |
| `portainer-data` (profilo opt-in) | `/data` | stato di Portainer |

Cloudflared non ha volumi: il token del tunnel è il secret `cloudflared_token`.

## Secrets

Vedi [SECRETS.md](SECRETS.md). Tutti file-mounted in `/run/secrets/<name>`: con Docker
Compose (non Swarm) un secret `file:` è un bind-mount in sola lettura del file sull'host,
non una tmpfs. Niente env var per cose sensibili. Ogni servizio vede solo i suoi: il
gateway ne ha cinque (`gateway_secret`, `oauth_signing_secret`, `admin_password_bcrypt`,
`telegram_webapp_secret`, `archive_desc_secret`), e il token del bot Telegram lo monta
solo `nb1777-bot`.

## Contratti tra servizi

| Caller → Callee | Protocollo | Path |
|---|---|---|
| Internet → gateway | HTTPS (ingress) | `/<SECRET>/<name>/mcp` |
| gateway → MCP servers | HTTP sulla rete `backend` | `http://<service>:<port>/mcp` |
| gateway → nb1777-mcp (profilo nlm, artefatti Studio) | HTTP interno + segreto condiviso | `/internal/nlm/{status,profile,artifacts,artifact}` |
| bot → nb1777-mcp (stato del profilo) | HTTP interno + segreto condiviso | `/internal/nlm/status` |
| bot → nb1777-mcp (notifiche #30) | HTTP interno + segreto condiviso | `/internal/{notifications,canonico/ack}` |
| nb1777-bot → nb1777-mcp | MCP client HTTP | `http://nb1777-mcp:8003/mcp` |
| archive-mcp → gateway (scheda del DB: `set_description`, `set_ruolo`) | HTTP interno + segreto condiviso | `/internal/archive/{description,ruolo}` — le uniche scritture di archive-mcp, che ha il volume in sola lettura |
| gateway → ocr (ingest immagini) | HTTP interno, bytes→testo | `http://ocr:8004/ocr` (env `OCR_URL`; il gateway NON esegue processi — presidio `test_gateway_non_tocca_docker`) |
| Telegram cloud → bot | long-poll outbound HTTPS | `api.telegram.org` |
| claude.ai → gateway | OAuth 2.1 + MCP streamable-http | `/<SECRET>/<name>/mcp` |

## Plugin pattern

Vedi [PLUGINS.md](PLUGINS.md). In sintesi:

1. Crei `plugins/<nome>/` con `Dockerfile` + `compose.<nome>.yaml`
2. Esponi un endpoint MCP su porta interna (es. `8010` — 8002/8003/8004 sono dei servizi base)
3. Aggiungi a `.env`: `GATEWAY_UPSTREAMS=archive=archive-mcp:8002,nb1777=nb1777-mcp:8003,<nome>=<container>:8010`
4. Ricrea il gateway: `docker compose up -d gateway` (`restart` non rilegge `.env`, e il nuovo `GATEWAY_UPSTREAMS` non entrerebbe)
5. URL del tuo plugin: `<PUBLIC_BASE>/<SECRET>/<nome>/mcp`

## Canale di aggiornamento

Il motore degli update vive **sull'host**, non nei container: la CLI
`/usr/local/bin/vps1777` (installata da `deploy.sh`, nella radice del repo) è l'unico punto
che tocca immagini e stack. Il gateway resta **senza privilegi**: il pulsante
*Aggiorna* del pannello admin scrive solo un **intent file** in `onboarding/`
(validato: schema, semver, TTL, nonce anti-replay); una systemd **path unit**
(`vps1777-update.path` → `vps1777-update.service`) lo vede e lancia lo stesso
`vps1777 update`. Un timer giornaliero (`vps1777-check-update.timer`) fa il
check release + notifica Telegram al owner. Un secondo timer giornaliero
(`vps1777-auto-update.timer`) installa da solo l'ultima release, ma solo quando è
pubblicata da almeno 48 ore (`vps1777 auto-update --eta-minima 48`): una release
sbagliata ha due giorni per essere ritirata prima di arrivare. Un terzo
(`vps1777-secrets-check.timer`) controlla le scadenze dei segreti.

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
locale esiste solo nell'overlay `compose.build.yaml`, dev/CI). Dopo un update il `.env`
porta, accanto al tag, il digest di ogni immagine (`VPS1777_DIGEST_<SERVIZIO>`, H22):
anche un `docker compose up` fatto a mano gira le immagini verificate. Un'installazione
nuova non li ha fino al primo update. Manuale utente
completo: [UPDATE.md](UPDATE.md).

## Healthcheck

Ogni servizio ha un healthcheck compose (usati anche dal health-gate dell'update):

| Servizio | Probe |
|---|---|
| gateway | `/health` → body pubblico minimo `{"ok":true}`. Con `?deep=1` proba TCP gli upstream MCP (503 se giù), ma è **riservato ai chiamanti interni**: da fuori risponde 403 (H33). L'updater lo chiama via `compose exec` *dentro* il gateway, quindi da loopback. |
| archive-mcp / nb1777-mcp | HTTP `GET /health` (dalla `v0.45.0`; prima era un TCP-connect, che dichiarava sano un processo con la porta aperta e l'app rotta). La sonda prova il mestiere — registry dei DB per archive, volume dati per nb1777 — mai NotebookLM; espone anche `mcp_sdk` e `mcp_protocol_max`, così «quale revisione MCP parla il gateway?» ha una risposta osservabile. |
| ocr | HTTP `GET /health` interno |
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
apre — provato sul caso più semplice (nessun `gateway_secret` → il proxy nega
tutto) da `services/gateway/tests/test_fail_closed_senza_config.py`. Segue la sintesi degli hardening: prima la review difensiva (luglio 2026,
`v0.19.1 → v0.33.0`, che alla chiusura del dossier contava **35 chiusi · 7 parziali ·
1 accettato · 0 aperti** su 43), poi quello che è venuto dopo. Oggi il registro ha
74 rilievi: 63 chiusi, 8 parziali, 3 accettati, 0 aperti. Il dettaglio operativo sta in
[SECURITY.md](../SECURITY.md), che è la fonte di verità — qui c'è la sintesi, là il
registro che la CI verifica.

### Baseline (dall'inizio)

- Backend su rete `internal: true` — world-isolated. *(Vero per tutti all'inizio;
  dalla v0.33.0 `nb1777-mcp` e il bot hanno un'uscita dedicata sulla rete `egress`
  — vedi **Rete** sopra. Chi resta solo su `backend`, come `archive-mcp`, non può
  esfiltrare nulla: è quello il punto, e per lui vale ancora alla lettera.)*
- OAuth 2.1 + DCR + PKCE; JWT con `typ` separati (`access` ≠ `admin_cookie` ≠ miniapp).
- `GATEWAY_SECRET` come path-namespace del proxy MCP.
- Servizi dello stack non-root, `cap_drop: ALL`, `no-new-privileges`. Gli overlay
  operativi fanno eccezione e lo dichiarano: `backup` e `watchtower` girano senza
  queste opzioni, `portainer` ha solo `no-new-privileges` (e il socket Docker: è
  accesso root all'host, per questo è un profilo opt-in su loopback).
- Gateway **senza** `docker.sock`; dell'host vede solo la cartella `onboarding/`
  (bind-mount, dove passano intent e stato dell'update). Vede i
  5 secret Docker a lui assegnati: non il token del bot, ma la chiave derivata `telegram_webapp_secret`
  (H54): compromesso il gateway, si può forgiare l'`initData` della Mini App, non
  parlare col bot — vedi `SECRETS.md`. Immagini pinnate a digest (`images.lock`).

### Hardening della review difensiva (v0.22.0 → v0.33.0)

Questa tabella è la storia del dossier di luglio: ogni riga dice cosa è entrato in
quella versione, non lo stato di oggi (per quello, la tabella dopo e SECURITY.md).

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
| v0.30.0 | **Il gateway non tocca i cookie Google**: `nlm-auth` in esercizio lo monta solo nb1777-mcp (rw); in sola lettura il backup (archivio cifrato) e il check scadenze (busybox senza rete, solo mtime); gateway e bot ad accesso-zero, via canale interno. Il proxy rifiuta i sotto-path `internal/`. |
| v0.31.0 | **Il registro dei rilievi**: `security/findings.yml` (43 rilievi, ognuno con evidenza ancorata al *contenuto* e non al numero di riga) + `security/check_findings.py` in CI. «Dichiarato fatto ma assente» diventa una build rossa: un claim di sicurezza senza coordinate non può marcire rumorosamente. |
| v0.32.0 | Revoca **reale** della sessione admin (`jti` + revoke-list: prima il logout cancellava solo il cookie, H20); cookie Google fuori dallo snapshot pre-update (H14); tetti sul **decompresso** (H39); **open-redirect** H30 dato per chiuso e invece bypassabile (`startswith` è un match di *prefisso*, non di *origine*) → chiuso davvero con 12 test d'attacco; **tag `v*` immutabili** (H24). |
| v0.33.0 | **Pagina di consenso OAuth** vera (H8); **rete `egress` separata** (H25); CORS scoped ai soli OAuth+`/app`, `/health` con body minimo e `?deep` interno-only, CSP globale `default-src 'none'` (H31/H33/H34/H36); PKCE constant-time (H32); rootfs `read_only` su gateway/archive-mcp/bot (H43). Dossier chiuso: **0 rilievi aperti**. |

### Dopo il dossier (v0.34.0 → oggi)

| Versione | Hardening |
|---|---|
| v0.40.x | Il gateway **perde l'uscita Internet** (H50, misurata sul vivo); il gateway non monta più il token del bot (H54, chiuso del tutto con la #61); nessun servizio pubblica porte in `compose.yaml` (H48); Portainer solo su loopback e opt-in (H47); hardening dell'host in tutti e tre gli installer (H45); ritenzione dei backup contata in giorni (H57-H59). |
| v0.43.1 | Quattro garanzie vere ma non presidiate diventano test (action pinnate a SHA H65, immagini di terzi a digest H66, gateway senza Docker H67, segreti solo come file H68); l'anagrafica dell'account esce redatta dai tool dell'archivio (H64). |
| v0.58.0 | Rootfs `read_only` anche su nb1777-mcp: ora su **tutti** i servizi (H43); **quarantena di 48 ore** dell'auto-update; H24 (protezione dei tag) diventa **rischio accettato** fino al 27/12/2026. |
| v0.59.0 | I **digest** delle immagini nel `.env` e nel compose (H22, parziale: un'installazione nuova li ha dal primo update). |
| v0.61.x | nb1777-mcp **senza Chromium** (902 → 221 MB); immagini base dei Dockerfile pinnate a digest; permessi dei workflow dentro i job; **release immutabili** su GitHub. |
| v0.62.x | **CI obbligatoria su main** (9 controlli, anche per gli amministratori); la redazione dell'archivio copre le credenziali in formato riconoscibile e il percorso dei tunnel trycloudflare, anche dentro gli evidenziatori dello snippet. |

> Le versioni v0.34.0 → v0.36.0 sono le funzioni nb1777 (fix studio, canonico,
> `memoria_check`; da v0.44.0 il canonico è un file del prodotto e `canonico(full=true)`
> ne serve il testo, `memoria_ack` registra l'ack) — vedi [NB1777.md](NB1777.md) e
> [MEMORIA-1777.md](MEMORIA-1777.md).
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

> **Su cosa poggia questa garanzia — le due gambe, e una non è nostra.**
> ① *la trust-list non è `*`* — è nostra, sta in `settings.py`, ed è presidiata da
> `services/gateway/tests/test_xff_trust_list.py`.
> ② *«uvicorn cammina l'XFF da destra»* — **non è nostro**: è il comportamento di
> `ProxyHeadersMiddleware`, e **è storicamente cambiato** (versioni più vecchie
> prendevano il primo elemento **da sinistra**, cioè la parte che un client può
> iniettare). Il vincolo in `services/gateway/pyproject.toml` è `>=`, aperto verso
> l'alto, e `uvicorn` è `0.x`: anche un minor può cambiare comportamento.
> ⇒ *La conseguenza scritta sopra vale finché ② regge.*
> ✅ **E dal 09/08 ② è presidiata anche lei** — `services/gateway/tests_runtime/`
> `test_gamba2_xff_da_destra.py`, che ESEGUE `ProxyHeadersMiddleware` con la trust-list
> letta da `settings.py` e verifica che l'XFF iniettato non vinca. *Qui c'era scritto
> «un test non può verificarlo: la suite del gateway gira senza le dipendenze del
> gateway»: era vero per QUELLA suite (`uvx pytest`, solo stdlib), non per il problema.
> La via era girare dove le dipendenze ci sono* — job dedicato in `ci.yml` con
> `uv sync --frozen`, così si misura la `uvicorn` che l'immagine installa davvero e non
> una presa a parte. Chiude la voce di registro `39b5a89d`.
> ⚠️ *Il test misura il COMPORTAMENTO, non ratifica la VERSIONE: il vincolo resta `>=`
> e le major continuano a entrare senza che nessuno le decida (`starlette>=0.45.0` era
> arrivata a 1.3.1 attraversando la 1.0 in silenzio; oggi il vincolo è `>=1.6.0`). Se un giorno l'IP client torna
> spoofabile, ora te lo dice la CI; se cambia il regime di versione di una dipendenza,
> **no** — quella resta una decisione da prendere a mano.*

### Il profilo NotebookLM e il canale interno (v0.30.0)

I cookie di sessione Google (volume `nlm-auth`): fra i servizi in esercizio lo
monta **solo `nb1777-mcp`** (rw), quello che li usa. Fuori dai servizi lo montano
in **sola lettura** due lavori a tempo: il **backup** (container `backup`, feature
attiva di default, o `tools/backup.sh` sull'host) che lo mette nell'archivio
cifrato con la chiave pubblica `age` — ed è il motivo per cui `nlm-auth` è escluso
dallo snapshot pre-update, che non è cifrato — e il **check scadenze**
(`vps1777 secrets-status`), che in un `busybox --network none` legge solo l'mtime
del file dei cookie. Il gateway (l'unico esposto su Internet) e il bot hanno
**accesso zero**: chiedono a lui.

```
gateway (esposto) ──┐
                    ├─ HTTP interno + segreto condiviso ─► nb1777-mcp ─► [ nlm-auth ]
bot               ──┘   X-Vps1777-Internal (constant-time)   (unico mount)
```

| Endpoint (solo rete `backend`) | Chi chiama | Cosa fa |
|---|---|---|
| `GET /internal/nlm/status` | gateway, bot | dice **se** c'è un profilo valido (`{ok, has_cookies, pending}`) — mai il contenuto |
| `POST /internal/nlm/profile` | gateway | riceve il tar.gz, **valida**, installa (staging → swap con rollback) |
| `GET /internal/nlm/artifacts` | gateway | l'elenco degli artefatti Studio scaricati (`nlm-artifacts`) |
| `GET /internal/nlm/artifact?name=` | gateway | un artefatto, per `/admin/nlm/artifact/{name}` |
| `GET /internal/notifications` | bot | preleva la coda notifiche (drift memoria + promemoria canonico, v0.36.0) |
| `POST /internal/canonico/ack` | bot | registra l'ack del bottone «✓ Fatto» (v0.36.0) |

Senza `gateway_secret` configurato → **403**: fail-closed anche qui. *Questi sei
endpoint li serve `nb1777-mcp`, e la guardia è `_internal_ok` (`server.py`): «senza
segreto configurato si nega tutto».* Il dettaglio dei due endpoint memoria e del perché
esistono sta in [NB1777.md](NB1777.md) §6-§7.

> **403 qui, 404 dal proxy — e non è un'incoerenza.** Sono due porte diverse:
> *da dentro* la rete `backend`, senza segreto, `nb1777-mcp` risponde **403**
> (fail-closed dichiarato); *da fuori*, il reverse-proxy del gateway rifiuta ogni
> sotto-path `internal/` con **404**, perché un 403 confermerebbe l'esistenza della
> rotta a chi la sta cercando (`proxy.py`, e la scelta è scritta in `routes.py`:
> «ogni gradino risponde 404, non 403»). Chi legge un log deve poterli distinguere:
> un **403** dice *il segreto non torna*, un **404** dice *questa superficie, per te,
> non esiste*.

Due proprietà da non perdere di vista se tocchi questa zona:

- **`internal/` non si attraversa.** Il reverse proxy MCP è un catch-all su
  `{path:path}`: senza un blocco esplicito, quegli endpoint sarebbero raggiungibili
  da Internet via `/<SECRET>/<service>/internal/…`. `proxy.py` rifiuta ogni
  sotto-path `internal/` con 404 **prima di ogni altro controllo** (secret, bearer),
  per **tutti** gli upstream. È un **prefisso riservato**: un plugin può usarlo per
  i propri endpoint privati sapendo che il proxy non li espone. Vedi [PLUGINS.md](PLUGINS.md).
- **L'upload è non distruttivo** (il flusso staging→valida→sostituisci vive in
  `services/nb1777-mcp/app/nlm_profile.py`, `install_profile`; il gateway inoltra
  soltanto): il tar si
  estrae in staging, si valida, e solo allora sostituisce il profilo buono —
  un file sbagliato non ti scollega da NotebookLM.
