# GLOSSARIO — the acronyms of the 1777 contract

> 🇮🇹 Italiano: [GLOSSARIO.it.md](GLOSSARIO.it.md). The Italian file is the source; this one
> is its English translation.

The acronyms in AGENTS.md and RIGHE.md say which decision of the template a rule comes from.
The decisions live in the working documents of whoever wrote the template (27-29/09/2026), which are
not published: this page has what you need to read them. «n» stands for a number.
`mise run check` goes red if a document uses an acronym that is missing here.

| acronym | what it means |
|---|---|
| DD-P8.n | a design decision of the template: .1 the table of rows, .2 the grade of a judgement gate, .3 the file for agents, .6 distribution and updates, .7 the files for contributors, .8 the command contract and the skeleton, .9 the conformance check |
| Ka.n | the rows of DD-P8.8 about the contract: .1 the 7 commands, .3 idempotent `setup`, .4 and .11 a description for every task, .5 mise's version pinned, .6 the skeletons per stack, .7 every task delegates to the stack's own tool, .8 the retrofit and the adoption step, .9 the test arguments, .10 secrets, .12 the composition root in Dart |
| Kb.n | the rows of DD-P8.8 about tests: .1 a filter that finds nothing exits ≠0, .2 no test without assertions |
| Kc.n | the rows of DD-P8.8 about the git hook: .1 the three-step test, .2 git's common directory, .3 `prepare` in TS, .4 no full test run in the hook, .5 `setup` installs the hook |
| K-a, K-b | the two blocks of DD-P8.8: K-a the contract on top of per-stack skeletons (CI calls only the contract's commands), K-b the test with an empty filter |
| K5 | the language of the documents for contributors (the fifth item of DD-P8.7) |
| AP.n | open points, later decided: .1 C3 is derived, .2 C5 only where there is a cycle, .3 triage is a gate, not a column, .5 a check never seen red is called «proposed» |
| Cn | the columns of the table in RIGHE.md: C1 kinds, C2 grade and reach, C3 seen red, C4 fact or value, C5 cycle, C6 way out, C7 twin, C8 source and date, C9 triage, C10 actor and test |
| R.1 | every ritual that finds something records it in a log that a check reads |
| M.1 | mise as the tool for toolchain and commands, with its ways out |
| D1 | copier without running the template's code (no `_tasks`, `_migrations`, `_jinja_extensions`) |
| Tn | the research that prepared the decisions: T1 the skeletons, T3 mise and just, T4 git hooks, T7 the retrofit and secrets |
| Pr.n | the clarifications written into the skeleton rows: Pr.4 `expectLater` in Dart, Pr.8 `.env.example` in Flutter clients |
| F.n | the frictions of the template's first trial on a real repo (vps1777, 29/09/2026): F.2 a named file that was not there, F.3 a `run` that Tera cannot read, F.4 mise's python shadowing the system one, F.7 the hook's marker, F.8 an apt step in CI, F.9 `_src_path` with a home folder |
| F2.n | the frictions of the second trial (29/09/2026): F2.3 documents in one language only and acronyms unreadable from outside, F2.4 uv's python and the CI runner not pinned |
