# Plugin — vps1777

Come aggiungere il **tuo** MCP o bot allo stack senza toccare il core.

## Caso 1 — Aggiungere un MCP server

### Step 1: scaffold

```bash
cp -r plugins/example-mcp plugins/mio-mcp
cd plugins/mio-mcp
```

Apri `app/server.py`, modifica i tool. Lo scheletro è FastMCP streamable-http.

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
      HOST: 0.0.0.0
      PORT: 8010                   # scegli una porta libera ≥ 8010
      FASTMCP_STATELESS_HTTP: "true"
    networks: [backend]
    expose: ["8010"]
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8010/health', timeout=3).status==200 else 1)"]
      interval: 30s
      timeout: 5s
      retries: 3
```

### Step 3: registra al gateway

Edita `.env`:

```dotenv
GATEWAY_UPSTREAMS=archive=archive-mcp:8002,nb1777=nb1777-mcp:8003,mio-mcp=mio-mcp:8010
```

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

## Caso 2 — Aggiungere un bot Telegram

Stesso pattern, ma il bot **non espone porte** (è long-poll outbound).

```bash
cp -r plugins/example-bot plugins/mio-bot
# edita app/bot.py
# crea plugins/mio-bot/compose.mio-bot.yaml senza `expose:` né `networks: ingress`
```

Token in `secrets/mio-bot-token.txt`, montato come `secrets: [mio_bot_token]` nel compose plugin.

## Auto-discovery (futuro)

Esiste un piano per auto-registrare i container con label `vps1777.role=mcp` senza dover editare `GATEWAY_UPSTREAMS`. Vedi tracker.

## Plugin community

Pubblica il tuo plugin nel TUO repo. Apri una PR a questo file per linkarlo qui sotto:

| Plugin | Autore | Descrizione |
|---|---|---|
| _aggiungi il tuo_ | | |
