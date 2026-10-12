# example-mcp

Scheletro MCP plugin per vps1777. Copia + modifica.

## Tool esposti

- `hello(name)` — saluto
- `echo(payload)` — debug

## Attiva

```bash
# 1. .env: aggiungi example=example-mcp:8010 alla riga GATEWAY_UPSTREAMS che c'è già
#    (non appenderne una seconda: due righe con la stessa chiave non si sa quale vale)
sed -i 's/^GATEWAY_UPSTREAMS=.*/&,example=example-mcp:8010/' .env

# 2. Avvia con il plugin
docker compose \
  -f compose.yaml \
  -f compose.ingress.tailscale.yaml \
  -f plugins/example-mcp/compose.example-mcp.yaml \
  --profile ingress.tailscale up -d

# 3. URL: <PUBLIC_BASE>/<SECRET>/example/mcp
```

Il comando del passo 2 vale con l'ingresso di default (Tailscale) e senza feature
opzionali. Con Caddy o Cloudflare usa il file e il profilo del tuo ingresso, e aggiungi
gli overlay delle feature accese (es. `-f compose.ops.backup.yaml --profile ops.backup`):
vedi [docs/PLUGINS.md](../../docs/PLUGINS.md), Step 4. Lì c'è anche cosa comporta, per
`vps1777 update`, avere il plugin in `GATEWAY_UPSTREAMS` (Step 3).

## Customizza

Modifica `app/__main__.py`. Aggiungi tool con `@mcp.tool()`. Vedi [docs/PLUGINS.md](../../docs/PLUGINS.md).
