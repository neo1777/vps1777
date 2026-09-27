# Contributing to vps1777

Grazie per voler contribuire. Spiegazione veloce di come lavoriamo.

## Tipi di contributo

- **Bug fix**: apri una issue prima per discutere il fix. Per fix banali (typo, log), una PR diretta va bene.
- **Nuova feature**: prima discuti l'idea in una issue. Non vogliamo PR grandi inaspettate.
- **Plugin** (MCP o bot): non vanno nel core. Pubblica nel tuo repo e linkalo in [docs/PLUGINS.md](docs/PLUGINS.md) → "plugin community".
- **Documentazione**: sempre benvenuta, anche piccole correzioni.

## Setup dev

```bash
git clone https://github.com/neo1777/vps1777.git   # o il tuo fork, se contribuisci
cd vps1777
./setup.sh                 # configura .env locale + secrets
docker compose -f compose.yaml -f compose.build.yaml -f compose.dev.yaml up --watch
```

Compose Watch ricarica i container su modifica `services/*/app/*.py`.
L'overlay `compose.build.yaml` serve perché `compose.yaml` è pull-only
(immagini da GHCR): il build locale esiste solo in dev/CI.

## Stile codice

- Python: `ruff` (versione pinnata nella CI, oggi `ruff==0.15.22`; `ruff check services/ tools/ security/`). Niente `mypy`: nessun controllo di tipi gira, né in CI né negli hook
- Bash: `shellcheck` (pulito, soglia al minimo come in CI)
- Yaml: 2 spazi indent, no `version:` in compose (deprecato)
- Commit message: un prefisso che dice **cosa** tocca, poi la frase in italiano. Quelli
  in uso: `fix:`, `feat:`, `docs:`, `ci:`, `build:` (i bump di Dependabot), `test:`,
  `changelog:` (la PR che apre una versione), oppure l'area toccata (`installer:`,
  `gateway:`, `indexer:`…); uno scope fra parentesi è benvenuto (`docs(architettura):`)

## Test e controlli in locale

Le suite girano **una alla volta**, come in CI:

```bash
uvx --with bcrypt --with cryptography pytest tools/tests/   # CLI, installer, presìdi del repo
uvx pytest services/archive-mcp/tests/                         # archive-mcp (stdlib)
uvx pytest services/gateway/tests/                             # gateway (stdlib)
(cd services/nb1777-mcp && uv sync && uv run pytest tests/)    # nb1777-mcp, col nlm pinnato
bash tools/esegui-test-bash.sh                                 # i test .sh di tools/tests/
```

⚠️ **Non mettere `tools/tests/` e `services/archive-mcp/tests/` nella stessa invocazione
di pytest**: tutte e due importano un package che si chiama `app` (quello del gateway e
quello di archive-mcp), e la seconda trova il primo — misurato: `ModuleNotFoundError: No
module named 'app.miniapp_core'`. Alcuni test di archive-mcp e del gateway saltano senza
le dipendenze del lock: la CI li rilancia dopo `uv sync --frozen` (vedi
`.github/workflows/ci.yml`).

Prima di aprire la PR, i controlli che la CI rifarà:

- `python3 tools/gate-locale.py` — esegue gli step di `ci.yml` **leggendoli dal workflow**,
  non riscritti a mano (`--elenco` dice cosa farebbe, `--job lint` ne esegue uno). Salta e
  nomina gli step `uses:` e quelli con `${{ … }}`; vuole `pyyaml`
  (`uv run --with pyyaml python3 tools/gate-locale.py`), e qualche step tocca l'ambiente
  (quello di ruff fa `uv tool install`)
- `python3 security/check_no_leaks.py` (niente segreti), `python3 security/check_findings.py`
  (il registro di sicurezza regge sulle sue evidenze), `python3 tools/verify-features.py`
  (il ledger delle feature), `python3 tools/doc-riferimenti.py` (i file che i doc nominano
  esistono)
- se hai toccato un documento che ha una traduzione (`README.it.md`, `CONTRIBUTING.it.md`,
  le pagine con una copia in `docs/en/`): aggiorna **anche la traduzione**, poi
  `python3 tools/aggiorna-traduzioni.py` — mai il contrario: l'hash senza la traduzione è
  un timbro

**Gli hook git sono versionati** in `tools/hooks/`. Si installano con
`bash tools/hooks/installa.sh`, che li copia in `.git/hooks/` (il posto che vedono tutti i
worktree del repo); `bash tools/hooks/installa.sh --stato` dice se la copia installata è
identica a quella versionata. Il `pre-commit` avvisa se non stai committando sul ramo
principale (non blocca), passa `shellcheck` sui `.sh` e `ruff` sui `.py` che stai
committando (blocca se trovano problemi), e lancia il gate anti-leak (lo script `gate-antileak`)
**se lo trova** — non è in questo repo: senza, stampa «NON MISURATO» e la rete resta
`security/check_no_leaks.py` in CI. Via d'uscita consapevole: `--no-verify`.

## Cosa non entra mai nel repo

Questo repo è **pubblico**. Quello che ci finisce è pubblico da subito, e toglierlo
dopo non lo disfa: resta nella storia di git, nel diff della PR e in ogni clone già
fatto. L'unico momento utile per fermarlo è **prima del commit**.

Non committare mai:

- **Export di sessione** — i `.txt` prodotti da `/export` di una chat di lavoro
  (`AAAA-MM-GG-HHMMSS-<slug>.txt`). Sono il caso insidioso: hanno un nome innocuo e
  non sembrano segreti, ma dentro c'è tutto il detto-e-fatto della sessione —
  credenziali incollate, indirizzi, path locali, roba personale. Il `.gitignore` li
  copre; se ti servono, tienili **fuori** dal repo.
- **Segreti veri**: `.env`, contenuto di `secrets/`, auth-key Tailscale, token del
  bot, chiavi `age` o PEM, cookie di sessione.
- **Dati**: database, backup, dump, archivi. Sono roba dell'installazione, non del
  progetto.

Nella doc i segnaposto si scrivono **riconoscibili** (`tskey-auth-...`,
`<il-tuo-token>`): mai un valore reale "tanto è di prova".

La rete di sicurezza è `security/check_no_leaks.py`, che gira in CI a ogni PR e fa
fallire la build. È una rete, non un permesso di distrazione: non ferma `git add -f`
in locale, e per un file **già** tracciato arriva tardi. Vale anche per te la regola
che vale per il codice — **se un segreto è passato, non basta toglierlo: va
ruotato.** La storia di git non dimentica.

## Pull Request

1. Forka, branch da `main`
2. Lavora su feature/<nome-corto>
3. Apri PR con descrizione: cosa, perché, come testato
4. Aspetta review — di norma 48h
5. Squash merge

`main` è protetto: si entra **solo da PR**, con i controlli obbligatori della CI verdi —
per tutti, owner compreso.

## Rilascio (per chi mantiene)

1. La versione sta nel file `VERSION`. La si alza con una PR su `main` che porta anche la
   sezione `## [X.Y.Z]` di `CHANGELOG.md` (commit `changelog: sezione X.Y.Z …`).
2. Il tag `vX.Y.Z` sul commit di `main` fa partire `.github/workflows/release.yml`, che
   prima controlla: `VERSION` uguale al tag, la sezione nel CHANGELOG (solo per le
   stable), la CI **verde** sul commit taggato. Poi builda le immagini (solo amd64), le
   firma con cosign keyless, le pubblica su GHCR e crea la release con il bundle runtime
   firmato che `vps1777 update` scarica.
3. **Tag e release sono immutabili**: i tag `v*` per un ruleset, gli asset delle release
   per l'impostazione *immutable releases*. Un errore non si ripara ritaggando: si esce
   con una versione nuova. Una release sbagliata si **ritira** segnandola *prerelease* su
   GitHub, entro le 48 ore di quarantena dell'auto-update
   ([docs/UPDATE.md](docs/UPDATE.md)).

## Codice di Condotta

Vedi [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Niente tolleranza per molestie.

## License

I contributi sono accettati sotto licenza MIT (vedi LICENSE).
