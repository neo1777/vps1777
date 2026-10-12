## Cosa
<descrizione cambia il PR>

## Perché
<motivazione: bug fix? nuova feature? refactor?>

## Come testato
- [ ] Provato in locale con l'overlay di build (`docker compose -f compose.yaml -f compose.build.yaml -f compose.dev.yaml up --watch`): `docker compose up` da solo avvia le immagini pubblicate su GHCR, non questo codice
- [ ] `bash tools/check.sh` verde (lint, guardiani e suite, come i job `lint` e `contract` della CI)
- [ ] Lint pulito (`ruff check`, `shellcheck`)
- [ ] CI verde

## Note per la review
<eventuali punti d'attenzione: breaking change? migration? se hai rigenerato un `uv.lock`: pacchetto e versione di ogni salto di regime, che il controllo della CI cerca nel corpo della PR>

- [ ] Se ho toccato un documento tradotto: traduzione aggiornata, poi `python3 tools/aggiorna-traduzioni.py`

## Issue collegata
Closes #
<!-- solo le keyword inglesi (Closes/Fixes/Resolves #N) chiudono la issue: «Chiude la #N» non basta, e il gate della CI lo segnala -->
