# example-bot

Scheletro bot Telegram plugin per vps1777. Copia + modifica.

## Attiva

```bash
# 1. Crea un bot nuovo su @BotFather
echo -n "12345:NUOVO_TOKEN" > secrets/example_bot_token.txt
chmod 600 secrets/example_bot_token.txt

# 2. Avvia
docker compose \
  -f compose.yaml \
  -f compose.ingress.tailscale.yaml \
  -f plugins/example-bot/compose.example-bot.yaml \
  --profile ingress.tailscale up -d

# 3. Manda /start al bot
```

Vedi [docs/PLUGINS.md](../../docs/PLUGINS.md).
