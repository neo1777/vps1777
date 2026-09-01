# Contributing to vps1777

> 🇮🇹 Versione italiana: [CONTRIBUTING.it.md](CONTRIBUTING.it.md) — this file is its
> English translation, freshness-checked in CI (see [docs/en/MANIFEST.json](docs/en/MANIFEST.json)).

Thanks for wanting to contribute. A quick tour of how we work.

## Kinds of contribution

- **Bug fixes**: open an issue first to discuss the fix. For trivial fixes (typos, logs), a direct PR is fine.
- **New features**: discuss the idea in an issue first. We don't want big unexpected PRs.
- **Plugins** (MCP servers or bots): they don't go into the core. Publish them in your own repo and link them in [docs/PLUGINS.md](docs/PLUGINS.md) → "community plugins".
- **Documentation**: always welcome, small fixes included.

## Dev setup

```bash
git clone https://github.com/neo1777/vps1777.git   # or your fork, if contributing
cd vps1777
./setup.sh                 # configures local .env + secrets
docker compose -f compose.yaml -f compose.build.yaml -f compose.dev.yaml up --watch
```

Compose Watch reloads containers when `services/*/app/*.py` changes.
The `compose.build.yaml` overlay exists because `compose.yaml` is pull-only
(images from GHCR): local builds exist only in dev/CI.

## Code style

- Python: `ruff` + `mypy` (lint passes in CI)
- Bash: `shellcheck` (clean)
- Yaml: 2-space indent, no `version:` key in compose files (deprecated)
- Commit messages: [Conventional Commits](https://www.conventionalcommits.org/)
  - `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `ci:`, `chore:`

## What never enters the repo

This repo is **public**. Whatever lands here is public immediately, and removing
it later doesn't undo it: it stays in git history, in the PR diff, and in every
existing clone. The only useful moment to stop it is **before the commit**.

Never commit:

- **Session exports** — the `.txt` files produced by `/export` from a working chat
  (`YYYY-MM-DD-HHMMSS-<slug>.txt`). They're the insidious case: an innocuous name,
  nothing that looks like a secret — but inside is everything said-and-done in the
  session: pasted credentials, addresses, local paths, personal material. The
  `.gitignore` covers them; if you need them, keep them **outside** the repo.
- **Real secrets**: `.env`, the contents of `secrets/`, Tailscale auth-keys, bot
  tokens, `age` or PEM keys, session cookies.
- **Data**: databases, backups, dumps, archives. They belong to the installation,
  not to the project.

Placeholders in docs are written to be **recognizable** (`tskey-auth-...`,
`<your-token>`): never a real value "because it's just a test one".

The safety net is `security/check_no_leaks.py`, which runs in CI on every PR and
fails the build. It's a net, not a license to be careless: it doesn't stop
`git add -f` locally, and for a file **already** tracked it comes too late. The
same rule that applies to code applies to you — **if a secret slipped through,
removing it isn't enough: rotate it.** Git history doesn't forget.

## Pull Requests

1. Fork, branch off `main`
2. Work on `feature/<short-name>`
3. Open a PR describing: what, why, how it was tested
4. Wait for review — usually within 48h
5. Squash merge

## Code of Conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Zero tolerance for harassment.

## License

Contributions are accepted under the MIT license (see [LICENSE](LICENSE)).
