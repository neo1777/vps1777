# Contributing to vps1777

Grazie per voler contribuire. Spiegazione veloce di come lavoriamo.

## Tipi di contributo

- **Bug fix**: apri una issue prima per discutere il fix. Per fix banali (typo, log), una PR diretta va bene.
- **Nuova feature**: prima discuti l'idea in una issue. Non vogliamo PR grandi inaspettate.
- **Plugin** (MCP o bot): non vanno nel core. Pubblica nel tuo repo e linkalo in [docs/PLUGINS.md](docs/PLUGINS.md) → "plugin community".
- **Documentazione**: sempre benvenuta, anche piccole correzioni.

## Setup dev

```bash
git clone https://github.com/<owner>/vps1777.git
cd vps1777
./setup.sh                 # configura .env locale + secrets
docker compose -f compose.yaml -f compose.build.yaml -f compose.dev.yaml up --watch
```

Compose Watch ricarica i container su modifica `services/*/app/*.py`.
L'overlay `compose.build.yaml` serve perché `compose.yaml` è pull-only
(immagini da GHCR): il build locale esiste solo in dev/CI.

## Stile codice

- Python: `ruff` + `mypy` (lint pass nel CI)
- Bash: `shellcheck` (pulito)
- Yaml: 2 spazi indent, no `version:` in compose (deprecato)
- Commit message: convenzione [Conventional Commits](https://www.conventionalcommits.org/)
  - `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `ci:`, `chore:`

## Pull Request

1. Forka, branch da `main`
2. Lavora su feature/<nome-corto>
3. Apri PR con descrizione: cosa, perché, come testato
4. Aspetta review — di norma 48h
5. Squash merge

## Codice di Condotta

Vedi [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Niente tolleranza per molestie.

## License

I contributi sono accettati sotto licenza MIT (vedi LICENSE).
