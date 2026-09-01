# Memory 1777 — the canonical, inside the product

> English translation of [`docs/MEMORIA-1777.md`](../MEMORIA-1777.md). Translations are freshness-checked in CI against the Italian source (see [`MANIFEST.json`](MANIFEST.json)): if this note is red in CI, the Italian moved first.

> **Status**: introduced in **v0.44.0** (2026-08-30). Current canonical: the title line of
> [`services/nb1777-mcp/app/memoria_1777/disciplina.md`](../../services/nb1777-mcp/app/memoria_1777/disciplina.md)
> — the only place that counts; this page explains how to use it, it does not repeat it.

See also: [NB1777.md](../NB1777.md) (Italian) §6 (the `canonico`, `memoria_check`, `memoria_ack`
tools and the notifications) · [BACKUP-RESTORE.md](BACKUP-RESTORE.md) (the local layers live in the
nightly core backup) · [SECURITY.md](../../SECURITY.md) §«Dati a riposo» (data at rest).

## In plain words, before anything else

- The **discipline** is a block of ~50 lines of rules you paste into every
  assistant's instructions (into the `CLAUDE.md` files, into the cloud
  preferences). The rules teach distrust of memories: who actually said this?
  was it true at the time? how do I discover that these very rules are old?
- The **canonical** is the single place that answers «which is the good version
  of that block?». It is a file inside vps1777; the `canonico` tool declares it
  and, with `full=true`, delivers its **text**.
- A **tool** is not a terminal command: it is a function that **the assistant**
  calls during the chat, if it has the vps1777 MCP connector. You can write to
  it in natural language: «call the `canonico` tool with full=true and give me
  the text» — and it does.
- **`fatti.md`** and **`errata.md`** are the two files that are *yours* (who you
  are, which false memories to correct): they do not live in the product, you
  load them with the CLI (`vps1777 memoria importa`, see [CLI.md](CLI.md)) and
  they stay in the encrypted backup.
- All the new words are in the [GLOSSARIO.md](../GLOSSARIO.md) (Italian).

## The why, before the how

An agent with memory fails in one precise way: it does not remember *too little*, it remembers
**false** things — and the more memory it has, the more it amplifies them. On 11 July 2026 an audit
found that «the user is a C++ programmer» was a third party's voice inside a pasted transcript, read
as if he had said it himself; and that a book «paused at chapter 19» was the line of a simulated
character, never ratified, while the book had been finished for months. The cure was not *adding
memories*: it was putting into every session **the rules for judging them** — who is speaking
(ATTRIBUZIONE — attribution), when it was true (FRESCHEZZA — freshness), and how to notice that the
rules themselves are old (CANONICO — the canonical). Those rules are the **1777 memory discipline**.

If the discipline lives *inside* every surface (every `CLAUDE.md`, the cloud preferences, the
Projects), a question arises: «which of the N copies is the good one?». The **canonical** is the
designated place that answers it. Up to 0.43 it was a NotebookLM notebook; since 0.44.0 it is
**a file of the product**.

## What vps1777 ships, and what it does not

The separation is the `/usr` versus `/etc` one: **ship the mechanism, not the content**.

| What | Nature | Where it lives | Who updates it |
|---|---|---|---|
| `disciplina.md` — the rules, in three cuts (PIENO / LITE / MICRO — full / lite / micro) | **product**: neutral, valid for anyone | in the repo, inside the `nb1777-mcp` image (`app/memoria_1777/`) | a vps1777 release (bump of the `vX.Y` in the title line + a line in «Storia») |
| `fatti.md` — who the user of *this* installation is | **data**: personal but stable | nb1777-mcp data volume, `/var/lib/nlm/memoria-1777/` | the administrator, with `vps1777 memoria importa fatti <file>` |
| `errata.md` — the corrected falsehoods, with the source that still generates them | **data** | same place | `vps1777 memoria importa errata <file>` |
| people, family, the personal | — | **in no canonical** | — |
| the state of the projects | volatile | in each project's own `CLAUDE.md` | whoever works on the project |
| the past | already indexed | `archive1777` — you query it, you don't duplicate it | — |

The two local layers **are not in the repo by construction** (not `.gitignore`: literally another
place), they enter the **nightly encrypted backup** along with the whole nb1777-mcp data volume, and
they require no git: a user installing vps1777 from the bundle fills them with the CLI and that's it.
Two examples with the instructions inside:
[`fatti.esempio.md`](../../services/nb1777-mcp/app/memoria_1777/fatti.esempio.md) and
[`errata.esempio.md`](../../services/nb1777-mcp/app/memoria_1777/errata.esempio.md).

## How a session uses it

1. **At startup**, if the version at the top of the block it carries might be old, it calls
   `canonico` (or `doctor`, which injects it): it receives `{version, date, note, sede}`.
2. **The verdict**: `memoria_check("v2.4")` → `{canonico, stale, delta}`; if it is stale, a Telegram
   ping goes out to the owner (max 1 per version pair per day).
3. **The cure** (new in 0.44.0): `canonico(full=true, taglio="pieno"|"lite"|"micro")` returns the
   **text** of the discipline in the requested cut plus the two local layers, each with its own
   `origine` (`prodotto · neutra` / `locale · non nel prodotto`). The session aligns itself **in
   context, right away**, without waiting for the surfaces to be updated by hand — which still
   remain to be done, and must be said to whoever is talking.
4. **The ack**: when the owner has updated the cloud surfaces by hand (claude.ai has no connectors
   in every Project), they declare it with the bot's «✓ Fatto» button **or** with the
   `memoria_ack("v2.5")` tool from a session. ⚠️ The tool is called **only on an explicit
   declaration** («I pasted it»): an ack written without the fact behind it is exactly the
   declaration-without-verification that the discipline forbids.

Up to 0.43 a stale session knew the **number** and not the **text**: the verdict without the cure.
That is the real gain of the migration, more than the privacy.

## How the VPS administrator manages it

The complete command reference, with examples: [CLI.md](CLI.md).

```bash
vps1777 memoria stato                      # versione della disciplina, strati presenti, ack cloud
vps1777 memoria mostra disciplina          # il canonico che il tool serve (dall'immagine)
cp services/nb1777-mcp/app/memoria_1777/fatti.esempio.md ~/fatti.md && $EDITOR ~/fatti.md
vps1777 memoria importa fatti ~/fatti.md   # carica (sostituisce) lo strato; verifica i byte scritti
vps1777 memoria importa errata ~/errata.md
vps1777 memoria mostra fatti
```

`importa` goes through `docker compose exec` (not `docker cp`): the file is born owned by the
container's `app` user, the write is atomic (`.parziale` → `mv`), and the outcome is the **byte
count re-read from the volume** compared against the file, not the exit code. An empty layer
**does not load** (it would silently wipe the good one): to remove one, delete the file in the volume.

## The pointer pattern (for the cloud surfaces)

The cloud surfaces (account preferences, Project instructions on claude.ai)
have no API: they can only be updated **by hand**. With many Projects, every
discipline bump would turn into a flurry of copy-paste. The remedy is not to
automate (impossible) but to **make it unnecessary**: the real rules live in
ONE surface only — the account preferences, which apply in every chat, Projects
included — and every Project carries only a fixed **pointer**, with no version
number:

```
Disciplina di memoria 1777: vale quella nelle preferenze dell'account.
Se il connettore nb1777 (vps1777) è collegato: all'avvio chiama il tool `canonico`
con full=true e allineati a quel testo; se dichiara una versione più nuova di
quella nelle preferenze, dillo a chi ti parla.
Se il connettore non è collegato: dichiara che non puoi sapere se sei aggiornato.
```

The pointer does not age (it carries no version); at every bump the owner
updates **one** surface and gives the ack. Chats with the connector align
themselves anyway with `canonico(full=true)`.

## Versioning the discipline

- The rules change → the `vX.Y` in the title line of `disciplina.md` changes, a line is added to
  «Storia» (date + what changes), and the three cuts carry the new version at the top. One test
  (`test_il_file_del_prodotto_esiste_e_si_legge`) verifies this; another
  (`test_il_canonico_del_prodotto_e_neutro`) forbids non-neutral references in the cuts.
- The bump ships with a release: **the canonical is updated by updating vps1777**, for everyone.
- After the bump the bot keeps reminding the owner about the cloud surfaces, until the ack arrives.
  The on-disk surfaces (the `CLAUDE.md` files) get aligned by the first Claude Code session that
  calls `canonico(full=true)` — or by the owner, pasting in the right cut.
- **The history** v2.2 → v2.4 (11–13 July 2026) stays in the NotebookLM notebook `claudemd1777`,
  read-only. It is not a mistake that it is there: in July 2026, with a format of the VPS imminent,
  a canonical on Google survived the machine and a file *on* the VPS did not. The third way — a file
  *in the repo*, served by the VPS — was not on the table back then; today it wins on every column
  (it survives a format via GitHub and the backups, it has `git log`, it does not go through Google,
  it is tested in CI, it does not depend on `nlm`).

## What it does NOT do

- It is not memory: it contains neither the past (that is in the archive) nor the state of the projects.
- It does not reach a claude.ai Project **without** an MCP connector: there the owner's hand remains,
  and the Telegram reminder is the net under that hole.
- It does not merge the layers: `full=true` returns them **separate and marked** — the session must
  know what is product and what belongs to the installation, and must not copy the facts into the
  block.
