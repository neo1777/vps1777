# Security Policy

## Supported Versions

Pre-1.0: solo l'ultima `main` riceve security fix.

## Reporting a Vulnerability

**Non** aprire una issue pubblica.

Mandami un'email a `[da configurare]` con:
- Descrizione della vuln
- Step di riproduzione (PoC se possibile)
- Impatto stimato
- Tuo nome/handle per il credit (se desideri)

Mi impegno a:
- Confermare ricezione entro **48h**
- Valutare e rispondere con un piano entro **7 giorni**
- Patchare e disclosure coordinata: 90 giorni se la severity lo richiede, prima se è semplice

## Security model

vps1777 espone su Internet **solo** il gateway (porta 443 via Tailscale Funnel / Caddy / Cloudflared).

Threat model dichiarato:
- Backend (archive-mcp, nb1777-mcp, bot) su rete Docker `internal: true` — non raggiungibili dall'esterno
- OAuth 2.1 + DCR + PKCE per tutti i client OAuth (claude.ai, Mini App, future integrazioni)
- JWT con `typ` separati: access_token (15min), refresh_token (30gg), admin (8h), miniapp (1h)
- Path namespacing via `GATEWAY_SECRET`: l'URL contiene un segreto rotabile (se compromesso, rota e cambi URL)
- Bcrypt rounds=12 per password admin (file `secrets/admin_password_bcrypt.txt`)
- Container non-root (UID 1000 `app`), `cap_drop: ALL`, `no-new-privileges`
- Il gateway (unico servizio esposto) non ha accesso al Docker socket né ai secret host
- Hardening host automatico all'install: `unattended-upgrades` + `fail2ban`
- Strumenti di management (Portainer) mai esposti: solo loopback + tunnel SSH (vedi [docs/OPS.md](docs/OPS.md))

## Out of scope

- Vulnerabilità in immagini base (Python, Tailscale, Caddy) — segnalale a monte
- Misconfigurazioni del DEPLOYER (es. lasciare la VPS aperta su altre porte)
- Account claude.ai compromessi (responsabilità Anthropic)
- Account Google compromessi (responsabilità Google)
