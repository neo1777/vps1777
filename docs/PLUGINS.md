# Plugin — vps1777

Come aggiungere il **tuo** MCP o bot allo stack senza toccare il core.

## Caso 1 — Aggiungere un MCP server

### Step 1: scaffold

```bash
cp -r plugins/example-mcp plugins/mio-mcp
cd plugins/mio-mcp
```

Apri `app/__main__.py`, modifica i tool. Lo scheletro è FastMCP streamable-http; legge
`PLUGIN_HOST` e `PLUGIN_PORT` (default `0.0.0.0:8010`).

### Step 2: compose

Crea `plugins/mio-mcp/compose.mio-mcp.yaml`:

```yaml
services:
  mio-mcp:
    build:
      context: ./plugins/mio-mcp
    image: vps1777/mio-mcp:${VPS1777_TAG:-dev}
    init: true
    environment:
      PLUGIN_HOST: 0.0.0.0
      PLUGIN_PORT: 8010            # scegli una porta libera ≥ 8010
      FASTMCP_STATELESS_HTTP: "true"
    networks: [backend]
    expose: ["8010"]
    restart: unless-stopped
    cap_drop: [ALL]
    security_opt:
      - no-new-privileges:true
    healthcheck:
      test: ["CMD", "python", "-c", "import socket,sys; s=socket.create_connection(('127.0.0.1',8010),timeout=3); s.close()"]
      interval: 30s
      timeout: 5s
      retries: 3
```

Il check è TCP perché lo scheletro non ha una rotta `/health`: dice solo che la porta è aperta.
Se aggiungi una rotta di salute (in FastMCP, con `@mcp.custom_route("/health", methods=["GET"])`,
come fanno `archive-mcp` e `nb1777-mcp`), puoi passare a un check HTTP che provi anche l'app.

### Step 3: registra al gateway

Edita `.env`:

```dotenv
GATEWAY_UPSTREAMS=archive=archive-mcp:8002,nb1777=nb1777-mcp:8003,mio-mcp=mio-mcp:8010
```

> **Onestà sulla fiducia.** Un plugin sulla rete `backend` gode di **fiducia piena**
> verso gli altri servizi interni: il modello di sicurezza isola i backend
> *dall'esterno* (solo il gateway è esposto), non l'uno dall'altro. Un plugin
> compromesso può parlare con `nb1777-mcp`, `archive-mcp`, ecc. sulla rete interna.
> Se il tuo plugin deve **uscire** su Internet, mettilo sulla rete `egress` (come
> `nb1777-mcp`), non su `ingress`. E se non deve uscire affatto, lascialo su
> `backend` (internal) e basta — non potrà esfiltrare nulla.

### Step 4: avvia

```bash
docker compose \
  -f compose.yaml \
  -f compose.ingress.tailscale.yaml \
  -f plugins/mio-mcp/compose.mio-mcp.yaml \
  up -d --build
```

`--build` qui builda **solo il tuo plugin** (l'unico servizio con `build:`):
il core è pull-only, le immagini vps1777 arrivano da GHCR e non si buildano
mai sulla VPS — vedi [UPDATE.md](UPDATE.md).

Il tuo MCP risponde a: `<PUBLIC_BASE>/<SECRET>/mio-mcp/mcp`.

Aggiungilo come connector su claude.ai.

> **`internal/` è un prefisso riservato — e ti serve.** Il reverse proxy inoltra
> al tuo servizio qualunque sotto-path (`/<SECRET>/mio-mcp/<qualsiasi-cosa>`),
> **tranne** quelli che iniziano per `internal/`: quelli li rifiuta con 404
> **prima** del controllo del secret e del token. Vuol dire che un endpoint
> `/internal/...` del tuo plugin **non è raggiungibile da Internet**, mai: è il
> canale privato per parlare con gli altri servizi sulla rete `backend`. È così
> che il gateway installa il profilo NotebookLM senza montarne i cookie
> (vedi [ARCHITECTURE.md](ARCHITECTURE.md)). Corollario da ricordare: **ogni
> altro path del tuo servizio è esposto** (dietro secret + OAuth) — se hai
> un'operazione che non deve uscire, mettila sotto `internal/`.

## Caso 2 — Aggiungere un bot Telegram

Stesso pattern, ma il bot **non espone porte** (è long-poll outbound).

```bash
cp -r plugins/example-bot plugins/mio-bot
# edita app/__main__.py
# crea plugins/mio-bot/compose.mio-bot.yaml senza `expose:` né `networks: ingress`
```

Il bot deve però **uscire** verso `api.telegram.org`, e la rete `backend` è `internal: true`: da lì
non si esce. Mettilo anche sulla rete `egress`, come `nb1777-bot` in `compose.yaml` e come fa già
`plugins/example-bot/compose.example-bot.yaml` (`networks: [backend, egress]`). Con il solo
`backend` il container parte ma il long-poll non raggiunge mai Telegram.

Token in `secrets/mio-bot-token.txt`, montato come `secrets: [mio_bot_token]` nel compose plugin.

## Auto-discovery (futuro)

Esiste un piano per auto-registrare i container con label `vps1777.role=mcp` senza dover editare `GATEWAY_UPSTREAMS`. Vedi tracker.

## Plugin community

Pubblica il tuo plugin nel TUO repo. Apri una PR a questo file per linkarlo qui sotto:

| Plugin | Autore | Descrizione |
|---|---|---|
| _aggiungi il tuo_ | | |
