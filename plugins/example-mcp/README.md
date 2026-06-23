# example-mcp

Scheletro MCP plugin per vps1777. Copia + modifica.

## Tool esposti

- `hello(name)` — saluto
- `echo(payload)` — debug

## Attiva

```bash
# 1. .env: aggiungi al GATEWAY_UPSTREAMS
echo "GATEWAY_UPSTREAMS=archive=archive-mcp:8002,nb1777=nb1777-mcp:8003,example=example-mcp:8010" >> .env

# 2. Avvia con il plugin
docker compose \
  -f compose.yaml \
  -f compose.ingress.tailscale.yaml \
  -f plugins/example-mcp/compose.example-mcp.yaml \
  --profile ingress.tailscale up -d

# 3. URL: <PUBLIC_BASE>/<SECRET>/example/mcp
```

## Customizza

Modifica `app/__main__.py`. Aggiungi tool con `@mcp.tool()`. Vedi [docs/PLUGINS.md](../../docs/PLUGINS.md).
