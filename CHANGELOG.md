# Changelog

Formato [Keep a Changelog](https://keepachangelog.com/it/1.1.0/), versioning [SemVer](https://semver.org/).

## [Unreleased]

### Aggiunto

- **`deploy.sh`** — deploy one-click dal PC locale via SSH. Chiede IP/user/password + config (email admin, OWNER_ID, ingress, token), poi: installa Docker+Compose v2, crea utente `operator`, trasferisce il repo (tar over SSH), genera `.env`+secrets (random + bcrypt) in batch, `docker compose up -d --build`, **riavvia la VPS e verifica che i container ripartano al boot**, stampa gli URL finali. Supporta auth password (sshpass) o SSH key. Pulisce known_hosts stale (VPS riformattata).
- `services/nb1777-mcp`: porting completo dei 35 tool MCP dal vecchio stack (`core.py` 653 righe + `server.py` 417 righe) — notebook/source/chat/studio (9 artefatti)/doctor.
- `plugins/example-mcp` + `plugins/example-bot`: scheletri per estendere lo stack con MCP/bot propri.
- `gateway`: endpoint `/app/plugins` (JSON dei servizi attivi per la Mini App tab "I miei plugin").
- Scaffold iniziale del progetto: README, LICENSE (MIT), CONTRIBUTING, CODE_OF_CONDUCT (Covenant 2.1), SECURITY, CHANGELOG
- Struttura cartelle Docker compose: `services/` (4 servizi core) + `plugins/` (estendibile) + `secrets/` + `tools/` + `docs/`
- `compose.yaml` base + override per dev (Watch hot-reload) e ingress modulare (Tailscale | Caddy | Cloudflared)
- `setup.sh` wizard interattivo per setup primo install
- `.github/` workflows scheletro: CI (lint + test + build), release-ghcr, trivy vuln scan

## Storia precedente

Le iterazioni precedenti (snapshot installer bash) vivono nel repo `notebookllm1777` che NON è incluso in questo progetto. Lezioni apprese in quella sessione:

- Bash multi-stage + Python heredoc + sudo + service user + systemd-user = troppe cose intrecciate, esplode in modo non riproducibile
- Cross-user permission gymnastics (operatore vs service) si risolve con container isolation
- Idempotenza fragile con `set -euo pipefail` → si risolve con container immutable
- L'install OAuth flow via browser per nlm auth è il design-win da preservare (`/admin/nlm`)
