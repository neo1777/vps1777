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

- Python: `ruff` + `mypy` (lint pass nel CI)
- Bash: `shellcheck` (pulito)
- Yaml: 2 spazi indent, no `version:` in compose (deprecato)
- Commit message: convenzione [Conventional Commits](https://www.conventionalcommits.org/)
  - `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `ci:`, `chore:`

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

## Codice di Condotta

Vedi [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Niente tolleranza per molestie.

## License

I contributi sono accettati sotto licenza MIT (vedi LICENSE).
