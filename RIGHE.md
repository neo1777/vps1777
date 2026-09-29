# RIGHE.md — the rows of the 1777 contract in this repo

> 🇮🇹 Italiano: [RIGHE.it.md](RIGHE.it.md). The Italian file is the source; this one
> is its English translation, and `mise run check` goes red if it falls behind.

The template's table of rows (DD-P8.1). Each row says which kinds of repo it applies to (C1), its
grade and how far it reaches (C2), whether its check has been seen red (C3), whether a fact or a
value decided it (C4), the cycle only where there is one (C5, AP.2), the way out (C6), the twin
(C7), the source with its date (C8), and who it serves with the test that keeps it alive (C10).
`tools/1777/GLOSSARIO.md` explains the acronyms (Ka.1, DD-P8.3, F.9…): they are the
decisions of the template each row comes from.

**C3 is derived, never written by hand (AP.1).** In the table, for a check, the cell only says
«derived: <id>»: the «yes» or «no» is written by `tools/1777/prova-controlli.sh` in the block at the
bottom, with **where** it was seen (locally, or «CI run <id>» in GitHub Actions) and **when**.
For machines: `tools/1777/visto-rosso.tsv` (lazy: written by the check run, also as a job artifact).
A CI run is brought here with `gh run download <id> -n visto-rosso` and `bash tools/1777/prova-controlli.sh --c3-da <file>`.
For a promise C3 does not apply. Until a check has been seen red on its built fault, it is
called a **proposed check** (AP.5).

Triage (C9) is the entry gate, not a column (AP.3): discarded rows are listed at the bottom,
with the reason.

C2 legend: **promise** (kept by whoever works) · **signal** (a check says it, does not stop) ·
**overridable block** (stops, but can be passed with a declared gesture) · **block**.
Reach: local commit · merge (CI) · release · agent.

| row | what | C1 kinds | C2 grade · reach | C3 seen red | C4 | C5 cycle | C6 way out | C7 twin | C8 source · date | C10 actor · test |
|---|---|---|---|---|---|---|---|---|---|---|
| Ka.1 | the 7 commands (setup, dev, test, lint, build, check, release); AGENTS.md names `check` and `mise tasks ls --json`, not the 7 | repo, every stack | signal · merge | derived: `comandi` | fact (the names); value (mise, M.1) | — | M.1: move to just + mise for the toolchain | Scripts to Rule Them All, GNU targets | DD-P8.8, 28/09/2026 | an agent who arrives finds the commands without asking · conformita [comandi] |
| Ka.4, Ka.11 | every task has a one-line description, which also says what it is NOT | repo | signal · merge | derived: `descrizione` | fact | — | if a description grows into a paragraph, shorten it; do not remove it | `mise tasks ls` (the column is already there) | DD-P8.8, 28/09/2026 | whoever reads `mise tasks ls` understands without opening the file · conformita [descrizione] |
| DD-P8.9 (1, 3) | the commands named in AGENTS.md, and the files named in backticks in AGENTS.md, in this file and in the glossary, exist according to an independent source; or are declared «lazy» | repo | signal · merge | derived: `file-nominati` | fact | — | if a name is ambiguous, drop the backticks, not the check | none searched | DD-P8.9, 27/09/2026 | an agent does not chase a file that is not there · conformita [file] |
| DD-P8.9 (4) | fail-loud: if a tool is missing the check says so and exits 2, never green | repo | signal · merge | derived: `fail-loud` | fact | — | — | vps1777's «NON MISURATO» | DD-P8.9, 27/09/2026 | whoever reads a green knows it was measured · conformita without mise → 2 |
| DD-P8.9 (2) | every check in this table has its test in `tools/1777/prova-controlli.sh` | repo | signal · merge | derived: `prova` | fact | at every new check · checkpoint: `check` · brief: the row here | — | prova-controlli of the 1777 skills | DD-P8.9, AP.1, AP.5, 27-28/09/2026 | whoever adds a check does not leave it decorative · conformita [prova] |
| DD-P8.3 | a single AGENTS.md; CLAUDE.md only with `@AGENTS.md` | repo | signal · merge | derived: `claude-import` | fact (Claude Code does not read AGENTS.md if there is a CLAUDE.md) | — | the symbolic link, if it holds with copier, git and every machine | AGENTS.md spec | DD-P8.3, 27/09/2026 | Claude Code reads the same rules as the other agents · conformita [claude-import] |
| Ka.3 | `setup` is idempotent: twice in a row, the second exits 0 and changes no tracked file | repo | signal · merge (prova-controlli job) | derived: `setup-idempotente` | fact | after every pull · checkpoint: the check run | — | script/setup from Scripts to Rule Them All | DD-P8.8, 28/09/2026 | whoever pulls reruns setup without fear · prova-controlli |
| Kc.2, Kc.5 | `setup` calls `tools/hooks/installa.sh` (the wire) | repo | signal · merge | derived: `filo` | fact | — | — | Husky's `prepare` (the other wire) | DD-P8.8, 28/09/2026; T4 | the hook installs itself inside a gesture people already make · conformita [filo] |
| Kc.1-Kc.4 | the hook in the common directory: dirty stopped, clean passes, worktree covered; fail-loud; calls the contract's commands; no full test run | repo | overridable block · local commit (who overrides: anyone, with `--no-verify`) + signal · merge (prova-controlli job, three steps on a fresh clone) | derived: `hook` | fact (measured by T4) | — | if the wire gets lost again, Husky `prepare` in TS (Kc.3) | Husky, lefthook, prek; vps1777's model | DD-P8.8, 28/09/2026; T4 27/09/2026 | whoever commits sees red before the push · prova-controlli [hook] |
| Ka.5, K-a | mise's version pinned: `min_version`, actions by sha (mise-action with `version`, checkout, upload-artifact), and `mise.lock` pinning every tool in `[tools]`; the `run:` steps of check.yml are only contract commands (no apt: a system tool lives in `[tools]`); the runner pinned (`runs-on`, never `-latest`, F2.4) | repo | signal · merge | derived: `ci-mise` | fact (T3: 9 declared breakages in 6 months) | batched updates (DD-P8.6) | M.1 | mise-action `version` + `sha256` | DD-P8.8, 28/09/2026; T3 27/09/2026; F2.4 29/09/2026 | a mise release or a new runner image does not break CI on its own · conformita [ci] |
| F.4, F2.4 | python is not in `[tools]` (the retrofit); uv's python is pinned by `UV_PYTHON` in `[env]` (or by `.python-version`), without touching PATH | Python repo | signal · merge | derived: `ci-mise` | fact (without it, uv uses the runner's python, which changes with the image) | batched updates | — | uv's `.python-version` | F.4, F2.4, 29/09/2026 | CI and local judge with the same python · conformita [ci] |
| K-b, Kb.1 | `test` with a filter that finds nothing exits ≠0 | repo | signal · merge | derived: `filtro-vuoto` | fact (pytest 5, Dart 79; vitest with the wrapper) | — | — | pytest `-k` (5 on its own) | DD-P8.8, 28/09/2026 | a green without tests does not pass · prova-controlli |
| Kb.2 | no test file without assertions; a Dart file with only `expectLater` is not red | repo | signal · merge | derived: `asserzioni` | fact; it is a floor, not a proof | — | — | [never searched] | DD-P8.8, Pr.4, 28/09/2026 | whoever reads a test knows it checks something · asserzioni.py |
| Ka.10 | secrets, by shape and across lines: `define` of `*_KEY`, `loadEnv(…, '')`, `import.meta.env.VITE_*KEY`, `--dart-define` with `*_KEY`, `.env` as an asset or in git; prints file, line, rule, never the value | repo | signal · merge + overridable block · local commit | derived: `segreti-forma` | fact (T7: the one-line rule misses AI Studio) | — | — | gitleaks, trufflehog (values); security-vite (shape, on one line) | DD-P8.8, 28/09/2026; T7 27/09/2026 | a key does not reach the client · segreti.sh |
| Ka.8 (idea) | the contract's lines in shared files: `.env` ignored by git | repo | signal · merge | derived: `gitignore-env` | fact | — | — | projen's anti-tamper | T7 27/09/2026; Ka.8 not decided | `.env` does not end up in git by mistake · conformita [gitignore] |
| F.9 | the repo does not reveal which home folder it was born from: `_src_path` in `.copier-answers.yml` is the template's remote | repo | signal · merge (red if the repo is public; a note if private) | derived: `src-path` | fact (no check of the first repo tried stopped it) | — | redact by hand before the first commit, knowing that `copier update` stops working | — | F.9, 29/09/2026 | a personal path does not leak onto a public repo · conformita [src-path] |
| F.3 | every task can be read by mise (which passes every `run` through Tera); logic lives in a script, a `run` is one line that calls | repo | signal · merge | derived: `tera` | fact (a `${#…}` in the lint run switched `check` off; `mise tasks ls` and `mise tasks validate` stay green, only `mise run --dry-run` says so, measured on 29/09) | — | — | — | F.3, 29/09/2026 | whoever adds a command does not switch `check` off · conformita [tera] |
| K5 | language: always Italian, the source; English too, if the repo is public (it,en): both files exist, point to each other, have the same shape, and the source's fingerprint is the one registered in `tools/1777/traduzioni.json` | repo | signal · merge | derived: `lingua` | value (the owner's choice, 27/09/2026) | at every change to the Italian · checkpoint: `check` | — | vps1777 (docs/en/MANIFEST.json) | DD-P8.7, 27/09/2026; F2.3, 29/09/2026 | an outside contributor reads an English that has not fallen behind · conformita [lingua] |
| F2.3 | every acronym in these documents is explained in the glossary | repo | signal · merge | derived: `glossario` | fact (a field trial counted more than a hundred, unreadable from outside) | — | if an acronym is needed only once, write the thing out | — | F2.3, 29/09/2026 | whoever comes from outside can read where the rules come from · conformita [glossario] |
| R.1 | every ritual that finds something records it in `RILIEVI.ndjson`; `check` counts those open for more than 14 days, with the denominator and the date | repo, every ritual | signal (the count) · promise with a ritual (the record, where there is no script) | derived: `rilievi` | value (a note of the owner on DD-P8.2); the 14 is not measured | trigger: a ritual that finds something · checkpoint: `check` · record: `RILIEVI.ndjson` (lazy: born with the first record) | if the queue grows faster than it empties, raise the bar for what counts; if in the first month more than half exceed 14 days, measure the 14 | a log of open items in another repo (internal) | R.1, 28/09/2026 | a finding does not stay in one day's minutes · rilievi.py conta |
| M.1 | mise for toolchain and commands | repo | promise | does not apply (promise) | value (the owner's choice, 28/09/2026) | batched updates | 2 breakages of one of the 7 commands in 2 repos within 6 months, at a pinned version; or contributors who refuse mise → just + mise for the toolchain | just, Task, make (T3) | M.1, 28/09/2026 | — · the differential test (same commit, old and new mise) |
| D1 | copier without `_tasks`, `_migrations`, `_jinja_extensions` | template | promise (verified by the template's own test) | does not apply (promise) | fact (they require `--trust`; free Renovate does not run them) | — | — | copier-uv | DD-P8.6, 27/09/2026 | an update does not run the template's code · prova-template.sh (it lives in the template, not in this repo: hence no backticks) |
| Ka.6 | the skeletons per stack | — | **placeholder: not decided yet** | does not apply | value | — | — | T1 | DD-P8.8: not decided | — |
| Ka.8 | the retrofit, the adoption step | — | **placeholder: not decided yet** (only the minimum is here: `_skip_if_exists`, and the answers `hook_propri`, `hook_marcatore`, `setup_crea_env`, `scheletro`, `python_da_mise`, `python_uv`) | does not apply | value | — | — | projen, nx init, copier `_skip_if_exists` | DD-P8.8: not decided | — |

## Discarded at triage (AP.3), with the reason
- `mise generate git-pre-commit`: it changed behaviour on 20/09/2026 (Kc.5, T3).
- Husky as the installer: absorbed by `prepare` → `tools/hooks/installa.sh` (Kc.3); it does not cover new worktrees (T4).
- A relative `core.hooksPath`: leaves without a hook the worktrees that lack `tools/hooks/` (Kc.2).
- The «the hook is there» check on a clone without setup: always red, hence switched off (T4); replaced by the three-step test.

## C3 · seen red
«where, when»: «local» if the test ran on a machine, «CI run <id>» if it ran in GitHub Actions.

<!-- C3:inizio — written by tools/1777/prova-controlli.sh, never by hand (AP.1) -->
No test run yet: every check is **proposed** (AP.5). Run `bash tools/1777/prova-controlli.sh`.
<!-- C3:fine -->
