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

- Python: `ruff` (version pinned in CI, currently `ruff==0.15.22`; `ruff check services/ tools/ security/`). No `mypy`: no type checking runs anywhere, neither in CI nor in the hooks
- Bash: `shellcheck` (clean, minimum severity threshold as in CI)
- Yaml: 2-space indent, no `version:` key in compose files (deprecated)
- Commit messages: a prefix that says **what** is touched, then the sentence in Italian.
  The ones in use: `fix:`, `feat:`, `docs:`, `ci:`, `build:` (Dependabot bumps), `test:`,
  `changelog:` (the PR that opens a version), or the area touched (`installer:`,
  `gateway:`, `indexer:`…); a scope in parentheses is welcome (`docs(architettura):`)

## Tests and checks locally

### Before opening a PR: `tools/check.sh`

```bash
bash tools/check.sh              # lint, guards and tests: what CI's lint and contract jobs do
bash tools/check.sh lint         # just ruff and shellcheck, at the same pins as CI
bash tools/check.sh guardiani    # the CI checks that aren't tests (the guards)
bash tools/check.sh test         # the suites, one at a time, and the bash tests
```

It ends with a summary of what is green and what is red, in about two minutes. It exits 0
if everything is green, 1 if something is red, 2 if a tool is missing (docker, uv, uvx):
it says so, and that is not a green. It installs nothing and never rewrites tracked files.
It doesn't cover the `build` job, nor the ratification of lock jumps, which lives in the
PR body.
The source of truth stays `.github/workflows/ci.yml`: if CI gains a check and `check.sh`
doesn't, `tools/tests/test_check_sh_segue_la_ci.py` turns red. And
`tools/tests/test_i_guardiani_mordono.py` proves that the guards without a self-test of
their own (anti-leak, security register, feature ledger, pre-commit, translations) still
turn red on a constructed fault, for the right reason.

### The commands one by one

The suites run **one at a time**, as in CI:

```bash
uvx --with bcrypt --with cryptography pytest tools/tests/   # CLI, installers, repo guards
uvx pytest services/archive-mcp/tests/                         # archive-mcp (stdlib)
uvx pytest services/gateway/tests/                             # gateway (stdlib)
(cd services/nb1777-mcp && uv sync && uv run pytest tests/)    # nb1777-mcp, with the pinned nlm
bash tools/esegui-test-bash.sh                                 # the .sh tests in tools/tests/
```

⚠️ **Don't put `tools/tests/` and `services/archive-mcp/tests/` in the same pytest
invocation**: both import a package named `app` (the gateway's and archive-mcp's), and
the second one finds the first — measured: `ModuleNotFoundError: No module named
'app.miniapp_core'`. Some archive-mcp and gateway tests skip without the locked
dependencies: CI re-runs them after `uv sync --frozen` (see
`.github/workflows/ci.yml`).

The checks CI will run again (`tools/check.sh` runs them all):

- `python3 tools/gate-locale.py` — runs the steps of `ci.yml` **reading them from the
  workflow**, not rewritten by hand (`--elenco` says what it would do, `--job lint` runs
  just one). It skips and names the `uses:` steps and those with `${{ … }}`; it needs
  `pyyaml` (`uv run --with pyyaml python3 tools/gate-locale.py`), and some steps touch
  the environment (the ruff one does `uv tool install`)
- `python3 security/check_no_leaks.py` (no secrets), `python3 security/check_findings.py`
  (the security register holds up against its evidence), `python3 tools/verify-features.py`
  (the feature ledger), `python3 tools/doc-riferimenti.py` (the files the docs name exist)
- if you touched a document that has a translation (`README.it.md`, `CONTRIBUTING.it.md`,
  the pages with a copy in `docs/en/`): update **the translation too**, then
  `python3 tools/aggiorna-traduzioni.py` — never the other way round: the hash without
  the translation is a rubber stamp

**The git hooks are versioned** in `tools/hooks/`. You install them with
`bash tools/hooks/installa.sh`, which copies them into `.git/hooks/` (the place every
worktree of the repo sees); `bash tools/hooks/installa.sh --stato` says whether the
installed copy is identical to the versioned one. The `pre-commit` warns if you are not
committing on the main branch (it doesn't block), runs `shellcheck` on the `.sh` and
`ruff` on the `.py` files you are committing (it blocks if they find problems), and runs
the anti-leak gate: on any clone it is `security/check_no_leaks.py`, the same one CI runs,
and it stops the commit if it finds credential material. Deliberate way out: `--no-verify`.

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

`main` is protected: changes get in **only through a PR**, with CI's required checks
green — for everyone, the owner included.

## Releasing (for maintainers)

1. The version lives in the `VERSION` file. It is bumped with a PR on `main` that also
   carries the `## [X.Y.Z]` section of `CHANGELOG.md` (commit `changelog: sezione X.Y.Z …`).
2. The `vX.Y.Z` tag on the `main` commit triggers `.github/workflows/release.yml`, which
   first checks: `VERSION` equal to the tag, the section in the CHANGELOG (stable
   releases only), CI **green** on the tagged commit. Then it builds the images (amd64
   only), signs them with keyless cosign, publishes them to GHCR and creates the release
   with the signed runtime bundle that `vps1777 update` downloads.
3. **Tags and releases are immutable**: `v*` tags through a ruleset, release assets
   through the *immutable releases* setting. A mistake isn't fixed by re-tagging: you ship
   a new version. A bad release is **withdrawn** by marking it as a *prerelease* on
   GitHub, within the auto-update's 48-hour quarantine
   ([docs/en/UPDATE.md](docs/en/UPDATE.md)).

## Code of Conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Zero tolerance for harassment.

## License

Contributions are accepted under the MIT license (see [LICENSE](LICENSE)).
